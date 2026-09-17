"""A playable guideline Tetris game model: 7-bag, hold, SRS with kick reporting, T-spin detection
(same rule as Cold Clear's libtetris), line clears, attack, and full undo/redo of placements.

No timing lives here; the UI decides when gravity ticks and when a piece locks."""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

from .board import Board
from .coldclear import PIECES
from .piece import E, N, S, W, FallingPiece, rotation_points

# Guideline attack (lines of garbage sent), matching libtetris lock_data.rs
ATTACK = {"single": 0, "double": 1, "triple": 2, "tetris": 4,
          "tsm": 0, "tss": 2, "tsd": 4, "tst": 6, "tsm2": 1}
COMBO_GARBAGE = [0, 0, 1, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5]  # index = combo count
DIFFICULT = {"tetris", "tss", "tsd", "tst", "tsm", "tsm2"}


@dataclass
class Lock:
    """What happened when a piece locked."""
    piece: str
    cells: list[tuple[int, int]]
    lines: int
    kind: str            # none/single/double/triple/tetris/tsm/tss/tsd/tst/tsm2
    tspin: str           # "", "mini", "full"
    kick: int | None     # SRS kick index (0-4) used by the last rotation, if the lock was a spin
    kick_offset: tuple[int, int] | None  # that kick's (dx, dy)
    rotation: str        # e.g. "N->W" for the spin's rotation, "" otherwise
    b2b: bool
    combo: int
    attack: int
    perfect_clear: bool

    def label(self) -> str:
        names = {"none": "", "single": "Single", "double": "Double", "triple": "Triple", "tetris": "TETRIS",
                 "tsm": "Mini T-Spin", "tsm2": "Mini T-Spin Double", "tss": "T-Spin Single", "tsd": "T-SPIN DOUBLE", "tst": "T-SPIN TRIPLE"}
        parts = [names[self.kind]] if self.kind != "none" else ([] if not self.tspin else ["T-Spin (no lines)"])
        if self.b2b and self.kind in DIFFICULT:
            parts.insert(0, "Back-to-Back")
        if self.combo > 0 and self.lines:
            parts.append(f"{self.combo} combo")
        if self.perfect_clear:
            parts.append("PERFECT CLEAR")
        if self.attack:
            parts.append(f"+{self.attack} attack")
        return "  ".join(p for p in parts if p)


@dataclass
class Snapshot:
    board_rows: list[int]
    queue: list[str]
    hold: str | None
    hold_used: bool
    bag: list[str]
    rng_state: object
    piece: FallingPiece | None
    b2b: bool
    combo: int
    stats: dict
    history_len: int


@dataclass
class Game:
    seed: int = 0
    previews: int = 6
    board: Board = field(default_factory=Board)
    queue: list[str] = field(default_factory=list)
    hold: str | None = None
    hold_used: bool = False
    piece: FallingPiece | None = None
    b2b: bool = False
    combo: int = -1
    stats: dict = field(default_factory=lambda: {"pieces": 0, "lines": 0, "attack": 0, "tsd": 0, "tst": 0, "tetris": 0, "pc": 0})
    locks: list[Lock] = field(default_factory=list)
    dead: bool = False
    # rotation bookkeeping for T-spin detection
    last_was_rotation: bool = False
    last_kick: int | None = None
    last_from_rot: int = 0

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.bag: list[str] = []
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        while len(self.queue) < self.previews + 1:
            self.queue.append(self._draw())
        self.spawn()

    # ---------------------------------------------------------------- pieces
    def _draw(self) -> str:
        if not self.bag:
            self.bag = list(PIECES)
            self.rng.shuffle(self.bag)
        return self.bag.pop()

    def next_queue(self) -> list[str]:
        return self.queue[: self.previews]

    def spawn(self) -> bool:
        kind = self.queue.pop(0)
        self.queue.append(self._draw())
        self.piece = FallingPiece.spawn(kind, self.board)
        self.last_was_rotation, self.last_kick = False, None
        if self.piece is None:
            self.dead = True
            return False
        return True

    def set_state(self, board: Board, queue: list[str], hold: str | None = None, current: str | None = None) -> None:
        """Load a scenario: board, the pieces to come (current first unless `current` given), hold."""
        self.board = Board(list(board.rows))
        self.queue = list(queue)
        self.hold, self.hold_used = hold, False
        self.bag = []
        while len(self.queue) < self.previews + 1:
            self.queue.append(self._draw())
        if current:
            self.queue.insert(0, current)
        self.b2b, self.combo = False, -1
        self.locks.clear(); self._undo.clear(); self._redo.clear()
        self.dead = False
        self.spawn()

    # ---------------------------------------------------------------- moves
    def move(self, dx: int) -> bool:
        ok = self.piece.shift(self.board, dx)
        if ok:
            self.last_was_rotation = False
        return ok

    def rotate(self, cw: bool) -> int | None:
        """Returns the SRS kick index used (0 = no kick) or None if the rotation failed."""
        p = self.piece
        target = (p.rot + (1 if cw else -1)) % 4
        x0, y0, r0 = p.x, p.y, p.rot
        for i, ((x1, y1), (x2, y2)) in enumerate(zip(rotation_points(p.kind, r0), rotation_points(p.kind, target))):
            p.rot, p.x, p.y = target, x0 + x1 - x2, y0 + y1 - y2
            if not p.obstructed(self.board):
                self.last_was_rotation, self.last_kick, self.last_from_rot = True, i, r0
                return i
        p.rot, p.x, p.y = r0, x0, y0
        return None

    def soft_drop(self) -> bool:
        p = self.piece
        p.y -= 1
        if p.obstructed(self.board):
            p.y += 1
            return False
        self.last_was_rotation = False
        return True

    def sonic_drop(self) -> bool:
        fell = self.piece.sonic_drop(self.board)
        if fell:
            self.last_was_rotation = False
        return fell

    def landed(self) -> bool:
        p = FallingPiece(self.piece.kind, self.piece.rot, self.piece.x, self.piece.y - 1)
        return p.obstructed(self.board)

    def ghost(self) -> FallingPiece:
        g = FallingPiece(self.piece.kind, self.piece.rot, self.piece.x, self.piece.y)
        g.sonic_drop(self.board)
        return g

    def use_hold(self) -> bool:
        if self.hold_used:
            return False
        self._snapshot_for_undo()
        cur = self.piece.kind
        if self.hold is None:
            self.hold = cur
            self.spawn()
        else:
            self.hold, kind = cur, self.hold
            self.piece = FallingPiece.spawn(kind, self.board)
            self.last_was_rotation, self.last_kick = False, None
            if self.piece is None:
                self.dead = True
        self.hold_used = True
        return True

    # ---------------------------------------------------------------- locking
    def _tspin_status(self) -> str:
        p = self.piece
        if p.kind != "T" or not self.last_was_rotation:
            return ""
        # front corners (relative to rotation point) per orientation, as in libtetris
        front = {N: [(-1, 1), (1, 1)], E: [(1, 1), (1, -1)], S: [(1, -1), (-1, -1)], W: [(-1, -1), (-1, 1)]}[p.rot]
        back = {N: [(-1, -1), (1, -1)], E: [(-1, 1), (-1, -1)], S: [(-1, 1), (1, 1)], W: [(1, -1), (1, 1)]}[p.rot]
        occ = lambda dx, dy: not (0 <= p.x + dx < 10 and 0 <= p.y + dy < 40) or self.board.get(p.x + dx, p.y + dy)
        f = sum(occ(*c) for c in front)
        b = sum(occ(*c) for c in back)
        if f + b < 3:
            return ""
        return "full" if (self.last_kick == 4 or f == 2) else "mini"

    def hard_drop(self) -> Lock:
        self.piece.sonic_drop(self.board)
        # a hard drop that moved the piece is not a spin any more
        return self.lock()

    def lock(self) -> Lock:
        self._snapshot_for_undo()
        p = self.piece
        tspin = self._tspin_status()
        cells = p.cells()
        lines = self.board.place(cells)
        pc = lines > 0 and all(r == 0 for r in self.board.rows)
        if tspin == "full":
            kind = {0: "none", 1: "tss", 2: "tsd", 3: "tst"}[lines]
        elif tspin == "mini":
            kind = {0: "none", 1: "tsm", 2: "tsm2"}.get(lines, "tsd")
        else:
            kind = {0: "none", 1: "single", 2: "double", 3: "triple", 4: "tetris"}[lines]
        attack = ATTACK.get(kind, 0)
        b2b_bonus = False
        if lines:
            self.combo += 1
            attack += COMBO_GARBAGE[min(self.combo, len(COMBO_GARBAGE) - 1)]
            if kind in DIFFICULT:
                if self.b2b:
                    attack += 1; b2b_bonus = True
                self.b2b = True
            else:
                self.b2b = False
        else:
            self.combo = -1
        if pc:
            attack += 10
        kick = self.last_kick if tspin else None
        offset, rotation = None, ""
        if kick is not None:
            (x1, y1), (x2, y2) = rotation_points(p.kind, self.last_from_rot)[kick], rotation_points(p.kind, p.rot)[kick]
            offset = (x1 - x2, y1 - y2)
            rotation = f"{'NESW'[self.last_from_rot]}->{'NESW'[p.rot]}"
        lk = Lock(p.kind, cells, lines, kind, tspin, kick, offset, rotation,
                  b2b_bonus, max(self.combo, 0), attack, pc)
        self.locks.append(lk)
        st = self.stats
        st["pieces"] += 1; st["lines"] += lines; st["attack"] += attack
        if kind == "tsd": st["tsd"] += 1
        if kind == "tst": st["tst"] += 1
        if kind == "tetris": st["tetris"] += 1
        if pc: st["pc"] += 1
        self.hold_used = False
        self._redo.clear()
        self.spawn()
        return lk

    # ---------------------------------------------------------------- undo / redo
    def _snapshot(self) -> Snapshot:
        return Snapshot(list(self.board.rows), list(self.queue), self.hold, self.hold_used, list(self.bag),
                        self.rng.getstate(), copy.copy(self.piece), self.b2b, self.combo, dict(self.stats), len(self.locks))

    def _restore(self, s: Snapshot) -> None:
        self.board = Board(list(s.board_rows)); self.queue = list(s.queue); self.hold = s.hold
        self.hold_used = s.hold_used; self.bag = list(s.bag); self.rng.setstate(s.rng_state)
        self.piece = copy.copy(s.piece); self.b2b, self.combo = s.b2b, s.combo; self.stats = dict(s.stats)
        del self.locks[s.history_len:]
        self.dead = False
        self.last_was_rotation, self.last_kick = False, None

    def _snapshot_for_undo(self) -> None:
        self._undo.append(self._snapshot())

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def can_undo(self) -> int:
        return len(self._undo)
