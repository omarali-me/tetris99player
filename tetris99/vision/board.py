"""Extract board, hold and queue from a 1080p frame."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import BOARD_COLS, BOARD_ROWS, Layout
from .cells import Cell, classify_patch
from .garbage import GarbageMeter, read_garbage_meter

PATCH = 3  # half-size of the sampled square around each cell center


@dataclass
class FrameState:
    grid: list[list[Cell]]          # [row][col], row 0 = top
    hold: Cell | None
    queue: list[Cell]
    garbage: GarbageMeter = field(default_factory=lambda: GarbageMeter(0, 0))

    def board_str(self) -> str:
        return "\n".join("".join(c.value for c in row) for row in self.grid)


def read_grid(frame: np.ndarray, layout: Layout) -> list[list[Cell]]:
    grid = []
    for r in range(BOARD_ROWS):
        row = []
        for c in range(BOARD_COLS):
            x, y = layout.cell_center(r, c)
            row.append(classify_patch(frame[y - PATCH : y + PATCH + 1, x - PATCH : x + PATCH + 1]))
        grid.append(row)
    return grid


def read_piece_box(frame: np.ndarray, box) -> Cell | None:
    """Identify the tetromino drawn in a hold/queue box by its dominant colored pixels."""
    roi = frame[box.y : box.y + box.h, box.x : box.x + box.w]
    counts: dict[Cell, int] = {}
    step = 4
    for y in range(0, roi.shape[0] - PATCH * 2, step):
        for x in range(0, roi.shape[1] - PATCH * 2, step):
            cell = classify_patch(roi[y : y + PATCH * 2 + 1, x : x + PATCH * 2 + 1])
            if cell not in (Cell.EMPTY, Cell.GARBAGE, Cell.GHOST):
                counts[cell] = counts.get(cell, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def read_frame(frame: np.ndarray, layout: Layout) -> FrameState:
    return FrameState(
        grid=read_grid(frame, layout),
        hold=read_piece_box(frame, layout.hold),
        queue=[read_piece_box(frame, q) for q in layout.queue],
        garbage=read_garbage_meter(frame, layout),
    )
