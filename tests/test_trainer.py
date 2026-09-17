"""Coach mode: on demand, lay out placements for every known piece; rows mapped through clears."""
import pytest

from tetris99.engine import coldclear
from tetris99.engine.board import Board
from tetris99.engine.coldclear import PlanStep
from tetris99.loop import Player, map_plan, rows_to_original
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


def test_map_plan_double_clear_then_more():
    # step 1 clears rows 9 and 10 (same pre-clear coordinates); step 2 sits on row 9 of the new board
    steps = [PlanStep("J", [(0, 10), (1, 10), (2, 9), (2, 10)], [9, 10]),
             PlanStep("L", [(0, 9), (0, 10), (1, 10), (2, 10)], [10]),
             PlanStep("J", [(0, 10), (0, 11), (1, 10), (2, 10)], [10])]
    laid, clears = map_plan(steps)
    assert laid[0][1] == [(0, 10), (1, 10), (2, 9), (2, 10)]
    assert sorted(laid[1][1]) == [(0, 11), (0, 12), (1, 12), (2, 12)]   # shifted up past rows 9-10
    assert sorted(laid[2][1]) == [(0, 13), (0, 14), (1, 13), (2, 13)]   # past rows 9, 10 and 12
    assert clears == [(9, 1), (10, 1), (12, 2), (13, 3)]


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


def test_remaining_steps_follow_the_live_board_after_a_clear():
    """After step 1 is placed and its row has cleared, the remaining steps are expressed in the
    live board's coordinates (no more offset for that clear)."""
    from tetris99.loop import DryRunOutput
    player = Player(DryRunOutput(), trainer=True)
    player.plan_steps = [PlanStep("I", [(0, 0), (1, 0), (2, 0), (3, 0)], [0]),
                         PlanStep("O", [(0, 0), (1, 0), (0, 1), (1, 1)], [])]
    laid, clears = player.layout()
    assert sorted(laid[1][1]) == [(0, 1), (0, 2), (1, 1), (1, 2)] and clears == [(0, 1)]  # before: shifted up
    player.laid_done = 1
    laid, clears = player.layout()
    assert sorted(laid[0][1]) == [(0, 0), (0, 1), (1, 0), (1, 1)] and clears == []       # after: on the floor
    numbered, _ = player.shown()
    assert numbered[0][0] == 2                                                             # keeps its number


def test_visibility_toggles():
    from tetris99.loop import DryRunOutput
    player = Player(DryRunOutput(), trainer=True)
    player.plan_steps = [PlanStep("I", [(0, 0), (1, 0), (2, 0), (3, 0)], []) for _ in range(4)]
    assert len(player.shown()[0]) == 4
    player.toggle_all(); assert player.shown()[0] == []
    player.toggle_all(); assert len(player.shown()[0]) == 4
    player.show_next(); assert [n for n, _ in player.shown()[0]] == [1]
    player.show_next(); assert [n for n, _ in player.shown()[0]] == [1, 2]
    player.laid_done = 1   # piece 1 placed: still two upcoming shown, numbered from 2
    player.visible = max(1, player.visible - 1)
    assert [n for n, _ in player.shown()[0]] == [2]
    player.close()
