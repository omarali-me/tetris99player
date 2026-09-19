# Commands and modes

Every command is run from the project root. `.venv/bin/python` is the project's own Python.

Two devices can each be held by **one program at a time**: the capture card (`/dev/video6`) and the
serial port (`/dev/ttyUSB0`). Close the preview, gamepad or a running bot before starting another
tool that needs the same device. To stop a bot that is running in the background:

```
ps -eo pid,args | awk '/[p]ython -u -m tetris99/ {print $1}' | xargs -r kill
```

## What needs what

| Command | Capture card | Arduino | Purpose |
|---|---|---|---|
| `pytest` | | | test suite |
| `tools/sandbox.py` | | | keyboard Tetris: coach, explorer, undo, lessons |
| `tools/watch.py` | | | watch the bot play a simulated game |
| `tetris99.engine.simulator` | | | text-only bot game, quickest engine check |
| `tetris99.loop --source synthetic` | | | full pipeline against a fake Switch |
| `tools/preview.py` | ✔ | | live feed with the vision overlay; save frames |
| `tools/calibrate.py` | | | click the screen layout on a saved frame |
| `tetris99.loop --trainer` | ✔ | | coach overlay while you play with Joy-Cons |
| `tetris99.loop --output dry` | ✔ | | bot decides on your live game but sends nothing |
| `tools/gamepad.py` | | ✔ | on-screen controller: mouse or keyboard |
| `tools/press.py`, `tools/hold.py` | ✔ / | ✔ | one press (+ screenshot); hold a button |
| `tools/restart_game.py` | | ✔ | Game Over → Try Again in single-player modes |
| `tools/measure_timing.py`, `tools/measure_drop.py` | ✔ | ✔ | measure the game's input timing |
| `tetris99.loop --output serial` | ✔ | ✔ | the bot plays |
| `tools/run_matches.py` | ✔ | ✔ | plays N online matches unattended |
| `tools/flash.sh` | | ✔ (on the PC) | build and flash the firmware |

## The bot: `python -m tetris99.loop`

```
.venv/bin/python -m tetris99.loop --source 6 --output serial --show --pace 0 --early-request --settle-frames 2
```

Start it when a match is about to begin or already running; it picks up from whatever is on screen.
Stop it with `q` in its window or Ctrl+C.

### Source and output

| Flag | Values | Meaning |
|---|---|---|
| `--source` | `synthetic` (default) | fake Switch, no hardware |
| | a number, e.g. `6` | V4L2 capture device index |
| | a video file path | play a recording through the pipeline |
| `--output` | `dry` (default) | log the moves, send nothing |
| | `serial` | send to the Arduino |
| `--port` | `auto` (default) or a path | serial port; auto prefers `/dev/ttyUSB*` |
| `--show` | | live window: feed plus what the tracker believes. Keys: `s` save frame, `q` quit |
| `-v` | | debug logging |

### Strategy

| Flag | Default | Meaning |
|---|---|---|
| `--weights FILE` | Cold Clear defaults | attack weight set (see `config/weights*.json`) |
| `--no-survival` | survival on | never switch to `config/weights_survival.json` |
| `--danger-height N` | 10 | stack height where it stops hunting T-spins and just clears |
| `--safe-height N` | 6 | height where it returns to the attack weights |
| `--no-softdrop` | soft drops on | hard-drop-only placements: no spins or tucks, steadier, less attack |
| `--targeting` | `kos` | `kos`, `random`, `badges`, `attackers`, `none`. Set once with the right stick at the first piece |
| `--threads N` | 2 | Cold Clear search threads |
| `--max-nodes N` | 100000 | Cold Clear search size |

### Speed

| Flag | Default | Meaning |
|---|---|---|
| `--pace S` | 0 | minimum seconds per piece. 0.7 is "human pace". It is a floor, not a throttle: the bot needs ~0.7 s per piece anyway |
| `--early-request` | off | ask Cold Clear when the spawn is first seen, while the spawn vote runs (~55 ms per piece) |
| `--settle-frames N` | 4 | extra frames voted at each spawn (4 ≈ 83 ms). 2 is faster and has held up |
| `--no-merge` | merge on | do not press rotate and sideways together |
| `--tap-ms N` | 34 | tap and gap length. **Never below 34 in battle mode**: 25 ms loses whole moves |

### Coach (`--trainer`): you play, the bot advises

```
.venv/bin/python -m tetris99.loop --source 6 --trainer --mode tspin
```

| Key | Action |
|---|---|
| `space` | read the live board, current piece, hold and queue; lay out Cold Clear's placements for all of them |
| `h` | hide / show the layout |
| `j` | show only the next step; press again to reveal one more |
| `t` / `a` / `n` | mode: T-spins / all clears / normal versus weights |
| `s` / `q` | save frame / quit |

Steps disappear as you place them, and the rest are re-drawn against the live board after line
clears. `--mode` sets the starting mode. Sends nothing to the Switch.

### Synthetic-only and debug flags

| Flag | Meaning |
|---|---|
| `--garbage-every N` | fake Switch adds 2 garbage lines every N pieces (default 15) |
| `--think MS` | think time per piece for the bot in synthetic runs (default 50) |
| `--save-softdrop` | save up to 45 raw frames while soft drops are held, to `recordings/sd_*.png` |

## Unattended matches: `tools/run_matches.py`

```
.venv/bin/python tools/run_matches.py --show --from-menu fast fast fast
```

Each word after the flags is one match, played in that mode, in order. For every match it presses
the start button, runs the bot until 30 s pass with no new piece, stops it, and saves
`recordings/matches/<time>_<n>_<mode>.log` and `.png` (the results screen). A one-line summary prints
per match.

| Flag | Meaning |
|---|---|
| `--from-menu` | the Switch is on the main menu with the TETRIS 99 tile selected (first match starts with a tap of A). Without it, a results screen with "Play Again" is assumed (A is held) |
| `--show` | open the bot's live window for each match |
| `--pace S` | default pace for modes that do not set their own |

| Mode word | Bot flags | Character |
|---|---|---|
| `fast` | `--early-request --settle-frames 2 --pace 0` | current best: spin-hunting with height-aware survival, full speed |
| `sd` | none (pace 0.7 from the runner) | same play at "human pace" |
| `early` | `--early-request` | isolates that one speed-up |
| `nosd` | `--no-softdrop` | hard drops only |
| `attack` | `--no-survival` | hunts T-spins at any height |
| `random` | `--targeting none` | leaves targeting on Random |
| `clean` | clean weights, `--no-survival --no-softdrop`, fast flags | no T-spins: clear lines, stay low |
| `cleansd` | as `clean` but soft drops allowed | |

Add `@S` to a word for a per-match pace: `sd@0.7 sd@0.4 sd@0`.

## Driving the Switch by hand

```
.venv/bin/python tools/gamepad.py            # add --dry to try the UI with no hardware
```

On-screen Pro Controller. Hold buttons with the mouse, drag the sticks (right-click a stick to click
it), or use the keyboard shortcuts printed under each control. `REBIND` lets you click a control and
press a new key; it saves to `config/keymap.json`. `esc` releases everything. Defaults: arrows d-pad,
WASD left stick, IJKL right stick, Enter A, Backspace B, x/y, q/e L/R, 1/3 ZL/ZR, -/= minus/plus,
h Home, c Capture, f/g stick clicks.

```
.venv/bin/python tools/press.py A            # tap A, wait, save a screenshot to recordings/screen.png
.venv/bin/python tools/press.py none         # just take a screenshot
.venv/bin/python tools/press.py RIGHT 1.2 out.png     # button or d-pad name, wait seconds, output file
.venv/bin/python tools/hold.py A 1.3         # hold a button: "Play Again" / "Try Again" are hold-to-confirm
.venv/bin/python tools/restart_game.py       # Game Over → Stats → Try Again (single-player modes)
```

Menu map: the main menu carousel runs … CPU Battle · Marathon · **TETRIS 99** · Team Battle …; the
cursor starts on the bottom row after returning from a game, so press UP first. Hold B ~1.3 s on a
results screen for the main menu. CPU Battle opens a level picker (LEFT/RIGHT, 1 to 5), then A.
The Switch dims its screen when idle and the first press only wakes it; `run_matches.py` sends ZL first.

## Looking at the game

```
.venv/bin/python tools/preview.py --device 6          # s = save frame to recordings/, p = print the board, q = quit
.venv/bin/python tools/calibrate.py recordings/frame_XXXX.png
```

`calibrate.py` asks for six clicks (board corners, hold box corners, first and last queue slot) and
writes `config/layout.json`. The measured 1080p layout is already the default, so this is only needed
if the capture resolution or the game's layout changes.

## Offline play and learning

```
.venv/bin/python tools/sandbox.py [--lesson 1-4]
```

| Key | Action |
|---|---|
| arrows, `up`/`x` CW, `z` CCW, `space` hard drop, `down` soft drop, `c`/shift hold | play |
| `p` pause, `g` gravity on/off, `u` undo, `r` redo, `F5` restart, `F1` help, `q` quit | control |
| `k` | coach: lay out all known pieces (`h`, `j`, `t`, `a`, `n` as in the live coach) |
| `e` | explorer: every reachable placement of the current piece. Left/right to browse, Enter to place, `v` to ask Cold Clear what follows from it, Esc to leave |
| `l` then `0`-`4` | lessons: 1 T-spin double, 2 T-spin triple (needs SRS kick 5), 3 build a TSD in 6 pieces, 4 perfect-clear opener, 0 free play |

Every lock is labelled (for example "Back-to-Back T-SPIN DOUBLE +5 attack") and spins report which
SRS kick was used and its offset.

```
.venv/bin/python tools/watch.py --garbage-every 8 --weights config/weights_tspin.json
```

Animated bot game against the fake Switch. `space` pause, `n` step, `+`/`-` speed, `q` quit. Flags:
`--seed`, `--pieces`, `--garbage-every`, `--threads`, `--max-nodes`, `--delay`, `--think`, `--weights`.

```
.venv/bin/python -m tetris99.engine.simulator         # 200 pieces, text output
.venv/bin/python -m tetris99.loop --source synthetic --garbage-every 6 --weights config/weights_clean.json --no-survival --no-softdrop
```

## Measuring the game

```
.venv/bin/python tools/measure_timing.py --device 6    # in a game with a LOW stack and slow gravity
.venv/bin/python tools/measure_drop.py --device 6 --trials 90     # in a CPU Battle
```

`measure_timing` reports press-to-visible latency, which tap lengths register, DAS delay and
auto-repeat rate. `measure_drop` tests whether a hard drop registers right after a rotation or move
at various gaps; results append to `recordings/drop_experiment.jsonl`.

## Firmware

```
tools/flash.sh /dev/ttyACM0       # board plugged into the PC; retry once if "butterfly_recv failed"
```

## Weight sets (`config/`)

| File | Used by | Character |
|---|---|---|
| `weights.json` | reference | every Cold Clear weight at its default, with notes. Copy and edit |
| `weights_survival.json` | default play, above `--danger-height` | clear lines, no setups, T may be spent freely |
| `weights_tspin.json` | coach mode `t` | heavy T-spin double/triple rewards |
| `weights_clean.json` | runner mode `clean` | no T-spin hunting for the whole match |
| `weights_safe.json` | example | lower, simpler stacking |

A weights file overrides only the keys it contains; unknown keys are an error; keys starting with
`_` are comments. All-clear coach mode is not a file: it turns on Cold Clear's perfect-clear solver.

## Tests

```
.venv/bin/pytest -q                 # all 51, a few seconds, no hardware
.venv/bin/pytest tests/test_tracker.py -v
```
