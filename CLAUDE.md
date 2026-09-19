# Instructions for AI agents working on tetris99player

A bot that plays Tetris 99 on a real Nintendo Switch: capture card → OpenCV → Cold Clear → Arduino
emulating a wired controller. Also a coach overlay and an offline training sandbox. The owner is a
seasoned Tetris player who built this to learn: explain mechanisms, not just results.

## Read first

1. `README.md`: what it is, hardware, setup.
2. `docs/ARCHITECTURE.md`: data flow, per-file map, **the table of where every rule, threshold, debounce and timing constant lives**, log messages.
3. `docs/HISTORY.md`: every bug already found and fixed, lessons, open issues, untried ideas. Check it before "discovering" a problem.
4. `docs/COMMANDS.md`: every command, flag and mode.

## Ground rules

- **Run `.venv/bin/pytest -q` before and after every change.** 51 tests, a few seconds, no hardware. Timing-sensitive code has bitten before: if a test fails once, run the suite 5-10 times to see whether it is flaky, and fix the cause.
- **Commit each change separately** with the reasoning in the message. Do not commit `recordings/`, `third_party/`, `tools/bin/`, `config/layout.json`, `config/keymap.json` (all gitignored).
- **The GitHub repository is public. Never commit screenshots, captured frames, match logs or videos**: results screens show real players' nicknames. `.gitignore` blocks `docs/*.png`, `*.log`, `*.jsonl`, `*.mp4`; keep such files under `recordings/`. Remote: `git@github-personal:omarali-me/tetris99player.git` (SSH host alias from `~/.ssh/config`), branch `main`.
- **Instrument before theorising.** Three confident theories in this project were wrong (see HISTORY "Lessons"). Use `tools/measure_timing.py`, `tools/measure_drop.py`, `--save-softdrop`, the saved `recordings/diverge_*.png` and `stall_*.png`, and the per-piece log. Look at frames.
- **Validate offline, then CPU Battle, then online.** `--source synthetic` and the tests first; CPU Battle (level picker 1-5) is the right live test bed because it has the same 99-board screen and overlays with nobody affected; online last.
- **Online matches use the owner's Nintendo account against real people. Ask before starting any**, and say how many. CPU Battle and single-player modes need no permission once the owner has asked you to test on hardware.
- **Small samples prove nothing.** Placement swings wildly with early targeting. Alternate the two settings being compared within one batch (`tools/run_matches.py a b a b a b`) and report the spread, not just the mean.

## Hardware you can drive

- Capture card: V4L2 index **6** ("Guermok USB3 Video"). Serial: **/dev/ttyUSB0** (CP2102) → Arduino pins → Switch. Both are single-owner: if a tool fails to open one, something else holds it (`fuser /dev/video6 /dev/ttyUSB0`).
- You can see and press: `tools/press.py <BUTTON|DPAD|none> [wait_s] [out.png]` presses then saves a 960x540 screenshot (default `recordings/screen.png`), which you can Read as an image. `tools/hold.py A 1.3` for hold-to-confirm buttons ("Play Again", "Try Again", "Main Menu" is B held).
- The Switch dims when idle; the first press only wakes it. Send `ZL` first.
- Menu map: main menu carousel … CPU Battle · Marathon · TETRIS 99 · Team Battle …. After returning from a game the cursor is on the bottom row: press UP. From a results screen, hold B for the main menu. A Nintendo "communication error" dialog closes with A and lands on the main menu; that match is void.
- Flashing: `tools/flash.sh` with the board plugged into the PC. The first attempt can fail with `butterfly_recv failed` (ModemManager grabs the bootloader port); retry.

## Operating the bot safely

- Start a bot in the background with `exec timeout 1800 .venv/bin/python -u -m tetris99.loop … > log 2>&1`, then follow the log.
- **Stop it with** `ps -eo pid,args | awk '/[p]ython -u -m tetris99/ {print $1}' | xargs -r kill`. A `pkill -f tetris99.loop` kills your own shell too, because your command line contains the pattern, and the rest of your command silently never runs.
- **A match is over only when** 30 s pass with no new `INFO #` line, or you look at the screen. `ignoring impossible reading` and `no spawn for 3 s` also appear mid-match. The bot has been wrongly stopped mid-match twice on log heuristics.
- Code edits take effect for every newly started bot process. **Do not edit code while a `run_matches.py` batch is running**: later matches in the batch would silently use the new code.
- 25 ms taps lose whole moves in battle mode. Keep `TAP_MS`/`GAP_MS` at 34.

## Changing vision thresholds

`vision/cells.py:classify_patch` (scalar) and `vision/board.py:classify_hsv` (vectorised) must give
identical answers. After any threshold change, check agreement and look at the diff over all saved
frames, and make sure only the cells you intended changed:

```python
import cv2, glob
from tetris99.config import Layout
from tetris99.vision.board import read_frame, SAMPLE_OFFSETS
L = Layout.load()
for p in sorted(glob.glob("recordings/*.png")):
    f = cv2.imread(p)
    if f is None or f.shape[:2] != (1080, 1920): continue
    print(p); print(read_frame(f, L).board_str())
```

Run it before and after, `diff` the outputs. `recordings/` holds real frames from every mode
(single-player, CPU Battle, online, KO screen, menus, soft drops, mismatches).

## Things that are easy to get wrong

- **Cold Clear aborts the whole process** (a Rust panic, not an exception) on an impossible piece sequence or a bag that contradicts the queue. Everything must pass `coldclear.valid_sequence()`; mid-game launches must pass the bag from `bag_boundary()`.
- Cold Clear thinks continuously on its own thread; `request_move` makes it answer as soon as it can. Requesting right after the previous answer gives depth-1 play.
- `cc_reset_async` with a request in flight returns a stale move. Relaunch instead (`Player._launch`).
- Weights cannot change on a running bot: relaunch.
- Plan steps from Cold Clear are in post-clear coordinates; use `coach.map_plan()`.
- After a hold, the piece in play is `Player.target[0]`, not `tracker.state.current`.
- A spawn reported while our own move is executing is the hold swap, not a new piece. A piece that is merely outside the known stack is not necessarily in play: a just-locked piece looks the same, only a **moving** piece is in play (`Player._rescue`).
- The screen lags the true board right after a line clear (no line-clear delay in Tetris 99); overlays (GO! banner, Targeting widget, attack lines, sparks, danger tint) are drawn over the board.
- Vision grid rows count from the top; engine rows count from the bottom.
- The ATmega32U4 serial RX buffer is 64 bytes: commands are paced, do not remove the pacing.

## Where to pick up

`docs/HISTORY.md` ends with "Open issues" and "Ideas not yet tried". The highest-value open items:

1. The source of the `out of step` events (a piece dropped by an input the bot did not intend), up to ~15 per long match.
2. The ~10 % board mismatches in battle mode, a third of them in column 9.
3. `garbage_rows()` never recognising real garbage arrivals.
4. Proper "match started / match over" detection instead of idle timers.

When you finish a piece of work, update `docs/HISTORY.md` (results, fixes, lessons) and, if a rule or
constant moved, the tables in `docs/ARCHITECTURE.md`.
