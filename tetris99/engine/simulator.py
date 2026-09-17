"""Offline game loop: 7-bag queue, Cold Clear decides, Board applies. Used to validate the binding
and later to unit-test the input executor by comparing expected vs achieved placements."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .board import Board
from .coldclear import PIECES, ColdClear, Move


@dataclass
class SimGame:
    seed: int = 0
    previews: int = 6
    rng: random.Random = field(init=False)
    board: Board = field(default_factory=Board)
    queue: list[str] = field(default_factory=list)
    hold: str | None = None
    pieces_placed: int = 0
    lines: int = 0

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self._bag: list[str] = []
        while len(self.queue) < self.previews + 1:
            self.queue.append(self._draw())

    def _draw(self) -> str:
        if not self._bag:
            self._bag = list(PIECES)
            self.rng.shuffle(self._bag)
        return self._bag.pop()

    def advance(self) -> str:
        """Pop the current piece; refill the queue and return the newly revealed preview."""
        self.queue.pop(0)
        new = self._draw()
        self.queue.append(new)
        return new

    def apply(self, move: Move) -> bool:
        current = self.queue[0]
        if move.hold:
            if self.hold is None:
                self.hold = current
                self.advance()
                current = self.queue[0]
            else:
                self.hold, current = current, self.hold
        if not self.board.fits(move.cells):
            return False
        self.lines += self.board.place(move.cells)
        self.pieces_placed += 1
        return True


def play(pieces: int = 100, seed: int = 0, verbose: bool = False) -> SimGame:
    game = SimGame(seed=seed)
    with ColdClear("".join(game.queue), threads=2, max_nodes=20_000) as bot:
        for _ in range(pieces):
            bot.request_move(0)
            move = bot.block_move()
            if move is None:
                if verbose:
                    print("bot dead")
                break
            if not game.apply(move):
                raise RuntimeError(f"illegal placement {move.cells}\n{game.board}")
            bot.add_next_piece(game.advance())
            if verbose:
                print(f"#{game.pieces_placed} hold={move.hold} cells={move.cells} moves={[m.name for m in move.movements]} depth={move.depth}")
    return game


if __name__ == "__main__":
    g = play(200, verbose=True)
    print(g.board)
    print(f"placed={g.pieces_placed} lines={g.lines} height={g.board.height()}")
