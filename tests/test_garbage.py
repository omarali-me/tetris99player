import numpy as np

from tetris99.config import Layout, Rect
from tetris99.vision.garbage import read_garbage_meter


def make_frame(layout: Layout, yellow: int, red: int) -> np.ndarray:
    frame = np.zeros((1080, 1920, 3), np.uint8)
    m = layout.garbage_meter
    cell_h = m.h / 20
    for i in range(yellow + red):
        y1 = int(m.y + m.h - (i + 1) * cell_h)
        y0 = int(m.y + m.h - i * cell_h)
        color = (0, 0, 220) if i < red else (0, 200, 240)  # BGR: red segments sit at the bottom
        frame[y1:y0, m.x : m.x + m.w] = color
    return frame


def test_meter_counts_segments():
    layout = Layout(garbage_meter=Rect(775, 145, 15, 660))
    assert read_garbage_meter(make_frame(layout, 0, 0), layout).total == 0
    g = read_garbage_meter(make_frame(layout, 3, 0), layout)
    assert (g.pending, g.imminent) == (3, 0)
    g = read_garbage_meter(make_frame(layout, 2, 4), layout)
    assert (g.pending, g.imminent) == (2, 4)
    g = read_garbage_meter(make_frame(layout, 0, 20), layout)
    assert g.imminent == 20
