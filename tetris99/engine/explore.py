"""Enumerate every placement the current piece can reach (0G), for browsing alternatives."""
from __future__ import annotations

from dataclasses import dataclass

from .board import Board
from .piece import FallingPiece


@dataclass
class Placement:
    piece: FallingPiece                 # final resting position
    path: list[str]                     # moves from spawn: L R CW CCW D(rop)
    spin: bool                          # last move before landing was a rotation (possible T-spin)

    @property
    def cells(self):
        return self.piece.cells()


def reachable_placements(board: Board, kind: str) -> list[Placement]:
    start = FallingPiece.spawn(kind, board)
    if start is None:
        return []
    key = lambda p: (p.kind, p.rot, p.x, p.y)
    seen = {key(start): []}
    frontier = [(start, [])]
    finals: dict[tuple, Placement] = {}
    while frontier:
        nxt = []
        for p, path in frontier:
            for mv in ("L", "R", "CW", "CCW", "D"):
                q = FallingPiece(p.kind, p.rot, p.x, p.y)
                if mv == "L": ok = q.shift(board, -1)
                elif mv == "R": ok = q.shift(board, 1)
                elif mv == "CW": ok = q.rotate(board, cw=True)
                elif mv == "CCW": ok = q.rotate(board, cw=False)
                else: ok = q.sonic_drop(board)
                if not ok or key(q) in seen:
                    continue
                seen[key(q)] = path + [mv]
                nxt.append((q, path + [mv]))
                # a landed state is a candidate final placement
                below = FallingPiece(q.kind, q.rot, q.x, q.y - 1)
                if below.obstructed(board):
                    k = tuple(sorted(q.cells()))
                    if k not in finals:
                        finals[k] = Placement(q, path + [mv], spin=mv in ("CW", "CCW"))
        frontier = nxt
    # spawn position itself, dropped
    d = FallingPiece(start.kind, start.rot, start.x, start.y); d.sonic_drop(board)
    k = tuple(sorted(d.cells()))
    finals.setdefault(k, Placement(d, ["D"], spin=False))
    out = list(finals.values())
    out.sort(key=lambda pl: (min(x for x, _ in pl.cells), pl.piece.rot))
    return out
