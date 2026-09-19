import pytest

from tetris99.engine import coldclear
from tetris99.loop import Player
from tetris99.sim_env import SimEnv

try:
    coldclear.lib()
except FileNotFoundError:
    pytest.skip("libcold_clear.so not built", allow_module_level=True)


def test_player_survives_with_garbage():
    env = SimEnv(seed=5, max_pieces=80, garbage_every=16)
    player = Player(env, threads=1, max_nodes=5000, think_ms=15)  # a little think time keeps the search depth, and the outcome, stable
    for fs in env.frames():
        player.step(fs)
    player.close()
    assert not env.dead
    assert env.game.pieces_placed == 80
    assert player.pieces == 80
    assert env.game.board.height() < 16


def test_garbage_rows_detection():
    from tetris99.engine.board import Board
    from tetris99.loop import garbage_rows
    exp = Board(); exp.rows[0] = 0b0000111111; exp.rows[1] = 0b11
    seen = Board(list(exp.rows)); seen.add_garbage(3, hole_col=4)
    assert garbage_rows(exp, seen) == 3
    assert garbage_rows(exp, exp) == 0
    wrong = Board(list(seen.rows)); wrong.rows[5] |= 1 << 7     # a misplaced cell as well
    assert garbage_rows(exp, wrong) == 0


class FakeLive:
    """Stands in for the serial controller: records what was sent."""
    live = True
    def __init__(self): self.sent = []
    def run(self, actions): self.sent.append([a.kind for a in actions])
    def duration(self, actions): return 0.0
    def down(self, pressed): self.sent.append(["down" if pressed else "up"])


def test_out_of_step_is_detected_and_resynchronised_from_the_screen():
    from tetris99.engine.board import Board
    from tetris99.engine.piece import FallingPiece
    from tetris99.vision.synthetic import render
    out = FakeLive()
    player = Player(out, threads=1, max_nodes=3000)
    board = Board()
    for _ in range(3):
        player.step(render(board, None, None, list("TSZJLO")))
    # the queue shifts as if T spawned, but the piece actually on screen is a Z:
    # a stray input already dropped a piece and the game is one piece ahead of our belief
    frame = render(board, FallingPiece.spawn("Z", board), None, list("SZJLOI"))
    for _ in range(10):
        player.step(frame)
    player.close()
    assert player.resyncs == 1
    assert player.tracker.state.current == "Z"
    assert out.sent, "a move should have been sent for the piece that is really in play"
    assert player.target[0] in ("Z", "S")   # Z placed, or Z held and the next piece (S) placed


def test_soft_drop_landing_watches_the_held_piece_after_a_hold():
    """A move that starts with hold places the swapped-in piece; the landing check must look for
    that piece's colour, not the colour of the piece that spawned."""
    from tetris99.engine.board import Board
    from tetris99.engine.piece import FallingPiece
    from tetris99.vision.synthetic import render
    out = FakeLive()
    player = Player(out, threads=1, max_nodes=3000)
    board = Board()
    player.tracker.state.current = "T"                       # T spawned...
    player.target = ("S", [(3, 0), (4, 0), (4, 1), (5, 1)], True)   # ...but we held it and are placing S
    player.drop_state = {"watch_from": 0.0, "deadline": 1e18, "land_y": 0, "hits": 0}
    landed = FallingPiece("S", 0, 4, 0)                       # the S resting on the floor
    assert min(y for _, y in landed.cells()) == 0
    for _ in range(3):
        if player.drop_state is not None:
            player._watch_drop(render(board, landed, "T", list("ZJLOIT")))
    assert player.drop_state is None, "landing of the held piece was not recognised"
    assert ["up"] in out.sent
    player.close()
