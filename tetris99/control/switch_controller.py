"""High-level Tetris actions on top of the serial protocol."""
from __future__ import annotations

import time

import serial

from .protocol import Button, Hat, Op, encode

# Tetris 99 handling is fixed by the game. Values in ms; refine by measurement.
TAP_MS = 34            # ~2 frames, reliably registered
GAP_MS = 34            # release time between inputs
DAS_MS = 300           # long enough for auto-shift to carry the piece to a wall
SOFT_DROP_MS = 400     # long enough to soft drop from the top to the floor


class SwitchController:
    def __init__(self, port: str, baud: int = 115200):
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2.0)  # Leonardo/Pro Micro reset on open
        self.ser.reset_input_buffer()

    def _send(self, op: Op, arg: int = 0) -> None:
        self.ser.write(encode(op, arg))

    def ping(self) -> bool:
        self._send(Op.PING)
        return self.ser.read(1) == bytes([Op.PING])

    def release_all(self) -> None:
        self._send(Op.RELEASE)

    def tap(self, button: Button) -> None:
        self._send(Op.PRESS, int(button))
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
        elif k == "soft_drop": ctl.hat_hold(Hat.DOWN, SOFT_DROP_MS)
        elif k == "hard_drop": ctl.hard_drop()
        else: raise ValueError(k)
