"""Runtime configuration: capture device, serial port, screen layout."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
LAYOUT_PATH = CONFIG_DIR / "layout.json"

# Tetris 99 renders at 1920x1080 when docked; all coordinates below are in that frame.
FRAME_W, FRAME_H = 1920, 1080
BOARD_COLS, BOARD_ROWS = 10, 20
QUEUE_LEN = 6


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Layout:
    """Pixel positions of the on-screen elements. Calibrate with tools/calibrate.py."""

    # Measured on a real 1080p capture (2026-09-17): the grid is 48 px per cell, 10x20 cells.
    board: Rect = field(default_factory=lambda: Rect(720, 59, 480, 960))
    hold: Rect = field(default_factory=lambda: Rect(590, 85, 112, 150))
    queue: list[Rect] = field(default_factory=lambda: [Rect(1218, 88 + i * 89, 112, 89) for i in range(QUEUE_LEN)])
    garbage_meter: Rect = field(default_factory=lambda: Rect(655, 259, 44, 760))

    @property
    def cell_w(self) -> float:
        return self.board.w / BOARD_COLS

    @property
    def cell_h(self) -> float:
        return self.board.h / BOARD_ROWS

    def cell_center(self, row: int, col: int) -> tuple[int, int]:
        """Row 0 is the top visible row."""
        return (
            int(self.board.x + (col + 0.5) * self.cell_w),
            int(self.board.y + (row + 0.5) * self.cell_h),
        )

    def save(self, path: Path = LAYOUT_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path = LAYOUT_PATH) -> "Layout":
        if not path.exists():
            return cls()
        d = json.loads(path.read_text())
        return cls(
            board=Rect(**d["board"]),
            hold=Rect(**d["hold"]),
            queue=[Rect(**r) for r in d["queue"]],
            garbage_meter=Rect(**d["garbage_meter"]),
        )


@dataclass
class Settings:
    capture_device: int | str = 0
    capture_fps: int = 60
    serial_port: str = "auto"   # or an explicit path like /dev/ttyUSB0
    serial_baud: int = 115200


def find_serial_port(requested: str = "auto") -> str:
    """Resolve 'auto' to the first USB serial device (the CP2102 adapter or a directly attached
    Arduino). Raises a clear error listing what was found when nothing suitable is present."""
    if requested != "auto":
        return requested
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    for p in ports:
        if p.device.startswith(("/dev/ttyUSB", "/dev/ttyACM", "COM")):
            return p.device
    usb = [p for p in ports if not p.device.startswith("/dev/ttyS")]  # ttyS* are legacy motherboard UARTs
    seen = ", ".join(f"{p.device} ({p.description})" for p in usb) or "none"
    raise FileNotFoundError(
        "no USB serial device found. Plug in the USB-to-TTL adapter (or the Arduino directly), "
        f"or pass --port explicitly. Serial ports seen: {seen}")
