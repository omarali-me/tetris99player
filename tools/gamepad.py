"""Use your keyboard as the Switch controller, through the same Arduino the bot uses.

Opens a small window; keys are only captured while it has focus, so you can alt-tab away safely.
Keys are held for as long as you hold them (real key-down / key-up), so menus scroll with DAS.

    .venv/bin/python tools/gamepad.py                     # /dev/ttyUSB0
    .venv/bin/python tools/gamepad.py --port /dev/ttyACM0
    .venv/bin/python tools/gamepad.py --dry               # no serial, just show the state

Keys
    arrows        d-pad          enter / space   A          backspace   B
    x             X              y               Y          q / e       L / R
    1 / 3         ZL / ZR        - / =           minus / plus
    h             Home           c               Capture
    esc           release everything            F10  quit
"""
from __future__ import annotations

import argparse
import sys
import time

import pygame

from tetris99.config import Settings
from tetris99.control.protocol import Button, Hat, Op, encode

KEY_BUTTONS = {
    pygame.K_RETURN: Button.A, pygame.K_SPACE: Button.A, pygame.K_BACKSPACE: Button.B,
    pygame.K_x: Button.X, pygame.K_y: Button.Y,
    pygame.K_q: Button.L, pygame.K_e: Button.R, pygame.K_1: Button.ZL, pygame.K_3: Button.ZR,
    pygame.K_MINUS: Button.MINUS, pygame.K_EQUALS: Button.PLUS,
    pygame.K_h: Button.HOME, pygame.K_c: Button.CAPTURE,
}
DPAD = {pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right"}
HAT_FROM_DIRS = {
    frozenset(): Hat.CENTER,
    frozenset({"up"}): Hat.UP, frozenset({"down"}): Hat.DOWN,
    frozenset({"left"}): Hat.LEFT, frozenset({"right"}): Hat.RIGHT,
    frozenset({"up", "right"}): Hat.UP_RIGHT, frozenset({"up", "left"}): Hat.UP_LEFT,
    frozenset({"down", "right"}): Hat.DOWN_RIGHT, frozenset({"down", "left"}): Hat.DOWN_LEFT,
}


class Link:
    def __init__(self, port: str | None, baud: int):
        self.ser = None
        if port:
            import serial
            self.ser = serial.Serial(port, baud, timeout=0.2)
            time.sleep(0.3)
            self.ser.reset_input_buffer()
            self.ser.write(encode(Op.PING))
            if self.ser.read(1) != bytes([Op.PING]):
                print("warning: Arduino did not answer ping; sending anyway", file=sys.stderr)

    def send(self, op: Op, arg: int = 0) -> None:
        if self.ser:
            self.ser.write(encode(op, arg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=Settings().serial_port)
    ap.add_argument("--baud", type=int, default=Settings().serial_baud)
    ap.add_argument("--dry", action="store_true", help="no serial; show what would be sent")
    args = ap.parse_args()
    link = Link(None if args.dry else args.port, args.baud)

    pygame.init()
    screen = pygame.display.set_mode((520, 300))
    pygame.display.set_caption("Switch keyboard pad" + ("  (dry run)" if args.dry else f"  {args.port}"))
    font = pygame.font.SysFont("monospace", 16)
    big = pygame.font.SysFont("monospace", 22, bold=True)

    held: set[Button] = set()
    dirs: set[str] = set()
    last_hat = Hat.CENTER
    focused = True

    def push_buttons():
        mask = 0
        for b in held:
            mask |= int(b)
        link.send(Op.SET, mask)

    def push_hat():
        nonlocal last_hat
        hat = HAT_FROM_DIRS.get(frozenset(dirs), last_hat if len(dirs) > 2 else Hat.CENTER)
        if hat != last_hat:
            last_hat = hat
            link.send(Op.HAT, int(hat))

    def release_all():
        held.clear(); dirs.clear()
        link.send(Op.RELEASE)
        nonlocal last_hat
        last_hat = Hat.CENTER

    clock = pygame.time.Clock()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.WINDOWFOCUSLOST:
                focused = False
                release_all()  # never leave a button stuck when you alt-tab away
            elif ev.type == pygame.WINDOWFOCUSGAINED:
                focused = True
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_F10:
                    running = False
                elif ev.key == pygame.K_ESCAPE:
                    release_all()
                elif ev.key in KEY_BUTTONS:
                    held.add(KEY_BUTTONS[ev.key]); push_buttons()
                elif ev.key in DPAD:
                    dirs.add(DPAD[ev.key]); push_hat()
            elif ev.type == pygame.KEYUP:
                if ev.key in KEY_BUTTONS:
                    held.discard(KEY_BUTTONS[ev.key]); push_buttons()
                elif ev.key in DPAD:
                    dirs.discard(DPAD[ev.key]); push_hat()

        screen.fill((24, 24, 28) if focused else (50, 30, 30))
        lines = [
            ("FOCUSED: keys go to the Switch" if focused else "NOT FOCUSED: click here to control", big),
            ("", font),
            (f"buttons: {' '.join(b.name for b in sorted(held, key=int)) or '-'}", font),
            (f"d-pad:   {last_hat.name}", font),
            ("", font),
            ("arrows d-pad   enter/space A   backspace B   x X   y Y", font),
            ("q/e L/R   1/3 ZL/ZR   -/= minus/plus   h Home   c Capture", font),
            ("esc release all   F10 quit", font),
        ]
        y = 20
        for text, f in lines:
            screen.blit(f.render(text, True, (230, 230, 230)), (20, y))
            y += 28
        pygame.display.flip()
        clock.tick(120)

    release_all()
    pygame.quit()


if __name__ == "__main__":
    main()
