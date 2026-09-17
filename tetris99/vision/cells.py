"""Classify a single board cell by color.

Tetris 99 uses guideline colors. Values are HSV hue ranges (OpenCV hue is 0-179).
Ghost pieces are the same hue but much dimmer/less saturated; garbage is gray.
Thresholds were measured on real 1080p capture frames (2026-09-17). Observed medians:
  I 91 · L 9-11 · O 25-26 · S 49-50 · J ~124 · T 140-141 · Z 171 (hue), sat 193-255, val 176-223.
Garbage blocks in the playfield: hue ~30, sat 0-5, val 111, and perfectly flat at the cell centre.
HUD overlays drawn over the top rows (the Targeting widget): the highlighted pill is sat ~100 /
val <= 101 (coloured but dim -> ignored as ghost), the text is grey but high-variance. So garbage
must be nearly unsaturated, bright enough, and flat; anything else grey is empty.
"""
from __future__ import annotations

from enum import Enum

import cv2
import numpy as np


class Cell(str, Enum):
    EMPTY = "."
    I = "I"
    O = "O"
    T = "T"
    S = "S"
    Z = "Z"
    J = "J"
    L = "L"
    GARBAGE = "G"
    GHOST = "g"


# (hue_lo, hue_hi) inclusive, OpenCV scale. Red wraps around.
HUE_RANGES: dict[Cell, tuple[int, int]] = {
    Cell.I: (84, 98),    # cyan      (measured 91)
    Cell.O: (19, 31),    # yellow    (25-26)
    Cell.T: (132, 150),  # purple    (140-141)
    Cell.S: (42, 60),    # green     (49-50)
    Cell.Z: (0, 5),      # red       (171, wraps; also 164-179 below)
    Cell.J: (112, 132),  # blue      (~124)
    Cell.L: (6, 16),     # orange    (9-11)
}
Z_WRAP_MIN = 164

SAT_MIN = 130           # coloured blocks are >= 190
VAL_MIN_BLOCK = 150     # coloured but dimmer than this: ghost outline or a HUD overlay -> ignored
GARBAGE_SAT_MAX = 60    # garbage is sat 0-5 (up to ~45 under the animated attack ray); the Targeting pill is ~100
VAL_MIN_GARBAGE = 95    # garbage is val 111; HUD text medians stay <= ~75
GARBAGE_STD_MAX = 12    # garbage centres are flat (std 0); text is ~40
VAL_MAX_EMPTY = 60


def classify_patch(bgr_patch: np.ndarray) -> Cell:
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    h, s, v = (int(np.median(hsv[..., i])) for i in range(3))

    if v < VAL_MAX_EMPTY:
        return Cell.EMPTY
    if s < SAT_MIN:
        flat = float(hsv[..., 2].std()) <= GARBAGE_STD_MAX
        return Cell.GARBAGE if (s <= GARBAGE_SAT_MAX and v >= VAL_MIN_GARBAGE and flat) else Cell.EMPTY

    piece = Cell.EMPTY
    if h >= Z_WRAP_MIN:
        piece = Cell.Z
    else:
        for cell, (lo, hi) in HUE_RANGES.items():
            if lo <= h <= hi:
                piece = cell
                break
    if piece is Cell.EMPTY:
        return Cell.EMPTY
    if v < VAL_MIN_BLOCK:
        return Cell.GHOST
    return piece
