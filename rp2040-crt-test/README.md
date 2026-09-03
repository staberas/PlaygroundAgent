# RP2040 CRT Composite Test

Minimal PAL-ish monochrome composite test pattern generator for the Pro Micro RP2040 board shown in the project notes.

## Wiring

This version uses two adjacent GPIOs to form a simple 2-bit resistor DAC:

- GP8 -> 330 ohm -> CRT VIDEO IN
- GP9 -> 1 kohm -> CRT VIDEO IN
- GND -> CRT VIDEO GND

The resistor values are intentionally conservative for initial bring-up. If the CRT input is very forgiving, you can also test one GPIO directly, but the two-resistor network gives separate sync/black/white levels.

## Board pins

Based on the provided pinout image, GP8 and GP9 are both broken out on the left side near the bottom of the board.

## Output

The sketch cycles through:

1. black raster
2. white raster
3. horizontal bars
4. vertical bars
5. checkerboard
6. border + crosshair
7. HELLO WORLD / PAL 50HZ screen

The generator targets PAL-like 625/50 monochrome timing.

## Arduino setup

Use an RP2040 Arduino core that supports `rp2040`/Pico SDK style timing. The sketch intentionally avoids external graphics libraries.

## Important

This is a diagnostic generator, not a standards-certified video encoder. Do not connect any CRT high-voltage circuitry to the microcontroller. Only connect the low-voltage composite/video input and ground.
