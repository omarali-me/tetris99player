import pytest

from tetris99.engine.board import Board
from tetris99.engine.coldclear import Move, Movement
from tetris99.engine.executor import compile_move
from tetris99.engine.piece import FallingPiece


def test_spawn_cells_match_coldclear_convention():
    p = FallingPiece.spawn("T", Board())
    assert sorted(p.cells()) == [(3, 19), (4, 19), (4, 20), (5, 19)]


def test_das_to_wall():
    b = Board()
    move = Move(hold=False, cells=[(0, 0), (1, 0), (2, 0), (3, 0)],
                movements=[Movement.LEFT] * 3, nodes=0, depth=0)
    actions, piece = compile_move(b, "I", move)
    assert [a.kind for a in actions] == ["das_left", "hard_drop"]


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
