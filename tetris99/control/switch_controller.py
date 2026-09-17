"""High-level Tetris actions on top of the serial protocol."""
from __future__ import annotations

import time

import serial

from .protocol import Button, Hat, Op, encode

# Tetris 99 handling is fixed by the game. Values in ms; refine by measurement.
TAP_MS = 34            # ~2 frames, reliably registered
GAP_MS = 34            # release time between inputs
DAS_MS = 300           # long enough for auto-shift to carry the piece to a wall


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
