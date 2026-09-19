"""From a Game Over or Stats screen in a Tetris 99 single-player mode, start a new game:
tap A (Game Over -> Stats), then HOLD A on "Try Again" (it is a hold-to-confirm, ~0.5 s)."""
import subprocess, sys, time
here = __file__.rsplit("/", 1)[0]
subprocess.run([sys.executable, f"{here}/hold.py", "A", "0.15"], check=True); time.sleep(2.0)
subprocess.run([sys.executable, f"{here}/hold.py", "A", "1.3"], check=True)
print("restart requested")
