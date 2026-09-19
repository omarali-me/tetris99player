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
    # a mismatch is re-checked for a few frames (lock flash, clear animation) before it is reported
    ev = None
    for _ in range(tr.recheck_frames + 1):
        ev = ev or tr.update(render(board, FallingPiece.spawn("S", board), None, list("ZJLOIT")))
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


def test_hold_change_alone_does_not_fire_before_queue_settles():
    """Real capture: after our hold press the hold box and queue may not update on the same frame."""
    tr = Tracker(confirm_frames=2)
    board = Board()
    for _ in range(2):
        tr.update(render(board, None, None, list("TSZJLO")))
    for _ in range(2):
        tr.update(render(board, FallingPiece.spawn("T", board), None, list("SZJLOI")))
    # hold from empty: frame shows hold=T but queue not yet redrawn -> no event
    assert tr.update(render(board, FallingPiece.spawn("S", board), "T", list("SZJLOI"))) is None
    assert tr.update(render(board, FallingPiece.spawn("S", board), "T", list("ZJLOIT"))) is None  # 1st confirm
    ev = tr.update(render(board, FallingPiece.spawn("S", board), "T", list("ZJLOIT")))
    assert ev and ev.piece == "S" and ev.hold == "T" and ev.new_pieces == ["T"]


def test_trust_expected_after_a_line_clear():
    """While cleared rows are still collapsing on screen, the predicted board is used as is."""
    tr = Tracker(confirm_frames=1)
    board = Board()
    tr.update(render(board, None, None, list("TSZJLO")))
    tr.update(render(board, FallingPiece.spawn("T", board), None, list("SZJLOI")))
    truth = Board(); truth.rows[0] = 0b0000001111          # what the board really is after the clear
    lagging = Board(); lagging.rows[0] = 0; lagging.rows[2] = 0b0000001111   # screen: rows not collapsed yet
    tr.expected_locked = board_cells(truth); tr.trust_expected = True
    ev = tr.update(render(lagging, FallingPiece.spawn("S", lagging), None, list("ZJLOIT")))
    assert ev and board_cells(ev.locked) == board_cells(truth) and not ev.garbage_arrived
    assert tr.trust_expected is False


def test_floating_remnant_is_kept_but_hud_junk_is_dropped():
    tr = Tracker(confirm_frames=1)
    board = Board()
    board.rows[0] = 0b0000001111
    board.rows[2] = 0b0000000001          # a genuine floating block left by a line clear
    tr.update(render(board, None, None, list("TSZJLO")))
    tr.update(render(board, FallingPiece.spawn("T", board), None, list("SZJLOI")))   # first spawn
    junk = Board(list(board.rows)); junk.rows[17] |= 1 << 8                            # widget misread
    ev = tr.update(render(junk, FallingPiece.spawn("S", junk), None, list("ZJLOIT")))
    cells = board_cells(ev.locked)
    assert (0, 2) in cells          # remnant survives
    assert (8, 17) not in cells     # HUD junk does not


def test_temporal_vote_ignores_a_one_frame_spark():
    tr = Tracker(confirm_frames=1); tr.settle_frames = 4
    board = Board(); board.rows[0] = 0b0000001111
    tr.update(render(board, None, None, list("TSZJLO")))
    piece = FallingPiece.spawn("T", board)
    sparked = Board(list(board.rows)); sparked.rows[0] |= 1 << 8      # a spark read as a block, one frame only
    frames = [render(sparked, piece, None, list("SZJLOI"))] + [render(board, piece, None, list("SZJLOI"))] * 5
    ev = None
    for f in frames:
        ev = ev or tr.update(f)
    assert ev and ev.piece == "T"
    assert board_cells(ev.locked) == board_cells(board)               # the spark did not make it in


def test_first_piece_of_a_match_is_recognised_without_a_queue_shift():
    tr = Tracker(confirm_frames=1)
    board = Board()
    q = list("SZJLOI")
    for _ in range(3):
        assert tr.update(render(board, None, None, q)) is None          # countdown: queue drawn, no piece
    piece = FallingPiece.spawn("T", board)
    ev = None
    for _ in range(4):
        ev = ev or tr.update(render(board, piece, None, q))              # GO: piece appears, queue unchanged
    assert ev and ev.piece == "T" and ev.queue == q and ev.new_pieces == []
    # and the normal queue-shift path carries on from there
    board.place([(0, 0), (1, 0), (2, 0), (1, 1)])
    ev2 = None
    for _ in range(2):
        ev2 = ev2 or tr.update(render(board, FallingPiece.spawn("S", board), None, list("ZJLOIT")))
    assert ev2 and ev2.piece == "S"
