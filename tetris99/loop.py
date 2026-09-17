"""Main loop: frames -> tracker -> Cold Clear -> executor -> controller.

    python -m tetris99.loop --source synthetic                 # fully offline, prints decisions
    python -m tetris99.loop --source recordings/game.mp4       # dry run against a recording
    python -m tetris99.loop --source 4 --output serial         # live: capture device 4 -> Arduino
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Iterable, Protocol

from .config import Layout, Settings
from .engine.board import Board
from .engine.coldclear import ColdClear, Move, PollStatus
from .engine.executor import Action, compile_move
from .vision.board import FrameState, read_frame
from .vision.tracker import Spawn, Tracker, board_cells

log = logging.getLogger("loop")


class Output(Protocol):
    def run(self, actions: list[Action]) -> None: ...


class DryRunOutput:
    def run(self, actions: list[Action]) -> None:
        log.info("ACTIONS %s", " ".join(a.kind for a in actions))


class SerialOutput:
    def __init__(self, port: str, baud: int):
        from .control.switch_controller import SwitchController, run_actions
        self.ctl = SwitchController(port, baud)
        self._run = run_actions
        if not self.ctl.ping():
            raise RuntimeError("controller did not answer ping")

    def run(self, actions: list[Action]) -> None:
        self._run(self.ctl, actions)


class Player:
    """Drives one game. Feed FrameStates via step(); it returns the actions it issued, if any."""

    def __init__(self, output: Output, threads: int = 2, max_nodes: int = 100_000, think_ms: int = 0):
        self.output = output
        self.tracker = Tracker()
        self.bot: ColdClear | None = None
        self.threads, self.max_nodes = threads, max_nodes
        self.think_ms = think_ms
        self.expected: Board | None = None
        self.pending_request = False
        self.pieces = 0
        # After we press hold, the game shows the swapped-in piece and the tracker reports a spawn
        # for it. That spawn is ours to ignore: (piece kind, locked board before our placement).
        self.own_hold_spawn: tuple[str, set] | None = None

    def _launch(self, sp: Spawn) -> None:
        if self.bot:
            self.bot.close()
        self.pending_request = False
        # Mid-game start: the bag is unknown, so speculation on unseen pieces is off.
        self.bot = ColdClear("".join([sp.piece] + sp.queue), threads=self.threads, max_nodes=self.max_nodes,
                             board=sp.locked, hold=sp.hold, speculate=False)
        log.info("bot launched: piece=%s hold=%s queue=%s", sp.piece, sp.hold, "".join(sp.queue))

    def _get_move(self) -> Move | None:
        assert self.bot
        if not self.pending_request:
            self.bot.request_move(0)
        self.pending_request = False
        deadline = time.perf_counter() + max(self.think_ms, 5) / 1000
        while True:
            status, move = self.bot.poll_move()
            if status is PollStatus.MOVE_PROVIDED:
                return move
            if status is PollStatus.BOT_DEAD:
                return None
            if time.perf_counter() > deadline:
                # give it up to 2s more; the bot only stalls if it lacks queue info
                status, move = self.bot.poll_move()
                if time.perf_counter() > deadline + 2.0:
                    log.warning("bot did not answer in time")
                    return None
            time.sleep(0.001)

    def on_spawn(self, sp: Spawn) -> list[Action] | None:
        t0 = time.perf_counter()
        if self.bot is None:
            self._launch(sp)
        else:
            for p in sp.new_pieces:
                self.bot.add_next_piece(p)
            if self.own_hold_spawn and self.own_hold_spawn == (sp.piece, board_cells(sp.locked)):
                self.own_hold_spawn = None
                self.tracker.expected_locked = board_cells(self.expected) if self.expected else None
                log.debug("ignoring spawn caused by our own hold press")
                return None
            self.own_hold_spawn = None
            if sp.garbage_arrived or (self.expected is not None and board_cells(sp.locked) != board_cells(self.expected)):
                # A reset with a request in flight can hand back a stale move; relaunching is race-free.
                log.info("board differs from prediction (garbage or misplaced piece): relaunching bot")
                self._launch(sp)

        move = self._get_move()
        if move is None:
            log.error("no move (bot dead?) — relaunching from current board")
            self._launch(sp)
            move = self._get_move()
            if move is None:
                return None

        # The piece that actually gets placed after an optional hold.
        kind = sp.piece
        if move.hold:
            kind = sp.hold if sp.hold else sp.queue[0]
        try:
            actions, final = compile_move(sp.locked, kind, move)
        except RuntimeError as e:
            log.error("executor rejected path: %s; relaunching bot", e)
            self._launch(sp)
            return None

        if move.hold:
            self.own_hold_spawn = (kind, board_cells(sp.locked))
        self.output.run(actions)
        board = Board(list(sp.locked.rows))
        board.place(final.cells())
        self.expected = board
        self.tracker.expected_locked = board_cells(board)
        # Think about the next piece during the drop/clear animation.
        self.bot.request_move(0)
        self.pending_request = True
        self.pieces += 1
        log.info("#%d %s hold=%s -> %s  (%.0f ms, depth %d)", self.pieces, sp.piece, move.hold,
                 " ".join(a.kind for a in actions), (time.perf_counter() - t0) * 1000, move.depth)
        return actions

    def step(self, fs: FrameState) -> list[Action] | None:
        sp = self.tracker.update(fs)
        return self.on_spawn(sp) if sp else None

    def close(self) -> None:
        if self.bot:
            self.bot.close()


def frame_states(source: str, layout: Layout) -> tuple[Iterable[FrameState], object]:
    if source == "synthetic":
        from .sim_env import SimEnv
        env = SimEnv(seed=0, max_pieces=200, garbage_every=15)
        return env.frames(), env
    if Path(source).is_file():
        from .capture import VideoFile
        src = VideoFile(source)
    else:
        from .capture import CaptureCard
        src = CaptureCard(int(source))
        log.info("capture: %s", src.describe())
    return (read_frame(f, layout) for f in src.frames()), src


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="synthetic", help="'synthetic', a video path, or a V4L2 device index")
    ap.add_argument("--output", choices=["dry", "serial"], default="dry")
    ap.add_argument("--port", default=Settings().serial_port)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-nodes", type=int, default=100_000)
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    layout = Layout.load()
    frames, src = frame_states(args.source, layout)

    output: Output
    if args.source == "synthetic":
        output = src  # the fake Switch consumes the actions itself
    elif args.output == "serial":
        output = SerialOutput(args.port, Settings().serial_baud)
    else:
        output = DryRunOutput()

    player = Player(output, threads=args.threads, max_nodes=args.max_nodes)
    t0 = time.perf_counter()
    n = 0
    try:
        for fs in frames:
            n += 1
            player.step(fs)
    except KeyboardInterrupt:
        pass
    finally:
        player.close()
        src.close()
    dt = time.perf_counter() - t0
    log.info("done: %d frames, %d pieces, %.1fs", n, player.pieces, dt)
    if args.source == "synthetic":
        g = src.game
        log.info("sim result: placed=%d lines=%d height=%d dead=%s\n%s", g.pieces_placed, g.lines, g.board.height(), src.dead, g.board)


if __name__ == "__main__":
    main()
