"""Classify a single board cell by color.

Tetris 99 uses guideline colors. Values are HSV hue ranges (OpenCV hue is 0-179).
Ghost pieces are the same hue but much dimmer/less saturated; garbage is gray.
Thresholds here are starting points; tune with tools/preview.py against real frames.
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
    Cell.I: (85, 100),   # cyan
    Cell.O: (22, 35),    # yellow
    Cell.T: (130, 155),  # purple
    Cell.S: (45, 75),    # green
    Cell.Z: (0, 8),      # red (also 170-179)
    Cell.J: (105, 125),  # blue
    Cell.L: (9, 21),     # orange
}

SAT_MIN = 90      # below this: gray (garbage) or dark (empty)
VAL_MIN_BLOCK = 120
VAL_MIN_GARBAGE = 90
VAL_MAX_EMPTY = 60
GHOST_VAL_MAX = 110  # colored but dim → ghost


def classify_patch(bgr_patch: np.ndarray) -> Cell:
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    h, s, v = (int(np.median(hsv[..., i])) for i in range(3))

    if v < VAL_MAX_EMPTY:
        return Cell.EMPTY
    if s < SAT_MIN:
        return Cell.GARBAGE if v >= VAL_MIN_GARBAGE else Cell.EMPTY

    piece = Cell.EMPTY
    if h >= 170:
        piece = Cell.Z
    else:
        for cell, (lo, hi) in HUE_RANGES.items():
            if lo <= h <= hi:
                piece = cell
                break
    if piece is Cell.EMPTY:
        return Cell.EMPTY
    if v < GHOST_VAL_MAX:
        return Cell.GHOST
    return piece
