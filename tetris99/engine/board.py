"""Minimal Tetris board model (10 wide, 40 tall, row 0 = bottom) used by the simulator and
to reconcile vision output with expected state. The decision engine (Cold Clear) is wired in
separately in engine/coldclear.py."""
from __future__ import annotations

from dataclasses import dataclass, field

COLS, ROWS = 10, 40
FULL_ROW = (1 << COLS) - 1

# SRS spawn shapes, as (x, y) offsets, y up.
SHAPES: dict[str, list[list[tuple[int, int]]]] = {
    "I": [[(0, 0), (1, 0), (2, 0), (3, 0)], [(2, 1), (2, 0), (2, -1), (2, -2)],
          [(0, -1), (1, -1), (2, -1), (3, -1)], [(1, 1), (1, 0), (1, -1), (1, -2)]],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]] * 4,
    "T": [[(0, 0), (1, 0), (2, 0), (1, 1)], [(1, 1), (1, 0), (1, -1), (2, 0)],
          [(0, 0), (1, 0), (2, 0), (1, -1)], [(1, 1), (1, 0), (1, -1), (0, 0)]],
    "S": [[(1, 0), (2, 0), (0, -1), (1, -1)], [(1, 1), (1, 0), (2, 0), (2, -1)],
          [(1, 0), (2, 0), (0, -1), (1, -1)], [(1, 1), (1, 0), (2, 0), (2, -1)]],
    "Z": [[(0, 0), (1, 0), (1, -1), (2, -1)], [(2, 1), (1, 0), (2, 0), (1, -1)],
          [(0, 0), (1, 0), (1, -1), (2, -1)], [(2, 1), (1, 0), (2, 0), (1, -1)]],
    "J": [[(0, 1), (0, 0), (1, 0), (2, 0)], [(1, 1), (2, 1), (1, 0), (1, -1)],
          [(0, 0), (1, 0), (2, 0), (2, -1)], [(1, 1), (1, 0), (0, -1), (1, -1)]],
    "L": [[(2, 1), (0, 0), (1, 0), (2, 0)], [(1, 1), (1, 0), (1, -1), (2, -1)],
          [(0, 0), (1, 0), (2, 0), (0, -1)], [(0, 1), (1, 1), (1, 0), (1, -1)]],
}


@dataclass
class Board:
    rows: list[int] = field(default_factory=lambda: [0] * ROWS)  # bitmask per row, bit c = column c

    def get(self, x: int, y: int) -> bool:
        return 0 <= x < COLS and 0 <= y < ROWS and bool(self.rows[y] >> x & 1)

    def fits(self, cells: list[tuple[int, int]]) -> bool:
        return all(0 <= x < COLS and 0 <= y < ROWS and not self.get(x, y) for x, y in cells)

    def place(self, cells: list[tuple[int, int]]) -> int:
        """Lock cells, clear full lines, return number cleared."""
        for x, y in cells:
            self.rows[y] |= 1 << x
        kept = [r for r in self.rows if r != FULL_ROW]
        cleared = ROWS - len(kept)
        self.rows = kept + [0] * cleared
        return cleared

    def add_garbage(self, lines: int, hole_col: int) -> None:
        garbage = FULL_ROW & ~(1 << hole_col)
        self.rows = [garbage] * lines + self.rows[: ROWS - lines]

    def height(self) -> int:
        for y in range(ROWS - 1, -1, -1):
            if self.rows[y]:
                return y + 1
        return 0

    @classmethod
    def from_grid(cls, grid: list[list[str]]) -> "Board":
        """Build from a visible 20-row grid (row 0 = top) of cell characters; '.' and 'g' are empty."""
        b = cls()
        visible = len(grid)
        for r, row in enumerate(grid):
            y = visible - 1 - r
            for x, ch in enumerate(row):
                if ch not in (".", "g"):
                    b.rows[y] |= 1 << x
        return b

    def __str__(self) -> str:
        top = max(self.height(), 20)
        return "\n".join(
            "".join("#" if self.get(x, y) else "." for x in range(COLS)) for y in range(top - 1, -1, -1)
        )
