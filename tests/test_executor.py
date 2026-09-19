import pytest

from tetris99.engine.board import Board
from tetris99.engine.coldclear import Move, Movement
from tetris99.engine.executor import compile_move
from tetris99.engine.piece import FallingPiece


def test_spawn_cells_match_coldclear_convention():
    p = FallingPiece.spawn("T", Board())
    assert sorted(p.cells()) == [(3, 19), (4, 19), (4, 20), (5, 19)]


def test_short_runs_are_tapped_not_das():
    # measured: tapping beats DAS for every distance reachable from spawn
    b = Board()
    move = Move(hold=False, cells=[(0, 0), (1, 0), (2, 0), (3, 0)],
                movements=[Movement.LEFT] * 3, nodes=0, depth=0)
    actions, piece = compile_move(b, "I", move)
    assert [a.kind for a in actions] == ["left", "left", "left", "hard_drop"]


def test_soft_drop_carries_its_distance():
    b = Board()
    move = Move(hold=False, cells=[(3, 0), (4, 0), (5, 0), (4, 1)], movements=[Movement.DROP], nodes=0, depth=0)
    actions, _ = compile_move(b, "T", move)
    assert actions[0].kind == "soft_drop" and actions[0].rows == 19
    assert actions[0].land_y == 0


def test_single_tap_not_das():
    b = Board()
    move = Move(hold=False, cells=[(2, 0), (3, 0), (4, 0), (5, 0)],
                movements=[Movement.LEFT], nodes=0, depth=0)
    actions, _ = compile_move(b, "I", move)
    assert [a.kind for a in actions] == ["left", "hard_drop"]


def test_tspin_double_via_overhang():
    b = Board()
    rows = ["...#......",   # y=2 overhang
            "###...####",   # y=1 slot
            "####.#####"]   # y=0
    for y, r in enumerate(reversed(rows)):
        for x, ch in enumerate(r):
            if ch == "#":
                b.rows[y] |= 1 << x
    move = Move(hold=False, cells=[(3, 1), (4, 1), (5, 1), (4, 0)],
                movements=[Movement.CW, Movement.DROP, Movement.CW], nodes=0, depth=0)
    actions, piece = compile_move(b, "T", move)
    assert [a.kind for a in actions] == ["cw", "soft_drop", "cw", "hard_drop"]
    assert b.place(piece.cells()) == 2


def test_wrong_path_raises():
    b = Board()
    move = Move(hold=False, cells=[(0, 0), (1, 0), (2, 0), (3, 0)], movements=[], nodes=0, depth=0)
    with pytest.raises(RuntimeError):
        compile_move(b, "I", move)


def test_merge_rotation_with_sideways_tap_in_open_air():
    from tetris99.engine.executor import Action, merge_simultaneous
    b = Board()
    acts = [Action(k) for k in ("left", "cw", "left", "left", "hard_drop")]
    merged = merge_simultaneous(b, "T", acts)
    assert [a.kind for a in merged] == ["left+cw", "left", "left", "hard_drop"]


def test_no_merge_after_a_soft_drop_or_when_order_matters():
    from tetris99.engine.executor import Action, merge_simultaneous
    b = Board()
    acts = [Action("soft_drop", rows=19, land_y=0), Action("cw"), Action("left"), Action("hard_drop")]
    assert [a.kind for a in merge_simultaneous(b, "T", acts)] == ["soft_drop", "cw", "left", "hard_drop"]
    # I piece hard against the right wall: rotating first kicks differently from moving first -> not merged
    acts = [Action("das_right"), Action("right"), Action("cw"), Action("hard_drop")]
    out = [a.kind for a in merge_simultaneous(b, "I", acts)]
    assert "right+cw" not in out


def test_merged_moves_land_where_cold_clear_expects():
    """Whole-game check: merged action lists, interpreted by the fake Switch, still reach every target."""
    from tetris99.loop import Player
    from tetris99.sim_env import SimEnv
    env = SimEnv(seed=4, max_pieces=60, garbage_every=0)
    player = Player(env, threads=1, max_nodes=5000, think_ms=15, merge_inputs=True)
    merged = 0
    orig = env.run
    def run(actions):
        nonlocal merged
        merged += sum("+" in a.kind for a in actions)
        orig(actions)
    env.run = run
    for fs in env.frames():
        player.step(fs)
    player.close()
    assert env.game.pieces_placed == 60 and player.divergences == 0
    assert merged > 5
