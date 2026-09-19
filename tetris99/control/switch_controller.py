"""High-level Tetris actions on top of the serial protocol."""
from __future__ import annotations

import time

import serial

from .protocol import Button, Hat, Op, encode

# Tetris 99 handling, measured with tools/measure_timing.py on 2026-09-19 (150 Line Mode, level 1):
#   press -> visible move 116 ms; taps of 17/25/34/50 ms all register; 3 taps at 34/34 and 25/25
#   moved 3 columns 8/8 times (17/17 dropped one in 8); DAS 200 ms, ARR 33 ms; soft drop ~50 ms/row.
# 50/50 was tried in battle mode on 2026-09-19 and did not reduce lost inputs, so tap length is not
# the cause; see the note on lost hard drops in README "Open issues".
TAP_MS = 34                 # 2 frames
GAP_MS = 34                 # 2 frames between inputs
DAS_MS = 560                # wall to wall: 200 + 9 x 33 + margin
SOFT_DROP_MS_PER_ROW = 55   # soft drop is 20x gravity: ~50 ms/row at level 1, faster later
SOFT_DROP_MARGIN_MS = 150   # covers input latency; over-holding after landing is harmless


class SwitchController:
    def __init__(self, port: str, baud: int = 115200):
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2.0)  # Leonardo/Pro Micro reset on open
        self.ser.reset_input_buffer()

    def _send(self, op: Op, arg: int = 0) -> None:
        """One 3-byte command, paced. The ATmega32U4's serial receive buffer is 64 bytes and the
        firmware can block ~8 ms per USB report, so a whole move sent in one burst (up to ~90 bytes)
        overflows it and the tail of the move, the hard drop, is lost. At one command per 2.5 ms
        at most ~10 bytes can queue up. The Arduino needs ~70 ms per tap anyway, so this is free."""
        self.ser.write(encode(op, arg))
        self.ser.flush()
        time.sleep(0.0025)

    def ping(self) -> bool:
        """Ping, re-aligning the 3-byte framing if needed. A stray byte on the wire (the adapter's
        port being opened or closed by another tool) shifts every later command; sending single
        padding bytes until the ping is answered restores alignment."""
        self.ser.timeout = 0.15
        for _ in range(4):
            self.ser.reset_input_buffer()
            self._send(Op.PING)
            if self.ser.read(1) == bytes([Op.PING]):
                self.ser.timeout = 1
                return True
            self.ser.write(b"\x00")
            time.sleep(0.03)
        self.ser.timeout = 1
        return False

    def release_all(self) -> None:
        self._send(Op.RELEASE)

    def tap(self, button: Button) -> None:
        # SET/WAIT/SET rather than the firmware's fixed 34 ms PRESS, so buttons use TAP_MS too
        self._send(Op.SET, int(button))
        self._send(Op.WAIT, TAP_MS)
        self._send(Op.SET, 0)
        self._send(Op.WAIT, GAP_MS)

    def hat_tap(self, hat: Hat) -> None:
        self._send(Op.HAT, int(hat))
        self._send(Op.WAIT, TAP_MS)
        self._send(Op.HAT, int(Hat.CENTER))
        self._send(Op.WAIT, GAP_MS)

    def hat_hold(self, hat: Hat, ms: int) -> None:
        self._send(Op.HAT, int(hat))
        self._send(Op.WAIT, ms)
        self._send(Op.HAT, int(Hat.CENTER))
        self._send(Op.WAIT, GAP_MS)

    # Tetris-specific
    def rotate_cw(self) -> None: self.tap(Button.A)
    def rotate_ccw(self) -> None: self.tap(Button.B)
    def hold(self) -> None: self.tap(Button.L)
    def hard_drop(self) -> None: self.hat_tap(Hat.UP)
    def left(self, n: int = 1) -> None:
        for _ in range(n): self.hat_tap(Hat.LEFT)
    def right(self, n: int = 1) -> None:
        for _ in range(n): self.hat_tap(Hat.RIGHT)
    def das_left(self) -> None: self.hat_hold(Hat.LEFT, DAS_MS)
    def das_right(self) -> None: self.hat_hold(Hat.RIGHT, DAS_MS)

    # Tetris 99 targeting is chosen with the right stick: up K.O.s, left Random, right Badges, down Attackers.
    TARGETING = {"kos": (128, 0), "random": (0, 128), "badges": (255, 128), "attackers": (128, 255)}

    def set_targeting(self, mode: str) -> None:
        from .protocol import stick_arg
        x, y = self.TARGETING[mode]
        self._send(Op.RSTICK, stick_arg(x, y))
        self._send(Op.WAIT, 180)
        self._send(Op.RSTICK, stick_arg(128, 128))
        self._send(Op.WAIT, GAP_MS)

    def close(self) -> None:
        self.release_all()
        self.ser.close()


def run_actions(ctl: "SwitchController", actions) -> None:
    """Execute a compiled action list from engine.executor on a controller."""
    from .protocol import Hat
    for a in actions:
        k = a.kind
        if k == "hold": ctl.hold()
        elif k == "cw": ctl.rotate_cw()
        elif k == "ccw": ctl.rotate_ccw()
        elif k == "left": ctl.left()
        elif k == "right": ctl.right()
        elif k == "das_left": ctl.das_left()
        elif k == "das_right": ctl.das_right()
        elif k == "soft_drop": ctl.hat_hold(Hat.DOWN, max(1, a.rows) * SOFT_DROP_MS_PER_ROW + SOFT_DROP_MARGIN_MS)
        elif k == "hard_drop": ctl.hard_drop()
        else: raise ValueError(k)
