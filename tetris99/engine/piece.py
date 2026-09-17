"""Falling piece with SRS rotation, mirroring Cold Clear's libtetris so that the movement paths it
returns replay to the same final cells here. Coordinates: x right, y up, (0,0) bottom-left."""
from __future__ import annotations

from dataclasses import dataclass

from .board import Board

N, E, S, W = 0, 1, 2, 3  # rotation states, cw order

# Cells relative to rotation point 1, in North orientation.
_NORTH: dict[str, list[tuple[int, int]]] = {
    "I": [(-1, 0), (0, 0), (1, 0), (2, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(-1, 0), (0, 0), (1, 0), (0, 1)],
    "L": [(-1, 0), (0, 0), (1, 0), (1, 1)],
    "J": [(-1, 0), (0, 0), (1, 0), (-1, 1)],
    "S": [(-1, 0), (0, 0), (0, 1), (1, 1)],
    "Z": [(-1, 1), (0, 1), (0, 0), (1, 0)],
}


def _rotated(cells, rot):
    if rot == N: return [(x, y) for x, y in cells]
    if rot == S: return [(-x, -y) for x, y in cells]
    if rot == E: return [(y, -x) for x, y in cells]
    return [(-y, x) for x, y in cells]


CELLS = {(k, r): _rotated(v, r) for k, v in _NORTH.items() for r in range(4)}


def rotation_points(kind: str, rot: int) -> list[tuple[int, int]]:
    if kind == "O":
        return [{N: (0, 0), E: (0, -1), S: (-1, -1), W: (-1, 0)}[rot]] * 5
    if kind == "I":
        return {
            N: [(0, 0), (-1, 0), (2, 0), (-1, 0), (2, 0)],
            E: [(-1, 0), (0, 0), (0, 0), (0, 1), (0, -2)],
            S: [(-1, 1), (1, 1), (-2, 1), (1, 0), (-2, 0)],
            W: [(0, 1), (0, 1), (0, 1), (0, -1), (0, 2)],
        }[rot]
    return {
        N: [(0, 0)] * 5,
        E: [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
        S: [(0, 0)] * 5,
        W: [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    }[rot]


@dataclass
class FallingPiece:
    kind: str
    rot: int = N
    x: int = 4
    y: int = 19

    def cells(self) -> list[tuple[int, int]]:
        return [(self.x + dx, self.y + dy) for dx, dy in CELLS[(self.kind, self.rot)]]

    def obstructed(self, board: Board) -> bool:
        return not board.fits(self.cells())

    def shift(self, board: Board, dx: int) -> bool:
        self.x += dx
        if self.obstructed(board):
            self.x -= dx
            return False
        return True

    def sonic_drop(self, board: Board) -> bool:
        fell = False
        while True:
            self.y -= 1
            if self.obstructed(board):
                self.y += 1
                return fell
            fell = True

    def rotate(self, board: Board, cw: bool) -> bool:
        target = (self.rot + (1 if cw else -1)) % 4
        x0, y0, r0 = self.x, self.y, self.rot
        for (x1, y1), (x2, y2) in zip(rotation_points(self.kind, r0), rotation_points(self.kind, target)):
            self.rot, self.x, self.y = target, x0 + x1 - x2, y0 + y1 - y2
            if not self.obstructed(board):
                return True
        self.rot, self.x, self.y = r0, x0, y0
        return False

    @classmethod
    def spawn(cls, kind: str, board: Board) -> "FallingPiece | None":
        for y in (19, 20):
            p = cls(kind, N, 4, y)
            if not p.obstructed(board):
                return p
        return None
