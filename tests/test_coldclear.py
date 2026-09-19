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


def test_plan_matches_move():
    import time
    with coldclear.ColdClear("IOTLJSZ", threads=1, max_nodes=5000) as bot:
        time.sleep(0.2)  # let it search a few pieces deep so the plan has several steps
        bot.request_move(0)
        for _ in range(200):
            status, move = bot.poll_move(plan_len=4)
            if status is coldclear.PollStatus.MOVE_PROVIDED:
                break
            time.sleep(0.005)
    assert move is not None and bot.plan
    assert sorted(bot.plan[0].cells) == sorted(move.cells)
    assert len(bot.plan) >= 2


def test_impossible_sequences_are_rejected():
    from tetris99.engine.coldclear import valid_sequence
    assert valid_sequence("LIIIIOO") is False          # the crash from the live run
    assert valid_sequence("IOTLJSZ") is True
    assert valid_sequence("IOTLJSZI") is True           # second bag starts
    assert valid_sequence("IOTLJSZ", hold="I") is True   # the hold piece is outside the bag rule
    assert valid_sequence("IIOTLJI") is False            # three I within 7
    assert valid_sequence("ILIOLTS") is True             # I L / I O L T S is a legal split
    assert valid_sequence("ILIOITS") is False            # three I would need two bag boundaries within 7 pieces
    assert valid_sequence("IOTLJS", hold="Z") is True
    assert valid_sequence("IOTXJS") is False            # not a piece
    with pytest.raises(ValueError):
        coldclear.ColdClear("IIIIOO", threads=1, max_nodes=100)


def test_bag_boundary_and_mid_bag_launch():
    from tetris99.engine.board import Board
    from tetris99.engine.coldclear import bag_boundary
    assert bag_boundary("JLTLSTZ") == 3          # J L T | L S T Z  (the queue that crashed Cold Clear live)
    assert bag_boundary("IOTLJSZ") == 7          # could all be one bag
    assert bag_boundary("IIOTLJS") == 1          # I | I O T L J S
    assert bag_boundary("IIIIOOT") is None
    # launching mid-bag with that queue must work and answer
    import time
    with coldclear.ColdClear("JLTLSTZ", threads=2, max_nodes=20000, board=Board(), hold="I", speculate=False) as bot:
        time.sleep(0.3)
        bot.request_move(0)
        assert bot.block_move() is not None
