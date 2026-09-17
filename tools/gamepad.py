"""An on-screen Switch Pro Controller driven by mouse or keyboard, sending to the bot's Arduino.

    .venv/bin/python tools/gamepad.py            # finds the USB serial adapter automatically
    .venv/bin/python tools/gamepad.py --dry      # no hardware: just the UI

Mouse: press and hold any button, drag a stick.  Keyboard: the shortcut shown under each label.
Rebind: click REBIND, click a button, press the new key. Saved to config/keymap.json.
Esc releases everything. Keys only count while this window is focused.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import pygame

from tetris99.config import CONFIG_DIR, Settings, find_serial_port
from tetris99.control.protocol import Button, Hat, Op, encode, stick_arg

KEYMAP_DEFAULT = CONFIG_DIR / "keymap.default.json"
KEYMAP_USER = CONFIG_DIR / "keymap.json"

# ---------------------------------------------------------------- controller model
HAT_FROM_DIRS = {
    frozenset(): Hat.CENTER,
    frozenset({"UP"}): Hat.UP, frozenset({"DOWN"}): Hat.DOWN, frozenset({"LEFT"}): Hat.LEFT, frozenset({"RIGHT"}): Hat.RIGHT,
    frozenset({"UP", "RIGHT"}): Hat.UP_RIGHT, frozenset({"UP", "LEFT"}): Hat.UP_LEFT,
    frozenset({"DOWN", "RIGHT"}): Hat.DOWN_RIGHT, frozenset({"DOWN", "LEFT"}): Hat.DOWN_LEFT,
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


class Pad:
    """Current controller state; pushes changes to the link."""

    def __init__(self, link: Link):
        self.link = link
        self.buttons: set[str] = set()      # Button names
        self.dpad: set[str] = set()         # UP/DOWN/LEFT/RIGHT
        self.sticks = {"LS": [128, 128], "RS": [128, 128]}
        self.stick_keys = {"LS": set(), "RS": set()}
        self.hat = Hat.CENTER

    def press(self, name: str, down: bool) -> None:
        if name in Button.__members__:
            (self.buttons.add if down else self.buttons.discard)(name)
            mask = 0
            for b in self.buttons:
                mask |= int(Button[b])
            self.link.send(Op.SET, mask)
        elif name.startswith("DPAD_"):
            (self.dpad.add if down else self.dpad.discard)(name[5:])
            hat = HAT_FROM_DIRS.get(frozenset(self.dpad), Hat.CENTER)
            if hat != self.hat:
                self.hat = hat
                self.link.send(Op.HAT, int(hat))
        elif name[:2] in ("LS", "RS") and name[2] == "_":
            stick, d = name[:2], name[3:]
            (self.stick_keys[stick].add if down else self.stick_keys[stick].discard)(d)
            ks = self.stick_keys[stick]
            x = 128 + (127 if "RIGHT" in ks else 0) - (128 if "LEFT" in ks else 0)
            y = 128 + (127 if "DOWN" in ks else 0) - (128 if "UP" in ks else 0)
            self.set_stick(stick, x, y)

    def set_stick(self, stick: str, x: int, y: int) -> None:
        x, y = max(0, min(255, int(x))), max(0, min(255, int(y)))
        if [x, y] != self.sticks[stick]:
            self.sticks[stick] = [x, y]
            self.link.send(Op.LSTICK if stick == "LS" else Op.RSTICK, stick_arg(x, y))

    def release_all(self) -> None:
        self.buttons.clear(); self.dpad.clear()
        for k in self.stick_keys.values(): k.clear()
        self.sticks = {"LS": [128, 128], "RS": [128, 128]}
        self.hat = Hat.CENTER
        self.link.send(Op.RELEASE)


# ---------------------------------------------------------------- keymap
def load_keymap() -> dict[str, str]:
    m = {k: v for k, v in json.loads(KEYMAP_DEFAULT.read_text()).items() if not k.startswith("_")}
    if KEYMAP_USER.exists():
        m.update({k: v for k, v in json.loads(KEYMAP_USER.read_text()).items() if not k.startswith("_")})
    return m


def save_keymap(m: dict[str, str]) -> None:
    KEYMAP_USER.write_text(json.dumps(m, indent=2))


def key_to_code(name: str) -> int | None:
    try:
        return pygame.key.key_code(name)
    except ValueError:
        return None


# ---------------------------------------------------------------- layout
W, H = 900, 520
BG = (28, 30, 36); SHELL = (52, 55, 64); SHELL_EDGE = (78, 82, 94)
FACE = (36, 38, 46); FACE_EDGE = (110, 115, 130); FACE_DOWN = (90, 140, 255)
INK = (232, 234, 240); INK2 = (150, 156, 170); KEYC = (255, 205, 90); REBIND = (255, 120, 90)

class Widget:
    def __init__(self, name, label, x, y, w, h, shape="circle"):
        self.name, self.label, self.rect, self.shape = name, label, pygame.Rect(x - w // 2, y - h // 2, w, h), shape
    def hit(self, pos):
        if self.shape == "circle":
            cx, cy = self.rect.center; r = self.rect.w / 2
            return (pos[0] - cx) ** 2 + (pos[1] - cy) ** 2 <= r * r
        return self.rect.collidepoint(pos)


def build_widgets() -> list[Widget]:
    ws = []
    # shoulders
    ws += [Widget("ZL", "ZL", 150, 48, 120, 30, "rect"), Widget("L", "L", 150, 86, 150, 30, "rect"),
           Widget("ZR", "ZR", 750, 48, 120, 30, "rect"), Widget("R", "R", 750, 86, 150, 30, "rect")]
    # left stick, minus, capture
    ws += [Widget("LSTICK", "LS", 150, 190, 84, 84), Widget("MINUS", "−", 330, 150, 36, 36), Widget("CAPTURE", "◼", 330, 330, 34, 34, "rect")]
    # d-pad
    dx, dy, s = 230, 330, 34
    ws += [Widget("DPAD_UP", "▲", dx, dy - s, s, s, "rect"), Widget("DPAD_DOWN", "▼", dx, dy + s, s, s, "rect"),
           Widget("DPAD_LEFT", "◀", dx - s, dy, s, s, "rect"), Widget("DPAD_RIGHT", "▶", dx + s, dy, s, s, "rect")]
    # right side: abxy diamond, plus, home, right stick
    ax, ay, d = 730, 190, 46
    ws += [Widget("X", "X", ax, ay - d, 44, 44), Widget("B", "B", ax, ay + d, 44, 44),
           Widget("Y", "Y", ax - d, ay, 44, 44), Widget("A", "A", ax + d, ay, 44, 44),
           Widget("PLUS", "+", 570, 150, 36, 36), Widget("HOME", "⌂", 570, 330, 34, 34),
           Widget("RSTICK", "RS", 640, 330, 84, 84)]
    return ws


def draw_text(surf, font, text, pos, color, anchor="center"):
    img = font.render(text, True, color)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=Settings().serial_port)
    ap.add_argument("--baud", type=int, default=Settings().serial_baud)
    ap.add_argument("--dry", action="store_true", help="no serial; just the UI")
    args = ap.parse_args()
    port = None
    if not args.dry:
        try:
            port = find_serial_port(args.port)
        except FileNotFoundError as e:
            sys.exit(f"{e}\nUse --dry to run without hardware.")
    pad = Pad(Link(port, args.baud))
    keymap = load_keymap()

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Switch controller" + ("  ·  dry run" if args.dry else f"  ·  {port}"))
    f_label = pygame.font.SysFont("dejavusans", 20, bold=True)
    f_key = pygame.font.SysFont("dejavusansmono", 12)
    f_ui = pygame.font.SysFont("dejavusans", 14)
    widgets = build_widgets()
    by_name = {w.name: w for w in widgets}
    rebind_btn = pygame.Rect(W - 130, H - 44, 110, 30)
    reset_btn = pygame.Rect(W - 260, H - 44, 120, 30)

    mouse_held: str | None = None
    drag_stick: str | None = None
    rebind_mode = False
    rebind_target: str | None = None
    status = "" if args.dry else f"connected to {port}"
    focused = True
    running = True
    clock = pygame.time.Clock()

    def code_map():
        return {key_to_code(v): k for k, v in keymap.items() if key_to_code(v) is not None}

    codes = code_map()

    def stick_from_mouse(stick, pos):
        w = by_name["LSTICK" if stick == "LS" else "RSTICK"]
        cx, cy = w.rect.center; r = w.rect.w / 2
        dx, dy = (pos[0] - cx) / r, (pos[1] - cy) / r
        mag = math.hypot(dx, dy)
        if mag > 1:
            dx, dy = dx / mag, dy / mag
        pad.set_stick(stick, 128 + dx * 127, 128 + dy * 127)

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.WINDOWFOCUSLOST:
                focused = False; pad.release_all(); mouse_held = drag_stick = None
            elif ev.type == pygame.WINDOWFOCUSGAINED:
                focused = True
            elif ev.type == pygame.KEYDOWN:
                if rebind_target:
                    if ev.key == pygame.K_ESCAPE:
                        rebind_target = None; status = "rebind cancelled"
                    else:
                        name = pygame.key.name(ev.key)
                        keymap[rebind_target] = name; save_keymap(keymap); codes = code_map()
                        status = f"{rebind_target} → {name}  (saved to config/keymap.json)"
                        rebind_target = None
                    continue
                if ev.key == pygame.K_ESCAPE:
                    pad.release_all(); rebind_mode = False
                elif ev.key in codes:
                    pad.press(codes[ev.key], True)
            elif ev.type == pygame.KEYUP:
                if ev.key in codes and not rebind_target:
                    pad.press(codes[ev.key], False)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if rebind_btn.collidepoint(ev.pos):
                    rebind_mode = not rebind_mode; rebind_target = None
                    status = "REBIND: click a button, then press its new key. Esc to cancel." if rebind_mode else ""
                    continue
                if reset_btn.collidepoint(ev.pos):
                    if KEYMAP_USER.exists(): KEYMAP_USER.unlink()
                    keymap = load_keymap(); codes = code_map(); status = "shortcuts reset to defaults"
                    continue
                for w in widgets:
                    if w.hit(ev.pos):
                        if rebind_mode:
                            rebind_target = w.name; status = f"press the new key for {w.label} ({w.name})…"
                        elif w.name in ("LSTICK", "RSTICK"):
                            drag_stick = "LS" if w.name == "LSTICK" else "RS"; stick_from_mouse(drag_stick, ev.pos)
                        else:
                            mouse_held = w.name; pad.press(w.name, True)
                        break
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
                # right-click a stick = click it in (L3 / R3)
                for w in widgets:
                    if w.name in ("LSTICK", "RSTICK") and w.hit(ev.pos):
                        mouse_held = w.name; pad.press(w.name, True)
            elif ev.type == pygame.MOUSEMOTION and drag_stick:
                stick_from_mouse(drag_stick, ev.pos)
            elif ev.type == pygame.MOUSEBUTTONUP:
                if mouse_held:
                    pad.press(mouse_held, False); mouse_held = None
                if drag_stick:
                    pad.set_stick(drag_stick, 128, 128); drag_stick = None

        # ---- draw
        screen.fill(BG)
        pygame.draw.rect(screen, SHELL, (60, 110, 780, 330), border_radius=90)
        pygame.draw.rect(screen, SHELL_EDGE, (60, 110, 780, 330), 2, border_radius=90)
        for w in widgets:
            down = (w.name in pad.buttons) or (w.name.startswith("DPAD_") and w.name[5:] in pad.dpad)
            col = FACE_DOWN if down else FACE
            edge = REBIND if (rebind_mode and rebind_target == w.name) else (KEYC if rebind_mode else FACE_EDGE)
            if w.shape == "circle":
                pygame.draw.circle(screen, col, w.rect.center, w.rect.w // 2)
                pygame.draw.circle(screen, edge, w.rect.center, w.rect.w // 2, 2)
            else:
                pygame.draw.rect(screen, col, w.rect, border_radius=6)
                pygame.draw.rect(screen, edge, w.rect, 2, border_radius=6)
            if w.name in ("LSTICK", "RSTICK"):
                st = "LS" if w.name == "LSTICK" else "RS"
                x, y = pad.sticks[st]
                cx = w.rect.centerx + (x - 128) / 127 * (w.rect.w / 2 - 14)
                cy = w.rect.centery + (y - 128) / 127 * (w.rect.h / 2 - 14)
                pygame.draw.circle(screen, FACE_DOWN if w.name in pad.buttons else (70, 74, 86), (int(cx), int(cy)), 14)
                pygame.draw.circle(screen, FACE_EDGE, (int(cx), int(cy)), 14, 2)
                draw_text(screen, f_key, f"{keymap.get(st+'_UP','?')} {keymap.get(st+'_LEFT','?')} {keymap.get(st+'_DOWN','?')} {keymap.get(st+'_RIGHT','?')}",
                          (w.rect.centerx, w.rect.bottom + 12), KEYC)
                draw_text(screen, f_key, f"click: {keymap.get(w.name,'?')}", (w.rect.centerx, w.rect.bottom + 26), INK2)
            elif w.name in ("ZL", "L", "ZR", "R"):
                draw_text(screen, f_label, w.label, w.rect.center, INK)
                draw_text(screen, f_key, keymap.get(w.name, "?"), (w.rect.right - 10, w.rect.centery), KEYC, "midright")
            elif w.name == "DPAD_UP":
                draw_text(screen, f_label, w.label, w.rect.center, INK)
                draw_text(screen, f_key, keymap.get(w.name, "?"), (w.rect.centerx, w.rect.top - 10), KEYC)
            else:
                draw_text(screen, f_label, w.label, w.rect.center, INK)
                draw_text(screen, f_key, keymap.get(w.name, "?"), (w.rect.centerx, w.rect.bottom + 11), KEYC)

        pygame.draw.rect(screen, (60, 62, 72) if not rebind_mode else (120, 70, 50), rebind_btn, border_radius=6)
        draw_text(screen, f_ui, "REBIND" if not rebind_mode else "DONE", rebind_btn.center, INK)
        pygame.draw.rect(screen, (60, 62, 72), reset_btn, border_radius=6)
        draw_text(screen, f_ui, "reset keys", reset_btn.center, INK)
        draw_text(screen, f_ui, status, (20, H - 30), INK2, "midleft")
        if not focused:
            draw_text(screen, f_ui, "window not focused: keys are not being sent", (20, 20), REBIND, "midleft")
        else:
            draw_text(screen, f_ui, "mouse: hold buttons, drag sticks (right-click = click stick)   ·   esc: release all", (20, 20), INK2, "midleft")
        pygame.display.flip()
        clock.tick(120)

    pad.release_all()
    pygame.quit()


if __name__ == "__main__":
    main()
