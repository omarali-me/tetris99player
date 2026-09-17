"""Live capture preview with the classified grid drawn over it. Use it to check the card and tune
layout/colors. Keys: q quit, s save frame to recordings/, p print board state."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from tetris99.capture import CaptureCard, VideoFile
from tetris99.config import BOARD_COLS, BOARD_ROWS, Layout
from tetris99.vision.board import read_frame

COLORS = {"I": (255, 255, 0), "O": (0, 255, 255), "T": (255, 0, 255), "S": (0, 255, 0),
          "Z": (0, 0, 255), "J": (255, 0, 0), "L": (0, 128, 255), "G": (160, 160, 160), "g": (80, 80, 80)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="0", help="V4L2 index or path to a video file")
    args = ap.parse_args()

    src = VideoFile(args.device, realtime=True) if Path(args.device).is_file() else CaptureCard(int(args.device))
    if isinstance(src, CaptureCard):
        print("capture:", src.describe())
    layout = Layout.load()
    Path("recordings").mkdir(exist_ok=True)

    last = time.perf_counter()
    for frame in src.frames():
        state = read_frame(frame, layout)
        vis = frame.copy()
        b = layout.board
        cv2.rectangle(vis, (b.x, b.y), (b.x + b.w, b.y + b.h), (0, 255, 0), 1)
        for r in range(BOARD_ROWS):
            for c in range(BOARD_COLS):
                cell = state.grid[r][c].value
                if cell != ".":
                    x, y = layout.cell_center(r, c)
                    cv2.circle(vis, (x, y), 5, COLORS[cell], -1)
        for box in [layout.hold, *layout.queue]:
            cv2.rectangle(vis, (box.x, box.y), (box.x + box.w, box.y + box.h), (255, 255, 0), 1)
        now = time.perf_counter()
        txt = f"{1 / (now - last):.0f} fps  hold={state.hold and state.hold.value}  queue={''.join(q.value if q else '?' for q in state.queue)}"
        last = now
        cv2.putText(vis, txt, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("preview", cv2.resize(vis, (1280, 720)))
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("s"):
            p = f"recordings/frame_{int(time.time())}.png"
            cv2.imwrite(p, frame)
            print("saved", p)
        if k == ord("p"):
            print(state.board_str())
    src.close()


if __name__ == "__main__":
    main()
