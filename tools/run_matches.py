"""Play a series of online matches back to back and keep the evidence.

    .venv/bin/python tools/run_matches.py nosd sd nosd sd        # modes to play, in order
    .venv/bin/python tools/run_matches.py --show --from-menu sd sd   # with a live window, starting from the main menu
    .venv/bin/python tools/run_matches.py --pace 0.4 sd sd sd        # faster: 0.4 s per piece for the whole batch
    .venv/bin/python tools/run_matches.py sd@0.7 sd@0.4 sd@0         # a different pace per match, to compare

Start it while the Switch shows a results screen with "A: Play Again". For every match it holds A,
runs the bot until 30 s pass without a new piece, stops it, and saves the log and the results
screen under recordings/matches/."""
import subprocess, sys, time, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = ROOT / "recordings" / "matches"; OUT.mkdir(parents=True, exist_ok=True)
# 25 ms taps were tried in battle mode on 2026-09-19 and whole moves went missing; 34 ms is the floor.
_FAST = ["--early-request", "--settle-frames", "2", "--pace", "0"]   # a later --pace overrides the runner's default
MODES = {"fast": _FAST,
         # no T-spins: clear lines, stay low, hard drops only, full speed
         "clean": ["--weights", "config/weights_clean.json", "--no-survival", "--no-softdrop", *_FAST],
         # same personality but allowed to soft-drop (tucks)
         "cleansd": ["--weights", "config/weights_clean.json", "--no-survival", *_FAST],
         "early": ["--early-request"],
         "sd": [], "nosd": ["--no-softdrop"], "attack": ["--no-survival"], "random": ["--targeting", "none"]}
FIRST_PRESS = {"hold": ("hold.py", ["A", "1.3"]), "tap": ("hold.py", ["A", "0.15"])}


def pieces(log: Path) -> int:
    return sum(1 for l in open(log, errors="ignore") if "INFO #" in l)


SHOW = False
PACE = 0.7     # seconds per piece; lower is faster, 0 = as fast as inputs allow


def play(tag: str, extra: list[str], press: str = "hold", pace: float | None = None) -> dict:
    log = OUT / f"{tag}.log"
    bot = None
    for attempt in range(2):
        script, a = FIRST_PRESS[press]
        subprocess.run([PY, str(ROOT / "tools" / script), *a], cwd=ROOT, check=False)
        press = "hold"
        bot = subprocess.Popen([PY, "-u", "-m", "tetris99.loop", "--source", "6", "--output", "serial", "--pace", str(PACE if pace is None else pace),
                                *(["--show"] if SHOW else []), *extra],
                               cwd=ROOT, stdout=open(log, "w"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 200 and bot.poll() is None and "bot launched" not in log.read_text(errors="ignore"):
            time.sleep(2)
        if "bot launched" in log.read_text(errors="ignore"):
            break
        bot.terminate(); bot.wait(timeout=10)      # match never started: try the button again
    last, idle_since, t_start = -1, time.time(), time.time()
    while bot.poll() is None and time.time() - t_start < 1500:
        n = pieces(log)
        if n != last:
            last, idle_since = n, time.time()
        if time.time() - idle_since > 30:
            break
        time.sleep(3)
    bot.terminate()
    try: bot.wait(timeout=10)
    except subprocess.TimeoutExpired: bot.kill()
    time.sleep(8)                                   # let the results screen settle
    shot = OUT / f"{tag}.png"
    subprocess.run([PY, str(ROOT / "tools/press.py"), "none", "0", str(shot)], cwd=ROOT, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    text = log.read_text(errors="ignore")
    times = re.findall(r"(\d\d):(\d\d):(\d\d),\d+ INFO #", text)
    secs = 0
    if times:
        a, b = times[0], times[-1]
        secs = (int(b[0]) * 3600 + int(b[1]) * 60 + int(b[2])) - (int(a[0]) * 3600 + int(a[1]) * 60 + int(a[2]))
    eff = PACE if pace is None else pace
    if "--pace" in extra and pace is None:          # the mode sets its own pace (argparse takes the last one)
        eff = float(extra[len(extra) - 1 - extra[::-1].index("--pace") + 1])
    return {"tag": tag, "pace": eff, "pieces": pieces(log), "seconds": secs,
            "pieces_per_s": round(pieces(log) / secs, 2) if secs else 0, "mismatches": text.count("DIVERGED"),
            "locked_in_softdrop": text.count("locked during a soft drop"), "stalls": text.count("no spawn for 3 s")}


if __name__ == "__main__":
    args = sys.argv[1:]
    SHOW = "--show" in args                      # open the bot's live window (capture feed + what it sees)
    if "--pace" in args:                         # default pace for the whole batch
        i = args.index("--pace"); PACE = float(args[i + 1]); del args[i:i + 2]
    from_menu = "--from-menu" in args          # first match: tap A on the TETRIS 99 tile instead of holding Play Again
    order = [a for a in args if not a.startswith("--")] or ["sd", "sd", "sd"]
    stamp = time.strftime("%H%M")
    # The Switch dims its screen when idle and the first input only wakes it. ZL does nothing in the
    # menus or on a results screen, so use it as the wake-up press.
    subprocess.run([PY, str(ROOT / "tools/hold.py"), "ZL", "0.15"], cwd=ROOT, check=False, stdout=subprocess.DEVNULL)
    time.sleep(1.0)
    for i, token in enumerate(order, 1):
        mode, _, p = token.partition("@")        # "sd@0.4" = this match at 0.4 s per piece
        r = play(f"{stamp}_{i}_{mode}" + (f"_p{p}" if p else ""), MODES[mode],
                 press="tap" if (from_menu and i == 1) else "hold", pace=float(p) if p else None)
        print(r, flush=True)
    print("ALL DONE", flush=True)
