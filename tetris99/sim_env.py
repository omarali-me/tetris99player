"""A fake Switch: takes controller actions, updates a simulated game, and renders FrameStates.
Interprets the action list independently of the executor (taps, DAS to wall, soft drop, hard drop)
so it doubles as a check that compiled inputs do what the executor believes."""
from __future__ import annotations

from typing import Iterator

from .engine.executor import Action
from .engine.piece import FallingPiece
from .engine.simulator import SimGame
from .vision.board import FrameState
from .vision.synthetic import render


class SimEnv:
    def __init__(self, seed: int = 0, max_pieces: int = 200, garbage_every: int = 0,
                 repeat: int = 2, max_idle: int = 30):
        self.game = SimGame(seed=seed)
        self.repeat = repeat        # frames each state is shown for (capture sees every state several times)
        self.max_idle = max_idle    # give up if the player never acts on a spawned piece
        self.max_pieces = max_pieces
        self.garbage_every = garbage_every
        self.piece: FallingPiece | None = None
        self.dead = False
        self.on_action = None   # optional callback(env, action) after each interpreted action
        self.last_actions: list[Action] = []

    # ---- output side (what the controller would do) ----
    def run(self, actions: list[Action]) -> None:
        g = self.game
        assert self.piece is not None, "no active piece"
        self.last_actions = actions
        for a in actions:
            k = a.kind
            if self.on_action:
                self.on_action(self, a)
            if k == "hold":
                cur = self.piece.kind
                if g.hold is None:
                    g.hold = cur
                    g.advance()
                    nxt = g.queue[0]
                else:
                    g.hold, nxt = cur, g.hold
                self.piece = FallingPiece.spawn(nxt, g.board)
            elif k == "cw": self.piece.rotate(g.board, cw=True)
            elif k == "ccw": self.piece.rotate(g.board, cw=False)
            elif k == "left": self.piece.shift(g.board, -1)
            elif k == "right": self.piece.shift(g.board, 1)
            elif k == "das_left":
                while self.piece.shift(g.board, -1): pass
            elif k == "das_right":
                while self.piece.shift(g.board, 1): pass
            elif k == "soft_drop": self.piece.sonic_drop(g.board)
            elif k == "hard_drop":
                self.piece.sonic_drop(g.board)
                g.lines += g.board.place(self.piece.cells())
                g.pieces_placed += 1
                if self.garbage_every and g.pieces_placed % self.garbage_every == 0:
                    g.board.add_garbage(2, hole_col=g.rng.randrange(10))
                self.piece = None
                g.advance()
                g.take_unreported()
            else:
                raise ValueError(k)
        if self.on_action:
            self.on_action(self, None)

    # ---- capture side ----
    def frames(self) -> Iterator[FrameState]:
        g = self.game
        for _ in range(self.repeat):
            yield render(g.board, None, g.hold, g.queue[:6])  # before first spawn
        idle = 0
        while g.pieces_placed < self.max_pieces:
            if self.piece is None:  # spawn the next piece
                self.piece = FallingPiece.spawn(g.queue[0], g.board)
                idle = 0
                if self.piece is None:
                    self.dead = True
                    return
            else:
                idle += 1
                if idle > self.max_idle:
                    raise RuntimeError("player never acted on the spawned piece")
            yield render(g.board, self.piece, g.hold, g.queue[1:])

    def close(self) -> None:
        pass
