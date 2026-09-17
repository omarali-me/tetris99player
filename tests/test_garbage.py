import numpy as np

from tetris99.config import Layout
from tetris99.vision.garbage import SEG, read_garbage_meter


def make_frame(layout: Layout, yellow: int, red: int, grey: int = 0) -> np.ndarray:
    """Draw segments the way the game does: 48 px tall with a dark 4 px top edge, oldest at the
    bottom (red, then yellow, then grey), and an 8 px gap before the grey group."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    m = layout.garbage_meter
    bottom = m.y + m.h
    y = bottom
    for i in range(yellow + red + grey):
        if i == red + yellow and grey:
            y -= 8  # gap between attacks
        color = (0, 0, 220) if i < red else (0, 200, 240) if i < red + yellow else (150, 150, 150)
        frame[y - SEG : y - 4, m.x : m.x + m.w] = color   # top 4 px stay dark: the bevel edge
        y -= SEG
    return frame


def test_meter_counts_segments():
    layout = Layout()
    assert read_garbage_meter(make_frame(layout, 0, 0), layout).total == 0
    g = read_garbage_meter(make_frame(layout, 3, 0), layout)
    assert (g.pending, g.imminent, g.queued) == (3, 0, 0)
    g = read_garbage_meter(make_frame(layout, 2, 4), layout)
    assert (g.pending, g.imminent) == (2, 4)
    g = read_garbage_meter(make_frame(layout, 3, 1, grey=4), layout)
    assert (g.imminent, g.pending, g.queued, g.total) == (1, 3, 4, 8)
    g = read_garbage_meter(make_frame(layout, 0, 0, grey=12), layout)
    assert g.queued == 12
