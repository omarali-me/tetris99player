"""Extract board, hold and queue from a 1080p frame.

Everything is vectorised: one HSV conversion per region, numpy for the rest. A full read_frame
is ~2 ms, which matters because the loop must keep up with 60 fps capture."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config import BOARD_COLS, BOARD_ROWS, Layout, Rect
from .cells import (Cell, GARBAGE_FLAT_FRAC, GARBAGE_SAT_MAX, GARBAGE_STD_MAX, HUE_RANGES, SAT_MIN,
                    VAL_MAX_EMPTY, VAL_MAX_GARBAGE, VAL_MIN_BLOCK, VAL_MIN_GARBAGE, Z_WRAP_MIN)
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


# ---------------------------------------------------------------- hue lookup table
def _hue_table() -> np.ndarray:
    """hue (0..179) -> piece index into PIECE_ORDER, or -1 when the hue is in a gap."""
    table = np.full(180, -1, np.int8)
    for i, cell in enumerate(PIECE_ORDER):
        lo, hi = HUE_RANGES[cell]
        table[lo : hi + 1] = i
    table[Z_WRAP_MIN:] = PIECE_ORDER.index(Cell.Z)
    return table


PIECE_ORDER = [Cell.I, Cell.O, Cell.T, Cell.S, Cell.Z, Cell.J, Cell.L]
HUE_TABLE = _hue_table()


CODE_CELLS = [Cell.EMPTY, Cell.GARBAGE, Cell.GHOST, *PIECE_ORDER]  # index = classification code


def classify_hsv(h: np.ndarray, s: np.ndarray, v: np.ndarray, v_std: np.ndarray,
                 v_flat: np.ndarray) -> np.ndarray:
    """Vectorised version of cells.classify_patch on arrays of per-cell median H, S, V, the std of
    V over the patch, and the fraction of V pixels within 10 of the median. Returns integer codes
    indexing CODE_CELLS."""
    out = np.zeros(h.shape, np.int8)
    grey = (v >= VAL_MAX_EMPTY) & (s < SAT_MIN)
    flat = (v_std <= GARBAGE_STD_MAX) | (v_flat >= GARBAGE_FLAT_FRAC)
    out[grey & (s <= GARBAGE_SAT_MAX) & (v >= VAL_MIN_GARBAGE) & (v <= VAL_MAX_GARBAGE) & flat] = 1
    coloured = (v >= VAL_MAX_EMPTY) & (s >= SAT_MIN)
    idx = HUE_TABLE[h]
    known = coloured & (idx >= 0)
    out[known & (v >= VAL_MIN_BLOCK)] = (idx[known & (v >= VAL_MIN_BLOCK)] + 3).astype(np.int8)
    out[known & (v < VAL_MIN_BLOCK)] = 2
    return out


# ---------------------------------------------------------------- board grid
class _GridSampler:
    """Precomputed pixel indices for the 200 cell patches of a layout."""

    def __init__(self, layout: Layout):
        self.layout = layout
        ys, xs = [], []
        for r in range(BOARD_ROWS):
            for c in range(BOARD_COLS):
                x, y = layout.cell_center(r, c)
                yy, xx = np.mgrid[y - PATCH : y + PATCH + 1, x - PATCH : x + PATCH + 1]
                ys.append(yy.ravel()); xs.append(xx.ravel())
        self.ys = np.array(ys); self.xs = np.array(xs)      # (200, 49)

    def medians(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        pix = frame[self.ys, self.xs]                        # (200, 49, 3) BGR
        hsv = cv2.cvtColor(pix.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(pix.shape)
        med = np.median(hsv, axis=1).astype(np.int32)        # (200, 3)
        vals = hsv[:, :, 2].astype(np.int32)
        v_std = vals.astype(np.float32).std(axis=1)
        v_flat = (np.abs(vals - med[:, 2:3]) <= 10).mean(axis=1)
        return med[:, 0], med[:, 1], med[:, 2], v_std, v_flat


_samplers: dict[int, _GridSampler] = {}


def _sampler(layout: Layout) -> _GridSampler:
    key = id(layout)
    if key not in _samplers:
        _samplers[key] = _GridSampler(layout)
    return _samplers[key]


def read_grid(frame: np.ndarray, layout: Layout) -> list[list[Cell]]:
    h, s, v, v_std, v_flat = _sampler(layout).medians(frame)
    codes = classify_hsv(h, s, v, v_std, v_flat).reshape(BOARD_ROWS, BOARD_COLS)
    return [[CODE_CELLS[c] for c in row] for row in codes]


# ---------------------------------------------------------------- hold / queue boxes
MIN_PIECE_PIXELS = 150  # a drawn preview piece is a few thousand vivid pixels; below this, empty


def read_piece_box(frame: np.ndarray, box: Rect) -> Cell | None:
    """Identify the tetromino drawn in a hold/queue box by the dominant vivid hue."""
    roi = frame[box.y : box.y + box.h, box.x : box.x + box.w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    vivid = (hsv[..., 1] >= SAT_MIN) & (hsv[..., 2] >= VAL_MIN_BLOCK)
    if int(vivid.sum()) < MIN_PIECE_PIXELS:
        return None
    idx = HUE_TABLE[hsv[..., 0][vivid]]
    counts = np.bincount(idx[idx >= 0], minlength=len(PIECE_ORDER))
    if counts.sum() < MIN_PIECE_PIXELS:
        return None
    return PIECE_ORDER[int(counts.argmax())]


def read_frame(frame: np.ndarray, layout: Layout) -> FrameState:
    return FrameState(
        grid=read_grid(frame, layout),
        hold=read_piece_box(frame, layout.hold),
        queue=[read_piece_box(frame, q) for q in layout.queue],
        garbage=read_garbage_meter(frame, layout),
    )
