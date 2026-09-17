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


def test_weights_override_and_validation():
    from tetris99.engine.coldclear import CCWeights, apply_weights, default_weights, load_weights
    import ctypes as C
    d = default_weights()
    assert d["clear4"] == 390 and d["well_column"][4] == 59
    w = CCWeights(); coldclear.lib().cc_default_weights(C.byref(w))
    apply_weights(w, {"clear4": 100, "well_column": [1] * 10, "use_bag": False, "_comment": "ignored"})
    assert w.clear4 == 100 and list(w.well_column) == [1] * 10 and w.use_bag is False
    with pytest.raises(KeyError):
        apply_weights(w, {"clear5": 1})
    assert load_weights("config/weights.json")["tspin2"] == 410
    with coldclear.ColdClear("IOTLJSZ", threads=1, max_nodes=2000, weights={"clear4": 0}) as bot:
        assert bot.weights.clear4 == 0
