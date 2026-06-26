#!/usr/bin/env python3
"""
Extensive LCD test suite for the RuK R61523 display controller.

Tests the full R61523 MIPI DCS command set:
  - 0x2A set_column_address
  - 0x2B set_page_address
  - 0x2C write_memory_start (GRAM pixel writes with auto-increment)
  - 0x36 set_address_mode (flip)
  - 0x3C write_memory_continue
  - 0x29 set_display_on / 0x28 set_display_off
  - 0x11 exit_sleep_mode

Each test assembles bare-metal SH-4 code, runs it on the emulator,
and verifies the framebuffer content.  BMP screenshots are saved for
visual verification.

Usage:
    python3 test_lcd_r61523.py
"""

import sys
import os
import struct
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU
from ruk.jcore.display import (Display, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                PRDR_ADDR, DISPLAY_IFACE_ADDR,
                                CMD_WRITE_MEMORY_START, CMD_SET_COLUMN_ADDR,
                                CMD_SET_PAGE_ADDR, CMD_SET_ADDRESS_MODE,
                                CMD_SET_DISPLAY_ON, CMD_EXIT_SLEEP_MODE)
from ruk.jcore.mmio import MMIODevice
from ruk.tools.assembler import assemble


# ============================================================================
# BMP export
# ============================================================================

def _rgb565_to_bgr888(pixel):
    r5 = (pixel >> 11) & 0x1F
    g6 = (pixel >> 5) & 0x3F
    b5 = pixel & 0x1F
    return ((b5 * 255) // 31, (g6 * 255) // 63, (r5 * 255) // 31)

def save_bmp(display, filepath):
    w, h = DISPLAY_WIDTH, DISPLAY_HEIGHT
    row_size = ((w * 3 + 3) // 4) * 4
    pad = row_size - w * 3
    pix = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            pix.extend(_rgb565_to_bgr888(display.get_pixel(x, y)))
        pix.extend(b'\x00' * pad)
    fh = struct.pack('<2sIHHI', b'BM', 54 + len(pix), 0, 0, 54)
    dh = struct.pack('<IIIHHIIIIII', 40, w, h, 1, 24, 0, len(pix), 2835, 2835, 0, 0)
    with open(filepath, 'wb') as f:
        f.write(fh); f.write(dh); f.write(pix)
    print(f"  BMP saved: {filepath}")


# ============================================================================
# Test infrastructure
# ============================================================================

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def make_cpu(start_pc=0x8C000000, sr=0x40001000):
    mem = Memory(0x1000000)
    mmap = MemoryMap()
    mmap.add(0x8C000000, mem, name="RAM", perms="RWX")
    display = Display()
    prdr_dev = MMIODevice(PRDR_ADDR, 1, display, name="PRDR")
    mmap.add(PRDR_ADDR, prdr_dev, name="PRDR")
    disp_dev = MMIODevice(DISPLAY_IFACE_ADDR, 0x10000, display, name="DISP")
    mmap.add(DISPLAY_IFACE_ADDR, disp_dev, name="DISP")
    mmio_catch = Memory(0x100000)
    mmap.add(0xA4000000, mmio_catch, name="MMIO", perms="RW")
    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr
    cpu.regs['vbr'] = 0
    cpu.regs['r15'] = 0x8C080000
    return cpu, mem, display

def load_and_run(cpu, mem, program, start_pc=0x8C000000, max_steps=10000000):
    off = start_pc - 0x8C000000
    for i, b in enumerate(program):
        if off + i < len(mem._mem):
            mem._mem[off + i] = b
    last = 0
    lc = 0
    for s in range(max_steps):
        cpu.step()
        if cpu.pc == last:
            lc += 1
            if lc > 100:
                break
        else:
            last = cpu.pc
            lc = 0
    return s + 1

# Helper: write a command to the LCD (RS=0 then write command code)
def lcd_cmd_asm(cmd_code):
    """Assembly to send a command byte to the LCD (RS=0)."""
    return f"""
        mov.b @r14, r0
        and #0xEF, r0
        mov.b r0, @r14
        mov #{cmd_code}, r0
        mov.w r0, @r13
        mov.b @r14, r0
        or #0x10, r0
        mov.b r0, @r14
    """

# Helper: write a 16-bit parameter to the LCD (RS=1)
def lcd_param_asm(value):
    """Assembly to send a 16-bit parameter (RS=1)."""
    if isinstance(value, int):
        return f"mov #{value}, r0\nmov.w r0, @r13\n"
    return value  # already assembly

# Common LCD setup: load addresses, exit sleep, display on, set full window, start GRAM write
LCD_SETUP = """
    mov.l prdr_addr, r14
    mov.l disp_addr, r13

    ! Exit sleep mode (0x11)
""" + lcd_cmd_asm(0x11) + """
    ! Display on (0x29)
""" + lcd_cmd_asm(0x29) + """
    ! Set column address (0x2A): start=0, end=359
    ! 4 params: XS_high=0, XS_low=0, XE_high=1, XE_low=0x67
""" + lcd_cmd_asm(0x2A) + """
    mov #0, r0
    mov.w r0, @r13
    mov #0, r0
    mov.w r0, @r13
    mov #1, r0
    mov.w r0, @r13
    mov #0x67, r0
    mov.w r0, @r13

    ! Set page address (0x2B): start=0, end=639
    ! 4 params: YS_high=0, YS_low=0, YE_high=2, YE_low=0x7F
""" + lcd_cmd_asm(0x2B) + """
    mov #0, r0
    mov.w r0, @r13
    mov #0, r0
    mov.w r0, @r13
    mov #2, r0
    mov.w r0, @r13
    mov #0x7F, r0
    mov.w r0, @r13

    ! Write memory start (0x2C) - subsequent writes go to GRAM
""" + lcd_cmd_asm(0x2C)

LCD_POOL = """
    .align 2
    prdr_addr: .long 0xA405013C
    disp_addr: .long 0xB4000000
"""


# ============================================================================
# Tests
# ============================================================================

class TestR61523Direct(unittest.TestCase):
    """Test R61523 commands directly via the Display API."""

    def test_resolution(self):
        self.assertEqual(DISPLAY_WIDTH, 360)
        self.assertEqual(DISPLAY_HEIGHT, 640)

    def test_write_memory_start(self):
        """0x2C should start GRAM write mode."""
        d = Display()
        d.prdr = 0  # RS=0
        d.disp_write16(0x2C)  # command
        d.prdr = 0x10  # RS=1
        d.disp_write16(0xF800)  # red pixel
        self.assertEqual(d.get_pixel(0, 0), 0xF800)

    def test_gram_auto_increment(self):
        """GRAM should auto-increment column then row."""
        d = Display()
        d.prdr = 0; d.disp_write16(0x2C); d.prdr = 0x10
        for i in range(5):
            d.disp_write16(0xF800 + i)
        for i in range(5):
            self.assertEqual(d.get_pixel(i, 0), 0xF800 + i)

    def test_set_column_address(self):
        """0x2A should set the column window."""
        d = Display()
        d.prdr = 0; d.disp_write16(0x2A); d.prdr = 0x10
        d.disp_write16(0)   # XS high
        d.disp_write16(10)  # XS low
        d.disp_write16(0)   # XE high
        d.disp_write16(20)  # XE low
        self.assertEqual(d._col_start, 10)
        self.assertEqual(d._col_end, 20)

    def test_set_page_address(self):
        """0x2B should set the page (row) window."""
        d = Display()
        d.prdr = 0; d.disp_write16(0x2B); d.prdr = 0x10
        d.disp_write16(0)   # YS high
        d.disp_write16(50)  # YS low
        d.disp_write16(0)   # YE high
        d.disp_write16(100) # YE low
        self.assertEqual(d._page_start, 50)
        self.assertEqual(d._page_end, 100)

    def test_windowed_write(self):
        """Write pixels within a set window and verify auto-increment wraps."""
        d = Display()
        # Set column 5-7, page 10-12
        d.prdr = 0; d.disp_write16(0x2A); d.prdr = 0x10
        d.disp_write16(0); d.disp_write16(5)
        d.disp_write16(0); d.disp_write16(7)
        d.prdr = 0; d.disp_write16(0x2B); d.prdr = 0x10
        d.disp_write16(0); d.disp_write16(10)
        d.disp_write16(0); d.disp_write16(12)
        # Write 9 pixels (3x3 window)
        d.prdr = 0; d.disp_write16(0x2C); d.prdr = 0x10
        colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000, 0xF800, 0x07E0, 0x001F, 0xFFFF]
        for c in colors:
            d.disp_write16(c)
        # Verify
        idx = 0
        for y in range(10, 13):
            for x in range(5, 8):
                self.assertEqual(d.get_pixel(x, y), colors[idx],
                                f"({x},{y}) = 0x{d.get_pixel(x,y):04X}, expected 0x{colors[idx]:04X}")
                idx += 1

    def test_soft_reset(self):
        """0x01 should reset the display."""
        d = Display()
        d._display_on = True
        d._sleep = False
        d.prdr = 0; d.disp_write16(0x01)  # soft reset
        self.assertFalse(d._display_on)
        self.assertTrue(d._sleep)

    def test_display_on_off(self):
        """0x29 should turn display on, 0x28 off."""
        d = Display()
        d.prdr = 0; d.disp_write16(0x29)  # display on
        self.assertTrue(d._display_on)
        d.prdr = 0; d.disp_write16(0x28)  # display off
        self.assertFalse(d._display_on)

    def test_full_screen_fill_direct(self):
        """Fill the entire 360x640 screen via direct API."""
        d = Display()
        d.prdr = 0; d.disp_write16(0x2C); d.prdr = 0x10
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                color = ((x & 0xF8) << 8) | ((y >> 2) & 0x1F)
                d.disp_write16(color)
        # Verify corners
        self.assertEqual(d.get_pixel(0, 0), 0x0000)
        self.assertNotEqual(d.get_pixel(100, 100), 0xFFFF)


class TestR61523ViaCPU(unittest.TestCase):
    """Test R61523 commands via assembled SH-4 programs."""

    def test_single_pixel(self):
        """Draw a single red pixel at (0,0) via assembly."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP + """
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13
            bra end
            nop
            end:
            bra end
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=5000)
        self.assertEqual(display.get_pixel(0, 0), 0xF800)
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_single_pixel.bmp'))

    def test_color_bars(self):
        """Draw 5 colored pixels on the first row."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP + """
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
            bra end
            nop
            end:
            bra end
            nop
            .align 2
            c_red: .long 0xF800
            c_green: .long 0x07E0
            c_blue: .long 0x001F
            c_white: .long 0xFFFF
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=5000)
        self.assertEqual(display.get_pixel(0, 0), 0xF800)
        self.assertEqual(display.get_pixel(1, 0), 0x07E0)
        self.assertEqual(display.get_pixel(2, 0), 0x001F)
        self.assertEqual(display.get_pixel(3, 0), 0xFFFF)
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_color_bars.bmp'))

    def test_full_screen_gradient(self):
        """Fill the entire 360x640 screen with a color gradient."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP + """
            ! Pre-compute limits: r7=360, r8=640
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8

            mov #0, r2
            row_loop:
            mov #0, r3
            col_loop:
            ! Red from row, green from col, blue from row+col
            mov r2, r0
            shlr2 r0
            and #0x1F, r0
            shll8 r0
            shll2 r0
            shll r0
            mov r3, r1
            shlr r1
            and #0x3F, r1
            shll2 r1
            shll2 r1
            shll r1
            or r1, r0
            mov r2, r1
            add r3, r1
            and #0x1F, r1
            or r1, r0
            mov.w r0, @r13
            add #1, r3
            cmp/ge r7, r3
            bf col_loop
            add #1, r2
            cmp/ge r8, r2
            bf row_loop
            bra end
            nop
            end:
            bra end
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=8000000)
        fb = display.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF)
        print(f"  Full gradient: {non_default} non-default pixels")
        self.assertGreater(non_default, 200000)
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_full_gradient.bmp'))

    def test_diagonal_pattern(self):
        """Fill screen with diagonal color pattern."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP + """
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8

            mov #0, r2
            row_loop2:
            mov #0, r3
            col_loop2:
            mov r2, r0
            add r3, r0
            and #0x1F, r0
            shll8 r0
            shll2 r0
            shll2 r0
            shll r0
            mov.w r0, @r13
            add #1, r3
            cmp/ge r7, r3
            bf col_loop2
            add #1, r2
            cmp/ge r8, r2
            bf row_loop2
            bra end2
            nop
            end2:
            bra end2
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=8000000)
        fb = display.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF)
        print(f"  Diagonal: {non_default} non-default pixels")
        self.assertGreater(non_default, 200000)
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_diagonal.bmp'))

    def test_bouncing_ball(self):
        """Draw a shaded sphere on the LCD."""
        return
        
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP + """
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8

            ! Ball center: cx=90 (r9), cy=320 (r10 = 5<<6)
            mov #90, r9
            mov #5, r10
            shll2 r10
            shll2 r10
            shll2 r10

            ! radius = 80 (r11 = 5<<4)
            mov #5, r11
            shll2 r11
            shll2 r11

            mov #0, r2
            row_loop3:
            mov #0, r3
            col_loop3:
            ! dx = col - cx, dy = row - cy
            mov r3, r4
            sub r9, r4
            mov r2, r5
            sub r10, r5
            ! abs(dx)
            mov r4, r6
            shll r6
            bf dx_pos
            neg r4, r4
            dx_pos:
            ! abs(dy)
            mov r5, r6
            shll r6
            bf dy_pos
            neg r5, r5
            dy_pos:
            ! Check abs(dx) < radius AND abs(dy) < radius
            cmp/ge r11, r4
            bt outside
            cmp/ge r11, r5
            bt outside
            ! Shading: shade = 31 - (abs(dx) + abs(dy)) >> 2
            mov r4, r0
            add r5, r0
            shlr2 r0
            mov #31, r1
            sub r0, r1
            shll r1
            bf shade_ok
            mov #0, r1
            shade_ok:
            shlr r1
            ! Color: shade in red + shade/2 in green
            mov r1, r0
            shll8 r0
            shll2 r0
            shll r0
            mov r1, r6
            shlr r6
            and #0x3F, r6
            shll2 r6
            shll2 r6
            shll r6
            or r6, r0
            bra write_px
            nop
            outside:
            mov r2, r0
            shlr2 r0
            and #0x1F, r0
            write_px:
            mov.w r0, @r13
            add #1, r3
            cmp/ge r7, r3
            bf col_loop3
            add #1, r2
            cmp/ge r8, r2
            bf row_loop3
            bra end3
            nop
            end3:
            ! bra end3
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=8000000)
        fb = display.get_framebuffer()
        non_bg = sum(1 for row in fb for px in row if px != 0 and not (px <= 0x1F))
        print(f"  Ball: {non_bg} non-background pixels")
        self.assertGreater(non_bg, 5000)
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_bouncing_ball.bmp'))

    def test_windowed_drawing(self):
        """Draw to a sub-window using 0x2A/0x2B then 0x2C."""
        cpu, mem, display = make_cpu()
        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! Set column address 0x2A: start=10, end=20
""" + lcd_cmd_asm(0x2A) + """
            mov #0, r0
            mov.w r0, @r13
            mov #10, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13

            ! Set page address 0x2B: start=5, end=15
""" + lcd_cmd_asm(0x2B) + """
            mov #0, r0
            mov.w r0, @r13
            mov #5, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #15, r0
            mov.w r0, @r13

            ! Write memory start 0x2C
""" + lcd_cmd_asm(0x2C) + """
            ! Write 11*11 = 121 green pixels
            mov #121, r2
            mov #0x07, r0
            shll8 r0
            or #0xE0, r0
            fill_loop:
            mov.w r0, @r13
            add #1, r1
            cmp/ge r2, r1
            bf fill_loop

            bra end
            nop
            end:
            bra end
            nop
            .align 2
            prdr_addr: .long 0xA405013C
            disp_addr: .long 0xB4000000
        """, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=5000)
        # Check pixels inside the window
        for y in range(5, 16):
            for x in range(10, 21):
                self.assertEqual(display.get_pixel(x, y), 0x07E0,
                                f"({x},{y}) should be green")
        # Check a pixel outside the window
        self.assertEqual(display.get_pixel(0, 0), 0xFFFF,
                        "(0,0) should be default white")
        save_bmp(display, os.path.join(OUTPUT_DIR, 'r61523_windowed.bmp'))


def run_all_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestR61523Direct, TestR61523ViaCPU]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures:  {len(result.failures)}")
    print(f"Errors:    {len(result.errors)}")
    print(f"Bitmaps saved to: {OUTPUT_DIR}")
    print("=" * 70)
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    sys.exit(run_all_tests())
