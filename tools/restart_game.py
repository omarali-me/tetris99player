"""From a Game Over or Stats screen in a Tetris 99 single-player mode, start a new game:
tap A (Game Over -> Stats), then HOLD A on "Try Again" (it is a hold-to-confirm, ~0.5 s)."""
import time
import serial
from tetris99.config import find_serial_port
from tetris99.control.protocol import Button, Op, encode

ser = serial.Serial(find_serial_port(), 115200, timeout=0.2); time.sleep(0.3)
def hold(btn, secs):
    ser.write(encode(Op.SET, int(btn))); ser.flush(); time.sleep(secs); ser.write(encode(Op.SET, 0)); ser.flush()
hold(Button.A, 0.15); time.sleep(2.0)
hold(Button.A, 1.3)
ser.close()
print("restart requested")
