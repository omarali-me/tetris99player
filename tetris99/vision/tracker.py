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

    def update(self, fs: FrameState) -> Spawn | None:
        st = self.state
        cells = grid_cells(fs.grid)
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

        if spawned is not None:
            self._pending_hold, self._pending_hold_count = None, 0
            active, locked = split_spawned(cells, spawned, self.expected_locked)
            garbage = self.expected_locked is not None and locked != self.expected_locked
            self.expected_locked = None
            st.locked, st.active, st.current = locked, active, spawned
            st.spawns += 1
            return Spawn(spawned, to_board(locked), st.hold, list(st.queue), garbage, new_pieces)

        # between spawns: attribute non-locked cells to the active piece
        visible = set(cells)
        if st.locked <= visible:
            extra = visible - st.locked
            if len(extra) <= 4:
                st.active = extra
        return None
