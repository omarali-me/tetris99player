# History: results, fixes, lessons, open work

Built over 2026-09-17 to 2026-09-19. Newest results first; fixes grouped by area. The git log has
one commit per change with the reasoning in the message.

## Results

### Online (Tetris 99, ~98 real players)

| When / settings | Places |
|---|---|
| First battles, several vision and logic bugs live | 94, 83, 89, 51, 67, 93, 91 |
| First clean run (HUD, watchdog, out-of-step fixed), pace 0.7 | 58 |
| `--no-softdrop` vs soft drops, pace 0.7 | 42, 66, 42 vs **12**, 71, 66 |
| Soft-drop fixes + K.O. targeting + height-aware strategy, pace 0.7 | 14, 10, 65, 43 and 16, 16, 15 |
| Pace test | 0.4 → 20, 32; 0.2 → **7**, **8** |
| `fast` vs `clean` (both full speed, ~1.3 pieces/s) | fast 10, 52 (+1 void, network error) vs clean 16, 79, 32 |

Best: **7th of 99**. Screens: `docs/online_12th_place.png`, `docs/online_10th_place.png`; all logs and
result screens are in `recordings/matches/` (gitignored).

### CPU Battle (98 CPUs)

| Level | Result |
|---|---|
| 1 | **1st**, 24 K.O.s, 221 pieces (`docs/first_win_cpu_battle.png`) |
| 3 | **1st** twice, 25 K.O.s, 307 and 322 pieces (`docs/win_cpu_level3.png`) |
| 5 | 25, 23, 19, **6**, 14, 11, 18, 36 (25 ms taps), **5** (fast settings), 21 (clean) (`docs/cpu_level5_6th.png`) |

### Single player

150 Line Mode: 148 pieces with 1 misplacement at ~1.5 pieces/s; 19 of 19 soft-drop spins.

## Fixes, by area

### Vision

| Problem | Cause | Fix |
|---|---|---|
| 3 fps | hold/queue readers converted thousands of tiny patches; OpenCV's decode inside the 1-frame driver buffer halved capture to 30 fps; overlay drawn at 1080p | one HSV conversion per region (344 → 2.5 ms); raw MJPG decoded on a thread (60 fps); overlay at 720p on alternate frames |
| J pieces invisible | blue range guessed too low (real hue ~124) | measured every hue on real frames |
| Garbage rows invisible, bot planned into them | garbage brightness is 111, floor was 115 | garbage = unsaturated, val 95-160, flat |
| Targeting widget read as blocks | its pill is dim yellow, pulses brighter in battle; stick icon is white | block brightness floor 150; O hue capped at 29; garbage brightness cap 160 |
| "GO!" banner read as blocks on piece 1 | | first board keeps only floor-connected cells |
| Pale side panel read as 8 incoming lines in single-player | | grey meter segments must be sat ≤ 60 |
| Meter miscounted | real segments are 48 px with dark edges, three colours (grey → yellow → red), gaps between attackers | segment walk re-anchored on each dark edge |
| Bottom-right cell misread under attack | the yellow attack lines fan out from that corner across the cell centre | five-point vote per cell in the lower half of the block |
| Sparks everywhere in battle mode (user's observation) | | temporal majority vote over ~5 frames at each spawn |
| Board read while rows were still collapsing | Tetris 99 has no line-clear delay | after a clearing move the prediction is trusted |
| My overlay filter deleted real floating blocks | line clears leave genuine floating remnants | floor-connection filter limited to the widget's rows after piece 1 |
| Strategy flipped on noise | one misread cell above the stack counted as height | height = floor-connected cells only |

### Tracking and decisions

| Problem | Cause | Fix |
|---|---|---|
| Hold display change fired a spawn before the queue settled | | hold debounced; a swap counts only if the queue is unchanged |
| Bot acted twice after its own hold | the swap shows a new piece | spawns during our own move are ignored |
| Whole match played one piece out of step | a hold swap was misrecognised and a second move was sent on top of the first | same rule made unconditional; later also: verify the piece on screen before every decision and resync |
| Stale move after garbage | `cc_reset_async` with a request in flight returns the old move | relaunch Cold Clear instead of resetting |
| Depth-1 play | requesting right after the previous answer truncates the search | request at spawn; 90 ms think time after a relaunch |
| Cold Clear aborted the process | impossible queue (misread menu) | 7-bag validation before anything reaches it |
| Cold Clear aborted on a **legal** queue | mid-game launch claimed a full bag while the queue repeated pieces early | `bag_boundary()` passes the true remaining bag |
| 3-20 s stalls, 1-3 per match | a lost hold press made the next real spawn look like "our own hold swap" | rescue: idle + a piece visibly falling → take over from the screen |
| Queue bookkeeping drift in the simulator | hold into an empty slot reveals two pieces | every revealed piece is reported |

### Input and hardware

| Problem | Cause | Fix |
|---|---|---|
| Wrong board delivered (ESP32-C3) | cannot do USB HID | ATmega32U4 |
| Serial port unusable during flashing | chmod is lost when the board re-enumerates | udev rule for the three vendor IDs |
| Third-party HID library would not build | STL dependency | firmware subclasses the core `HID_` class directly (~15 lines) |
| D-pad wrong in the first firmware draft | called `pressHatButton` with hat values | direct report field |
| "Try Again" ignored | it is hold-to-confirm | `tools/hold.py`, A for 1.3 s |
| Soft drops locked early once the level rose | fixed hold time | closed loop: release when the landing is seen |
| Half of all soft drops timed out | the landing check watched the **spawned** piece's colour; after a hold the piece in play is another colour | watch the piece being placed (`Player.target[0]`) |
| Hold's own spawn seen as "piece locked" mid soft drop | | recognised and ignored |
| After a soft-drop timeout the rest of the move hit the next piece | | abandon the move if the piece is gone |
| Hard drops "lost" in battle mode | **misdiagnosis**: the watchdog fired falsely while garbage rose; `tools/measure_drop.py` registered 27/27 | watchdog re-sends only if the target cells are still empty |
| Commands corrupted after another tool used the port | 3-byte framing shifted by a stray byte | ping re-aligns with padding bytes |
| End of long moves missing | 32U4 RX buffer is 64 bytes; bursts overflowed | 2.5 ms pacing per command |
| 25 ms taps | whole moves vanish in battle mode (fine in single-player) | 34 ms is the floor |

### Speed study

Pace 0.7, 0.4 and 0.2 all gave ~1.1 pieces/s: pace was never the limiter. Per piece: ~360 ms fixed
(game spawn delay + capture latency ~200, queue debounce 33, spawn vote 83, Cold Clear answer 55) plus
68 ms per input; soft-drop moves ~1.6 s each and ~25 % of a match. Gains kept: merged rotate+move
inputs, early request, 3-frame vote, rescue (dead time 16 % → 2.5 %). Net ~1.1 → ~1.3 pieces/s.

### Strategy (from the player's advice)

- K.O. targeting at the first piece.
- T-spins only while the stack is low: attack weights below row 10, survival weights from row 10 until back to row 6.
- "Clean" (no T-spins at all) was tried online: 16, 79, 32 against 10, 52 for spin-hunting. No evidence it helps; it sends little garbage and was not read more reliably.

## Lessons

1. **Instrument before theorising.** Three confident theories were wrong: "the game drops hard drops after rotations", "soft drops fail because of gravity", "soft-dropped pieces change colour". A controlled experiment or saved frames found the real cause each time.
2. **Trust the screen, but know when it lags.** Rebuilding the board at every spawn bounds any error to one piece; the exceptions (line-clear collapse, overlays) need explicit rules.
3. **Never judge a match over from the log.** Twice the bot was stopped mid-match. Use 30 s without a new piece, or look at the screen.
4. **Small samples say little.** Placement depends heavily on who targets you early. Three matches a side cannot separate two strategies.
5. **Single-player timing does not transfer to battle mode.**

## Open issues

- ~10 % board mismatches in battle mode. Roughly a third are single cells in column 9 (attack lines along the board edge); the rest are moves partly not applied.
- `out of step … resynchronising` fires up to ~15 times in a long match. The resync rescues it; the source of the stray drops is not found (suspects: the hard-drop watchdog, a tap landing just after a lock).
- Garbage arrivals are logged as `DIVERGED`, almost never as `garbage +N`: the exact-shift check in `garbage_rows()` does not match real frames. Compare against a saved `recordings/diverge_*.png`.
- The danger tint (red glow when the stack is high) has not been measured against the garbage thresholds.
- More than 20 queued garbage lines: the meter reader caps at 20 segments.

## Ideas not yet tried

- `--danger-height 8`: stop setting up spins a little earlier.
- Raise Cold Clear's `move_time` penalty in the attack weights: soft-drop moves are 13 % of pieces but ~25 % of the clock.
- Detect "match over" (the all-grey KO board, the results screen) and "match started" properly, instead of idle timers.
- Navigate menus by recognising screens rather than fixed press sequences.
- Badge- and K.O.-aware targeting changes late in a match (for example Attackers when heavily targeted).
- A larger Cold Clear search (`--threads`, `--max-nodes`) now that ~400 ms per piece is fixed overhead anyway.
