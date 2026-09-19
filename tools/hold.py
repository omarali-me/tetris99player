"""Hold one button on the Switch for a while (menus with hold-to-confirm need ~1 s).
    tools/hold.py A 1.3"""
import sys, time
from tetris99.config import find_serial_port
from tetris99.control.protocol import Button, Op
from tetris99.control.switch_controller import SwitchController

btn, secs = sys.argv[1].upper(), float(sys.argv[2]) if len(sys.argv) > 2 else 1.3
ctl = SwitchController(find_serial_port())
if not ctl.ping():
    sys.exit("the Arduino did not answer (even after re-aligning the framing)")
ctl._send(Op.SET, int(Button[btn])); ctl.ser.flush(); time.sleep(secs)
ctl._send(Op.SET, 0); ctl.ser.flush(); time.sleep(0.05)
ctl.ser.close()
print(f"held {btn} for {secs} s")
