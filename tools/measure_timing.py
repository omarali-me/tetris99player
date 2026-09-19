"""Measure how Tetris 99 responds to our controller, using the capture feed as the stopwatch.

Needs: a game in progress with a LOW stack and slow gravity (the first minute of any mode), the
capture card free, and the Arduino on the dock with the USB-TTL adapter on the PC.

    .venv/bin/python tools/measure_timing.py --device 6

Reports:
  1. end-to-end latency: command sent -> piece visibly moved (includes game, HDMI, capture, decode)
  2. which tap lengths the game registers reliably
  3. DAS delay and auto-repeat rate while a direction is held
and suggests values for tetris99/control/switch_controller.py.
"""
from __future__ import annotations

import argparse
import statistics
import time

import serial

from tetris99.capture import CaptureCard
from tetris99.config import Layout, find_serial_port
from tetris99.control.protocol import Hat, Op, encode
from tetris99.vision.board import read_grid
from tetris99.vision.cells import Cell

PIECES = {Cell.I, Cell.O, Cell.T, Cell.S, Cell.Z, Cell.J, Cell.L}
TOP_ROWS = 12  # the falling piece is looked for in the top 12 rows; keep the stack below that


class Rig:
    def __init__(self, device: int, port: str):
        self.layout = Layout.load()
        self.src = CaptureCard(device)
        self.frames = self.src.frames()
        self.ser = serial.Serial(port, 115200, timeout=0.5)
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.ser.write(encode(Op.PING))
        if self.ser.read(1) != bytes([Op.PING]):
            raise SystemExit("the Arduino did not answer the ping")
        self.send(Op.RELEASE)

    def send(self, op: Op, arg: int = 0) -> None:
        self.ser.write(encode(op, arg))
        self.ser.flush()

    def piece_x(self) -> tuple[int, int] | None:
        """(leftmost column, topmost row) of the falling piece in the next frame, or None.
        The piece is the connected same-colour group containing the topmost coloured cell, so a
        stack reaching into the upper rows does not confuse it (as long as the piece is above it)."""
        grid = read_grid(next(self.frames), self.layout)
        top = next(((c, r) for r in range(TOP_ROWS) for c in range(10) if grid[r][c] in PIECES), None)
        if top is None:
            return None
        colour = grid[top[1]][top[0]]
        seen, todo = {top}, [top]
        while todo:
            c, r = todo.pop()
            for n in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
                if 0 <= n[0] < 10 and 0 <= n[1] < 20 and n not in seen and grid[n[1]][n[0]] is colour:
                    seen.add(n); todo.append(n)
        if len(seen) > 4:
            return None
        # it must be floating: nothing solid directly under its lowest cells would mean it has landed
        return min(c for c, _ in seen), min(r for _, r in seen)

    def wait_piece(self, timeout=5.0) -> tuple[int, int]:
        """Wait until a piece is visible and its column is stable for a few frames."""
        t0 = time.perf_counter(); last = None; stable = 0
        while time.perf_counter() - t0 < timeout:
            p = self.piece_x()
            if p is not None and last is not None and p[0] == last[0]:
                stable += 1
                if stable >= 4:
                    return p
            else:
                stable = 0
            last = p
        raise SystemExit("no falling piece found in the top rows: start a game and keep the stack low")

    def wait_move(self, x0: int, timeout=0.6) -> float | None:
        """Time until the piece's column differs from x0."""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            p = self.piece_x()
            if p is not None and p[0] != x0:
                return time.perf_counter() - t0
        return None

    def new_piece(self) -> None:
        """Hard-drop the current piece somewhere new each time so the stack stays low and flat:
        slide to a wall, step back 0-3 columns, drop."""
        self.drops = getattr(self, "drops", 0) + 1
        wall = Hat.LEFT if self.drops % 2 else Hat.RIGHT
        back = Hat.RIGHT if self.drops % 2 else Hat.LEFT
        self.send(Op.HAT, int(wall)); time.sleep(0.5); self.send(Op.HAT, int(Hat.CENTER)); time.sleep(0.08)
        for _ in range((self.drops // 2) % 4):
            self.send(Op.HAT, int(back)); self.send(Op.WAIT, 50); self.send(Op.HAT, int(Hat.CENTER)); self.send(Op.WAIT, 50)
        time.sleep(0.5)
        self.send(Op.HAT, int(Hat.UP)); self.send(Op.WAIT, 50); self.send(Op.HAT, int(Hat.CENTER))
        time.sleep(0.8)

    def close(self):
        self.send(Op.RELEASE); self.ser.close(); self.src.close()


def pick_dir(x: int) -> tuple[Hat, str]:
    return (Hat.RIGHT, "right") if x <= 4 else (Hat.LEFT, "left")


def test_latency(rig: Rig, n=12) -> list[float]:
    out = []
    for _ in range(n):
        x, row = rig.wait_piece()
        if row > 7:
            rig.new_piece(); x, row = rig.wait_piece()
        hat, _ = pick_dir(x)
        rig.send(Op.HAT, int(hat))
        t = rig.wait_move(x)
        rig.send(Op.HAT, int(Hat.CENTER))
        if t is not None:
            out.append(t * 1000)
        time.sleep(0.25)
    return out


def test_tap_lengths(rig: Rig, lengths=(17, 25, 34, 50), trials=8) -> dict[int, float]:
    res = {}
    for ms in lengths:
        ok = 0
        for _ in range(trials):
            x, row = rig.wait_piece()
            if row > 7:
                rig.new_piece(); x, row = rig.wait_piece()
            hat, _ = pick_dir(x)
            rig.send(Op.HAT, int(hat)); rig.send(Op.WAIT, ms); rig.send(Op.HAT, int(Hat.CENTER))
            if rig.wait_move(x, timeout=0.4) is not None:
                ok += 1
            time.sleep(0.25)
        res[ms] = ok / trials
    return res


def test_das(rig: Rig, runs=5) -> tuple[list[float], list[float]]:
    das, arr = [], []
    for _ in range(runs):
        rig.new_piece()
        x, _ = rig.wait_piece()
        # go to the right wall first, then hold left and time every column change
        rig.send(Op.HAT, int(Hat.RIGHT)); time.sleep(0.6); rig.send(Op.HAT, int(Hat.CENTER)); time.sleep(0.3)
        x, _ = rig.wait_piece()
        rig.send(Op.HAT, int(Hat.LEFT))
        t0 = time.perf_counter(); times = []; last = x
        while time.perf_counter() - t0 < 1.2:
            p = rig.piece_x()
            if p is not None and p[0] != last:
                times.append(time.perf_counter() - t0); last = p[0]
        rig.send(Op.HAT, int(Hat.CENTER))
        if len(times) >= 3:
            das.append((times[1] - times[0]) * 1000)
            arr += [(b - a) * 1000 for a, b in zip(times[1:], times[2:])]
        time.sleep(0.3)
    return das, arr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=6)
    ap.add_argument("--port", default="auto")
    args = ap.parse_args()
    rig = Rig(args.device, find_serial_port(args.port))
    try:
        print("1/3 end-to-end latency (press -> visible move)...")
        lat = test_latency(rig)
        print(f"    n={len(lat)}  median {statistics.median(lat):.0f} ms   min {min(lat):.0f}   max {max(lat):.0f}")
        print("2/3 which tap lengths register...")
        taps = test_tap_lengths(rig)
        for ms, rate in taps.items():
            print(f"    {ms:3d} ms tap: {rate * 100:3.0f}% registered")
        print("3/3 DAS delay and auto-repeat while holding...")
        das, arr = test_das(rig)
        if das:
            print(f"    DAS delay  median {statistics.median(das):.0f} ms  ({min(das):.0f}-{max(das):.0f})")
            print(f"    ARR step   median {statistics.median(arr):.0f} ms  (n={len(arr)})")
        reliable = [ms for ms, r in taps.items() if r == 1.0]
        print("\nsuggested constants for tetris99/control/switch_controller.py:")
        if reliable:
            print(f"    TAP_MS = {min(reliable)}   # shortest tap that registered every time")
        if das and arr:
            wall = statistics.median(das) + 9 * statistics.median(arr)
            print(f"    DAS_MS = {int(wall + 60)}   # DAS {statistics.median(das):.0f} + 9 columns x ARR {statistics.median(arr):.0f} + margin")
    finally:
        rig.close()


if __name__ == "__main__":
    main()
