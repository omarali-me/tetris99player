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

from .config import Layout, Settings, find_serial_port
from .engine.board import Board
from .engine.coldclear import ColdClear, Move, PollStatus, load_weights
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

    def __init__(self, output: Output, threads: int = 2, max_nodes: int = 100_000, think_ms: int = 0,
                 weights: dict | None = None):
        self.output = output
        self.weights = weights
        self.tracker = Tracker()
        self.bot: ColdClear | None = None
        self.threads, self.max_nodes = threads, max_nodes
        self.think_ms = think_ms
        self.expected: Board | None = None
        self.pieces = 0
        # After we press hold, the game shows the swapped-in piece and the tracker reports a spawn
        # for it. That spawn is ours to ignore: (piece kind, locked board before our placement).
        self.own_hold_spawn: tuple[str, set] | None = None
        self.count_pending_garbage = True

    def _launch(self, sp: Spawn) -> None:
        if self.bot:
            self.bot.close()
        # Mid-game start: the bag is unknown, so speculation on unseen pieces is off.
        self.bot = ColdClear("".join([sp.piece] + sp.queue), threads=self.threads, max_nodes=self.max_nodes,
                             board=sp.locked, hold=sp.hold, speculate=False, weights=self.weights)
        log.info("bot launched: piece=%s hold=%s queue=%s", sp.piece, sp.hold, "".join(sp.queue))

    def _get_move(self, incoming: int = 0) -> Move | None:
        """Ask for a move now. Cold Clear thinks continuously from the moment it knows the queue, and
        a request makes it answer as soon as it can, so we ask only when the piece has spawned and
        we actually need the answer. `think_ms` (synthetic mode) sleeps first to stand in for the
        drop/clear animation time a real game gives the bot."""
        assert self.bot
        if self.think_ms:
            time.sleep(self.think_ms / 1000)
        self.bot.request_move(incoming)
        deadline = time.perf_counter() + 2.0
        while True:
            status, move = self.bot.poll_move()
            if status is PollStatus.MOVE_PROVIDED:
                return move
            if status is PollStatus.BOT_DEAD:
                return None
            if time.perf_counter() > deadline:
                log.warning("bot did not answer within 2s")
                return None
            time.sleep(0.0005)

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

        # Cold Clear's `incoming` is the garbage expected after placing this piece. Red segments are
        # certain; yellow ones may still be cancelled by our own attack, so count them with a discount.
        incoming = sp.imminent + (sp.incoming - sp.imminent) // 2 if self.count_pending_garbage else sp.imminent
        move = self._get_move(incoming)
        if move is None:
            log.error("no move (bot dead?) — relaunching from current board")
            self._launch(sp)
            move = self._get_move(incoming)
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
        self.pieces += 1
        log.info("#%d %s hold=%s -> %s  (%.0f ms, depth %d%s)", self.pieces, sp.piece, move.hold,
                 " ".join(a.kind for a in actions), (time.perf_counter() - t0) * 1000, move.depth,
                 f", incoming {sp.incoming}" if sp.incoming else "")
        return actions

    def step(self, fs: FrameState) -> list[Action] | None:
        sp = self.tracker.update(fs)
        return self.on_spawn(sp) if sp else None

    def close(self) -> None:
        if self.bot:
            self.bot.close()


def frame_states(source: str, layout: Layout, garbage_every: int = 15) -> tuple[Iterable[tuple[object, FrameState]], object]:
    """Yields (raw frame or None, FrameState)."""
    if source == "synthetic":
        from .sim_env import SimEnv
        env = SimEnv(seed=0, max_pieces=200, garbage_every=garbage_every)
        return ((None, fs) for fs in env.frames()), env
    if Path(source).is_file():
        from .capture import VideoFile
        src = VideoFile(source)
    else:
        from .capture import CaptureCard
        src = CaptureCard(int(source))
        log.info("capture: %s", src.describe())
    return ((f, read_frame(f, layout)) for f in src.frames()), src


class LiveView:
    """Capture feed with the tracker's belief drawn over it. Keys: q quit, s save frame."""

    COLORS = {"I": (201, 183, 0), "O": (0, 194, 242), "T": (191, 63, 160), "S": (75, 180, 60),
              "Z": (47, 51, 224), "J": (214, 75, 47), "L": (26, 140, 242), "G": (173, 161, 154)}

    def __init__(self, layout: Layout, player: "Player"):
        import cv2
        self.cv2, self.layout, self.player = cv2, layout, player
        self.last_line = ""
        Path("recordings").mkdir(exist_ok=True)

    def show(self, frame, fs: FrameState) -> bool:
        """Returns False when the user quits."""
        cv2, L = self.cv2, self.layout
        vis = frame.copy()
        st = self.player.tracker.state
        cw, ch = int(L.cell_w), int(L.cell_h)
        for (x, y) in st.locked:
            if y < 20:
                px, py = L.cell_center(19 - y, x)
                cv2.rectangle(vis, (px - cw // 2 + 4, py - ch // 2 + 4), (px + cw // 2 - 4, py + ch // 2 - 4), (255, 255, 255), 1)
        for (x, y) in st.active:
            if y < 20:
                px, py = L.cell_center(19 - y, x)
                cv2.circle(vis, (px, py), 6, (0, 255, 0), -1)
        for r in range(20):
            for c in range(10):
                cell = fs.grid[r][c].value
                if cell in self.COLORS:
                    px, py = L.cell_center(r, c)
                    cv2.circle(vis, (px, py), 3, self.COLORS[cell], -1)
        b = L.board
        cv2.rectangle(vis, (b.x, b.y), (b.x + b.w, b.y + b.h), (0, 255, 0), 1)
        hud = [
            f"current={st.current or '?'} hold={st.hold or '-'} queue={''.join(st.queue) or '?'} spawns={st.spawns} pieces={self.player.pieces}",
            f"read: hold={fs.hold.value if fs.hold else '-'} queue={''.join(q.value if q else '?' for q in fs.queue)} garbage={fs.garbage.pending}+{fs.garbage.imminent}red",
            self.last_line,
            "white boxes = locked stack   green dots = active piece   |   s save frame   q quit",
        ]
        for i, t in enumerate(hud):
            cv2.putText(vis, t, (20, 40 + 32 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(vis, t, (20, 40 + 32 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (60, 255, 60), 2)
        cv2.imshow("tetris99 live", cv2.resize(vis, (1280, 720)))
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            return False
        if k == ord("s"):
            p = f"recordings/frame_{int(time.time())}.png"
            cv2.imwrite(p, frame)
            log.info("saved %s", p)
        return True

    def close(self):
        self.cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="synthetic", help="'synthetic', a video path, or a V4L2 device index")
    ap.add_argument("--output", choices=["dry", "serial"], default="dry")
    ap.add_argument("--port", default=Settings().serial_port)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--max-nodes", type=int, default=100_000)
    ap.add_argument("--show", action="store_true", help="show the capture feed with the tracker's view drawn over it")
    ap.add_argument("--garbage-every", type=int, default=15, help="synthetic only: 2 garbage lines every N pieces")
    ap.add_argument("--think", type=int, default=50, help="synthetic only: ms the bot may think per piece (a real game gives it this during the drop animation)")
    ap.add_argument("--weights", help="JSON file overriding Cold Clear weights (see config/weights.json)")
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    weights = load_weights(args.weights) if args.weights else None
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    layout = Layout.load()
    frames, src = frame_states(args.source, layout, args.garbage_every)

    output: Output
    if args.source == "synthetic":
        output = src  # the fake Switch consumes the actions itself
    elif args.output == "serial":
        output = SerialOutput(find_serial_port(args.port), Settings().serial_baud)
    else:
        output = DryRunOutput()

    player = Player(output, threads=args.threads, max_nodes=args.max_nodes, weights=weights,
                    think_ms=args.think if args.source == "synthetic" else 0)
    view = LiveView(layout, player) if args.show and args.source != "synthetic" else None

    class _Hook(logging.Handler):  # mirror the last decision line into the overlay
        def emit(self, record):
            if view and record.levelno >= logging.INFO:
                view.last_line = record.getMessage()[:110]
    log.addHandler(_Hook())

    t0 = time.perf_counter()
    n = 0
    try:
        for frame, fs in frames:
            n += 1
            player.step(fs)
            if view and not view.show(frame, fs):
                break
    except KeyboardInterrupt:
        pass
    finally:
        player.close()
        src.close()
        if view:
            view.close()
    dt = time.perf_counter() - t0
    log.info("done: %d frames, %d pieces, %.1fs", n, player.pieces, dt)
    if args.source == "synthetic":
        g = src.game
        log.info("sim result: placed=%d lines=%d height=%d dead=%s\n%s", g.pieces_placed, g.lines, g.board.height(), src.dead, g.board)


if __name__ == "__main__":
    main()
