"""Coach: ask Cold Clear for a layout of every known piece from a given position, and map the
per-step coordinates it returns onto the board as it is now. Shared by the live loop and the
sandbox."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .board import Board
from .coldclear import ColdClear, PlanStep, PollStatus, load_weights, valid_sequence

CONFIG = Path(__file__).resolve().parent.parent.parent / "config"
MODES = {
    "normal":   {"weights": None, "pcloop": 0},
    "tspin":    {"weights": str(CONFIG / "weights_tspin.json"), "pcloop": 0},
    "allclear": {"weights": {"perfect_clear": 2000}, "pcloop": 1},
}


def rows_to_original(y: int, cleared_orig: list[int]) -> int:
    """Map a row index from a board after some rows were cleared back to the board before."""
    for r in cleared_orig:
        if r <= y:
            y += 1
    return y


def map_plan(steps: list[PlanStep], first_number: int = 1):
    """Cold Clear gives each step in the coordinates of the board when that piece is placed (after
    earlier clears). Map onto the board as it is at the first of these steps.
    Returns ([(piece, cells)], [(row, step number that clears it)])."""
    cleared_orig: list[int] = []
    laid, clears = [], []
    for i, step in enumerate(steps, start=first_number):
        cells = [(x, rows_to_original(y, cleared_orig)) for x, y in step.cells]
        laid.append((step.piece, cells))
        new = [rows_to_original(r, cleared_orig) for r in step.cleared]
        clears += [(r, i) for r in new]
        cleared_orig = sorted(cleared_orig + new)
    return laid, clears


@dataclass
class Plan:
    steps: list[PlanStep]
    depth: int
    mode: str

    def summary(self) -> str:
        kinds = []
        for s in self.steps:
            if s.tspin == "full" and len(s.cleared) == 2: kinds.append("TSD")
            elif s.tspin == "full" and len(s.cleared) == 3: kinds.append("TST")
            elif s.tspin == "full" and len(s.cleared) == 1: kinds.append("TSS")
            elif len(s.cleared) == 4: kinds.append("Tetris")
            elif s.cleared: kinds.append(f"{len(s.cleared)}L")
        return f"{len(self.steps)} pieces, {sum(len(s.cleared) for s in self.steps)} lines" + (": " + " ".join(kinds) if kinds else "")


def plan_from(board: Board, current: str, queue: list[str], hold: str | None, mode: str = "normal",
              think_ms: int = 600, max_steps: int = 8, threads: int = 2, max_nodes: int = 100_000) -> Plan | None:
    seq = [current] + list(queue)
    if not valid_sequence(seq, hold):
        return None
    cfg = MODES[mode]
    weights = cfg["weights"]
    if isinstance(weights, str):
        weights = load_weights(weights)
    with ColdClear("".join(seq), threads=threads, max_nodes=max_nodes, board=board, hold=hold,
                   speculate=False, weights=weights, pcloop=cfg["pcloop"]) as bot:
        time.sleep(think_ms / 1000)
        bot.request_move(0)
        deadline = time.perf_counter() + 2.0
        move = None
        while time.perf_counter() < deadline:
            status, move = bot.poll_move(max_steps)
            if status is not PollStatus.WAITING:
                break
            time.sleep(0.002)
        if move is None:
            return None
        return Plan(list(bot.plan), move.depth, mode)
