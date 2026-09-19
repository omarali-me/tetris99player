# tetris99player

A bot that plays Tetris 99 on a real Switch.

```
Switch dock ──HDMI──▶ capture card ──USB──▶ PC (OpenCV → state → engine) ──serial──▶ Arduino ──USB──▶ Switch
```

## Learning
`tools/sandbox.py` is a keyboard Tetris sandbox on the project's engine: coach layouts (k), an explorer of every placement of the current piece (e) with Cold Clear evaluation (v), undo/redo (u/r), pause (p), and T-spin / perfect-clear lessons (l) that explain the SRS kick used.

`docs/field-guide.html` explains Cold Clear's internals, the USB controller emulation, and the vision pipeline. Open it in a browser.

## Layout
- `tetris99/capture.py` – frame source (capture card or recorded video)
- `tetris99/vision/` – cell color classification, board/hold/queue extraction
- `tetris99/engine/` – board model and simulator; the decision engine (Cold Clear) plugs in here
- `tetris99/control/` – serial protocol and Tetris-level actions for the controller emulator
- `firmware/switch_hid/` – Arduino sketch that emulates a HORI wired pad
- `tools/preview.py` – live overlay to check capture and tune vision
- `tools/calibrate.py` – click-to-calibrate screen layout
- `tools/sandbox.py` – keyboard Tetris with coach, explorer, undo and lessons
- `tetris99/engine/game.py` – playable game model (7-bag, hold, SRS kicks, T-spin detection, undo/redo)

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

Evaluation weights: `config/weights.json` lists every Cold Clear weight at its default value with notes.
Copy it, edit, and pass `--weights my.json` to the loop or the viewer. Only the keys you keep are
overridden. `config/weights_safe.json` is an example that plays lower and simpler.

## Running
```
.venv/bin/python -m tetris99.loop --source synthetic            # offline, fake Switch, prints decisions
.venv/bin/python tools/watch.py                                 # same, but animated in a window
.venv/bin/python -m tetris99.loop --source recordings/game.mp4  # dry run on a recording (logs actions)
.venv/bin/python -m tetris99.loop --source 4 --output serial    # live: capture device 4 -> Arduino
.venv/bin/python tools/gamepad.py                               # on-screen controller (mouse or keyboard) -> Arduino, for menus
.venv/bin/python -m tetris99.loop --source 6 --trainer          # coach: you play; space lays out placements for all known pieces (t/a/n = T-spin / all-clear / normal)
```

## Status
- [x] project skeleton, board model, serial protocol, firmware sketch
- [x] capture card verified (Guermok USB3, device 6, 1080p60) and layout calibrated
- [x] active piece / locked stack tracker driven by queue shifts (tested on synthetic frames)
- [x] garbage meter reader feeding Cold Clear's incoming-garbage input
- [x] cell colours and garbage meter verified on real frames; frame read takes ~2.5 ms
- [x] Cold Clear integration and offline simulator
- [x] input executor: Cold Clear movements -> presses with DAS, replay-verified
- [x] main loop with dry-run and synthetic modes (`python -m tetris99.loop --source synthetic`)
- [x] controller firmware flashed (ATmega32U4 as HORI pad, 0f0d:0092) and verified from the PC: ping, buttons, hat, sticks
- [x] adapter wired, board on the dock: the Switch accepts it; timings measured (latency 116 ms, DAS 200, ARR 33, soft drop ~50 ms/row)
- [x] first live games in 150 Line Mode: ~1.5 pieces/s, 148 pieces with 1 misplacement; soft drops are closed-loop (release on seen landing)
- [x] first Tetris 99 battles (2026-09-19): places 94, 83, 89, 51, 67 of ~98. Fixed along the way: the pulsing Targeting pill read as O blocks, white HUD icons read as garbage, the board lagging the truth right after a line clear (the prediction is now trusted after clearing moves), serial framing resync, paced serial writes
- [ ] OPEN: in battle mode the final hard drop is often not registered when it directly follows a rotation (40% of such moves, ~50% of soft-drop moves, ~15% otherwise; it was 1 in 148 in 150 Line Mode). A watchdog re-sends the drop after 0.7 s, which rescues the piece but costs time. Ruled out: tap length (50 ms no better), serial RX overflow (pacing no better). Next: a controlled rotate-then-drop experiment in CPU Battle, varying the gap
- [ ] OPEN: `garbage +N` events were never classified in battle logs although garbage arrived; check the garbage-row reading against a saved battle frame
