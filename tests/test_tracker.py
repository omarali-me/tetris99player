"""Drive the tracker with synthetic frames rendered from the engine's own board/piece model."""
from tetris99.engine.board import Board
from tetris99.engine.piece import FallingPiece
from tetris99.vision.synthetic import render
from tetris99.vision.tracker import Tracker, board_cells


def test_spawn_lock_clear_cycle():
    tr = Tracker(confirm_frames=1)
    board = Board()
    board.rows[0] = 0b1111110000  # columns 4-9 filled
    q = list("TSZJLO")
    # frame: T spawned, queue TSZJLO
    piece = FallingPiece.spawn("T", board)
    assert tr.update(render(board, piece, None, q)) is None  # first reading, no spawn info

    # queue shifts: piece T spawned (tracker infers spawned piece = old queue[0])
    q2 = list("SZJLOI")
    ev = tr.update(render(board, piece, None, q2))
    assert ev and ev.piece == "T"
    assert board_cells(ev.locked) == board_cells(board)
    assert tr.state.active == set(piece.cells()) - {(4, 20)}  # top cell hidden

    # piece moves left twice and drops
    piece.shift(board, -1); piece.shift(board, -1); piece.sonic_drop(board)
    tr.update(render(board, piece, None, q2))
    assert tr.state.active == set(piece.cells())

    # lock (still same queue); no event
    board.place(piece.cells())
    assert tr.update(render(board, None, None, q2)) is None

    # next spawn: S piece, queue shifts again
    piece = FallingPiece.spawn("S", board)
    ev = tr.update(render(board, piece, None, list("ZJLOIT")))
    assert ev and ev.piece == "S"
    assert board_cells(ev.locked) == board_cells(board)
    assert not ev.garbage_arrived


def test_hold_from_empty_advances_queue_by_two():
    tr = Tracker(confirm_frames=1)
    board = Board()
    q = list("TSZJLO")
    tr.update(render(board, None, None, q))
    tr.update(render(board, FallingPiece.spawn("T", board), None, list("SZJLOI")))  # T spawned
    # player holds T: S spawns, hold shows T, queue advanced by two total relative to "SZJLOI"
    ev = tr.update(render(board, FallingPiece.spawn("S", board), "T", list("ZJLOIT")))
    assert ev and ev.piece == "S" and ev.hold == "T"


def test_hold_swap_with_full_slot():
    tr = Tracker(confirm_frames=1)
    board = Board()
    tr.update(render(board, None, "I", list("TSZJLO")))
    tr.update(render(board, FallingPiece.spawn("T", board), "I", list("SZJLOI")))  # T spawned
    # swap: hold now shows T, I spawns, queue unchanged
    ev = tr.update(render(board, FallingPiece.spawn("I", board), "T", list("SZJLOI")))
    assert ev and ev.piece == "I" and ev.hold == "T"


def test_garbage_flagged_when_locked_differs_from_expected():
    tr = Tracker(confirm_frames=1)
    board = Board()
    tr.update(render(board, None, None, list("TSZJLO")))
    tr.update(render(board, FallingPiece.spawn("T", board), None, list("SZJLOI")))
    tr.expected_locked = set()  # we expect an empty board after the T... but garbage arrives
    board.add_garbage(2, hole_col=3)
    ev = tr.update(render(board, FallingPiece.spawn("S", board), None, list("ZJLOIT")))
    assert ev and ev.garbage_arrived
    assert ev.locked.rows[0] == board.rows[0]


def test_queue_debounce():
    tr = Tracker(confirm_frames=2)
    board = Board()
    tr.update(render(board, None, None, list("TSZJLO")))
    tr.update(render(board, None, None, list("TSZJLO")))
    p = FallingPiece.spawn("T", board)
    assert tr.update(render(board, p, None, list("SZJLOI"))) is None  # one frame: not yet
    ev = tr.update(render(board, p, None, list("SZJLOI")))
    assert ev and ev.piece == "T"
