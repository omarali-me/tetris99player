# Architecture: how it works and where everything lives

For the theory behind the pieces (Cold Clear's search, USB HID, HSV vision) read
[field-guide.html](field-guide.html). This document is the map of the code.

## 1. One piece, start to finish

```
capture.py         frame (1080x1920x3 BGR), decoded on a background thread, newest frame only
vision/board.py    read_frame(): 200 cells (5-point vote each) + hold + 6 queue slots + garbage meter → FrameState
vision/tracker.py  Tracker.update(): queue shift = "a piece spawned" → vote over frames → Spawn(piece, locked board, hold, queue)
loop.py            Player.step(): hold the decision until its pace time → verify the piece on screen → on_spawn()
engine/coldclear   request_move / poll_move → Move(hold, target cells, path)
engine/executor    compile_move(): replay the path on the piece model, must land on the target cells → [Action]
                   merge_simultaneous(): rotate + sideways in one input slot where order cannot matter
loop.py            _execute(): taps sent in one burst; soft drops are closed-loop segments
control/           run_actions() → 3-byte serial commands, paced
firmware           queue of timed commands → 8-byte HID report every 8 ms → Switch
loop.py            predicts the resulting board; the next Spawn is compared with it
```

Everything after `read_frame` works on symbols, never pixels. Everything in `engine/` is pure
and offline-testable.

### Coordinates

| Where | Convention |
|---|---|
| frames | `frame[y, x]`, BGR, 1920x1080 |
| vision grid (`FrameState.grid`) | `[row][col]`, row 0 = **top** visible row |
| engine (`Board`, `FallingPiece`, Cold Clear) | `(x, y)`, y = 0 is the **bottom**; 40 rows, 20 visible |
| conversion | `y = 19 - row`. `tracker.grid_cells()`, `tracker.to_board()`, `Layout.cell_center(row, col)` |

## 2. Per-file guide

### `tetris99/`

| File | What lives there |
|---|---|
| `config.py` | `Layout` (pixel rectangles of board, hold, queue, garbage meter; measured 1080p defaults; `config/layout.json` overrides), `Settings`, `find_serial_port()` (auto-detect, prefers `/dev/ttyUSB*`) |
| `capture.py` | `CaptureCard`: V4L2 MJPG 1080p60, raw JPEG bytes decoded on a background thread, always yields the newest frame. `VideoFile` for recordings |
| `loop.py` | The main program. `Player` (decisions, execution, prediction, all live safety nets, the coach), `SerialOutput` / `DryRunOutput`, `LiveView` (the `--show` window and coach overlay), `stack_height()`, `garbage_rows()`, CLI |
| `sim_env.py` | `SimEnv`: a fake Switch. Interprets the action list independently of the executor and renders `FrameState`s, including the garbage meter |
| `render.py` | Draws a game state as an image (used by `tools/watch.py`) |

### `tetris99/vision/`

| File | What lives there |
|---|---|
| `cells.py` | **All colour thresholds.** `HUE_RANGES`, saturation/value limits, garbage rules, `classify_patch()` (scalar reference implementation), `is_flat()` |
| `board.py` | `read_frame()`. Vectorised classifier `classify_hsv()` (must agree with `cells.classify_patch`), `SAMPLE_OFFSETS` + `vote()` (five-point vote per cell), `read_piece_box()` for hold/queue, `FrameState` |
| `garbage.py` | `read_garbage_meter()`: walks the meter segment by segment (48 px, dark top edge, gaps between attacks). `GarbageMeter(pending, imminent, queued)` = yellow, red, grey |
| `tracker.py` | `Tracker`: queue/hold debouncing, spawn detection, locked/active split (`split_spawned`), temporal vote (`_vote`), re-check on mismatch (`_emit`), `grounded()` overlay filter, `trust_expected`. `Spawn` event |
| `synthetic.py` | `render()`: builds a `FrameState` from engine state, for tests and `SimEnv` |

### `tetris99/engine/`

| File | What lives there |
|---|---|
| `board.py` | `Board`: 40 rows of bitmasks, `fits`, `place` (returns lines cleared), `add_garbage`, `height` |
| `piece.py` | `FallingPiece`: SRS cells and kick tables copied from Cold Clear's libtetris, `shift`, `rotate`, `sonic_drop`, `spawn` (x=4, y=19 or 20) |
| `coldclear.py` | ctypes binding of Cold Clear's C API. `ColdClear` (launch, request/poll, plan), structs mirroring `coldclear.h`, weights load/apply, **`bag_boundary()` / `valid_sequence()`** (7-bag rules) |
| `executor.py` | `compile_move()` path → `Action` list with replay verification; DAS rule (`DAS_MIN_RUN`); soft drops carry `rows` and `land_y`; `merge_simultaneous()` |
| `coach.py` | `plan_from()`: one-shot Cold Clear plan from a position in a coach mode (`MODES`); `map_plan()` maps per-step coordinates back through line clears |
| `game.py` | `Game`: playable guideline Tetris for the sandbox. 7-bag, hold, kick reporting, T-spin detection (libtetris's rule), attack table, undo/redo |
| `explore.py` | `reachable_placements()`: every placement of a piece with its input path |
| `simulator.py` | `SimGame` + `play()`: minimal bot-vs-board loop used by tests and `tools/watch.py` |

### `tetris99/control/` and firmware

| File | What lives there |
|---|---|
| `protocol.py` | Wire format: 3 bytes (opcode, uint16 LE). `Op`, `Button` (bit order of the HID report), `Hat`, `stick_arg()` |
| `switch_controller.py` | **Input timing constants.** `SwitchController` (paced `_send`, resyncing `ping`, taps, `tap_together`, `set_targeting`), `run_actions()` |
| `firmware/switch_hid/switch_hid.ino` | HID report descriptor of the HORI Pokken pad, a 64-entry command queue executed on the board's own clock, listens on `Serial` (USB) and `Serial1` (pins), re-sends the report every 8 ms |

### `tools/`, `config/`, `tests/`

`tools/` is described command by command in [COMMANDS.md](COMMANDS.md). `config/` holds the weight
sets, `keymap.default.json`, and (gitignored) `layout.json` / `keymap.json`. Tests mirror the modules;
`test_pipeline.py` and `test_loop.py` run the whole loop against `SimEnv`.

## 3. Where each rule lives

### Seeing: colour and shape rules

| Rule | Value | Location |
|---|---|---|
| Piece hues (OpenCV 0-179) | I 84-98, O 19-29, T 132-150, S 42-60, Z 0-5 and ≥164, J 112-132, L 6-16 | `cells.py` `HUE_RANGES`, `Z_WRAP_MIN` |
| A coloured cell is a block | sat ≥ 130 and val ≥ 150 | `SAT_MIN`, `VAL_MIN_BLOCK` |
| Coloured but dim = ghost or HUD overlay → treated as empty | val < 150 | `VAL_MIN_BLOCK` |
| O capped at hue 29 | the Targeting pill pulses at 31-33 | `HUE_RANGES` comment |
| Garbage | sat ≤ 60, 95 ≤ val ≤ 160, and flat (std ≤ 12 or ≥ 55 % of pixels within 10 of the median) | `GARBAGE_*`, `VAL_MIN_GARBAGE`, `VAL_MAX_GARBAGE`, `is_flat()` |
| Five-point vote per cell | centre + 4 points in the lower half; 2 agreeing samples needed | `board.py` `SAMPLE_OFFSETS`, `VOTES_NEEDED` |
| Hold/queue box is a piece | ≥ 150 vivid pixels, dominant hue wins | `board.py` `MIN_PIECE_PIXELS`, `read_piece_box()` |
| Garbage meter | 48 px segments, empty below val 115, grey if sat ≤ 60, red hue ≤ 8 or ≥ 160, yellow 12-40 | `garbage.py` |
| Incoming garbage handed to Cold Clear | red + yellow + grey/2 | `tracker.py` (`Spawn.incoming`), used in `Player.on_spawn` |

The two classifiers must stay identical. After changing a threshold, run the agreement check in
[CLAUDE.md](../CLAUDE.md) over `recordings/`.

### Debouncing and voting (time)

| Rule | Value | Location |
|---|---|---|
| Queue change must be read identically on N frames | 2 | `Tracker(confirm_frames=2)`, `_stable_queue()` |
| Hold change likewise | 2 | `_stable_hold()` |
| A hold change counts as a swap only if the queue is unchanged in that frame | | `Tracker.update()` |
| Queue shifted by 1 → piece = old `queue[0]`; by 2 → hold into an empty slot, piece = old `queue[1]` | | `Tracker.update()` |
| Temporal vote of the locked board at each spawn | `settle_frames + 1` frames, per-cell majority; up to 2 extensions if it still disagrees with the prediction | `_vote()`; live default 4, `--settle-frames` |
| Without the vote: re-check a mismatch for N frames | 5 | `recheck_frames`, `_emit()` |
| After a line-clearing move, use the predicted board as is | the screen lags while rows collapse; garbage never enters on a clear | `trust_expected` |
| Locked cells must connect to the floor | always at the first spawn (GO! banner); afterwards only for rows ≥ 14 (Targeting widget) | `grounded()`, `HUD_MIN_ROW` |
| Spawn zone for finding the new piece | rows 17-19, columns 2-7 | `SPAWN_ROWS`, `SPAWN_COLS` |

### Input timing

| Rule | Value | Location |
|---|---|---|
| Tap / gap | 34 ms / 34 ms (2 frames). 25 ms loses moves in battle mode | `switch_controller.py` `TAP_MS`, `GAP_MS`; `--tap-ms` |
| DAS hold to a wall | 560 ms (measured DAS 200 + 9 × ARR 33 + margin) | `DAS_MS` |
| DAS only for runs of ≥ 6 | tapping is faster from spawn | `executor.py` `DAS_MIN_RUN` |
| Serial pacing | 2.5 ms per 3-byte command (32U4 RX buffer is 64 bytes) | `SwitchController._send()` |
| Framing resync | unanswered ping → send one padding byte, retry up to 4× | `SwitchController.ping()` |
| Firmware PRESS length, report keep-alive | 34 ms, every 8 ms | `switch_hid.ino` |
| Targeting flick | right stick held 180 ms | `set_targeting()` |
| Measured game facts | press → visible 116 ms; DAS 200 ms; ARR 33 ms; soft drop ≈ 50 ms/row at level 1; "Play Again" needs A held ≈ 1 s | `tools/measure_timing.py` |

### Decision and safety rules (`loop.py`, class `Player`)

| Rule | Value | Location |
|---|---|---|
| Pace: earliest decision time | `last_sent + pace_s` (a deferred decision, not a sleep) | `step()` |
| Verify the piece in play before deciding; resync from the screen if it differs | | `_verified()`, `_piece_on_screen()` |
| Spawns while our own move is still executing are our hold swap, never a new decision | | `on_spawn()` (`busy_until`), `step()` (`own_hold` during a soft drop) |
| Think time after a relaunch | 90 ms | `fresh_think_ms` |
| Early request | ask Cold Clear when the spawn vote starts | `step()`, `early_request` |
| Board differs from prediction → relaunch Cold Clear from the observed board (never `reset`: a request in flight returns a stale move) | | `on_spawn()` |
| Rejected path → relaunch and ask once more | | `on_spawn()` |
| Impossible 7-bag reading → ignore, drop the bot | | `on_spawn()`, `valid_sequence()` |
| Soft drop = hold down until the **placed** piece's lowest cell is on `land_y` for 2 frames | fallback timer `0.12 + rows × 0.07 + 0.30 s` | `_watch_drop()`, `_advance_segments()` |
| Soft drop timed out and the piece is gone → abandon the rest of the move | | `_watch_drop()` |
| Hard-drop watchdog | 0.7 s after the move; re-send only if the target cells are still empty and no lines were cleared; max 3 | `_arm_watchdog()`, `_target_filled()`, `step()` |
| Rescue | idle > 0.6 s after our move and > 0.9 s since sending, a piece of one colour is visibly **moving down** → take over from the screen | `_rescue()` |
| Strategy switch | survival weights at stack height ≥ 10, attack again at ≤ 6; height counts only floor-connected cells | `_update_strategy()`, `stack_height()` |
| Targeting | sent once at the first piece | `on_spawn()` |
| Stall log | no new piece for 3 s → warning + `recordings/stall_*.png` | `main()` |
| Every mismatch saves a frame | `recordings/diverge_*.png` | `main()` |

### Cold Clear specifics (`engine/coldclear.py`)

| Rule | Location |
|---|---|
| Piece enum order is `IOTLJSZ` | `PIECES` |
| Mid-game launch passes the true remaining bag, inferred from the queue | `bag_boundary()`, `ColdClear.__init__` |
| An impossible bag makes Cold Clear **abort the process**; never pass one | `valid_sequence()` guard in `__init__` |
| Weights cannot change on a running bot → relaunch | `Player._update_strategy()` |
| A request makes it answer as soon as it can; it thinks continuously by itself, so do not request early without reason | `Player._get_move()` |
| Plan steps are in post-clear coordinates; a step's cleared rows share one coordinate system | `coach.map_plan()` |
| `hard_drop_only=True` → `CC_HARD_DROP_ONLY` movement mode | `ColdClear.__init__` |

## 4. Log messages and what they mean

| Message | Meaning |
|---|---|
| `#N T hold=.. -> ...  (ms, depth D, incoming K)` | a decision: piece, inputs, time inside the decision, Cold Clear's search depth, garbage on the meter |
| `bot launched: piece=.. hold=.. queue=..` | Cold Clear (re)started from the observed position |
| `DIVERGED after X [...]: missing=.. extra=.. cleared=N` | the board at the next spawn differed from the prediction. Many cells = garbage rose or an unexpected clear; a few = misread or misplacement |
| `garbage +N lines (placement was correct)` | the difference was exactly N garbage rows (rarely matches in practice; open issue) |
| `stack height H: switching to SURVIVAL / attack weights` | strategy change |
| `out of step: believed X ... screen shows Y` | the piece in play was not the expected one; resynchronised from the screen |
| `idle while a X is falling ... taking over` | rescue after a lost input |
| `no new piece 0.7 s after the hard drop: re-sending it` | watchdog; frequent only if taps are too short |
| `piece locked during a soft drop` / `soft drop released on the timer` | soft-drop failures; should be rare |
| `ignoring impossible reading` | a menu, countdown or results screen was read as a game; harmless |
| `no spawn for 3 s` | stall; a frame was saved |
