#!/usr/bin/env bash
# Compile firmware/switch_hid with the HORI Pokken pad identity and flash an ATmega32U4 board.
#   tools/flash.sh [/dev/ttyACM0]
# If the upload fails with "butterfly_recv failed", just run it again: ModemManager sometimes
# grabs the bootloader's port for a moment. Permanent fix: sudo systemctl disable --now ModemManager
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-/dev/ttyACM0}"
CLI=tools/bin/arduino-cli
OUT="$(mktemp -d)"
"$CLI" compile --fqbn arduino:avr:leonardo \
  --build-property "build.vid=0x0f0d" --build-property "build.pid=0x0092" \
  --build-property 'build.usb_product="POKKEN CONTROLLER"' \
  --build-property 'build.usb_manufacturer="HORI CO.,LTD."' \
  --output-dir "$OUT" firmware/switch_hid
"$CLI" upload --fqbn arduino:avr:leonardo -p "$PORT" --input-dir "$OUT"
sleep 3
lsusb | grep -i -E "0f0d:0092" && echo "OK: board enumerates as the HORI pad"
