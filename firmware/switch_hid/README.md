# Switch controller firmware

Presents the Arduino as a HORI Pokken Tournament Pro Pad, which the Switch accepts as a wired controller.

## Hardware
Any ATmega32U4 board: Arduino Leonardo, Pro Micro, Micro. The Uno will not work (its USB chip is not programmable from a sketch).

## Setup
1. Install the Arduino IDE (or `arduino-cli`).
2. Install [SwitchControlLibrary](https://github.com/celclow/SwitchControlLibrary) into `~/Arduino/libraries`.
3. Patch `boards.txt` for your board so the USB identity is the HORI pad:
   ```
   leonardo.build.vid=0x0f0d
   leonardo.build.pid=0x0092
   leonardo.build.usb_product="POKKEN CONTROLLER"
   leonardo.build.usb_manufacturer="HORI CO.,LTD."
   ```
   (The library README has the exact lines for each board.)
4. Flash `switch_hid.ino`.
5. On the Switch: System Settings → Controllers and Sensors → enable **Pro Controller Wired Communication**.
6. Plug the Arduino into the dock's USB port. Serial to the PC goes over the same cable, so the PC must be
   between the board and the dock: use a USB hub, or a Pro Micro with a second serial link. Simplest
   reliable setup is a board with two USB ports (Teensy 4.x with a USB host shield, or an Arduino Leonardo
   for the Switch plus a cheap USB-serial adapter on its hardware `Serial1` pins wired to the PC).

Note on step 6: the sketch uses `Serial` (USB CDC). When the board is plugged into the Switch that CDC port is
not reachable from the PC. For the real setup, change `Serial` to `Serial1` in the sketch and connect a
USB-to-TTL adapter to pins TX/RX; the PC then talks on that adapter's `/dev/ttyUSB0`.
