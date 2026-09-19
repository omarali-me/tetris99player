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
- [x] 2026-09-19: FIRST WIN. CPU Battle (level 1), 1st of 99 with 24 K.O.s, 221 pieces in 3m15s (docs/first_win_cpu_battle.png)
- [x] 2026-09-19: second win at CPU level 3: 1st of 99, 25 K.O.s, 307 pieces in 4m39s, no re-sent drops (docs/win_cpu_level3.png)
- [x] 2026-09-19: third CPU win (level 3, 322 pieces) with a temporal vote over frames at each spawn and `--pace 0.7`; mismatches 14% -> 8%. First clean ONLINE result with all fixes: 58th of 98 (141 pieces, 2m33s). Earlier online results (94/83/89/51/67/93/91) were all played with at least one of: HUD phantoms, false watchdog re-sends, or the bot running one piece out of step after a misrecognised hold
- [x] 2026-09-19 online comparison, 6 matches at `--pace 0.7`, alternating modes (tools/run_matches.py; logs and result screens in recordings/matches/):

  | mode | places | mean | pieces per match | board mismatches |
  |---|---|---|---|---|
  | `--no-softdrop` | 42, 66, 42 | 50 | 234, 149, 230 | 8.5%, 8.7%, 8.7% |
  | soft drops on | **12**, 71, 66 | 50 | 378, 124, 130 | 14%, 12%, 12% |

  Same average, different character: hard-drop-only is steadier, soft drops (T-spins) have the higher ceiling (docs/online_12th_place.png) and the lower floor. Three matches each is far too few to separate them. Soft drops stay on by default; the thing to fix is their reliability ('piece locked during a soft drop' 9/6/3 times per match)
- [x] 2026-09-19 SOFT-DROP RELIABILITY FIXED. It was never gravity or colour. Frames captured during soft drops (`--save-softdrop`) plus the log showed three bugs:
  1. the landing check watched the colour of the piece that SPAWNED; after a hold the piece in play is the swapped-in one, so every hold+soft-drop move timed out (that was ~half of all soft drops)
  2. the hold's own spawn event, arriving while down was held, was treated as "the piece locked" and the move was abandoned
  3. after a timeout the rest of the move (including its hard drop) was still sent even if the piece had already locked, which dropped the NEXT piece and left the bot one piece out of step; from then on every move landed on the wrong piece. Decisions are now verified against the screen at decision time (`out of step ... resynchronising`), and a timed-out soft drop abandons the move when the piece is gone
  Landing is now "the placed piece's lowest cell is on the landing row the executor computed", which holds at any gravity.
  CPU Battle level 5 (hardest), same settings: before 13 of 23 soft drops timed out (25th); after 1 of 34, 0 early locks, 6th of 99 (docs/cpu_level5_6th.png)
- [x] 2026-09-19 two pieces of player advice built in: K.O. targeting set at the first piece (right stick up; `--targeting`), and height-aware strategy: attack weights (T-spins) while the floor-connected stack is below row 10, `config/weights_survival.json` (clear lines, no setups) from row 10 until it is back down to row 6 (`--danger-height`, `--safe-height`, `--no-survival`). CPU level 5: 14th. Online, 4 matches back to back with everything on: **14th, 10th, 65th, 43rd** (mean 33; the previous six averaged 50). Two matches passed 420 pieces and 6m40s. docs/online_10th_place.png
- [x] 2026-09-19 online, user's batch at pace 0.7: **16th, 16th, 15th**. Speed test batch: pace 0.4 -> 20th, 32nd; pace 0.2 -> **7th, 8th** (best online results)
- [x] 2026-09-19 SPEED STUDY. `--pace` turned out not to be the limiter: 0.7, 0.4 and 0.2 all gave ~1.1 pieces/s. Per piece: ~360 ms fixed overhead (game spawn delay + capture latency ~200 ms, queue debounce 33, spawn vote 83, Cold Clear answer 55) + 68 ms per input; soft-drop moves cost ~1.6 s each and take ~25% of match time. Added: simultaneous rotate+move inputs where order provably does not matter (on by default, `--no-merge`), `--early-request` (ask Cold Clear while the spawn vote runs), `--settle-frames`, `--tap-ms`. **25 ms taps lose whole moves in battle mode** (fine in single-player): 34 ms is the floor. Result at CPU level 5 with `--pace 0 --early-request --settle-frames 2`: 1.22 pieces/s, 12% mismatches, **5th of 99**. `run_matches.py` mode `fast` = those flags; `sd@0.4` sets a per-match pace
- [x] Rescue: when the bot is idle and a piece is visibly FALLING, it takes over from the screen. Root cause found for the recurring 3-20 s stalls: a lost hold press made the next real spawn look like "our own hold swap" and it was ignored. Long waits went from 16% of match time to 2.5%
- [x] Cold Clear abort on a LEGAL queue (J LTLSTZ): mid-game launches claimed a full bag while the queue repeated pieces early. `bag_boundary()` now infers the real remaining bag, and doubles as the exact 7-bag validity test
- [x] 2026-09-19 'clean' strategy (user's idea: no T-spins, clear lines, keep the board empty): `config/weights_clean.json` + hard drops only, runner mode `clean` (`cleansd` = same with soft drops). Offline it holds a slightly lower stack than the default under heavy garbage. CPU level 5: 21st. Online, alternating with `fast` (spin-hunting, same speed settings), all at ~1.3 pieces/s:

  | mode | places |
  |---|---|
  | clean | 16, 79, 32 |
  | fast | 10, 52, (third match void: Nintendo communication error 2306-0332 mid-game) |

  No evidence that dropping T-spins helps: clean averaged 42nd, fast 31st, on 3 and 2 matches, which is noise-level. Clean had MORE board mismatches (12-14% vs 8-11%), so its stacks are not easier to read either
- [ ] IDEA: soft-drop moves are 13% of pieces but ~25% of time; raising Cold Clear's `move_time` penalty in the attack weights would trade some spins for tempo
- [ ] OPEN: `out of step ... resynchronising` fires ~15 times in a long match. The resync rescues it, but each one means a piece was dropped by an input the bot did not intend; find the source (suspect: hard-drop watchdog or a tap landing after a lock)
- [ ] (superseded) soft-drop moves fail more as gravity rises ('piece locked during a soft drop' x7 in one match) and two 8-11 s stalls came right after such moves with 10 lines incoming. Try `--no-softdrop` (Cold Clear hard-drop-only mode) and compare placings
- [ ] OPEN: ~10% small board mismatches remain in battle mode. About a third are single cells in the right-hand column (x=9), where the attack lines run along the board edge; the rest are genuine misplacements where part of a move was not applied. Garbage arrivals are still logged as DIVERGED rather than `garbage +N` (the exact-shift check never matches; check the bottom garbage rows on a saved diverge_*.png)
- [x] RESOLVED: the 'lost hard drop after a rotation' was a misdiagnosis. A controlled experiment (tools/measure_drop.py) registered 27/27 drops at gaps down to 17 ms. The re-sends were the watchdog firing falsely while garbage rose (its animation delays the next spawn); it now re-sends only when the screen shows the piece did not land. The real damage came from vision: attack lines crossing a cell fooled the single centre sample, so cells now use a five-point vote
- [ ] (historical note) in battle mode the final hard drop is often not registered when it directly follows a rotation (40% of such moves, ~50% of soft-drop moves, ~15% otherwise; it was 1 in 148 in 150 Line Mode). A watchdog re-sends the drop after 0.7 s, which rescues the piece but costs time. Ruled out: tap length (50 ms no better), serial RX overflow (pacing no better). Next: a controlled rotate-then-drop experiment in CPU Battle, varying the gap
- [ ] OPEN: `garbage +N` events were never classified in battle logs although garbage arrived; check the garbage-row reading against a saved battle frame
