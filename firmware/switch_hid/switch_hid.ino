// Switch controller emulator: presents as a HORI Pokken Tournament Pro Pad (VID 0x0F0D, PID 0x0092)
// and takes button state from the PC over serial. See tetris99/control/protocol.py for the wire format.
//
// Board: Arduino Leonardo / Pro Micro (ATmega32U4) or Teensy 2.0.
// Requires the SwitchControlLibrary (https://github.com/celclow/SwitchControlLibrary) and its
// boards.txt patch that sets the USB VID/PID — see firmware/switch_hid/README.md.

#include <SwitchControlLibrary.h>

enum Op : uint8_t { OP_SET = 1, OP_PRESS = 2, OP_HAT = 3, OP_RELEASE = 4, OP_WAIT = 5, OP_PING = 6, OP_LSTICK = 7, OP_RSTICK = 8 };

const uint16_t PRESS_MS = 34;
const uint8_t QUEUE_LEN = 64;

struct Cmd { uint8_t op; uint16_t arg; };
Cmd queue_[QUEUE_LEN];
uint8_t qHead = 0, qTail = 0;
uint32_t busyUntil = 0;   // millis() until which the next command must wait
uint16_t pressMask = 0;   // buttons currently held by a PRESS
uint32_t pressUntil = 0;

void applyButtons(uint16_t mask) {
  for (uint8_t b = 0; b < 14; b++) {
    if (mask & (1 << b)) SwitchControlLibrary().pressButton(1 << b);
    else SwitchControlLibrary().releaseButton(1 << b);
  }
  SwitchControlLibrary().sendReport();
}

void applyHat(uint8_t hat) {
  // hat is the report value 0..7 for the eight directions, 8 = centred
  SwitchControlLibrary().moveHat(hat);
  SwitchControlLibrary().sendReport();
}

void releaseAll() {
  applyButtons(0);
  applyHat(8);
  SwitchControlLibrary().moveLeftStick(128, 128);
  SwitchControlLibrary().moveRightStick(128, 128);
  SwitchControlLibrary().sendReport();
  pressMask = 0;
}

void setup() {
  Serial.begin(115200);
  releaseAll();
}

void enqueue(uint8_t op, uint16_t arg) {
  uint8_t next = (qTail + 1) % QUEUE_LEN;
  if (next == qHead) return; // drop on overflow
  queue_[qTail] = {op, arg};
  qTail = next;
}

void loop() {
  // read complete 3-byte commands
  while (Serial.available() >= 3) {
    uint8_t op = Serial.read();
    uint16_t arg = Serial.read() | (Serial.read() << 8);
    if (op == OP_PING) { Serial.write(OP_PING); continue; }
    enqueue(op, arg);
  }

  uint32_t now = millis();

  if (pressMask && (int32_t)(now - pressUntil) >= 0) {
    applyButtons(0);
    pressMask = 0;
  }

  if (qHead != qTail && (int32_t)(now - busyUntil) >= 0) {
    Cmd c = queue_[qHead];
    qHead = (qHead + 1) % QUEUE_LEN;
    switch (c.op) {
      case OP_SET:     applyButtons(c.arg); break;
      case OP_PRESS:   applyButtons(c.arg); pressMask = c.arg; pressUntil = now + PRESS_MS; busyUntil = pressUntil; break;
      case OP_HAT:     applyHat((uint8_t)c.arg); break;
      case OP_RELEASE: releaseAll(); break;
      case OP_WAIT:    busyUntil = now + c.arg; break;
      case OP_LSTICK:  SwitchControlLibrary().moveLeftStick(c.arg & 0xff, c.arg >> 8); SwitchControlLibrary().sendReport(); break;
      case OP_RSTICK:  SwitchControlLibrary().moveRightStick(c.arg & 0xff, c.arg >> 8); SwitchControlLibrary().sendReport(); break;
    }
  }
}
