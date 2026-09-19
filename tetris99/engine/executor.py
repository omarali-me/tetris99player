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

Kind = Literal["hold", "cw", "ccw", "left", "right", "das_left", "das_right", "soft_drop", "hard_drop",
               "left+cw", "left+ccw", "right+cw", "right+ccw"]


# Measured on Tetris 99 (2026-09-19): DAS delay 200 ms, auto-repeat 33 ms/column, and taps of
# 34 ms with 34 ms gaps register every time. From spawn a wall is at most 5 columns away, where
# tapping (5 x 68 = 340 ms) still beats a DAS slide (200 + 4 x 33 + margin = ~380 ms), so DAS is
# only used for long slides.
DAS_MIN_RUN = 6


@dataclass(frozen=True)
class Action:
    kind: Kind
    rows: int = 0     # soft_drop only: how many rows the piece falls, so the hold time can be scaled
    land_y: int = -1  # soft_drop only: lowest row of the piece once it has landed


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
            if n >= DAS_MIN_RUN and at_wall:
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
            y0 = piece.y
            piece.sonic_drop(board)
            actions.append(Action("soft_drop", rows=y0 - piece.y, land_y=min(y for _, y in piece.cells())))
        i += 1

    piece.sonic_drop(board)
    actions.append(Action("hard_drop"))
    if sorted(piece.cells()) != sorted(move.cells):
        raise RuntimeError(f"path ends at {sorted(piece.cells())}, expected {sorted(move.cells)}")
    return actions, piece


def merge_simultaneous(board: Board, piece_kind: str, actions: list[Action]) -> list[Action]:
    """Press a rotation and a sideways tap in the same input frame where that is provably safe.

    A human does this all the time; it removes one ~70 ms input slot per merged pair. It is only done
    while the piece is still in the air (before any soft drop), and only when moving-then-rotating
    and rotating-then-moving both succeed and end in the same place on this board, so the result
    cannot depend on which one the game happens to process first."""
    piece = FallingPiece.spawn(piece_kind, board)
    if piece is None:
        return actions

    def apply(p: FallingPiece, kind: str) -> bool:
        if kind == "left": return p.shift(board, -1)
        if kind == "right": return p.shift(board, 1)
        if kind == "cw": return p.rotate(board, cw=True)
        if kind == "ccw": return p.rotate(board, cw=False)
        return False

    out: list[Action] = []
    i, in_air = 0, True
    while i < len(actions):
        a = actions[i]
        b = actions[i + 1] if i + 1 < len(actions) else None
        if a.kind == "hold":
            out.append(a); i += 1; continue
        if a.kind == "soft_drop":
            in_air = False
        pair = None
        if in_air and b is not None:
            kinds = {a.kind, b.kind}
            move = next((k for k in kinds if k in ("left", "right")), None)
            rot = next((k for k in kinds if k in ("cw", "ccw")), None)
            if move and rot and len(kinds) == 2:
                p1 = FallingPiece(piece.kind, piece.rot, piece.x, piece.y)
                p2 = FallingPiece(piece.kind, piece.rot, piece.x, piece.y)
                ok1 = apply(p1, move) and apply(p1, rot)
                ok2 = apply(p2, rot) and apply(p2, move)
                if ok1 and ok2 and (p1.rot, p1.x, p1.y) == (p2.rot, p2.x, p2.y):
                    pair = (f"{move}+{rot}", p1)
        if pair:
            out.append(Action(pair[0]))
            piece = pair[1]
            i += 2
            continue
        # keep the simulated piece in step with the unmerged action
        if a.kind in ("left", "right", "cw", "ccw"):
            apply(piece, a.kind)
        elif a.kind == "das_left":
            while piece.shift(board, -1): pass
        elif a.kind == "das_right":
            while piece.shift(board, 1): pass
        elif a.kind == "soft_drop":
            piece.sonic_drop(board)
        out.append(a); i += 1
    return out
