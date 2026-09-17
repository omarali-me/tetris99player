"""Coach mode: on demand, lay out placements for every known piece; rows mapped through clears."""
import pytest

from tetris99.engine import coldclear
from tetris99.engine.board import Board
from tetris99.loop import Player, rows_to_original
from tetris99.sim_env import SimEnv

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def test_rows_to_original():
    assert rows_to_original(0, []) == 0
    assert rows_to_original(0, [0]) == 1          # row 0 was cleared: new row 0 was row 1
    assert rows_to_original(0, [0, 1]) == 2
    assert rows_to_original(3, [0, 5]) == 4       # only clears at or below count
    assert rows_to_original(5, [0, 5]) == 7       # row 6 -> then cleared 5 pushes to 7


def apply_layout(board: Board, laid) -> None:
    """Every laid-out placement must be legal on the board as it stands at that point,
    once earlier placements and their clears are applied (rows given in original coordinates)."""
    b = Board(list(board.rows))
    for piece, cells in laid:
        assert b.fits(cells), (piece, cells)
        b.place(cells)


def test_plan_now_lays_out_known_pieces():
    env = SimEnv(seed=2, max_pieces=5, garbage_every=0)
    player = Player(env, threads=1, max_nodes=20000, trainer=True)
    frames = env.frames()
    for _ in range(4):
        player.step(next(frames))
    assert player.tracker.state.current
    laid = player.plan_now(think_ms=100)
    assert 5 <= len(laid) <= 8
    known = set([player.tracker.state.current] + player.tracker.state.queue + ([player.tracker.state.hold] if player.tracker.state.hold else []))
    assert all(p in known for p, _ in laid)
    player.close()


def test_layout_rows_survive_clears():
    # A board where the first placement clears a line: later placements' rows must be mapped up.
    env = SimEnv(seed=2, max_pieces=5, garbage_every=0)
    b = env.game.board
    b.rows[0] = 0b1111111100  # bottom row needs columns 0-1 (an O or a vertical piece fills it)
    b.rows[1] = 0b1111111100
    player = Player(env, threads=1, max_nodes=20000, trainer=True)
    frames = env.frames()
    for _ in range(4):
        player.step(next(frames))
    laid = player.plan_now(think_ms=200)
    assert laid
    # legal in sequence on the ORIGINAL board (this is what mapping guarantees)
    apply_layout(Board(list(b.rows)), laid)
    player.close()
