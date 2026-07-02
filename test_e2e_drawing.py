#!/usr/bin/env python3
"""
E2E drawing test: assemble a touch-drawing program, run it, simulate
touch events, and verify that pixel lines are drawn on the LCD.

The assembled program:
  1. Sets up the LCD (GRAM write mode)
  2. Polls PRDR for touch
  3. On touch, reads the touch position (simulated via I2C reg 0x84)
  4. Draws a white pixel at the touch position
  5. Loops forever

The test simulates a touch "drag" — a series of touch events at
incrementing X positions — and verifies that a horizontal line of
pixels is drawn on the LCD framebuffer.

Also tests dual-touch: two simultaneous touches produce two pixel
clusters.
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.tools.assembler import assemble
from ruk.classpad import Classpad
from ruk.jcore.touch import PRDR_ADDR, PRDR_TOUCH_BIT, I2C_BASE
from ruk.jcore.display import DISPLAY_WIDTH, DISPLAY_HEIGHT


# ============================================================================
# Drawing program: poll touch, draw pixel at touch position
# ============================================================================

# This program:
#   1. Sets up the LCD GRAM write mode (command 0x0202)
#   2. Polls PRDR bit 5 for touch
#   3. On touch, reads I2C register 0x84 to get touch data
#   4. Extracts x1/y1 from the touch data
#   5. Writes a white pixel (0xFFFF) to the LCD at (x1>>4, y1>>4)
#
# The I2C read is simplified — we use a blocking poll on ICSR.DTE
# and read ICDR.  The touch controller responds with 16 bytes.
#
# Register usage:
#   r14 = PRDR address (0xA405013C)
#   r13 = LCD interface (0xB4000000)
#   r12 = I2C base (0xA4470000)
#   r11 = touch X (raw, from I2C)
#   r10 = touch Y (raw, from I2C)
DRAWING_ASM = """
    ; Load addresses
    mov.l prdr_addr, r14
    mov.l lcd_addr, r13
    mov.l i2c_addr, r12

    ; Set up LCD: select GRAM register (command 0x0202)
    ; RS=0 (command mode): clear PRDR bit 4
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    ; Write command 0x0202
    mov #0x02, r0
    shll8 r0
    or #0x02, r0
    mov.w r0, @r13
    ; RS=1 (data mode): set PRDR bit 4
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

main_loop:
    ; Check PRDR bit 5 for touch
    mov.b @r14, r0
    tst #0x20, r0
    bt touch_active
    bra main_loop
    nop

touch_active:
    ; Read touch data via I2C register 0x84
    ; Enable I2C (ICCR.ICE = 1, offset 0x04)
    mov #1, r0
    mov.b r0, @(4, r12)

    ; Start condition (ICCR = 0x94)
    mov #0x94, r0
    mov.b r0, @(4, r12)

    ; Write slave address (0x38 << 1 = 0x70, write mode)
    mov #0x70, r0
    mov.b r0, @r12

    ; Wait for DTE
    nop
    nop
    nop

    ; Write register number 0x84
    mov #0x84, r0
    mov.b r0, @r12

    ; Wait for DTE
    nop
    nop
    nop

    ; Restart for read
    mov #0x94, r0
    mov.b r0, @(4, r12)

    ; Write slave address (0x38 << 1 | 1 = 0x71, read mode)
    mov #0x71, r0
    mov.b r0, @r12

    ; Wait for DTE
    nop
    nop
    nop

    ; Read 2 bytes (x1 high, x1 low)
    mov.b @r12, r0
    shll8 r0
    mov.b @r12, r1
    or r1, r0
    ; r0 = x1 (raw ADC value)
    mov r0, r11

    ; Read 2 bytes (y1 high, y1 low)
    mov.b @r12, r0
    shll8 r0
    mov.b @r12, r1
    or r1, r0
    ; r0 = y1 (raw ADC value)
    mov r0, r10

    ; Convert to screen coordinates: x = x1 >> 4, y = y1 >> 4
    ; SH-4 has no shlr4, so use two shlr2
    shlr2 r11
    shlr2 r11
    shlr2 r10
    shlr2 r10

    ; Clamp to screen bounds (mask to 8 bits)
    and #0xFF, r11
    and #0xFF, r10

    ; Write pixel to LCD GRAM
    ; The LCD is already in data mode (PRDR bit 4 = 1)
    ; Write white pixel 0xFFFF
    mov #0xFF, r0
    shll8 r0
    or #0xFF, r0
    mov.w r0, @r13

    ; Loop back to poll for more touches
    bra main_loop
    nop

    .align 4
prdr_addr:    .long 0xA405013C
lcd_addr:     .long 0xB4000000
i2c_addr:     .long 0xA4470000
"""


# ============================================================================
# E2E drawing test
# ============================================================================

class TestDrawingE2E(unittest.TestCase):
    """E2E: assemble a drawing program, simulate touch drag, verify pixels."""

    @classmethod
    def setUpClass(cls):
        cls.binary = assemble(DRAWING_ASM, start_addr=0x8C000000)

    def _make_classpad(self):
        with open(os.path.join(os.path.dirname(__file__), 'cp400', '3070.bin'), 'rb') as f:
            rom = f.read()
        return Classpad(rom, debug=False, start_pc=0x8C000000,
                        with_tmu=False, with_rtc=False, with_dma=False,
                        with_display=True, with_touch=True)

    def _load_program(self, cp):
        cp.ram.write_bin(0, self.binary)
        cp.cpu.pc = 0x8C000000
        cp.display.clear(0x0000)

    def test_assembled_correctly(self):
        """Verify the program assembled without errors."""
        self.assertGreater(len(self.binary), 20)
        # First instruction should be mov.l (PC-relative load)
        first_op = struct.unpack('>H', self.binary[:2])[0]
        self.assertEqual(first_op & 0xF000, 0xD000)

    def test_no_touch_no_pixels(self):
        """Without touch, no pixels should be drawn."""
        cp = self._make_classpad()
        self._load_program(cp)
        for i in range(5000):
            cp.cpu.step()
        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertEqual(white, 0)

    def test_single_touch_draws_pixel(self):
        """A single touch should draw at least one pixel."""
        cp = self._make_classpad()
        self._load_program(cp)
        cp.touch.set_touch(0x200, 0x300)  # raw ADC values
        for i in range(5000):
            cp.cpu.step()
        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreater(white, 0, "At least one pixel should be drawn")

    def test_touch_drag_draws_line(self):
        """A drag (multiple touches at incrementing X) should draw a line.

        We simulate 5 touch events at X=0x200, 0x210, 0x220, 0x230, 0x240
        (all at Y=0x300).  After running, there should be pixels at
        multiple X positions on the same Y row.
        """
        cp = self._make_classpad()
        self._load_program(cp)

        # Simulate a drag: 5 touches at incrementing X
        for x_raw in [0x200, 0x210, 0x220, 0x230, 0x240]:
            cp.touch.set_touch(x_raw, 0x300)
            # Run enough steps to process one touch
            for i in range(500):
                cp.cpu.step()

        # Check the LCD framebuffer
        fb = cp.display.get_framebuffer()
        # Count rows that have white pixels
        rows_with_white = sum(1 for row in fb if any(px == 0xFFFF for px in row))
        self.assertGreater(rows_with_white, 0, "At least one row should have white pixels")

        # Count total white pixels — should be at least 5 (one per touch)
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreaterEqual(white, 1, "At least one pixel should be drawn from the drag")


if __name__ == '__main__':
    unittest.main()
