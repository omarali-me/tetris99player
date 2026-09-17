"""Serial protocol between the PC and the controller-emulating Arduino.

The Arduino is dumb on purpose: it holds whatever button state it was last told and
reports it to the Switch every USB poll. Timing lives on the PC side, with the Arduino
able to execute short timed sequences so a press/release pair is not subject to
serial jitter.

Wire format (binary, 3 bytes per command, little-endian):
    byte 0: opcode
    byte 1-2: uint16 argument
Opcodes:
    0x01 SET     arg = button bitmask (buttons held from now on)
    0x02 PRESS   arg = button bitmask; held for PRESS_MS then released
    0x03 HAT     arg = hat value 0-8 (see HAT_*)
    0x04 RELEASE arg ignored; releases everything
    0x05 WAIT    arg = milliseconds; delays subsequent queued commands
    0x06 PING    arg ignored; Arduino answers with a single byte 0x06
    0x07 LSTICK  arg = x | (y << 8), each 0..255 with 128 = centre
    0x08 RSTICK  arg = x | (y << 8)
"""
from __future__ import annotations

import struct
from enum import IntEnum, IntFlag


class Button(IntFlag):
    """Bit order matches the HORI Pokken Tournament Pro Pad HID report."""
    Y = 1 << 0
    B = 1 << 1
    A = 1 << 2
    X = 1 << 3
    L = 1 << 4
    R = 1 << 5
    ZL = 1 << 6
    ZR = 1 << 7
    MINUS = 1 << 8
    PLUS = 1 << 9
    LSTICK = 1 << 10
    RSTICK = 1 << 11
    HOME = 1 << 12
    CAPTURE = 1 << 13


class Hat(IntEnum):
    UP = 0
    UP_RIGHT = 1
    RIGHT = 2
    DOWN_RIGHT = 3
    DOWN = 4
    DOWN_LEFT = 5
    LEFT = 6
    UP_LEFT = 7
    CENTER = 8


class Op(IntEnum):
    SET = 0x01
    PRESS = 0x02
    HAT = 0x03
    RELEASE = 0x04
    WAIT = 0x05
    PING = 0x06
    LSTICK = 0x07
    RSTICK = 0x08


def encode(op: Op, arg: int = 0) -> bytes:
    return struct.pack("<BH", int(op), arg & 0xFFFF)


def stick_arg(x: int, y: int) -> int:
    """Pack stick axes (0..255, 128 centre) into one 16-bit argument."""
    return (max(0, min(255, x))) | (max(0, min(255, y)) << 8)
