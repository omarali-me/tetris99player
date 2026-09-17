"""Trainer mode against the fake Switch, with a 'human' that follows the plan exactly, and one
that deviates once."""
import pytest

from tetris99.engine import coldclear
from tetris99.engine.piece import FallingPiece
from tetris99.loop import Player
from tetris99.sim_env import SimEnv

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def human_places(env: SimEnv, target) -> None:
    """Do what the overlay asks: optional hold, then lock the piece on the target cells."""
    kind, cells, hold_first = target
    g = env.game
    if hold_first:
        cur = env.piece.kind
        if g.hold is None:
            g.hold = cur; g.advance(); g.take_unreported()
        else:
            g.hold = cur
    assert g.board.fits(cells)
    g.lines += g.board.place(cells)
    g.pieces_placed += 1
    env.piece = None
    g.advance(); g.take_unreported()


def run(follow_every: int | None, pieces: int = 24):
    env = SimEnv(seed=1, max_pieces=pieces, garbage_every=0)
    player = Player(env, threads=1, max_nodes=5000, think_ms=30, trainer=True, plan_len=4)
    replans = 0
    orig = player._replan
    def counting(sp):
        nonlocal replans; replans += 1; orig(sp)
    player._replan = counting
    placed = 0
    seen = 0
    for fs in env.frames():
        player.step(fs)
        if env.piece is not None and player.target and player.pieces > seen:  # act once per instruction
            seen = player.pieces
            placed += 1
            if follow_every and placed % follow_every == 0:
                # deviate: drop the spawned piece straight down instead
                p = env.piece; p.sonic_drop(env.game.board)
                env.game.board.place(p.cells()); env.game.pieces_placed += 1; env.piece = None
                env.game.advance(); env.game.take_unreported()
            else:
                human_places(env, player.target)
    player.close()
    return env, replans


def test_plan_is_kept_while_followed():
    env, replans = run(follow_every=None)
    assert env.game.pieces_placed == 24
    assert replans <= 24 // 4 + 1   # one plan per four pieces, plus the first


def test_deviation_triggers_replan():
    env, replans = run(follow_every=5)
    assert env.game.pieces_placed == 24
    assert replans > 24 // 4 + 1
