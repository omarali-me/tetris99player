"""Read the incoming-garbage meter: the vertical bar on the left of the playfield.

Each pending garbage line is one segment, stacked from the bottom, one board-cell tall. Segments are
yellow/orange while the sender's attack is still in flight and turn red once the lines are committed
and will be added at the next lock. We sample one patch per cell row along the bar and classify it.
Thresholds are starting points; tune against real frames with tools/preview.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..config import BOARD_ROWS, Layout

VAL_MIN = 90       # below this the segment slot is empty
SAT_MIN = 80
RED_HUES = ((0, 10), (165, 179))
YELLOW_HUES = ((12, 40),)


@dataclass
class GarbageMeter:
    pending: int    # yellow: announced, not yet committed
    imminent: int   # red: will drop in at the next lock

    @property
    def total(self) -> int:
        return self.pending + self.imminent


def _in_ranges(h: int, ranges) -> bool:
    return any(lo <= h <= hi for lo, hi in ranges)


def read_garbage_meter(frame: np.ndarray, layout: Layout) -> GarbageMeter:
    m = layout.garbage_meter
    cell_h = m.h / BOARD_ROWS
    cx = m.x + m.w // 2
    half = max(1, m.w // 4)
    pending = imminent = 0
    for i in range(BOARD_ROWS):
        # row i counts from the bottom of the meter
        cy = int(m.y + m.h - (i + 0.5) * cell_h)
        patch = frame[cy - 2 : cy + 3, cx - half : cx + half + 1]
        if patch.size == 0:
            break
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        h, s, v = (int(np.median(hsv[..., k])) for k in range(3))
        if v < VAL_MIN or s < SAT_MIN:
            break  # segments are contiguous from the bottom; first empty slot ends the bar
        if _in_ranges(h, RED_HUES):
            imminent += 1
        elif _in_ranges(h, YELLOW_HUES):
            pending += 1
        else:
            break
    return GarbageMeter(pending, imminent)
