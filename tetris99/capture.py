"""Frame sources: capture card (V4L2 via OpenCV) or a recorded video for offline testing."""
from __future__ import annotations

import threading
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
        # Take the raw JPEG bytes and decode them ourselves. With a 1-frame buffer, letting the
        # driver decode inside read() stalls it and halves the rate to 30 fps; this way it is 60.
        self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        self.raw = bool(self.cap.get(cv2.CAP_PROP_CONVERT_RGB) == 0)
        # Read and decode on a background thread (OpenCV releases the GIL in both), so the loop
        # always gets the newest frame and never pays the ~15 ms decode itself.
        self._latest: np.ndarray | None = None
        self._seq = 0
        self._cond = threading.Condition()
        self._stop = False
        self._err: Exception | None = None
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            while not self._stop:
                ok, frame = self.cap.read()
                if not ok:
                    raise RuntimeError("capture read failed")
                if self.raw:
                    frame = cv2.imdecode(frame.reshape(-1), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue  # a torn JPEG; skip it
                with self._cond:
                    self._latest = frame
                    self._seq += 1
                    self._cond.notify_all()
        except Exception as e:  # surfaced to the consumer in frames()
            with self._cond:
                self._err = e
                self._cond.notify_all()

    def describe(self) -> str:
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        return f"{w}x{h} @ {fps:.0f}fps"

    def frames(self) -> Iterator[np.ndarray]:
        """Yields each new frame; if the consumer falls behind, intermediate frames are skipped."""
        seen = 0
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._seq != seen or self._err is not None, timeout=2.0)
                if self._err is not None:
                    raise self._err
                if self._seq == seen:
                    raise RuntimeError("capture stalled: no frame for 2 s")
                seen, frame = self._seq, self._latest
            yield frame

    def close(self) -> None:
        self._stop = True
        self._thread.join(timeout=1.0)
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
