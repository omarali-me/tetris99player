// Switch controller emulator for ATmega32U4 boards (Leonardo / Micro / Pro Micro).
// Presents as a HORI Pokken Tournament Pro Pad (VID 0x0F0D, PID 0x0092) and takes button state
// from the PC. Wire format: tetris99/control/protocol.py (3 bytes: opcode, uint16 little-endian).
//
// Commands are accepted on BOTH serial ports:
//   Serial1 (pins TX/RX, via a USB-TTL adapter) - used when the board's USB is plugged into the Switch
//   Serial  (USB CDC)                            - handy for bench testing from the PC
// No external library: the gamepad is a subclass of the core's HID class with our own descriptor.
// Build with the HORI identity:  see firmware/switch_hid/README.md (arduino-cli --build-property ...).

#include <HID.h>

static const uint8_t PAD_DESCRIPTOR[] PROGMEM = {
  0x05, 0x01,       // USAGE_PAGE (Generic Desktop)
  0x09, 0x05,       // USAGE (Game Pad)
  0xa1, 0x01,       // COLLECTION (Application)
  0x15, 0x00,       //   LOGICAL_MINIMUM (0)
  0x25, 0x01,       //   LOGICAL_MAXIMUM (1)
  0x35, 0x00,       //   PHYSICAL_MINIMUM (0)
  0x45, 0x01,       //   PHYSICAL_MAXIMUM (1)
  0x75, 0x01,       //   REPORT_SIZE (1)
  0x95, 0x10,       //   REPORT_COUNT (16)
  0x05, 0x09,       //   USAGE_PAGE (Button)
  0x19, 0x01,       //   USAGE_MINIMUM (1)
  0x29, 0x10,       //   USAGE_MAXIMUM (16)
  0x81, 0x02,       //   INPUT (Data,Var,Abs)          16 button bits
  0x05, 0x01,       //   USAGE_PAGE (Generic Desktop)
  0x25, 0x07,       //   LOGICAL_MAXIMUM (7)
  0x46, 0x3b, 0x01, //   PHYSICAL_MAXIMUM (315)
  0x75, 0x04,       //   REPORT_SIZE (4)
  0x95, 0x01,       //   REPORT_COUNT (1)
  0x65, 0x14,       //   UNIT (degrees)
  0x09, 0x39,       //   USAGE (Hat Switch)
  0x81, 0x42,       //   INPUT (Data,Var,Abs,Null)     hat nibble
  0x65, 0x00,       //   UNIT (none)
  0x95, 0x01,       //   REPORT_COUNT (1)
  0x81, 0x01,       //   INPUT (Const)                 padding nibble
  0x26, 0xff, 0x00, //   LOGICAL_MAXIMUM (255)
  0x46, 0xff, 0x00, //   PHYSICAL_MAXIMUM (255)
  0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x35, // USAGE X, Y, Z, Rz
  0x75, 0x08,       //   REPORT_SIZE (8)
  0x95, 0x04,       //   REPORT_COUNT (4)
  0x81, 0x02,       //   INPUT (Data,Var,Abs)          LX LY RX RY
  0x06, 0x00, 0xff, //   USAGE_PAGE (Vendor)
  0x09, 0x20,       //   USAGE (32)
  0x95, 0x01,       //   REPORT_COUNT (1)
  0x81, 0x02,       //   INPUT (Data,Var,Abs)          vendor byte
  0x0a, 0x21, 0x26, //   USAGE (9761)
  0x95, 0x08,       //   REPORT_COUNT (8)
  0x91, 0x02,       //   OUTPUT (Data,Var,Abs)
  0xc0              // END_COLLECTION
};

struct PadReport {
  uint16_t buttons;
  uint8_t hat;
  uint8_t lx, ly, rx, ry;
  uint8_t vendor;
} __attribute__((packed));

class Pad_ : public HID_ {
 public:
  int send(const PadReport& r) { return USB_Send(pluggedEndpoint | TRANSFER_RELEASE, &r, sizeof(r)); }
};

Pad_ Pad;
HIDSubDescriptor padNode(PAD_DESCRIPTOR, sizeof(PAD_DESCRIPTOR));
PadReport report = {0, 8, 128, 128, 128, 128, 0};

enum Op : uint8_t { OP_SET = 1, OP_PRESS = 2, OP_HAT = 3, OP_RELEASE = 4, OP_WAIT = 5, OP_PING = 6, OP_LSTICK = 7, OP_RSTICK = 8 };

const uint16_t PRESS_MS = 34;
const uint8_t QUEUE_LEN = 64;
struct Cmd { uint8_t op; uint16_t arg; };
Cmd queue_[QUEUE_LEN];
uint8_t qHead = 0, qTail = 0;
uint32_t busyUntil = 0;
uint16_t pressMask = 0;
uint32_t pressUntil = 0;
uint32_t lastSend = 0;

void sendNow() { Pad.send(report); lastSend = millis(); }

void releaseAll() {
  report.buttons = 0; report.hat = 8;
  report.lx = report.ly = report.rx = report.ry = 128;
  pressMask = 0;
  sendNow();
}

void enqueue(uint8_t op, uint16_t arg) {
  uint8_t next = (qTail + 1) % QUEUE_LEN;
  if (next == qHead) return;  // drop on overflow
  queue_[qTail] = {op, arg};
  qTail = next;
}

void readFrom(Stream& s) {
  while (s.available() >= 3) {
    uint8_t op = s.read();
    uint16_t arg = s.read(); arg |= (uint16_t)s.read() << 8;
    if (op == OP_PING) { s.write((uint8_t)OP_PING); continue; }
    enqueue(op, arg);
  }
}

void setup() {
  Pad.AppendDescriptor(&padNode);
  Serial.begin(115200);
  Serial1.begin(115200);
  releaseAll();
}

void loop() {
  readFrom(Serial1);
  readFrom(Serial);

  uint32_t now = millis();
  if (pressMask && (int32_t)(now - pressUntil) >= 0) {
    report.buttons &= ~pressMask;
    pressMask = 0;
    sendNow();
  }
  if (qHead != qTail && (int32_t)(now - busyUntil) >= 0) {
    Cmd c = queue_[qHead];
    qHead = (qHead + 1) % QUEUE_LEN;
    switch (c.op) {
      case OP_SET:     report.buttons = c.arg; sendNow(); break;
      case OP_PRESS:   report.buttons |= c.arg; pressMask = c.arg; pressUntil = now + PRESS_MS; busyUntil = pressUntil; sendNow(); break;
      case OP_HAT:     report.hat = c.arg > 8 ? 8 : (uint8_t)c.arg; sendNow(); break;
      case OP_RELEASE: releaseAll(); break;
      case OP_WAIT:    busyUntil = now + c.arg; break;
      case OP_LSTICK:  report.lx = c.arg & 0xff; report.ly = c.arg >> 8; sendNow(); break;
      case OP_RSTICK:  report.rx = c.arg & 0xff; report.ry = c.arg >> 8; sendNow(); break;
    }
  }
  // keep-alive: repeat the current state every 8 ms so the host always has a fresh report
  if (now - lastSend >= 8) sendNow();
}
