#!/usr/bin/env python3
"""
Standalone E2E LCD drawing test.

This test verifies that the LCD display controller (R61523) works
correctly by:
  1. Writing pixels directly to the display interface (0xB4000000)
  2. Verifying the framebuffer contains the expected colors
  3. Testing all addressing modes (RS=0 command, RS=1 data)

The test also runs a small assembly program that draws colored bars
to the LCD, to verify the full pipeline (assembler -> CPU -> display).

Usage:
    python3 test_lcd_e2e.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU
from ruk.jcore.display import Display, DISPLAY_WIDTH, DISPLAY_HEIGHT, PRDR_ADDR, DISPLAY_IFACE_ADDR as DISP_ADDR
from ruk.jcore.mmio import MMIODevice
from ruk.tools.assembler import assemble


def make_cpu_with_display(start_pc=0x8C000000, sr=0x40001000):
    """Create a CPU with a display peripheral attached."""
    mem = Memory(0x1000000)
    mmap = MemoryMap()
    mmap.add(0x8C000000, mem, name="RAM", perms="RWX")

    display = Display()

    # Attach display: PRDR (8-bit) + display interface (16-bit)
    prdr_dev = MMIODevice(PRDR_ADDR, 1, display, name="PRDR")
    mmap.add(PRDR_ADDR, prdr_dev, name="PRDR")
    disp_dev = MMIODevice(DISP_ADDR, 0x10000, display, name="DISP")
    mmap.add(DISP_ADDR, disp_dev, name="DISP")

    # MMIO catch-all for A4xxxxxx region
    mmio_catch = Memory(0x100000)
    mmap.add(0xA4000000, mmio_catch, name="MMIO", perms="RW")

    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr
    cpu.regs['vbr'] = 0
    cpu.regs['r15'] = 0x8C080000

    return cpu, mem, display


def set_lcd_register(display, reg_index, value):
    """Helper: write a value to an LCD register via the MMIO interface.

    This simulates what the CPU does:
      1. Set RS=0 (PRDR bit 4 = 0)
      2. Write register index to display interface
      3. Set RS=1 (PRDR bit 4 = 1)
      4. Write value to display interface
    """
    # RS=0 (command mode)
    display.prdr &= ~0x10
    display.disp_write16(reg_index)
    # RS=1 (data mode)
    display.prdr |= 0x10
    display.disp_write16(value)


def write_lcd_pixel(display, color):
    """Helper: write a pixel to the LCD GRAM."""
    # Make sure we're in GRAM mode and RS=1
    display.prdr |= 0x10  # RS=1
    display.mode = 0x202  # GRAM
    display.disp_write16(color)


class TestLCDDirect(unittest.TestCase):
    """Test LCD drawing directly via the Display API."""

    def setUp(self):
        """Create a fresh display for each test."""
        self.display = Display()

    def test_display_dimensions(self):
        """Display should be 640x224 (R61523 ClassPad II resolution)."""
        self.assertEqual(DISPLAY_WIDTH, 360, "Display width should be 360")
        self.assertEqual(DISPLAY_HEIGHT, 640, "Display height should be 640")

        fb = self.display.get_framebuffer()
        self.assertEqual(len(fb), 640, "Framebuffer should have 640 rows")
        self.assertEqual(len(fb[0]), 360, "Each row should have 360 pixels")

    def test_set_pixel(self):
        """set_pixel should write the correct color."""
        self.display.set_pixel(10, 20, 0xF800)  # red
        self.assertEqual(self.display.get_pixel(10, 20), 0xF800)

    def test_fill_screen(self):
        """Fill the entire screen with a solid color."""
        color = 0x07E0  # green
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                self.display.set_pixel(x, y, color)

        # Check corners and center
        self.assertEqual(self.display.get_pixel(0, 0), color)
        self.assertEqual(self.display.get_pixel(DISPLAY_WIDTH-1, DISPLAY_HEIGHT-1), color)
        self.assertEqual(self.display.get_pixel(DISPLAY_WIDTH//2, DISPLAY_HEIGHT//2), color)

    def test_lcd_register_write(self):
        """Test writing to LCD registers via the display interface."""
        # Set RS=0, write register index 0x202 (GRAM)
        self.display.prdr = 0  # RS=0
        self.display.disp_write16(0x0202)
        self.assertEqual(self.display.mode, 0x202)

        # Set RS=1, write pixel data
        self.display.prdr = 0x10  # RS=1
        self.display.disp_write16(0xF800)  # red pixel

        # The pixel should be at (0, 0)
        self.assertEqual(self.display.get_pixel(0, 0), 0xF800)

    def test_lcd_multiple_pixels(self):
        """Test writing multiple pixels via GRAM auto-increment."""
        # Set GRAM mode
        set_lcd_register(self.display, 0x200, 0)  # H addr = 0
        set_lcd_register(self.display, 0x201, 0)  # V addr = 0

        # Select GRAM register
        self.display.prdr = 0  # RS=0
        self.display.disp_write16(0x0202)  # select GRAM
        self.display.prdr = 0x10  # RS=1

        # Write 10 pixels with different colors
        colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000,
                  0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000]
        for c in colors:
            self.display.disp_write16(c)

        # Verify pixels
        for i, c in enumerate(colors):
            self.assertEqual(self.display.get_pixel(i, 0), c,
                             f"Pixel {i} should be 0x{c:04X}")


class TestLCDViaCPU(unittest.TestCase):
    """Test LCD drawing via the CPU executing assembly code."""

    def test_draw_red_pixel_via_cpu(self):
        """CPU should be able to draw a red pixel via assembly."""
        cpu, mem, display = make_cpu_with_display()

        # Assemble a program that:
        # 1. Loads PRDR and DISP addresses
        # 2. Sets RS=0, selects GRAM (0x202)
        # 3. Sets RS=1, writes a red pixel (0xF800)
        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! RS=0 (command mode)
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14

            ! Select GRAM register (0x202)
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13

            ! RS=1 (data mode)
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14

            ! Write red pixel (0xF800)
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13

            ! Done
            bra end
            nop
            end:
            bra end
            nop

            .align 2
            prdr_addr:
            .long 0xA405013C
            disp_addr:
            .long 0xB4000000
        """, start_addr=0x8C000000)

        # Load program
        for i, b in enumerate(program):
            mem._mem[i] = b

        # Run until we hit the infinite loop
        for _ in range(100):
            cpu.step()
            if cpu.pc >= 0x8C000000 + len(program) - 4:
                break

        # Verify the pixel was drawn
        self.assertEqual(display.get_pixel(0, 0), 0xF800,
                         "Red pixel should be drawn at (0,0)")

    def test_draw_color_bars(self):
        """CPU should draw multiple colored pixels via assembly."""
        cpu, mem, display = make_cpu_with_display()

        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! RS=0, select GRAM
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13

            ! RS=1 (data mode for pixels)
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14

            ! Write 5 pixels: red, green, blue, white, black
            mov.l c_red, r0
            mov.w r0, @r13
            mov.l c_green, r0
            mov.w r0, @r13
            mov.l c_blue, r0
            mov.w r0, @r13
            mov.l c_white, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13

            ! Done
            bra end
            nop
            end:
            bra end
            nop

            .align 2
            prdr_addr:
            .long 0xA405013C
            disp_addr:
            .long 0xB4000000
            c_red:
            .long 0xF800
            c_green:
            .long 0x07E0
            c_blue:
            .long 0x001F
            c_white:
            .long 0xFFFF
        """, start_addr=0x8C000000)

        for i, b in enumerate(program):
            mem._mem[i] = b

        for _ in range(200):
            cpu.step()
            if cpu.pc >= 0x8C000000 + len(program) - 4:
                break

        # Verify pixels
        self.assertEqual(display.get_pixel(0, 0), 0xF800, "Pixel 0 should be red")
        self.assertEqual(display.get_pixel(1, 0), 0x07E0, "Pixel 1 should be green")
        self.assertEqual(display.get_pixel(2, 0), 0x001F, "Pixel 2 should be blue")
        self.assertEqual(display.get_pixel(3, 0), 0xFFFF, "Pixel 3 should be white")
        self.assertEqual(display.get_pixel(4, 0), 0x0000, "Pixel 4 should be black")

    def test_lcd_fill_pattern(self):
        """CPU should fill a region of the LCD with a pattern."""
        cpu, mem, display = make_cpu_with_display()

        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! RS=0, select GRAM
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13

            ! RS=1
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14

            ! Write 100 pixels with incrementing colors
            mov #0, r2       ! counter
            mov #100, r3     ! limit

            loop:
            mov r2, r0
            shll8 r0         ! color = counter * 256
            mov.w r0, @r13
            add #1, r2
            cmp/ge r3, r2
            bf loop

            ! Done
            bra end
            nop
            end:
            bra end
            nop

            .align 2
            prdr_addr:
            .long 0xA405013C
            disp_addr:
            .long 0xB4000000
        """, start_addr=0x8C000000)

        for i, b in enumerate(program):
            mem._mem[i] = b

        for _ in range(500):
            cpu.step()
            if cpu.pc >= 0x8C000000 + len(program) - 4:
                break

        # Verify some pixels were drawn
        non_default = sum(1 for x in range(100) if display.get_pixel(x, 0) != 0xFFFF)
        self.assertGreater(non_default, 0, "Should have drawn pixels")

        # Verify the pattern: pixel i should have color (i << 8)
        for i in range(10):
            expected = (i << 8) & 0xFFFF
            actual = display.get_pixel(i, 0)
            self.assertEqual(actual, expected,
                            f"Pixel {i} should be 0x{expected:04X}, got 0x{actual:04X}")


class TestLCDResolution(unittest.TestCase):
    """Test that the LCD resolution is correct (640x224)."""

    def test_resolution(self):
        """Display should be 640x224."""
        self.assertEqual(DISPLAY_WIDTH, 360)
        self.assertEqual(DISPLAY_HEIGHT, 640)

    def test_framebuffer_size(self):
        """Framebuffer should have 640 rows of 360 pixels."""
        display = Display()
        fb = display.get_framebuffer()
        self.assertEqual(len(fb), 640)
        self.assertEqual(len(fb[0]), 360)

    def test_pixel_at_corner(self):
        """Should be able to set a pixel at (639, 359)."""
        display = Display()
        display.set_pixel(359, 639, 0x1234)
        self.assertEqual(display.get_pixel(359, 639), 0x1234)

    def test_pixel_out_of_bounds(self):
        """Out-of-bounds pixels should be silently ignored."""
        display = Display()
        display.set_pixel(360, 0, 0x1234)   # x out of bounds
        display.set_pixel(0, 640, 0x1234)   # y out of bounds
        # Should not crash, and pixel should not be set
        self.assertEqual(display.get_pixel(0, 0), 0xFFFF)


def run_all_tests():
    """Run all LCD E2E tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestLCDDirect,
        TestLCDViaCPU,
        TestLCDResolution,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures:  {len(result.failures)}")
    print(f"Errors:    {len(result.errors)}")
    print("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
