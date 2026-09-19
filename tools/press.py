"""Press one controller input on the Switch and save what the screen shows afterwards.
    tools/press.py A            tools/press.py DOWN          tools/press.py none   (just look)
Used for stepping through menus while watching the capture feed."""
import sys, time
import cv2, serial
from tetris99.capture import CaptureCard
from tetris99.config import find_serial_port
from tetris99.control.protocol import Button, Hat, Op, encode

what = sys.argv[1].upper() if len(sys.argv) > 1 else "NONE"
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 1.2
out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/claude-1000/-home-omar-tetris99player/3c4c597d-3cf2-49dd-98a7-4fe14b0813e6/scratchpad/screen.png"
if what != "NONE":
    ser = serial.Serial(find_serial_port(), 115200, timeout=0.5); time.sleep(0.2)
    if what in Hat.__members__:
        ser.write(encode(Op.HAT, int(Hat[what]))); ser.write(encode(Op.WAIT, 80)); ser.write(encode(Op.HAT, int(Hat.CENTER)))
    else:
        ser.write(encode(Op.SET, int(Button[what]))); ser.write(encode(Op.WAIT, 150)); ser.write(encode(Op.SET, 0))
    ser.flush(); time.sleep(wait); ser.close()
src = CaptureCard(6); it = src.frames()
for _ in range(6): f = next(it)
src.close()
cv2.imwrite(out, cv2.resize(f, (960, 540)))
print("pressed", what)
