"""Render a FrameState from engine state. Used by tests and the dry-run loop before real capture."""
from __future__ import annotations

from ..config import BOARD_COLS, BOARD_ROWS
from ..engine.board import Board
from ..engine.piece import FallingPiece
from .board import FrameState
from .cells import Cell
from .tracker import board_cells


def render(board: Board, piece: FallingPiece | None, hold: str | None, queue: list[str],
           colors: dict | None = None) -> FrameState:
    grid = [[Cell.EMPTY] * BOARD_COLS for _ in range(BOARD_ROWS)]
    colors = colors or {}
    for x, y in board_cells(board):
        if y < BOARD_ROWS:
            grid[BOARD_ROWS - 1 - y][x] = colors.get((x, y), Cell.GARBAGE)
    if piece:
        for x, y in piece.cells():
            if y < BOARD_ROWS:
                grid[BOARD_ROWS - 1 - y][x] = Cell(piece.kind)
    return FrameState(grid=grid, hold=Cell(hold) if hold else None, queue=[Cell(q) for q in queue])
