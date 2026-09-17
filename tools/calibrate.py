"""Calibrate the screen layout from a saved frame. Click, in order:
board top-left, board bottom-right, hold box top-left, hold bottom-right, then queue slot 1 top-left
and queue slot 6 bottom-right (slots are assumed evenly spaced). Saves config/layout.json."""
from __future__ import annotations

import sys

import cv2

from tetris99.config import QUEUE_LEN, Layout, Rect

PROMPTS = ["board top-left", "board bottom-right", "hold top-left", "hold bottom-right",
           "queue slot 1 top-left", "queue slot 6 bottom-right"]


def main() -> None:
    frame = cv2.imread(sys.argv[1])
    if frame is None:
        sys.exit(f"cannot read {sys.argv[1]}")
    pts: list[tuple[int, int]] = []

    def on_mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN:
            pts.append((x, y))
            print(f"{PROMPTS[len(pts) - 1]}: {x},{y}")

    cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("calibrate", on_mouse)
    while len(pts) < len(PROMPTS):
        vis = frame.copy()
        cv2.putText(vis, f"click: {PROMPTS[len(pts)]}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        for p in pts:
            cv2.circle(vis, p, 4, (0, 0, 255), -1)
        cv2.imshow("calibrate", vis)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            sys.exit("aborted")

    def rect(a, b) -> Rect:
        return Rect(a[0], a[1], b[0] - a[0], b[1] - a[1])

    q0, q5 = pts[4], pts[5]
    pitch = (q5[1] - q0[1]) / QUEUE_LEN
    queue = [Rect(q0[0], int(q0[1] + i * pitch), q5[0] - q0[0], int(pitch)) for i in range(QUEUE_LEN)]
    layout = Layout(board=rect(pts[0], pts[1]), hold=rect(pts[2], pts[3]), queue=queue)
    layout.save()
    print("saved config/layout.json:", layout)


if __name__ == "__main__":
    main()
