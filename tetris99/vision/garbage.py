"""Read the incoming-garbage meter: the vertical bar on the left of the playfield.

Each incoming garbage line is one segment, stacked from the bottom, one board-cell tall (48 px at
1080p). Segments age through three colours, oldest at the bottom: grey when just queued, yellow as
they get close, red when about to be added. Measured on real frames 2026-09-17: grey segments have
sat <= ~117 like garbage blocks; yellow hue ~25; red hue ~171/0.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..config import BOARD_ROWS, Layout

VAL_MIN = 115      # below this the segment slot is empty (HUD text is ~75)
SAT_MIN = 130      # coloured segments are far above this; grey ones below
RED_HUES = ((0, 8), (160, 179))
YELLOW_HUES = ((12, 40),)


@dataclass
class GarbageMeter:
    pending: int        # yellow: getting close
    imminent: int       # red: will drop in at the next lock
    queued: int = 0     # grey: just received, furthest from dropping

    @property
    def total(self) -> int:
        return self.queued + self.pending + self.imminent


def _in_ranges(h: int, ranges) -> bool:
    return any(lo <= h <= hi for lo, hi in ranges)


SEG = 48          # segment height in px at 1080p, same as a board cell
EDGE_DARK = 4     # each segment has a dark band ~4 px at its top edge
GAP_MAX = 14      # attacks from different senders are separated by ~8 px gaps
BODY = SEG // 2   # where to sample a segment's colour, measured from its bottom


def read_garbage_meter(frame: np.ndarray, layout: Layout) -> GarbageMeter:
    """Walk up the centre of the bar one segment at a time. Segments are 48 px with a dark top
    edge; consecutive attacks may be separated by a small gap. Re-anchoring on each segment's top
    edge keeps the walk from drifting."""
    m = layout.garbage_meter
    cx = m.x + m.w // 2
    half = max(1, m.w // 4)
    hsv = cv2.cvtColor(frame[m.y : m.y + m.h, cx - half : cx + half + 1], cv2.COLOR_BGR2HSV)
    col = np.median(hsv, axis=1).astype(int)          # (m.h, 3): median across the bar's width
    top_limit = 0
    y = m.h - 1                                        # bottom row of the bar, local coordinates
    pending = imminent = queued = 0

    def val(i):
        return col[i, 2] if 0 <= i < m.h else 0

    while pending + imminent + queued < BOARD_ROWS:
        gap = 0
        while y >= top_limit and val(y) < VAL_MIN and gap < GAP_MAX:
            y -= 1; gap += 1
        if y < top_limit or val(y) < VAL_MIN:
            break
        h, s, v = (int(x) for x in col[max(top_limit, y - BODY)])
        if s < SAT_MIN:
            queued += 1
        elif _in_ranges(h, RED_HUES):
            imminent += 1
        elif _in_ranges(h, YELLOW_HUES):
            pending += 1
        else:
            break
        # re-anchor: find this segment's dark top edge within one segment height
        top = y - SEG
        for i in range(y - BODY, max(top_limit - 1, y - SEG - EDGE_DARK), -1):
            if val(i) < VAL_MIN:
                top = i
                break
        y = top
    return GarbageMeter(pending, imminent, queued)
