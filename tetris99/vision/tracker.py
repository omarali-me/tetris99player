"""Turn per-frame readings (grid, hold, queue) into game state: locked board, active piece, spawns.

Key facts about Tetris 99 that this relies on:
- The next queue shifts at the exact moment a new piece spawns. That is the spawn trigger, and the
  piece that spawned is whatever was at the front of the queue before the shift. This is far more
  robust than trying to spot the piece itself, which can be partly hidden above the visible rows.
- Line clears and incoming garbage are resolved before the next piece spawns, so at spawn time the
  visible cells are exactly: locked stack + the new piece (parked near the top, columns 3-6).
- Hold swaps also shift the queue when the hold slot was empty; if it wasn't, the hold display changes.

So at each spawn we rebuild the locked board from the frame rather than trying to track clears and
garbage ourselves. Between spawns, active = visible cells - locked, sanity checked.

Coordinates: vision grid is [row][col] with row 0 at the top; engine boards use y up from the
bottom. `to_board()` converts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import BOARD_COLS, BOARD_ROWS
from ..engine.board import Board
from .board import FrameState
from .cells import Cell

Coord = tuple[int, int]  # (x, y) engine coordinates
SPAWN_ROWS = {BOARD_ROWS - 1, BOARD_ROWS - 2, BOARD_ROWS - 3}  # y=19,18,17
HUD_MIN_ROW = 14   # the Targeting widget covers roughly y >= 15; floating cells up there are not blocks
SPAWN_COLS = {2, 3, 4, 5, 6, 7}
PIECE_CELLS = {Cell.I, Cell.O, Cell.T, Cell.S, Cell.Z, Cell.J, Cell.L}
SOLID = PIECE_CELLS | {Cell.GARBAGE}


@dataclass
class Spawn:
    piece: str
    locked: Board
    hold: str | None
    queue: list[str]
    garbage_arrived: bool  # locked board differed from what we predicted
    new_pieces: list[str]  # queue entries revealed by this spawn (0, 1 or 2 pieces)
    incoming: int = 0      # garbage lines shown on the meter at spawn
    imminent: int = 0      # of those, lines already committed (red)


@dataclass
class TrackerState:
    locked: set[Coord] = field(default_factory=set)
    active: set[Coord] = field(default_factory=set)
    current: str | None = None
    hold: str | None = None
    queue: list[str] = field(default_factory=list)
    spawns: int = 0


def grid_cells(grid: list[list[Cell]]) -> dict[Coord, Cell]:
    out: dict[Coord, Cell] = {}
    for r, row in enumerate(grid):
        y = BOARD_ROWS - 1 - r
        for x, c in enumerate(row):
            if c in SOLID:
                out[(x, y)] = c
    return out


def to_board(cells: set[Coord]) -> Board:
    b = Board()
    for x, y in cells:
        if 0 <= y < 40:
            b.rows[y] |= 1 << x
    return b


def board_cells(board: Board) -> set[Coord]:
    return {(x, y) for y in range(40) for x in range(BOARD_COLS) if board.rows[y] >> x & 1}


def _component(start: Coord, cells: set[Coord]) -> set[Coord]:
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in cells and n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def grounded(cells: set[Coord]) -> set[Coord]:
    """Cells connected to the floor through other cells. Used to drop floating junk."""
    seen: set[Coord] = set()
    todo = [c for c in cells if c[1] == 0]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        x, y = c
        todo += [n for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if n in cells and n not in seen]
    return seen


def split_spawned(cells: dict[Coord, Cell], piece: str,
                  expected_locked: set[Coord] | None = None) -> tuple[set[Coord], set[Coord]]:
    """At spawn time, separate the freshly spawned piece from the locked stack.
    Returns (active, locked). Active may have fewer than 4 cells (rows above 19 are hidden).
    If the caller predicted the locked board and the frame agrees with it, trust that first: it is
    immune to the spawned piece touching same-colored stack cells."""
    visible = set(cells)
    if expected_locked is not None and expected_locked <= visible:
        extra = visible - expected_locked
        if len(extra) <= 4 and all(cells[c] is Cell(piece) for c in extra):
            return extra, expected_locked
    color = Cell(piece)
    candidates = {c for c, k in cells.items() if k is color and c[1] in SPAWN_ROWS and c[0] in SPAWN_COLS}
    best: set[Coord] = set()
    same_color = {c for c, k in cells.items() if k is color}
    for c in sorted(candidates, key=lambda c: -c[1]):
        comp = _component(c, same_color)
        if len(comp) <= 4 and comp <= candidates and len(comp) > len(best):
            best = comp
    return best, set(cells) - best


class Tracker:
    """Feed FrameState objects in order; returns a Spawn event when a new piece appears."""

    def __init__(self, confirm_frames: int = 2):
        self.state = TrackerState()
        self.confirm_frames = confirm_frames
        self._pending_queue: list[str] | None = None
        self._pending_count = 0
        self._pending_hold: str | None = None
        self._pending_hold_count = 0
        self._deferred: tuple[str, list[str], int] | None = None  # (piece, new pieces, frames left)
        self.recheck_frames = 5
        # Set by the caller when its last placement cleared lines. Tetris 99 has no line-clear delay:
        # the next piece spawns while the rows are still visibly collapsing, so the screen lags the
        # true board. Garbage never enters on a clearing placement, so the prediction is exact.
        self.trust_expected = False
        # Live play: read the locked board over this many extra frames after a spawn and take a
        # per-cell majority. Sparks, attack lines and flashes move from frame to frame; blocks don't.
        self.settle_frames = 0
        self._collect: dict | None = None
        self.expected_locked: set[Coord] | None = None  # set by the controller after a placement

    def _stable_queue(self, queue: list[str]) -> list[str] | None:
        """Debounce queue readings; returns the queue once it has been read identically N times."""
        if queue == self.state.queue:
            self._pending_queue, self._pending_count = None, 0
            return None
        if queue == self._pending_queue:
            self._pending_count += 1
        else:
            self._pending_queue, self._pending_count = queue, 1
        return queue if self._pending_count >= self.confirm_frames else None

    def _stable_hold(self, hold: str | None) -> bool:
        """True once a changed hold reading has been seen N times in a row."""
        if hold == self.state.hold:
            self._pending_hold, self._pending_hold_count = None, 0
            return False
        if hold == self._pending_hold:
            self._pending_hold_count += 1
        else:
            self._pending_hold, self._pending_hold_count = hold, 1
        return self._pending_hold_count >= self.confirm_frames

    def _emit(self, fs: FrameState, cells, spawned: str, new_pieces: list[str], final: bool) -> Spawn | None:
        """Build the spawn event. If the locked board disagrees with the caller's prediction, wait a
        few frames first: the lock flash and the line-clear collapse can still be on screen."""
        st = self.state
        if self.trust_expected and self.expected_locked is not None:
            locked = set(self.expected_locked)
            active, _ = split_spawned({c: k for c, k in cells.items() if c not in locked}, spawned, None)
            self.expected_locked, self.trust_expected, self._deferred = None, False, None
            st.locked, st.active, st.current = locked, active, spawned
            st.spawns += 1
            return Spawn(spawned, to_board(locked), st.hold, list(st.queue), False, new_pieces,
                         fs.garbage.imminent + fs.garbage.pending + fs.garbage.queued // 2, fs.garbage.imminent)
        active, locked = split_spawned(cells, spawned, self.expected_locked)
        # Overlays can read as blocks: the GO! banner mid-board at the start, and the Targeting widget
        # over the top rows in battle mode. Real stacks connect to the floor, EXCEPT that a line
        # clear can leave a genuine floating remnant lower down, so after the first spawn only the
        # widget's rows are filtered.
        connected = grounded(locked)
        if st.spawns == 0:
            locked = connected
        else:
            locked = {c for c in locked if c in connected or c[1] < HUD_MIN_ROW}
        if self.expected_locked is not None and locked != self.expected_locked and not final:
            return None
        garbage = self.expected_locked is not None and locked != self.expected_locked
        self.expected_locked = None
        self._deferred = None
        st.locked, st.active, st.current = locked, active, spawned
        st.spawns += 1
        return Spawn(spawned, to_board(locked), st.hold, list(st.queue), garbage, new_pieces,
                     fs.garbage.imminent + fs.garbage.pending + fs.garbage.queued // 2, fs.garbage.imminent)

    def _vote(self, fs: FrameState, cells) -> Spawn | None:
        """Temporal vote while collecting frames after a spawn (settle_frames > 0)."""
        st, col = self.state, self._collect
        active, locked = split_spawned(cells, col["piece"], self.expected_locked)
        col["locked"].append(locked); col["active"] = active or col["active"]
        col["left"] -= 1
        if col["left"] > 0:
            return None
        n = len(col["locked"])
        counts: dict[Coord, int] = {}
        for ls in col["locked"]:
            for c in ls:
                counts[c] = counts.get(c, 0) + 1
        voted = {c for c, k in counts.items() if k * 2 > n}
        connected = grounded(voted)
        voted = connected if st.spawns == 0 else {c for c in voted if c in connected or c[1] < HUD_MIN_ROW}
        if self.expected_locked is not None and voted != self.expected_locked and col["extensions"] < 2:
            # still disagrees with the prediction: an animation may be in progress, look a bit longer
            col["extensions"] += 1; col["left"] = self.settle_frames; col["locked"] = col["locked"][-2:]
            return None
        garbage = self.expected_locked is not None and voted != self.expected_locked
        piece, new_pieces = col["piece"], col["new_pieces"]
        self.expected_locked, self._collect = None, None
        st.locked, st.active, st.current = voted, col["active"], piece
        st.spawns += 1
        return Spawn(piece, to_board(voted), st.hold, list(st.queue), garbage, new_pieces,
                     fs.garbage.imminent + fs.garbage.pending + fs.garbage.queued // 2, fs.garbage.imminent)

    def update(self, fs: FrameState) -> Spawn | None:
        st = self.state
        cells = grid_cells(fs.grid)
        if self._collect is not None:
            return self._vote(fs, cells)
        if self._deferred is not None:
            piece, new_pieces, left = self._deferred
            ev = self._emit(fs, cells, piece, new_pieces, final=left <= 1)
            if ev is None:
                self._deferred = (piece, new_pieces, left - 1)
            return ev
        queue = [q.value for q in fs.queue if q is not None]
        if len(queue) != len(fs.queue):
            queue = st.queue  # unreadable slot: keep last reading
        hold = fs.hold.value if fs.hold else None

        new_queue = self._stable_queue(queue)
        spawned: str | None = None
        new_pieces: list[str] = []
        if new_queue is not None:
            if not st.queue:
                spawned = None  # first reading; no piece info yet
            elif new_queue[:-1] == st.queue[1:]:
                spawned = st.queue[0]
                new_pieces = new_queue[-1:]
            elif new_queue[:-2] == st.queue[2:]:
                # hold used on an empty hold slot: queue advanced by two
                spawned = st.queue[1]
                new_pieces = new_queue[-2:]
            else:
                spawned = st.queue[0]  # misread or game start; best effort
                new_pieces = list(new_queue)
            st.queue = new_queue
            self._pending_queue, self._pending_count = None, 0
        hold_changed = self._stable_hold(hold)
        if spawned is None and hold_changed and queue == st.queue and hold is not None and st.hold is not None and st.current:
            # hold swap with a non-empty slot: the old hold piece spawns, queue unchanged
            spawned, st.hold = st.hold, hold
        elif spawned is not None:
            if hold is not None:
                st.hold = hold
        elif hold_changed:
            st.hold = hold

        if spawned is not None and self.settle_frames > 0 and not (self.trust_expected and self.expected_locked is not None):
            self._pending_hold, self._pending_hold_count = None, 0
            self._collect = {"piece": spawned, "new_pieces": new_pieces, "locked": [], "active": set(),
                             "left": self.settle_frames + 1, "extensions": 0}
            return self._vote(fs, cells)
        if spawned is not None:
            self._pending_hold, self._pending_hold_count = None, 0
            ev = self._emit(fs, cells, spawned, new_pieces, final=self.recheck_frames <= 0)
            if ev is None:
                self._deferred = (spawned, new_pieces, self.recheck_frames)
            return ev

        # between spawns: the active piece is whatever shows the current piece's colour outside the
        # locked stack. Matching on colour keeps sparks and other overlays out of it.
        if st.current:
            colour = Cell(st.current)
            mine = {c for c, k in cells.items() if k is colour and c not in st.locked}
            if 1 <= len(mine) <= 4:
                st.active = mine

        # The first piece of a match spawns without the queue shifting (the queue is already drawn
        # during the countdown), so it has to be recognised directly: one small single-coloured group
        # at the very top of an otherwise empty upper board, seen on a few consecutive frames.
        if st.spawns == 0 and st.current is None and len(st.queue) == len(fs.queue) and not self._collect:
            top = {c: k for c, k in cells.items() if c[1] >= BOARD_ROWS - 3 and k in PIECE_CELLS}
            kinds = {k for k in top.values()}
            upper_clear = not any(BOARD_ROWS - 8 <= c[1] < BOARD_ROWS - 3 for c in cells)
            if len(kinds) == 1 and 2 <= len(top) <= 4 and upper_clear and queue == st.queue:
                kind = next(iter(kinds)).value
                self._first_seen = self._first_seen + 1 if getattr(self, "_first_kind", None) == kind else 1
                self._first_kind = kind
                if self._first_seen >= 3:
                    locked = grounded({c for c in cells if c not in top})
                    st.locked, st.active, st.current = locked, set(top), kind
                    st.spawns += 1
                    self.first_piece_detected = True
                    return Spawn(kind, to_board(locked), st.hold, list(st.queue), False, [],
                                 fs.garbage.imminent + fs.garbage.pending + fs.garbage.queued // 2, fs.garbage.imminent)
            else:
                self._first_seen = 0
        return None
