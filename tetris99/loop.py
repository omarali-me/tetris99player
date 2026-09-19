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
from .engine.coach import MODES, map_plan, plan_from, rows_to_original
from .engine.coldclear import ColdClear, Move, PlanStep, PollStatus, load_weights, valid_sequence
from .engine.executor import Action, compile_move
from .vision.board import FrameState, read_frame
from .vision.tracker import Spawn, Tracker, board_cells, to_board


log = logging.getLogger("loop")


def garbage_rows(expected: Board, seen: Board) -> int:
    """If `seen` is `expected` pushed up by k garbage rows (each full except one hole), return k."""
    for k in range(1, 13):
        if seen.rows[k:] == expected.rows[: len(expected.rows) - k] and all(
                bin(r).count("1") == 9 for r in seen.rows[:k]):
            return k
    return 0


class Output(Protocol):
    def run(self, actions: list[Action]) -> None: ...


class DryRunOutput:
    def run(self, actions: list[Action]) -> None:
        log.info("ACTIONS %s", " ".join(a.kind for a in actions))


class SerialOutput:
    """Real controller. `live` tells the Player it can do closed-loop soft drops: press down, watch
    the piece through the capture feed, release when it lands."""
    live = True

    def __init__(self, port: str, baud: int):
        from .control import switch_controller as sc
        self.sc = sc
        self.ctl = sc.SwitchController(port, baud)
        if not self.ctl.ping():
            raise RuntimeError("controller did not answer ping")

    def run(self, actions: list[Action]) -> None:
        self.sc.run_actions(self.ctl, actions)

    def duration(self, actions: list[Action]) -> float:
        """Seconds the Arduino needs to play these (taps only)."""
        return len(actions) * (self.sc.TAP_MS + self.sc.GAP_MS) / 1000

    def down(self, pressed: bool) -> None:
        from .control.protocol import Hat, Op
        self.ctl._send(Op.HAT, int(Hat.DOWN if pressed else Hat.CENTER))
        if not pressed:
            self.ctl._send(Op.WAIT, self.sc.GAP_MS)


class Player:
    """Drives one game. Feed FrameStates via step(); it returns the actions it issued, if any."""

    def __init__(self, output: Output, threads: int = 2, max_nodes: int = 100_000, think_ms: int = 0,
                 weights: dict | None = None, trainer: bool = False, plan_len: int = 4):
        self.output = output
        self.weights = weights
        self.trainer = trainer          # coach mode: a human plays; layouts are shown on demand
        self.plan_len = plan_len
        self.target: tuple[str, list[tuple[int, int]], bool] | None = None  # (piece, cells, hold first)
        self.plan: list[PlanStep] = []
        self.mode = "normal"
        self.plan_steps: list[PlanStep] = []   # coach layout as Cold Clear gave it (per-step coordinates)
        self.laid_done = 0                      # steps already placed: hidden, and the rest re-mapped to the live board
        self.visible: int | None = None         # None = show all remaining steps, k = show the first k
        self._last_locked: set = set()
        self.tracker = Tracker()
        self.bot: ColdClear | None = None
        self.threads, self.max_nodes = threads, max_nodes
        self.think_ms = think_ms
        self.expected: Board | None = None
        self.pieces = 0
        # After we press hold, the game shows the swapped-in piece and the tracker reports a spawn
        # for it. That spawn is ours to ignore: (piece kind, locked board before our placement).
        self.own_hold_spawn: tuple[str, set] | None = None
        self.divergences = 0
        self.garbage_events = 0
        self.fresh_think_ms = 90
        # closed-loop execution: segments of taps separated by soft drops that end when the piece lands
        self.segments: list[list[Action]] = []
        self.drop_state: dict | None = None
        self.last_actions: list[Action] = []
        self.last_kind = ""
        self.last_cleared = 0
        self.count_pending_garbage = True

    def _launch(self, sp: Spawn) -> None:
        self._fresh = True   # a new bot has no search tree yet: let it think briefly before asking
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
        elif getattr(self, "_fresh", False) and getattr(self.output, "live", False):
            time.sleep(self.fresh_think_ms / 1000)   # ~depth 5-6 instead of depth 1 after a relaunch
        self._fresh = False
        self.bot.request_move(incoming)
        deadline = time.perf_counter() + 2.0
        while True:
            status, move = self.bot.poll_move(self.plan_len)
            if status is PollStatus.MOVE_PROVIDED:
                self.plan = list(self.bot.plan)
                return move
            if status is PollStatus.BOT_DEAD:
                return None
            if time.perf_counter() > deadline:
                log.warning("bot did not answer within 2s")
                return None
            time.sleep(0.0005)

    def on_spawn(self, sp: Spawn) -> list[Action] | None:
        t0 = time.perf_counter()
        if not valid_sequence([sp.piece] + sp.queue, sp.hold):
            # A misread (menu, countdown, KO screen). Drop the bot; it is relaunched from a sane reading.
            log.warning("ignoring impossible reading: piece=%s hold=%s queue=%s", sp.piece, sp.hold, "".join(sp.queue))
            if self.bot:
                self.bot.close()
                self.bot = None
            self.expected = None
            self.target = None
            self.plan = []
            return None
        if self.bot is None:
            self._launch(sp)
        else:
            for p in sp.new_pieces:
                self.bot.add_next_piece(p)
            if self.own_hold_spawn and self.own_hold_spawn == (sp.piece, board_cells(sp.locked)):
                self.own_hold_spawn = None
                self.tracker.expected_locked = board_cells(self.expected) if self.expected else None
                self.tracker.trust_expected = self.last_cleared > 0 and getattr(self.output, "live", False)
                log.debug("ignoring spawn caused by our own hold press")
                return None
            self.own_hold_spawn = None
            if sp.garbage_arrived or (self.expected is not None and board_cells(sp.locked) != board_cells(self.expected)):
                # A reset with a request in flight can hand back a stale move; relaunching is race-free.
                if self.expected is not None:
                    seen, exp = board_cells(sp.locked), board_cells(self.expected)
                    k = garbage_rows(self.expected, sp.locked)
                    if k:
                        self.garbage_events += 1
                        log.info("garbage +%d lines (placement was correct)", k)
                    else:
                        self.divergences += 1
                        log.info("DIVERGED after %s [%s]: missing=%s extra=%s cleared=%d",
                                 self.last_kind, " ".join(a.kind for a in self.last_actions),
                                 sorted(exp - seen)[:12], sorted(seen - exp)[:12], self.last_cleared)
                (log.debug if self.trainer else log.info)("board differs from prediction (garbage or misplaced piece): relaunching bot")
                self._launch(sp)

        # Cold Clear's `incoming` is the garbage expected after placing this piece. Red and yellow
        # segments are close; grey ones are freshly queued and may still be cancelled by our own
        # attack, so they count half.
        incoming = sp.incoming if self.count_pending_garbage else sp.imminent
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
            # The bot's idea of the board was stale. Relaunch from what we see and ask again, once.
            log.error("executor rejected path: %s; relaunching bot and retrying", e)
            self._launch(sp)
            move = self._get_move(incoming)
            if move is None:
                return None
            kind = sp.piece if not move.hold else (sp.hold if sp.hold else sp.queue[0])
            try:
                actions, final = compile_move(sp.locked, kind, move)
            except RuntimeError as e2:
                log.error("rejected again (%s); skipping this piece", e2)
                return None

        if move.hold:
            self.own_hold_spawn = (kind, board_cells(sp.locked))
        self.target = (kind, list(final.cells()), move.hold)
        if not self.trainer:
            self._execute(actions)
        board = Board(list(sp.locked.rows))
        self.last_cleared = board.place(final.cells())
        self.last_actions, self.last_kind = actions, kind
        self.expected = board
        self.tracker.expected_locked = board_cells(board)
        self.tracker.trust_expected = self.last_cleared > 0 and getattr(self.output, "live", False)
        self.pieces += 1
        if self.trainer:
            log.info("#%d place %s%s at %s  (depth %d)", self.pieces, kind,
                     " (press HOLD first)" if move.hold else "", sorted(final.cells()), move.depth)
        else:
            log.info("#%d %s hold=%s -> %s  (%.0f ms, depth %d%s)", self.pieces, sp.piece, move.hold,
                     " ".join(a.kind for a in actions), (time.perf_counter() - t0) * 1000, move.depth,
                     f", incoming {sp.incoming}" if sp.incoming else "")
        return actions

    # ------------------------------------------------------------------ coach (trainer) mode
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        log.info("coach mode: %s", mode)

    def plan_now(self, think_ms: int = 600, max_steps: int = 8) -> list[tuple[str, list[tuple[int, int]]]]:
        """Read the tracker's current view of the game and lay out Cold Clear's placements for every
        known piece (current, hold, queue). Returns [(piece, cells in the CURRENT board's rows)]."""
        st = self.tracker.state
        if not st.current or not st.queue:
            log.warning("no piece information yet; wait for a piece to spawn, then press space")
            return []
        plan = plan_from(to_board(st.locked), st.current, list(st.queue), st.hold, self.mode,
                         think_ms=think_ms, max_steps=max_steps, threads=self.threads, max_nodes=self.max_nodes)
        if plan is None:
            log.warning("no plan (impossible reading or bot gave nothing); try again")
            return []
        steps = plan.steps
        self.plan_steps = steps
        self.laid_done = 0
        self.visible = None
        self._last_locked = set(st.locked)
        laid, _ = self.layout()
        log.info("coach [%s]: %s", self.mode, " ".join(f"{i + 1}:{p}" for i, (p, _) in enumerate(laid)) or "no plan")
        return laid

    @property
    def laid(self) -> list[tuple[str, list[tuple[int, int]]]]:
        return self.layout()[0] if self.plan_steps else []

    def layout(self) -> tuple[list[tuple[str, list[tuple[int, int]]]], list[tuple[int, int]]]:
        """Remaining steps mapped onto the board as it is now (earlier steps' clears have happened)."""
        return map_plan(self.plan_steps[self.laid_done:], first_number=self.laid_done + 1)

    def shown(self) -> tuple[list[tuple[int, tuple[str, list[tuple[int, int]]]]], list[tuple[int, int]]]:
        """(numbered remaining steps to draw, clear markers), honouring the h / j visibility setting."""
        laid, clears = self.layout()
        numbered = list(enumerate(laid, start=self.laid_done + 1))
        if self.visible is not None:
            numbered = numbered[: self.visible]
            last = numbered[-1][0] if numbered else 0
            clears = [(r, n) for r, n in clears if n <= last]
        return numbered, clears

    def toggle_all(self) -> None:          # h
        self.visible = 0 if self.visible is None else None

    def show_next(self) -> None:           # j
        remaining = len(self.plan_steps) - self.laid_done
        self.visible = 1 if self.visible in (None, 0) else min(remaining, self.visible + 1)

    def coach_step(self, fs: FrameState) -> None:
        """Trainer mode per frame: keep tracking. Each time the locked stack changes a piece was
        placed, so the next step of the layout is hidden (hold presses change nothing and are not
        counted). The layout is cleared once every step is placed."""
        sp = self.tracker.update(fs)
        if sp is None or not self.plan_steps:
            return
        locked = board_cells(sp.locked)
        if locked != self._last_locked:
            self._last_locked = locked
            self.laid_done += 1
            if self.visible:
                self.visible = max(1, self.visible - 1)  # keep the same number of upcoming steps visible
            if self.laid_done >= len(self.plan_steps):
                log.info("layout complete; press space for the next one")
                self.plan_steps, self.laid_done = [], 0

    # ------------------------------------------------------------------ execution
    def _execute(self, actions: list[Action]) -> None:
        """Send a move. With a live controller, a soft drop is closed-loop: everything up to it is
        sent, then down is held until the capture feed shows the piece has stopped falling."""
        if not getattr(self.output, "live", False) or not any(a.kind == "soft_drop" for a in actions):
            self.output.run(actions)
            return
        self.segments, cur = [], []
        for a in actions:
            if a.kind == "soft_drop":
                self.segments.append(cur); self.segments.append([a]); cur = []
            else:
                cur.append(a)
        self.segments.append(cur)
        self._advance_segments()

    def _advance_segments(self) -> None:
        while self.segments:
            seg = self.segments.pop(0)
            if seg and seg[0].kind == "soft_drop":
                self.output.down(True)
                now = time.perf_counter()
                self.drop_state = {"watch_from": now + self._busy_for + 0.12, "deadline": now + self._busy_for + seg[0].rows * 0.07 + 1.0,
                                   "y": None, "start_y": None, "stable": 0, "rows": seg[0].rows}
                self._busy_for = 0.0
                return
            if seg:
                self.output.run(seg)
                self._busy_for = self.output.duration(seg)
        self.drop_state = None

    _busy_for = 0.0

    def _watch_drop(self) -> None:
        """Called every frame while down is held: release once the piece's height stops changing."""
        ds, now = self.drop_state, time.perf_counter()
        active = self.tracker.state.active
        y = min((c[1] for c in active), default=None)
        if now >= ds["watch_from"] and y is not None:
            if ds["start_y"] is None:
                ds["start_y"] = y
            ds["stable"] = ds["stable"] + 1 if y == ds["y"] else 0
            ds["y"] = y
        # Landed = it has come down from where it started AND then held still for 100 ms. Right after
        # down is pressed the piece looks still for ~120 ms of latency; that must not count.
        descended = ds["rows"] == 0 or (ds["start_y"] is not None and ds["y"] is not None and ds["y"] < ds["start_y"])
        if (descended and ds["stable"] >= 6) or now >= ds["deadline"]:
            if now >= ds["deadline"]:
                log.warning("soft drop: landing not seen in time; releasing")
            self.output.down(False)
            self.drop_state = None
            self._busy_for = 0.0
            self._advance_segments()

    def step(self, fs: FrameState) -> list[Action] | None:
        if self.trainer:
            self.coach_step(fs)
            return None
        sp = self.tracker.update(fs)
        if self.drop_state is not None:
            if sp is not None:          # the piece locked under us; abandon the rest of this move
                log.warning("piece locked during a soft drop; dropping the rest of the move")
                self.output.down(False)
                self.drop_state, self.segments = None, []
            else:
                self._watch_drop()
                return None
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

    SCALE = 2 / 3  # draw on a 1280x720 copy: same window, a third of the pixels to touch

    def __init__(self, layout: Layout, player: "Player"):
        import os
        if os.path.isdir("/usr/share/fonts/truetype/dejavu"):
            os.environ.setdefault("QT_QPA_FONTDIR", "/usr/share/fonts/truetype/dejavu")  # quiets cv2's Qt font warning
        import cv2
        self.cv2, self.layout, self.player = cv2, layout, player
        self.last_line = ""
        Path("recordings").mkdir(exist_ok=True)
        cv2.namedWindow("tetris99 live", cv2.WINDOW_NORMAL)  # resizable; maximise it for a bigger view
        cv2.resizeWindow("tetris99 live", 1280, 720)

    def render(self, frame, fs: FrameState):
        """Draw the overlay onto a 1280x720 copy of the frame and return it."""
        cv2, L, k = self.cv2, self.layout, self.SCALE
        vis = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        st = self.player.tracker.state
        S = lambda v: int(v * k)
        cw, ch = S(L.cell_w), S(L.cell_h)
        coach = self.player.trainer

        def cell_box(x, y, inset):
            px, py = L.cell_center(19 - y, x)
            return (S(px) - cw // 2 + inset, S(py) - ch // 2 + inset), (S(px) + cw // 2 - inset, S(py) + ch // 2 - inset)

        if not coach:
            for (x, y) in st.locked:
                if y < 20:
                    p0, p1 = cell_box(x, y, 3)
                    cv2.rectangle(vis, p0, p1, (255, 255, 255), 1)
            for (x, y) in st.active:
                if y < 20:
                    px, py = L.cell_center(19 - y, x)
                    cv2.circle(vis, (S(px), S(py)), 5, (0, 255, 0), -1)
            for r in range(20):
                for c in range(10):
                    cell = fs.grid[r][c].value
                    if cell in self.COLORS:
                        px, py = L.cell_center(r, c)
                        cv2.circle(vis, (S(px), S(py)), 2, self.COLORS[cell], -1)
            b = L.board
            cv2.rectangle(vis, (S(b.x), S(b.y)), (S(b.x + b.w), S(b.y + b.h)), (0, 255, 0), 1)

        # coach layout: translucent fills, one outline per tetromino, a big number on each
        todo, clears = self.player.shown() if coach else ([], [])
        if todo:
            fill = vis.copy()
            for _, (piece, cells) in todo:
                col = self.COLORS.get(piece, (200, 200, 200))
                for (x, y) in cells:
                    if y < 20:
                        p0, p1 = cell_box(x, y, 2)
                        cv2.rectangle(fill, p0, p1, col, -1)
            cv2.addWeighted(fill, 0.22, vis, 0.78, 0, vis)  # faint tint: ghost and placed blocks show through
            b = L.board
            for row, step in clears:
                if row < 20:
                    y = S(L.cell_center(19 - row, 0)[1])
                    for x0 in range(S(b.x), S(b.x + b.w), 12):
                        cv2.line(vis, (x0, y), (min(x0 + 6, S(b.x + b.w)), y), (255, 255, 255), 2)
                    cv2.putText(vis, f"clears @{step}", (S(b.x + b.w) + 6, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
                    cv2.putText(vis, f"clears @{step}", (S(b.x + b.w) + 6, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            for i, (piece, cells) in todo:
                col = self.COLORS.get(piece, (200, 200, 200))
                cs = set(cells)
                for (x, y) in cells:
                    if y >= 20:
                        continue
                    p0, p1 = cell_box(x, y, 2)
                    # outline in the piece colour with a dark halo; only edges not shared within the piece
                    edges = []
                    if (x, y + 1) not in cs: edges.append(((p0[0], p0[1]), (p1[0], p0[1])))
                    if (x, y - 1) not in cs: edges.append(((p0[0], p1[1]), (p1[0], p1[1])))
                    if (x - 1, y) not in cs: edges.append(((p0[0], p0[1]), (p0[0], p1[1])))
                    if (x + 1, y) not in cs: edges.append(((p1[0], p0[1]), (p1[0], p1[1])))
                    for a, b_ in edges:
                        cv2.line(vis, a, b_, (0, 0, 0), 4)
                    for a, b_ in edges:
                        cv2.line(vis, a, b_, (255, 255, 255), 2)
                vis_cells = [c for c in cells if c[1] < 20]
                if vis_cells:
                    cx = sum(S(L.cell_center(19 - y, x)[0]) for x, y in vis_cells) / len(vis_cells)
                    cy = sum(S(L.cell_center(19 - y, x)[1]) for x, y in vis_cells) / len(vis_cells)
                    label = str(i)
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.95, 2)
                    org = (int(cx - tw / 2), int(cy + th / 2))
                    cv2.putText(vis, label, org, cv2.FONT_HERSHEY_DUPLEX, 0.95, (0, 0, 0), 5)
                    cv2.putText(vis, label, org, cv2.FONT_HERSHEY_DUPLEX, 0.95, (255, 255, 255), 2)

        if self.player.target and not coach:
            kind, cells, hold_first = self.player.target
            col = self.COLORS.get(kind, (255, 255, 255))
            for (x, y) in cells:
                if y < 20:
                    p0, p1 = cell_box(x, y, 3)
                    cv2.rectangle(vis, p0, p1, (255, 255, 255), 4)
                    cv2.rectangle(vis, p0, p1, col, 2)
            if hold_first:
                hb = L.hold
                cv2.rectangle(vis, (S(hb.x) - 4, S(hb.y) - 4), (S(hb.x + hb.w) + 4, S(hb.y + hb.h) + 4), (0, 255, 255), 3)
                cv2.putText(vis, "HOLD", (S(hb.x), S(hb.y + hb.h) + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        if coach:
            hud = [
                f"COACH [{self.player.mode}]   piece={st.current or '?'} hold={st.hold or '-'} next={''.join(st.queue) or '?'}"
                + (f"   layout: {self.player.laid_done}/{len(self.player.plan_steps)} placed"
                   + ("   (hidden: h)" if self.player.visible == 0 else f"   (showing {self.player.visible})" if self.player.visible else "")
                   if self.player.plan_steps else "   press SPACE to lay out"),
                self.last_line,
                "space: new layout   h: hide/show   j: reveal one more   t: T-spins   a: all clears   n: normal   s: save   q: quit",
            ]
        else:
            hud = [
                f"current={st.current or '?'} hold={st.hold or '-'} queue={''.join(st.queue) or '?'} spawns={st.spawns} pieces={self.player.pieces}",
                f"read: hold={fs.hold.value if fs.hold else '-'} queue={''.join(q.value if q else '?' for q in fs.queue)} garbage={fs.garbage.pending}+{fs.garbage.imminent}red",
                self.last_line,
                "white boxes = locked stack   green dots = active piece   |   s save frame   q quit",
            ]
        for i, t in enumerate(hud):
            cv2.putText(vis, t, (14, 26 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(vis, t, (14, 26 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 255, 60), 1)
        return vis

    def show(self, frame, fs: FrameState) -> bool:
        """Returns False when the user quits."""
        cv2 = self.cv2
        cv2.imshow("tetris99 live", self.render(frame, fs))
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            return False
        if self.player.trainer:
            if k == ord(" "):
                self.player.plan_now()
            elif k == ord("h"):
                self.player.toggle_all()
            elif k == ord("j"):
                self.player.show_next()
            elif k == ord("t"):
                self.player.set_mode("tspin")
            elif k == ord("a"):
                self.player.set_mode("allclear")
            elif k == ord("n"):
                self.player.set_mode("normal")
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
    ap.add_argument("--trainer", action="store_true", help="coach: you play; press space to lay out Cold Clear's placements for all known pieces (implies --show)")
    ap.add_argument("--mode", choices=["normal", "tspin", "allclear"], default="normal", help="coach: starting mode")
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

    if args.trainer:
        args.show = True
        output = DryRunOutput()
    player = Player(output, threads=args.threads, max_nodes=args.max_nodes, weights=weights,
                    think_ms=args.think if args.source == "synthetic" else (300 if args.trainer else 0),
                    trainer=args.trainer)
    player.mode = args.mode
    view = LiveView(layout, player) if args.show and args.source != "synthetic" else None

    class _Hook(logging.Handler):  # mirror the last decision line into the overlay
        def emit(self, record):
            if view and record.levelno >= logging.INFO:
                view.last_line = record.getMessage()[:110]
    log.addHandler(_Hook())

    t0 = time.perf_counter()
    n = 0
    t_report, n_report = t0, 0
    last_progress, last_pieces, stall_logged = t0, 0, False
    try:
        for frame, fs in frames:
            n += 1
            player.step(fs)
            # stall detector: in game mode a spawn should come every second or two
            if player.pieces != last_pieces:
                last_pieces, last_progress, stall_logged = player.pieces, time.perf_counter(), False
            elif (not args.trainer and frame is not None and player.pieces > 0 and not stall_logged
                  and time.perf_counter() - last_progress > 3.0):
                stall_logged = True
                import cv2
                path = f"recordings/stall_{int(time.time())}.png"
                cv2.imwrite(path, frame)
                st = player.tracker.state
                log.warning("no spawn for 3 s. tracker: current=%s hold=%s queue=%s | frame reads hold=%s queue=%s | saved %s",
                            st.current, st.hold, "".join(st.queue), fs.hold.value if fs.hold else "-",
                            "".join(q.value if q else "?" for q in fs.queue), path)
            if view and n % 2 == 0 and not view.show(frame, fs):  # overlay at 30 fps, tracking at 60
                break
            now = time.perf_counter()
            if args.source != "synthetic" and now - t_report >= 5.0:
                log.info("fps %.1f", (n - n_report) / (now - t_report))
                t_report, n_report = now, n
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
