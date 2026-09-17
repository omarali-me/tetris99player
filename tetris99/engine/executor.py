"""Turn a Cold Clear move into controller actions and verify by replay against the piece model.

Cold Clear paths are lists of LEFT/RIGHT/CW/CCW/DROP with an implicit hard drop at the end.
Runs of LEFT/RIGHT that end against a wall (or the stack) are replaced by a DAS hold, which is
one input instead of several and deterministic under auto-shift."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .board import Board
from .coldclear import Move, Movement
from .piece import FallingPiece

Kind = Literal["hold", "cw", "ccw", "left", "right", "das_left", "das_right", "soft_drop", "hard_drop"]


@dataclass(frozen=True)
class Action:
    kind: Kind


def compile_move(board: Board, piece_kind: str, move: Move) -> tuple[list[Action], FallingPiece]:
    """Return (actions, final piece). Raises if the path does not reach move.cells.
    `piece_kind` is the piece that will actually be placed (after any hold swap)."""
    actions: list[Action] = []
    if move.hold:
        actions.append(Action("hold"))
    piece = FallingPiece.spawn(piece_kind, board)
    if piece is None:
        raise RuntimeError("spawn blocked")

    i, ms = 0, move.movements
    while i < len(ms):
        m = ms[i]
        if m in (Movement.LEFT, Movement.RIGHT):
            j = i
            while j < len(ms) and ms[j] == m:
                j += 1
            n = j - i
            dx = -1 if m == Movement.LEFT else 1
            for _ in range(n):
                if not piece.shift(board, dx):
                    raise RuntimeError(f"shift {m.name} blocked at {piece}")
            at_wall = FallingPiece(piece.kind, piece.rot, piece.x + dx, piece.y).obstructed(board)
            if n >= 2 and at_wall:
                actions.append(Action("das_left" if dx < 0 else "das_right"))
            else:
                actions.extend([Action("left" if dx < 0 else "right")] * n)
            i = j
            continue
        if m == Movement.CW:
            if not piece.rotate(board, cw=True):
                raise RuntimeError(f"CW blocked at {piece}")
            actions.append(Action("cw"))
        elif m == Movement.CCW:
            if not piece.rotate(board, cw=False):
                raise RuntimeError(f"CCW blocked at {piece}")
            actions.append(Action("ccw"))
        elif m == Movement.DROP:
            piece.sonic_drop(board)
            actions.append(Action("soft_drop"))
        i += 1

    piece.sonic_drop(board)
    actions.append(Action("hard_drop"))
    if sorted(piece.cells()) != sorted(move.cells):
        raise RuntimeError(f"path ends at {sorted(piece.cells())}, expected {sorted(move.cells)}")
    return actions, piece
