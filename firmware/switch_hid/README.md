# Switch controller firmware

Presents an ATmega32U4 board (Arduino Leonardo, Micro, Pro Micro) as a HORI Pokken Tournament Pro
Pad, which the Switch accepts as a wired controller. No external Arduino library is needed: the
sketch subclasses the core's HID class and appends the pad's report descriptor.

## Build and flash
```
tools/flash.sh /dev/ttyACM0
```
This uses `tools/bin/arduino-cli` with the `arduino:avr` core and passes the identity as build
properties (VID 0x0F0D, PID 0x0092, "HORI CO.,LTD." / "POKKEN CONTROLLER"), so `boards.txt` is not
edited. One-time setup:
```
curl -fsSL https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz | tar -xz -C tools/bin arduino-cli
tools/bin/arduino-cli core update-index && tools/bin/arduino-cli core install arduino:avr
```
Serial permissions: a udev rule giving mode 0666 to tty devices of vendors 2341 (Arduino
bootloader), 0f0d (the flashed board) and 10c4 (CP2102) survives the re-enumeration that happens
during flashing; a one-off chmod does not.

## Talking to it
Commands (3 bytes, see `tetris99/control/protocol.py`) are accepted on both serial ports:
- `Serial` (USB CDC): when the board is plugged into the PC, for bench tests. It appears as
  `/dev/ttyACM0` and as a joystick under `/dev/input/by-id/`.
- `Serial1` (pins TX/RX): when the board's USB is plugged into the Switch dock. Wire a USB-TTL
  adapter: adapter TX -> board RX, adapter RX -> board TX, GND -> GND. Do not connect VCC.

On the Switch enable System Settings -> Controllers and Sensors -> Pro Controller Wired Communication.

## Recovery
The bootloader is untouched and still identifies as Arduino. If a bad sketch ever breaks the USB
serial port, double-tap the reset button: the board stays in the bootloader for 8 seconds and
`tools/flash.sh` can upload during that window.
