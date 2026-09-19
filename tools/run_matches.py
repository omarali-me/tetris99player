"""Play a series of online matches back to back and keep the evidence.

    .venv/bin/python tools/run_matches.py nosd sd nosd sd        # modes to play, in order

Start it while the Switch shows a results screen with "A: Play Again". For every match it holds A,
runs the bot until 30 s pass without a new piece, stops it, and saves the log and the results
screen under recordings/matches/."""
import subprocess, sys, time, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = ROOT / "recordings" / "matches"; OUT.mkdir(parents=True, exist_ok=True)
MODES = {"sd": [], "nosd": ["--no-softdrop"], "attack": ["--no-survival"], "random": ["--targeting", "none"]}
FIRST_PRESS = {"hold": ("hold.py", ["A", "1.3"]), "tap": ("hold.py", ["A", "0.15"])}


def pieces(log: Path) -> int:
    return sum(1 for l in open(log, errors="ignore") if "INFO #" in l)


def play(tag: str, extra: list[str], press: str = "hold") -> dict:
    log = OUT / f"{tag}.log"
    bot = None
    for attempt in range(2):
        script, a = FIRST_PRESS[press]
        subprocess.run([PY, str(ROOT / "tools" / script), *a], cwd=ROOT, check=False)
        press = "hold"
        bot = subprocess.Popen([PY, "-u", "-m", "tetris99.loop", "--source", "6", "--output", "serial", "--pace", "0.7", *extra],
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
    return {"tag": tag, "pieces": pieces(log), "seconds": secs, "mismatches": text.count("DIVERGED"),
            "locked_in_softdrop": text.count("locked during a soft drop"), "stalls": text.count("no spawn for 3 s")}


if __name__ == "__main__":
    args = sys.argv[1:]
    from_menu = "--from-menu" in args          # first match: tap A on the TETRIS 99 tile instead of holding Play Again
    order = [a for a in args if not a.startswith("--")] or ["sd", "sd", "sd"]
    stamp = time.strftime("%H%M")
    for i, mode in enumerate(order, 1):
        r = play(f"{stamp}_{i}_{mode}", MODES[mode], press="tap" if (from_menu and i == 1) else "hold")
        print(r, flush=True)
    print("ALL DONE", flush=True)
