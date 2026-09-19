# tetris99player

A bot that plays Tetris 99 on a real Nintendo Switch. It watches the game through an HDMI capture
card, decides with the Cold Clear engine, and presses buttons through an Arduino that the Switch
believes is a licensed wired controller. It also doubles as a training tool: a coach overlay on
your own live games, and a keyboard Tetris sandbox with lessons, undo, and a placement explorer.

```
Switch dock ──HDMI──▶ capture card ──USB──▶ PC ──USB──▶ CP2102 ──TX/RX──▶ Arduino (32U4) ──USB──▶ Switch dock
                                             │
                        frames → vision → tracker → Cold Clear → executor → serial commands
```

**Where it stands (2026-09-19).** Three outright wins against 98 CPUs (levels 1 and 3), 5th of 99 at
CPU level 5, and online against real players a best of **7th of 99**, typically inside the top 20.
About 1.3 pieces per second. See [docs/HISTORY.md](docs/HISTORY.md) for every result and fix.
Result screenshots and match logs are deliberately not in the repository (they show other players'
nicknames); the bot saves them locally under `recordings/`.

## Documentation

| Document | What it covers |
|---|---|
| [docs/COMMANDS.md](docs/COMMANDS.md) | Every command, flag and mode, with examples |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works, what lives in which file, where each rule, threshold, debounce and timing constant is |
| [docs/HISTORY.md](docs/HISTORY.md) | Results, every bug found and how it was fixed, lessons, open issues, ideas |
| [docs/field-guide.html](docs/field-guide.html) | Learning material: Cold Clear's algorithm, USB HID controller emulation, the OpenCV pipeline |
| [firmware/switch_hid/README.md](firmware/switch_hid/README.md) | Building and flashing the controller firmware, wiring, recovery |
| [CLAUDE.md](CLAUDE.md) | Instructions for an AI agent picking this project up |

## Hardware

| Part | Used here | Notes |
|---|---|---|
| Capture card | "Guermok USB3 Video" (MacroSilicon MS2130), `/dev/video6` | Any 1080p60 MJPG UVC card. One program at a time can open it |
| Controller | ATmega32U4 board (enumerates as Arduino Leonardo; Pro Micro style, pins labelled TXO/RXI) | Must be a 32U4. Uno/Nano and ESP32-C3 cannot do USB HID |
| Serial link | CP2102 USB-TTL adapter, `/dev/ttyUSB0` | Adapter TXD→RXI, RXD→TXO, GND→GND, no VCC |
| Switch | Docked, 1080p output, **Pro Controller Wired Communication** on | System Settings → Controllers and Sensors |

Linux needs a udev rule so the serial devices are accessible and stay so when the board
re-enumerates during flashing:

```
printf 'SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", MODE="0666"\nSUBSYSTEM=="tty", ATTRS{idVendor}=="0f0d", MODE="0666"\nSUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", MODE="0666"\n' | sudo tee /etc/udev/rules.d/99-tetris99.rules
sudo udevadm control --reload && sudo udevadm trigger
```

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -e .[dev]

# Cold Clear (the decision engine), built as a shared library
git clone --depth 1 https://github.com/MinusKelvin/cold-clear third_party/cold-clear
(cd third_party/cold-clear && cargo build --release -p c-api)

.venv/bin/pytest            # 51 tests, no hardware needed
tools/flash.sh              # build + flash the controller firmware (see firmware/switch_hid/README.md)
```

## Quick start

```
# No hardware at all
.venv/bin/python tools/sandbox.py --lesson 1                     # keyboard Tetris with coach, explorer, undo, lessons
.venv/bin/python tools/watch.py                                  # watch the bot play a simulated game
.venv/bin/python -m tetris99.loop --source synthetic             # the whole pipeline against a fake Switch

# Capture card only
.venv/bin/python tools/preview.py --device 6                     # see the Switch, with the vision overlay
.venv/bin/python -m tetris99.loop --source 6 --trainer           # coach: you play, space shows Cold Clear's layout

# Capture card + Arduino
.venv/bin/python tools/gamepad.py                                # on-screen controller, to navigate menus
.venv/bin/python -m tetris99.loop --source 6 --output serial --show --pace 0 --early-request --settle-frames 2
.venv/bin/python tools/run_matches.py --show --from-menu fast fast fast   # three online matches, unattended
```

Everything else is in [docs/COMMANDS.md](docs/COMMANDS.md).

## Layout

```
tetris99/            the package: capture, vision, engine, control, the main loop
  vision/            pixels → symbols → game events
  engine/            board and piece model, Cold Clear binding, move compiler, playable game, coach
  control/           serial protocol and button-level actions
  sandbox/           lesson definitions for tools/sandbox.py
tools/               runnable scripts (viewers, calibration, hardware tests, match runner)
firmware/switch_hid/ Arduino sketch that emulates the HORI pad
config/              screen layout, Cold Clear weight sets, keyboard shortcuts
tests/               pytest suite, all offline
docs/                documentation
recordings/          (gitignored) saved frames, match logs, result screens (recordings/results/)
third_party/         (gitignored) Cold Clear checkout and build
```

The per-file guide is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Credits

- **[Cold Clear](https://github.com/MinusKelvin/cold-clear)** by MinusKelvin is the decision engine: the
  move generator, board evaluation and search are entirely its work. It is licensed under the
  Mozilla Public License 2.0. It is not included in this repository; the setup steps clone and build
  it, and the bot calls it through its C API (`tetris99/engine/coldclear.py`).
- The piece shapes and SRS wall-kick tables in `tetris99/engine/piece.py` were transcribed from Cold
  Clear's `libtetris` so that the paths it returns replay identically here. The T-spin rule in
  `tetris99/engine/game.py` follows the same source.
- The idea of presenting an ATmega32U4 as a HORI Pokken Tournament Pro Pad comes from the Switch
  homebrew community, notably progmem's Switch-Fightstick and celclow's SwitchControlLibrary, whose
  HID report descriptor layout the firmware reproduces.
- Tetris 99 and Nintendo Switch are trademarks of their owners. This is an unaffiliated hobby project.

Everything else in this repository is released under [CC0 1.0](LICENSE).
