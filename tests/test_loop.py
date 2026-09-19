import pytest

from tetris99.engine import coldclear
from tetris99.loop import Player
from tetris99.sim_env import SimEnv

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def test_player_survives_with_garbage():
    env = SimEnv(seed=5, max_pieces=80, garbage_every=16)
    player = Player(env, threads=1, max_nodes=5000, think_ms=15)  # a little think time keeps the search depth, and the outcome, stable
    for fs in env.frames():
        player.step(fs)
    player.close()
    assert not env.dead
    assert env.game.pieces_placed == 80
    assert player.pieces == 80
    assert env.game.board.height() < 16


def test_garbage_rows_detection():
    from tetris99.engine.board import Board
    from tetris99.loop import garbage_rows
    exp = Board(); exp.rows[0] = 0b0000111111; exp.rows[1] = 0b11
    seen = Board(list(exp.rows)); seen.add_garbage(3, hole_col=4)
    assert garbage_rows(exp, seen) == 3
    assert garbage_rows(exp, exp) == 0
    wrong = Board(list(seen.rows)); wrong.rows[5] |= 1 << 7     # a misplaced cell as well
    assert garbage_rows(exp, wrong) == 0
