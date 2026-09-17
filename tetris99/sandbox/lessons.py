"""Training scenarios for the sandbox. Boards are written bottom row first."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..engine.board import Board
from ..engine.game import Game, Lock


def board_from(rows_bottom_first: list[str]) -> Board:
    b = Board()
    for y, row in enumerate(rows_bottom_first):
        for x, ch in enumerate(row):
            if ch == "#":
                b.rows[y] |= 1 << x
    return b


@dataclass
class Lesson:
    key: str
    title: str
    text: list[str]                         # teaching notes, shown in the side panel
    rows: list[str]                          # bottom row first
    queue: list[str]                         # current piece first
    hold: str | None = None
    goal: str = ""                           # shown to the player
    done: Callable[[Game, Lock], bool] = lambda g, lk: False
    coach_mode: str = "tspin"

    def load(self, game: Game) -> None:
        game.set_state(board_from(self.rows), list(self.queue), self.hold)


LESSONS: list[Lesson] = [
    Lesson(
        key="1", title="T-spin double: the slot",
        text=[
            "A TSD slot is a T-shaped hole with a one-cell lip",
            "over one side, so the T cannot drop straight in.",
            "",
            "Do it: rotate the T once so it stands upright,",
            "let it fall beside the lip, then rotate once more.",
            "The final rotation twists the T under the lip.",
            "The LAST input before locking must be a rotation:",
            "moving or dropping afterwards cancels the spin.",
            "",
            "SRS then checks the four corners around the T's",
            "centre: three filled = T-spin. Two lines = TSD,",
            "which sends 4 lines, same as a Tetris, for 2 lines.",
        ],
        rows=["####.#####", "###...####", "...#......"],
        queue=["T", "I", "O"],
        goal="Perform a T-spin double",
        done=lambda g, lk: lk.kind == "tsd",
    ),
    Lesson(
        key="2", title="T-spin triple: the kick",
        text=[
            "A TST slot is a vertical column three deep with a",
            "notch to one side, capped by an overhang. The T",
            "enters upright from above and needs a KICK: the",
            "plain rotation collides, so SRS tries its five",
            "offsets in order and the last one drops the T two",
            "rows into the slot.",
            "",
            "Do it: drop the T flat just right of the slot so",
            "it rests on the stack, slide it LEFT under the",
            "overhang, then rotate counter-clockwise. Kicks 1-4",
            "collide; kick 5 (+1,-2) drops it into the slot.",
            "Watch the kick number reported when it locks.",
        ],
        rows=["##.#######", "#..#######", "##.#######", "..........", "..#......."],
        queue=["T", "L", "J"],
        goal="Perform a T-spin triple",
        done=lambda g, lk: lk.kind == "tst",
    ),
    Lesson(
        key="3", title="Build a TSD from a flat stack",
        text=[
            "Set-up practice. Build a T slot on the LEFT: you",
            "need a 3-wide notch with a lip over its outer cell.",
            "Common builders: an L or J laid flat makes the floor",
            "of the slot; an S or Z lying on top makes the lip.",
            "",
            "Press K for the coach's layout in T-spin mode, or",
            "try your own. U undoes a placement, R redoes it.",
            "E lets you browse every placement of the piece.",
        ],
        rows=["...#######", "...#######"],
        queue=["L", "S", "O", "T", "I", "Z", "J"],
        goal="Perform a T-spin double within 6 pieces",
        done=lambda g, lk: lk.kind == "tsd" and g.stats["pieces"] <= 6,
    ),
    Lesson(
        key="4", title="Perfect clear opener",
        text=[
            "From an empty board, 10 pieces fill exactly 40",
            "cells: four full rows. Many bags allow a perfect",
            "clear if you find the arrangement.",
            "",
            "Press K with the coach in all-clear mode (A) to see",
            "Cold Clear's solution for this bag, then try to",
            "reproduce it without help. Undo is your friend.",
        ],
        rows=[],
        queue=["I", "L", "J", "O", "S", "Z", "T", "T", "L", "J"],
        goal="Perfect clear within 10 pieces",
        done=lambda g, lk: lk.perfect_clear and g.stats["pieces"] <= 10,
        coach_mode="allclear",
    ),
]

BY_KEY = {l.key: l for l in LESSONS}
