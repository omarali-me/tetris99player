"""Controlled experiment: is a hard drop lost when it directly follows a rotation?

Run inside a game with the 99-board screen (CPU Battle). For every piece: a few spreading taps, then
the input under test, a chosen gap, then the hard drop. The next-queue shift is the stopwatch.
Results are appended to recordings/drop_experiment.jsonl so several games can be pooled.

    .venv/bin/python tools/measure_drop.py --device 6 --trials 90
"""
from __future__ import annotations

import argparse, json, random, time
from collections import defaultdict

from tetris99.capture import CaptureCard
from tetris99.config import Layout, find_serial_port
from tetris99.control.protocol import Button, Hat, Op
from tetris99.control.switch_controller import SwitchController
from tetris99.vision.board import read_frame

TAP, GAP = 34, 34
CONDITIONS = [("move", 34), ("cw", 34), ("cw", 67), ("cw", 100), ("cw", 150), ("ccw", 34), ("cw", 17)]


class Rig:
    def __init__(self, device, port):
        self.layout = Layout.load()
        self.src = CaptureCard(device); self.frames = self.src.frames()
        self.ctl = SwitchController(port)
        if not self.ctl.ping():
            raise SystemExit("the Arduino did not answer")
        self.ctl.release_all()

    def queue(self):
        fs = read_frame(next(self.frames), self.layout)
        return tuple(q.value for q in fs.queue) if all(fs.queue) else None

    def stable_queue(self, timeout=6.0):
        t0, last, n = time.perf_counter(), None, 0
        while time.perf_counter() - t0 < timeout:
            q = self.queue()
            if q is not None and q == last:
                n += 1
                if n >= 3: return q
            else: n = 0
            last = q
        return None

    def wait_change(self, q0, timeout):
        """Seconds until a different readable queue has been seen on 2 consecutive frames, else None."""
        t0, cand, n = time.perf_counter(), None, 0
        while time.perf_counter() - t0 < timeout:
            q = self.queue()
            if q is not None and q != q0:
                n = n + 1 if q == cand else 1
                cand = q
                if n >= 2: return time.perf_counter() - t0
            else: n = 0
        return None

    def hat(self, h, ms=TAP, gap=GAP):
        s = self.ctl._send
        s(Op.HAT, int(h)); s(Op.WAIT, ms); s(Op.HAT, int(Hat.CENTER)); s(Op.WAIT, gap)

    def button(self, b, ms=TAP, gap=GAP):
        s = self.ctl._send
        s(Op.SET, int(b)); s(Op.WAIT, ms); s(Op.SET, 0); s(Op.WAIT, gap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=6)
    ap.add_argument("--trials", type=int, default=90)
    ap.add_argument("--out", default="recordings/drop_experiment.jsonl")
    args = ap.parse_args()
    rig = Rig(args.device, find_serial_port())
    plan = [c for c in CONDITIONS for _ in range(args.trials // len(CONDITIONS) + 1)][: args.trials]
    random.shuffle(plan)
    results = defaultdict(list); done = 0
    out = open(args.out, "a")
    try:
        for i, (last, gap) in enumerate(plan):
            q0 = rig.stable_queue()
            if q0 is None:
                print("queue unreadable for 6 s: the game is probably over"); break
            shift = [-4, 3, -2, 1, 4, -3, 2, -1, 0][i % 9]          # spread the stack
            if last == "move":                                       # the move itself is the last input
                shift = shift if shift != 0 else 1
            pre = abs(shift) - (1 if last == "move" else 0)
            d = Hat.LEFT if shift < 0 else Hat.RIGHT
            for _ in range(max(0, pre)):
                rig.hat(d)
            if last == "move":
                rig.hat(d, gap=gap)
            else:
                rig.button(Button.A if last == "cw" else Button.B, gap=gap)
            rig.hat(Hat.UP)
            exec_s = (max(0, pre) * (TAP + GAP) + TAP + gap + TAP) / 1000
            dt = rig.wait_change(q0, exec_s + 0.65)
            rec = {"last": last, "gap": gap, "pre": max(0, pre), "ok": dt is not None,
                   "t_change": None if dt is None else round(dt - exec_s, 3)}
            if dt is None:                                           # lost? send a recovery drop and time it
                rig.hat(Hat.UP)
                r = rig.wait_change(q0, 2.5)
                rec["recovery_change"] = None if r is None else round(r, 3)
                if r is None:
                    print("no reaction even to a recovery drop: the game is over; stopping"); break
            results[(last, gap)].append(rec); done += 1
            out.write(json.dumps(rec) + "\n"); out.flush()
            print(f"{i + 1:3d} {last:4s} gap {gap:3d}  pre {rec['pre']}  ->  "
                  + (f"ok  (+{rec['t_change'] * 1000:.0f} ms after the drop was sent)" if rec["ok"]
                     else f"LOST  (recovery drop -> new piece after {rec.get('recovery_change')})"), flush=True)
            time.sleep(0.15)
    finally:
        rig.ctl.release_all(); rig.ctl.ser.close(); rig.src.close()
    print(f"\n{done} trials this run")
    for (last, gap), rs in sorted(results.items()):
        ok = sum(r["ok"] for r in rs)
        print(f"  last={last:4s} gap={gap:3d} ms: {ok}/{len(rs)} hard drops registered")


if __name__ == "__main__":
    main()
