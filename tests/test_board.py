from tetris99.engine.board import Board, FULL_ROW


def test_place_and_clear():
    b = Board()
    b.rows[0] = FULL_ROW & ~0b11  # bottom row missing columns 0 and 1
    cleared = b.place([(0, 0), (1, 0), (0, 1), (1, 1)])  # O piece in the gap
    assert cleared == 1
    assert b.rows[0] == 0b11
    assert b.height() == 1


def test_garbage():
    b = Board()
    b.rows[0] = 0b1
    b.add_garbage(2, hole_col=3)
    assert b.rows[0] == b.rows[1] == FULL_ROW & ~(1 << 3)
    assert b.rows[2] == 0b1


def test_from_grid():
    grid = ["." * 10] * 18 + ["g" * 3 + "." * 7, "##########"[:9] + "."]
    b = Board.from_grid([list(r) for r in grid])
    assert b.rows[0] == (1 << 9) - 1
    assert b.rows[1] == 0
