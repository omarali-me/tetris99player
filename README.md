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

## Cold Clear (decision engine)
```
git clone --depth 1 https://github.com/MinusKelvin/cold-clear third_party/cold-clear
(cd third_party/cold-clear && cargo build --release -p c-api)
.venv/bin/python -m tetris99.engine.simulator   # bot plays 200 pieces offline
```
The binding is `tetris99/engine/coldclear.py`; `engine/simulator.py` runs a 7-bag game against the board model.

## Running
```
.venv/bin/python -m tetris99.loop --source synthetic            # offline, fake Switch, prints decisions
.venv/bin/python -m tetris99.loop --source recordings/game.mp4  # dry run on a recording (logs actions)
.venv/bin/python -m tetris99.loop --source 4 --output serial    # live: capture device 4 -> Arduino
```

## Status
- [x] project skeleton, board model, serial protocol, firmware sketch
- [ ] verify capture card and calibrate layout on real frames
- [x] active piece / locked stack tracker driven by queue shifts (tested on synthetic frames)
- [ ] tune color thresholds on real frames
- [x] Cold Clear integration and offline simulator
- [x] input executor: Cold Clear movements -> presses with DAS, replay-verified
- [x] main loop with dry-run and synthetic modes (`python -m tetris99.loop --source synthetic`)
- [ ] closed loop vs CPU battle mode
