"""Frame sources: capture card (V4L2 via OpenCV) or a recorded video for offline testing."""
from __future__ import annotations

import time
from typing import Iterator, Protocol

import cv2
import numpy as np

from .config import FRAME_H, FRAME_W


class FrameSource(Protocol):
    def frames(self) -> Iterator[np.ndarray]: ...
    def close(self) -> None: ...


class CaptureCard:
    def __init__(self, device: int | str = 0, fps: int = 60, width: int = FRAME_W, height: int = FRAME_H):
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"could not open capture device {device!r}")
        # MJPG is what cheap MS2130/MS2109 cards use to reach 1080p60 over USB2.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # always read the freshest frame

    def describe(self) -> str:
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        return f"{w}x{h} @ {fps:.0f}fps"

    def frames(self) -> Iterator[np.ndarray]:
        while True:
            ok, frame = self.cap.read()
            if not ok:
                raise RuntimeError("capture read failed")
            yield frame

    def close(self) -> None:
        self.cap.release()


class VideoFile:
    def __init__(self, path: str, realtime: bool = False):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise RuntimeError(f"could not open video {path!r}")
        self.realtime = realtime
        self.interval = 1.0 / (self.cap.get(cv2.CAP_PROP_FPS) or 60)

    def frames(self) -> Iterator[np.ndarray]:
        while True:
            t0 = time.perf_counter()
            ok, frame = self.cap.read()
            if not ok:
                return
            yield frame
            if self.realtime:
                time.sleep(max(0.0, self.interval - (time.perf_counter() - t0)))

    def close(self) -> None:
        self.cap.release()
