/*
 * RP2040 PAL-ish monochrome CRT diagnostic generator
 * Target: Pro Micro RP2040
 *
 * GP8 -- 330R --+
 *               +---- CRT VIDEO IN
 * GP9 -- 1K ----+
 * GND ---------------- CRT VIDEO GND
 *
 * GP8/GP9 are adjacent broken-out pins on the supplied board pinout.
 *
 * This deliberately starts with a simple software raster generator.
 * Once the CRT is confirmed alive, move the timing engine to PIO for a
 * framebuffer/text implementation with tighter timing.
 */

#include <Arduino.h>

static constexpr uint8_t VIDEO_A = 8;
static constexpr uint8_t VIDEO_B = 9;

// PAL-ish timing, microseconds.
static constexpr uint32_t LINE_US = 64;
static constexpr uint32_t HSYNC_US = 5;
static constexpr uint32_t BACK_PORCH_US = 6;
static constexpr uint32_t ACTIVE_US = 52;
static constexpr uint32_t FRONT_PORCH_US = 1;

static constexpr int LINES = 312;       // one non-interlaced 50 Hz-ish field
static constexpr int VISIBLE_FIRST = 32;
static constexpr int VISIBLE_LAST = 287;

// Logical levels produced by the two resistor branches.
// We only need three useful monochrome levels.
static inline void levelSync() {
  digitalWrite(VIDEO_A, LOW);
  digitalWrite(VIDEO_B, LOW);
}

static inline void levelBlack() {
  digitalWrite(VIDEO_A, LOW);
  digitalWrite(VIDEO_B, HIGH);
}

static inline void levelWhite() {
  digitalWrite(VIDEO_A, HIGH);
  digitalWrite(VIDEO_B, HIGH);
}

static inline void waitUs(uint32_t us) {
  delayMicroseconds(us);
}

static void hsync() {
  levelSync();
  waitUs(HSYNC_US);
  levelBlack();
  waitUs(BACK_PORCH_US);
}

static void finishLine(uint32_t activeUsed) {
  levelBlack();
  if (activeUsed < ACTIVE_US) waitUs(ACTIVE_US - activeUsed);
  waitUs(FRONT_PORCH_US);
}

static bool glyphPixel(char c, int x, int y) {
  // Tiny purpose-built 5x7 font for the diagnostic strings.
  // Each glyph is five columns, LSB at the top.
  struct Glyph { char c; uint8_t col[5]; };
  static const Glyph font[] = {
    {'A',{0x7E,0x09,0x09,0x09,0x7E}}, {'C',{0x3E,0x41,0x41,0x41,0x22}},
    {'D',{0x7F,0x41,0x41,0x22,0x1C}}, {'E',{0x7F,0x49,0x49,0x49,0x41}},
    {'H',{0x7F,0x08,0x08,0x08,0x7F}}, {'L',{0x7F,0x40,0x40,0x40,0x40}},
    {'O',{0x3E,0x41,0x41,0x41,0x3E}}, {'P',{0x7F,0x09,0x09,0x09,0x06}},
    {'R',{0x7F,0x09,0x19,0x29,0x46}}, {'T',{0x01,0x01,0x7F,0x01,0x01}},
    {'W',{0x3F,0x40,0x38,0x40,0x3F}}, {'Z',{0x61,0x51,0x49,0x45,0x43}},
    {'0',{0x3E,0x45,0x49,0x51,0x3E}}, {'2',{0x62,0x51,0x49,0x49,0x46}},
    {'4',{0x18,0x14,0x12,0x7F,0x10}}, {'5',{0x4F,0x49,0x49,0x49,0x31}},
    {'6',{0x3E,0x49,0x49,0x49,0x30}}, {' ',{0,0,0,0,0}}
  };
  for (const auto &g : font) {
    if (g.c == c) return x >= 0 && x < 5 && y >= 0 && y < 7 && ((g.col[x] >> y) & 1);
  }
  return false;
}

static bool textPixel(const char *s, int px, int py, int scale) {
  if (py < 0 || py >= 7 * scale || px < 0) return false;
  int cell = 6 * scale;
  int ci = px / cell;
  if (!s[ci]) return false;
  int gx = (px % cell) / scale;
  int gy = py / scale;
  if (gx >= 5) return false;
  return glyphPixel(s[ci], gx, gy);
}

static bool patternPixel(int pattern, int x, int y) {
  switch (pattern) {
    case 0: return false;                         // black
    case 1: return true;                          // white
    case 2: return ((y / 24) & 1) == 0;          // horizontal bars
    case 3: return ((x / 32) & 1) == 0;          // vertical bars
    case 4: return (((x / 24) + (y / 24)) & 1) == 0; // checkerboard
    case 5: {                                     // border + crosshair
      bool border = x < 6 || x >= 250 || y < 6 || y >= 250;
      bool cross = (x >= 126 && x <= 130) || (y >= 126 && y <= 130);
      return border || cross;
    }
    default: {                                    // text card
      if (textPixel("HELLO WORLD", x - 28, y - 70, 3)) return true;
      if (textPixel("PAL 50HZ", x - 52, y - 125, 2)) return true;
      if (textPixel("RP2040 CRT", x - 34, y - 165, 2)) return true;
      return x < 4 || x > 251 || y < 4 || y > 251;
    }
  }
}

static void activePatternLine(int pattern, int y) {
  // 256 coarse horizontal samples distributed across ~52 us.
  // Direct GPIO writes/delay granularity means this is intentionally a
  // bring-up pattern rather than precision broadcast video.
  const int samples = 64;
  for (int s = 0; s < samples; ++s) {
    int x = s * 4;
    patternPixel(pattern, x, y) ? levelWhite() : levelBlack();
    // Approx 52us / 64 samples. Busy work provides the sub-us-ish spacing;
    // exact timing depends on Arduino core/clock.
    for (volatile int n = 0; n < 10; ++n) { __asm volatile("nop"); }
  }
  levelBlack();
}

static void frame(int pattern) {
  // Simplified vertical sync: several long low periods. This is deliberately
  // non-interlaced PAL-ish timing for CRT identification/bring-up.
  for (int line = 0; line < LINES; ++line) {
    if (line >= 4 && line < 9) {
      levelSync();
      waitUs(58);
      levelBlack();
      waitUs(6);
      continue;
    }

    hsync();
    if (line >= VISIBLE_FIRST && line <= VISIBLE_LAST) {
      activePatternLine(pattern, line - VISIBLE_FIRST);
      // activePatternLine consumes approximately the active interval.
      waitUs(FRONT_PORCH_US);
    } else {
      levelBlack();
      waitUs(ACTIVE_US + FRONT_PORCH_US);
    }
  }
}

void setup() {
  pinMode(VIDEO_A, OUTPUT);
  pinMode(VIDEO_B, OUTPUT);
  levelBlack();
}

void loop() {
  static int pattern = 0;
  // About five seconds at ~50 fields/s.
  for (int i = 0; i < 250; ++i) frame(pattern);
  pattern = (pattern + 1) % 7;
}
