# tetris99player

A bot that plays Tetris 99 on a real Switch.

```
Switch dock ──HDMI──▶ capture card ──USB──▶ PC (OpenCV → state → engine) ──serial──▶ Arduino ──USB──▶ Switch
```

## Layout
- `tetris99/capture.py` – frame source (capture card or recorded video)
- `tetris99/vision/` – cell color classification, board/hold/queue extraction
- `tetris99/engine/` – board model and simulator; the decision engine (Cold Clear) plugs in here
- `tetris99/control/` – serial protocol and Tetris-level actions for the controller emulator
- `firmware/switch_hid/` – Arduino sketch that emulates a HORI wired pad
- `tools/preview.py` – live overlay to check capture and tune vision
- `tools/calibrate.py` – click-to-calibrate screen layout

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/pytest
.venv/bin/python tools/preview.py --device 0     # check the capture card
```
Press `s` in the preview to save a frame, then `python tools/calibrate.py recordings/frame_*.png`.

## Status
- [x] project skeleton, board model, serial protocol, firmware sketch
- [ ] verify capture card and calibrate layout on real frames
- [ ] tune color thresholds, detect active piece vs locked stack
- [ ] Cold Clear integration
- [ ] closed loop vs CPU battle mode
