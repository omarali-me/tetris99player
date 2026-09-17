"""Draw a game state as an image (OpenCV). Used by tools/watch.py."""
from __future__ import annotations

import cv2
import numpy as np

from .config import BOARD_COLS, BOARD_ROWS
from .engine.board import Board
from .engine.piece import CELLS, FallingPiece

CELL = 30
COLORS = {  # BGR
    "I": (215, 205, 0), "O": (0, 210, 240), "T": (200, 50, 170), "S": (60, 200, 60),
    "Z": (50, 50, 230), "J": (220, 90, 30), "L": (20, 140, 250), "G": (120, 120, 120),
}
BG = (24, 24, 28)
GRID = (45, 45, 52)
TEXT = (230, 230, 230)

BOARD_X, BOARD_Y = 200, 40
W, H = BOARD_X + BOARD_COLS * CELL + 220, BOARD_Y + BOARD_ROWS * CELL + 40


def _block(img, px, py, color, size=CELL, dim=False):
    c = tuple(int(v * (0.35 if dim else 1)) for v in color)
    cv2.rectangle(img, (px + 1, py + 1), (px + size - 1, py + size - 1), c, -1)
    if not dim:
        hi = tuple(min(255, int(v * 1.35)) for v in color)
        cv2.rectangle(img, (px + 1, py + 1), (px + size - 1, py + size - 1), hi, 1)


def _mini_piece(img, kind, cx, cy, size=18):
    for dx, dy in CELLS[(kind, 0)]:
        _block(img, cx + dx * size, cy - dy * size, COLORS[kind], size)


METER_W = 14
PENDING = (0, 200, 240)   # yellow: announced
IMMINENT = (40, 40, 230)  # red: committed, drops at next lock


def draw(board: Board, piece: FallingPiece | None, hold: str | None, queue: list[str],
         colors: dict[tuple[int, int], str] | None = None, info: list[str] = (),
         garbage_pending: int = 0, garbage_imminent: int = 0) -> np.ndarray:
    img = np.full((H, W, 3), BG, np.uint8)
    colors = colors or {}

    # incoming-garbage meter, like Tetris 99: a bar to the left of the board, filling from the bottom
    mx = BOARD_X - METER_W - 8
    top, bottom = BOARD_Y, BOARD_Y + BOARD_ROWS * CELL
    cv2.rectangle(img, (mx, top), (mx + METER_W, bottom), GRID, 1)
    for i in range(min(BOARD_ROWS, garbage_pending + garbage_imminent)):
        color = IMMINENT if i < garbage_imminent else PENDING
        y0 = bottom - (i + 1) * CELL + 2
        cv2.rectangle(img, (mx + 2, y0), (mx + METER_W - 2, y0 + CELL - 4), color, -1)

    def px(x, y):
        return BOARD_X + x * CELL, BOARD_Y + (BOARD_ROWS - 1 - y) * CELL

    for y in range(BOARD_ROWS):
        for x in range(BOARD_COLS):
            X, Y = px(x, y)
            cv2.rectangle(img, (X, Y), (X + CELL, Y + CELL), GRID, 1)
            if board.rows[y] >> x & 1:
                _block(img, X, Y, COLORS[colors.get((x, y), "G")])
    if piece:
        ghost = FallingPiece(piece.kind, piece.rot, piece.x, piece.y)
        ghost.sonic_drop(board)
        for x, y in ghost.cells():
            if y < BOARD_ROWS:
                _block(img, *px(x, y), COLORS[piece.kind], dim=True)
        for x, y in piece.cells():
            if y < BOARD_ROWS:
                _block(img, *px(x, y), COLORS[piece.kind])
    cv2.rectangle(img, (BOARD_X - 1, BOARD_Y - 1), (BOARD_X + BOARD_COLS * CELL + 1, BOARD_Y + BOARD_ROWS * CELL + 1), (90, 90, 100), 2)

    cv2.putText(img, "HOLD", (60, BOARD_Y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT, 1)
    if hold:
        _mini_piece(img, hold, 70, BOARD_Y + 70)
    qx = BOARD_X + BOARD_COLS * CELL + 40
    cv2.putText(img, "NEXT", (qx, BOARD_Y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT, 1)
    for i, q in enumerate(queue[:6]):
        _mini_piece(img, q, qx + 20, BOARD_Y + 70 + i * 70)
    for i, line in enumerate(info):
        cv2.putText(img, line, (20, BOARD_Y + 150 + i * 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT, 1)
    return img
