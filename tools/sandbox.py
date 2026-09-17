"""Keyboard Tetris sandbox with the coach, an explorer of alternative placements, undo/redo,
pause, and T-spin lessons. Everything runs on the project's own engine and Cold Clear.

    .venv/bin/python tools/sandbox.py            # free play
    .venv/bin/python tools/sandbox.py --lesson 2 # start in a lesson

Keys (also shown with F1):
  move: arrows       rotate: up / x = CW, z = CCW      soft drop: down     hard drop: space
  hold: c or shift   pause: p   gravity on/off: g      undo / redo: u / r  restart: F5
  coach: k lay out all known pieces   h hide/show   j reveal one more   t / a / n mode
  explore: e enter/leave   left/right pick a placement   enter place it   v evaluate it with Cold Clear
  lessons: l menu, then 1-9          quit: q
"""
from __future__ import annotations

import argparse
import sys
import time

import pygame

from tetris99.engine.board import Board
from tetris99.engine.coach import MODES, map_plan, plan_from
from tetris99.engine.explore import Placement, reachable_placements
from tetris99.engine.game import Game, Lock
from tetris99.engine.piece import CELLS, FallingPiece, rotation_points
from tetris99.sandbox.lessons import BY_KEY, LESSONS

CELL = 32
BOARD_X, BOARD_Y = 230, 40
PANEL_X = BOARD_X + 10 * CELL + 40
W, H = PANEL_X + 470, BOARD_Y + 20 * CELL + 40
BG = (22, 23, 28); GRID = (42, 44, 52); INK = (232, 234, 240); INK2 = (150, 156, 170); WARN = (255, 170, 80)
COLORS = {"I": (0, 205, 215), "O": (240, 210, 0), "T": (170, 50, 200), "S": (60, 200, 60),
          "Z": (230, 50, 50), "J": (30, 90, 220), "L": (250, 140, 20), "G": (120, 120, 120)}
ROT_NAMES = ["N", "E", "S", "W"]
LOCK_DELAY_MS = 500


def draw_cell(surf, px, py, color, size=CELL, alpha=None, outline=None):
    if alpha is None:
        pygame.draw.rect(surf, color, (px + 1, py + 1, size - 2, size - 2))
        hi = tuple(min(255, int(c * 1.3)) for c in color)
        pygame.draw.rect(surf, hi, (px + 1, py + 1, size - 2, size - 2), 1)
    else:
        s = pygame.Surface((size - 2, size - 2), pygame.SRCALPHA)
        s.fill((*color, alpha))
        surf.blit(s, (px + 1, py + 1))
    if outline:
        pygame.draw.rect(surf, outline, (px + 1, py + 1, size - 2, size - 2), 2)


class Coach:
    """Layout state: Cold Clear's steps, how many were placed, what is shown (same rules as live mode)."""

    def __init__(self):
        self.mode = "normal"
        self.steps = []
        self.done = 0
        self.visible: int | None = None
        self.summary = ""

    def layout(self):
        return map_plan(self.steps[self.done:], first_number=self.done + 1)

    def shown(self):
        laid, clears = self.layout()
        numbered = list(enumerate(laid, start=self.done + 1))
        if self.visible is not None:
            numbered = numbered[: self.visible]
            last = numbered[-1][0] if numbered else 0
            clears = [(r, n) for r, n in clears if n <= last]
        return numbered, clears

    def placed(self):
        if not self.steps:
            return
        self.done += 1
        if self.visible:
            self.visible = max(1, self.visible - 1)
        if self.done >= len(self.steps):
            self.steps, self.done = [], 0


class App:
    def __init__(self, lesson: str | None):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("tetris99 sandbox")
        self.f = pygame.font.SysFont("dejavusansmono", 15)
        self.fb = pygame.font.SysFont("dejavusansmono", 15, bold=True)
        self.fl = pygame.font.SysFont("dejavusans", 26, bold=True)
        pygame.key.set_repeat(170, 33)  # DAS 170 ms, ARR 33 ms
        self.game = Game(seed=int(time.time()) % 100000)
        self.coach = Coach()
        self.paused = False
        self.gravity = True
        self.gravity_ms = 800
        self.last_fall = time.time()
        self.landed_since: float | None = None
        self.resets = 0
        self.lesson = None
        self.lesson_done = False
        self.lesson_menu = False
        self.help = False
        self.explore: list[Placement] = []
        self.explore_idx = 0
        self.explore_eval: dict[int, str] = {}
        self.msg = ""
        self.last_lock: Lock | None = None
        self.kick_note: list[str] = []
        if lesson:
            self.start_lesson(lesson)

    # ------------------------------------------------------------ lessons / state
    def start_lesson(self, key: str):
        les = BY_KEY.get(key)
        if not les:
            return
        self.lesson, self.lesson_done = les, False
        les.load(self.game)
        self.coach = Coach(); self.coach.mode = les.coach_mode
        self.explore = []; self.paused = False; self.gravity = False
        self.msg = f"Lesson {les.key}: {les.title}"

    def restart(self):
        if self.lesson:
            self.start_lesson(self.lesson.key)
        else:
            self.game = Game(seed=int(time.time()) % 100000)
            self.coach = Coach(); self.explore = []; self.msg = "new game"

    def after_lock(self, lk: Lock):
        self.last_lock = lk
        self.coach.placed()
        self.landed_since, self.resets = None, 0
        self.explore = []
        self.kick_note = self.explain_kick(lk)
        if self.lesson and not self.lesson_done and self.lesson.done(self.game, lk):
            self.lesson_done = True
            self.msg = f"LESSON COMPLETE: {self.lesson.goal}"
        elif lk.label():
            self.msg = lk.label()
        if self.game.dead:
            self.msg = "topped out: F5 restarts, U undoes"

    def explain_kick(self, lk: Lock) -> list[str]:
        if not lk.tspin:
            return []
        note = [f"T-spin ({lk.tspin}): 3+ corners filled after the rotation {lk.rotation}."]
        if lk.kick is not None:
            dx, dy = lk.kick_offset
            if lk.kick == 0:
                note.append("Kick 1 of 5: no offset, the T turned in place.")
            else:
                note.append(f"Kick {lk.kick + 1} of 5: offset ({dx:+d}, {dy:+d}) after the first {lk.kick} collided.")
            if lk.kick == 4:
                note.append("The fifth kick moves 1 sideways and 2 down: the TST kick.")
        return note

    # ------------------------------------------------------------ input
    def key(self, ev):
        g, k = self.game, ev.key
        if self.lesson_menu:
            self.lesson_menu = False
            if ev.unicode in BY_KEY:
                self.start_lesson(ev.unicode)
            elif ev.unicode == "0":
                self.lesson = None; self.restart()
            return
        if k == pygame.K_q:
            raise SystemExit
        if k == pygame.K_F1: self.help = not self.help; return
        if k == pygame.K_F5: self.restart(); return
        if k == pygame.K_l: self.lesson_menu = True; return
        if k == pygame.K_p: self.paused = not self.paused; self.msg = "paused" if self.paused else ""; return
        if k == pygame.K_g: self.gravity = not self.gravity; self.msg = f"gravity {'on' if self.gravity else 'off'}"; return
        if k == pygame.K_u:
            if g.undo(): self.coach.done = max(0, self.coach.done - 1); self.explore = []; self.msg = "undo"
            return
        if k == pygame.K_r:
            if g.redo(): self.explore = []; self.msg = "redo"
            return
        # coach
        if k == pygame.K_k: self.lay_out(); return
        if k == pygame.K_h: self.coach.visible = 0 if self.coach.visible is None else None; return
        if k == pygame.K_j:
            rem = len(self.coach.steps) - self.coach.done
            self.coach.visible = 1 if self.coach.visible in (None, 0) else min(rem, self.coach.visible + 1); return
        if k == pygame.K_t: self.coach.mode = "tspin"; self.msg = "coach: T-spin mode"; return
        if k == pygame.K_a: self.coach.mode = "allclear"; self.msg = "coach: all-clear mode"; return
        if k == pygame.K_n: self.coach.mode = "normal"; self.msg = "coach: normal mode"; return
        # explore
        if k == pygame.K_e:
            if self.explore:
                self.explore = []; self.msg = ""
            else:
                self.explore = reachable_placements(g.board, g.piece.kind); self.explore_idx = 0; self.explore_eval = {}
                self.msg = f"explore: {len(self.explore)} placements for {g.piece.kind}. left/right, enter, v evaluates"
            return
        if self.explore:
            if k == pygame.K_LEFT: self.explore_idx = (self.explore_idx - 1) % len(self.explore)
            elif k == pygame.K_RIGHT: self.explore_idx = (self.explore_idx + 1) % len(self.explore)
            elif k == pygame.K_RETURN: self.place_explored()
            elif k == pygame.K_v: self.evaluate_explored()
            elif k == pygame.K_ESCAPE: self.explore = []
            return
        if g.dead or self.paused:
            return
        moved = False
        if k == pygame.K_LEFT: moved = g.move(-1)
        elif k == pygame.K_RIGHT: moved = g.move(1)
        elif k in (pygame.K_UP, pygame.K_x): moved = g.rotate(True) is not None
        elif k == pygame.K_z: moved = g.rotate(False) is not None
        elif k == pygame.K_DOWN:
            if not g.soft_drop():
                pass
            moved = True
        elif k == pygame.K_SPACE: self.after_lock(g.hard_drop()); return
        elif k in (pygame.K_c, pygame.K_LSHIFT, pygame.K_RSHIFT):
            if g.use_hold(): self.explore = []
            return
        if moved and self.landed_since is not None and self.resets < 15:
            self.landed_since = time.time(); self.resets += 1

    # ------------------------------------------------------------ coach / explore actions
    def lay_out(self):
        g = self.game
        self.msg = "coach is thinking..."; self.draw(); pygame.display.flip()
        plan = plan_from(g.board, g.piece.kind, g.next_queue(), g.hold, self.coach.mode, think_ms=700)
        if plan is None:
            self.msg = "coach: no plan (bag looks impossible)"; return
        self.coach.steps, self.coach.done, self.coach.visible = plan.steps, 0, None
        self.coach.summary = plan.summary()
        self.msg = f"coach [{self.coach.mode}]: {plan.summary()}"

    def place_explored(self):
        g = self.game
        pl = self.explore[self.explore_idx]
        # replay its path from spawn so the spin/kick bookkeeping is genuine
        g.piece = FallingPiece.spawn(g.piece.kind, g.board)
        g.last_was_rotation, g.last_kick = False, None
        for mv in pl.path:
            {"L": lambda: g.move(-1), "R": lambda: g.move(1), "CW": lambda: g.rotate(True),
             "CCW": lambda: g.rotate(False), "D": g.sonic_drop}[mv]()
        self.after_lock(g.lock())
        self.explore = []

    def evaluate_explored(self):
        g = self.game
        pl = self.explore[self.explore_idx]
        self.msg = "evaluating with Cold Clear..."; self.draw(); pygame.display.flip()
        b = Board(list(g.board.rows)); b.place(pl.cells)
        queue = g.next_queue()
        plan = plan_from(b, queue[0], queue[1:], g.hold, self.coach.mode, think_ms=400, max_steps=7)
        text = plan.summary() if plan else "no continuation"
        self.explore_eval[self.explore_idx] = text
        self.msg = f"after this placement: {text}"

    # ------------------------------------------------------------ time
    def tick(self):
        g = self.game
        if self.paused or g.dead or self.explore:
            self.last_fall = time.time(); return
        now = time.time()
        if g.landed():
            if self.landed_since is None:
                self.landed_since = now
            elif now - self.landed_since > LOCK_DELAY_MS / 1000 and self.gravity:
                self.after_lock(g.lock())
        else:
            self.landed_since = None
            if self.gravity and now - self.last_fall > self.gravity_ms / 1000:
                g.soft_drop(); self.last_fall = now

    # ------------------------------------------------------------ drawing
    def px(self, x, y):
        return BOARD_X + x * CELL, BOARD_Y + (19 - y) * CELL

    def text(self, s, x, y, color=INK, font=None):
        self.screen.blit((font or self.f).render(s, True, color), (x, y))

    def mini(self, kind, cx, cy, size=16):
        for dx, dy in CELLS[(kind, 0)]:
            draw_cell(self.screen, cx + dx * size, cy - dy * size, COLORS[kind], size)

    def draw(self):
        g, scr = self.game, self.screen
        scr.fill(BG)
        # board
        for y in range(20):
            for x in range(10):
                X, Y = self.px(x, y)
                pygame.draw.rect(scr, GRID, (X, Y, CELL, CELL), 1)
                if g.board.get(x, y):
                    draw_cell(scr, X, Y, COLORS["G"])
        pygame.draw.rect(scr, (90, 92, 104), (BOARD_X - 2, BOARD_Y - 2, 10 * CELL + 4, 20 * CELL + 4), 2)
        # coach layout
        shown, clears = self.coach.shown()
        for row, n in clears:
            if row < 20:
                Y = self.px(0, row)[1] + CELL // 2
                for x0 in range(BOARD_X, BOARD_X + 10 * CELL, 12):
                    pygame.draw.line(scr, INK, (x0, Y), (x0 + 6, Y), 2)
                self.text(f"clears @{n}", BOARD_X + 10 * CELL + 6, Y - 8, INK2)
        for n, (piece, cells) in shown:
            col = COLORS[piece]
            for x, y in cells:
                if y < 20:
                    draw_cell(scr, *self.px(x, y), col, alpha=70, outline=col)
            vis = [c for c in cells if c[1] < 20]
            if vis:
                cx = sum(self.px(x, y)[0] for x, y in vis) / len(vis) + CELL / 2
                cy = sum(self.px(x, y)[1] for x, y in vis) / len(vis) + CELL / 2
                lab = self.fl.render(str(n), True, INK)
                sh = self.fl.render(str(n), True, (0, 0, 0))
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                    scr.blit(sh, (cx - lab.get_width() / 2 + dx, cy - lab.get_height() / 2 + dy))
                scr.blit(lab, (cx - lab.get_width() / 2, cy - lab.get_height() / 2))
        # explore candidate
        if self.explore:
            pl = self.explore[self.explore_idx]
            for x, y in pl.cells:
                if y < 20:
                    draw_cell(scr, *self.px(x, y), COLORS[pl.piece.kind], alpha=150, outline=INK)
        elif g.piece and not g.dead:
            gh = g.ghost()
            for x, y in gh.cells():
                if y < 20:
                    draw_cell(scr, *self.px(x, y), COLORS[g.piece.kind], alpha=50, outline=tuple(int(c * 0.6) for c in COLORS[g.piece.kind]))
            for x, y in g.piece.cells():
                if y < 20:
                    draw_cell(scr, *self.px(x, y), COLORS[g.piece.kind])
        # hold / next
        self.text("HOLD", 80, BOARD_Y, INK2)
        if g.hold:
            self.mini(g.hold, 90, BOARD_Y + 60)
        self.text("NEXT", PANEL_X, BOARD_Y, INK2)
        for i, q in enumerate(g.next_queue()):
            self.mini(q, PANEL_X + 24, BOARD_Y + 60 + i * 58)
        # stats
        st = g.stats
        y0 = BOARD_Y + 130
        for i, line in enumerate([f"pieces {st['pieces']}", f"lines  {st['lines']}", f"attack {st['attack']}",
                                  f"TSD {st['tsd']}  TST {st['tst']}", f"tetris {st['tetris']}  PC {st['pc']}",
                                  f"b2b {'on' if g.b2b else 'off'}  combo {max(g.combo, 0)}"]):
            self.text(line, 40, y0 + i * 20, INK2)
        # message + lock info
        self.text(self.msg, BOARD_X, BOARD_Y + 20 * CELL + 10, WARN if "LESSON" in self.msg else INK)
        px = PANEL_X + 110
        self.text(f"coach: {self.coach.mode}" + (f"  {self.coach.done}/{len(self.coach.steps)} placed" if self.coach.steps else "  (k to lay out)"), px, BOARD_Y, INK2)
        y = BOARD_Y + 24
        if self.last_lock:
            self.text(self.last_lock.label() or f"{self.last_lock.piece} placed", px, y, INK, self.fb); y += 20
            for line in self.kick_note:
                self.text(line, px, y, INK2); y += 18
        y += 8
        if self.lesson:
            self.text(f"LESSON {self.lesson.key}: {self.lesson.title}", px, y, WARN, self.fb); y += 22
            self.text("goal: " + self.lesson.goal + ("   DONE" if self.lesson_done else ""), px, y, INK); y += 22
            for line in self.lesson.text:
                self.text(line, px, y, INK2); y += 17
        else:
            self.text("free play   (l: lessons)", px, y, INK2); y += 20
        if self.explore:
            y += 10
            pl = self.explore[self.explore_idx]
            self.text(f"explore {self.explore_idx + 1}/{len(self.explore)}: {pl.piece.kind} rot {ROT_NAMES[pl.piece.rot]} at x={pl.piece.x}" + ("  (spin)" if pl.spin else ""), px, y, WARN, self.fb); y += 20
            self.text("path: " + " ".join(pl.path), px, y, INK2); y += 18
            if self.explore_idx in self.explore_eval:
                self.text("then: " + self.explore_eval[self.explore_idx], px, y, INK); y += 18
        if self.lesson_menu:
            y += 10
            self.text("choose a lesson:", px, y, WARN, self.fb); y += 20
            self.text("0  free play", px, y, INK); y += 18
            for les in LESSONS:
                self.text(f"{les.key}  {les.title}", px, y, INK); y += 18
        if self.help:
            lines = __doc__.strip().splitlines()[5:]
            for i, line in enumerate(lines):
                self.text(line.strip(), BOARD_X + 8, BOARD_Y + 8 + i * 18, INK)
        if self.paused:
            self.text("PAUSED", BOARD_X + 110, BOARD_Y + 300, WARN, self.fl)

    def run(self):
        clock = pygame.time.Clock()
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type == pygame.KEYDOWN:
                    try:
                        self.key(ev)
                    except SystemExit:
                        return
            self.tick()
            self.draw()
            pygame.display.flip()
            clock.tick(60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lesson", help="start in lesson 1-4")
    args = ap.parse_args()
    App(args.lesson).run()
    pygame.quit()


if __name__ == "__main__":
    main()
