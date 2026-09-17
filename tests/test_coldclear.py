import pytest

from tetris99.engine import coldclear
from tetris99.engine.simulator import play

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def test_first_move():
    with coldclear.ColdClear("IOTLJSZ", threads=1, max_nodes=5000) as bot:
        bot.request_move(0)
        move = bot.block_move()
    assert move is not None
    assert len(move.cells) == 4 and all(0 <= x < 10 for x, _ in move.cells)


def test_play_100_pieces():
    game = play(100, seed=1)
    assert game.pieces_placed == 100
    assert game.board.height() < 15
    assert game.lines > 20
