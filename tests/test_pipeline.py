"""Closed loop entirely offline: simulator renders frames -> tracker -> Cold Clear -> executor ->
simulator applies the placement. Checks the tracker's view stays consistent with ground truth."""
import pytest

from tetris99.engine import coldclear
from tetris99.engine.executor import compile_move
from tetris99.engine.piece import FallingPiece
from tetris99.engine.simulator import SimGame
from tetris99.vision.tracker import Tracker, board_cells
from tetris99.vision.synthetic import render

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def test_closed_loop_60_pieces():
    game = SimGame(seed=3)
    tr = Tracker(confirm_frames=1)
    # initial reading: current piece spawned, queue shows the next 6
    tr.update(render(game.board, None, None, game.queue[:6]))  # pre-spawn frame: current piece still shown in queue

    with coldclear.ColdClear("".join(game.queue), threads=1, max_nodes=5000) as bot:
        for n in range(60):
            # A new piece spawns: queue shifts, piece appears at top.
            spawned = FallingPiece.spawn(game.queue[0], game.board)
            ev = tr.update(render(game.board, spawned, game.hold, game.queue[1:]))
            assert ev is not None, f"no spawn event at piece {n}"
            assert ev.piece == game.queue[0]
            assert board_cells(ev.locked) == board_cells(game.board)
            assert ev.queue == game.queue[1:]

            bot.request_move(0)
            move = bot.block_move()
            assert move is not None
            kind = game.piece_after_hold(move)
            actions, piece = compile_move(game.board, kind, move)

            if move.hold:
                # the game shows the swap immediately: new piece at top, hold updated, queue maybe shifted
                ev2 = tr.update(render(game.board, FallingPiece.spawn(kind, game.board), game.hold, game.queue[1:]))
                assert ev2 is not None and ev2.piece == kind, f"hold not tracked at piece {n}"

            # piece lands and locks; tracker sees it before the next spawn
            tr.update(render(game.board, piece, game.hold, game.queue[1:]))
            assert tr.state.active == set(piece.cells())
            tr.expected_locked = None
            game.lines += game.board.place(piece.cells())
            game.pieces_placed += 1
            game.advance()
            for p in game.take_unreported():
                bot.add_next_piece(p)
    assert game.pieces_placed == 60
