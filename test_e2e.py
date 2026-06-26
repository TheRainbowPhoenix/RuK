#!/usr/bin/env python3
"""
Comprehensive E2E tests for the RuK SH4AL-DSP emulator.

Each test assembles a small bare-metal program, loads it into RAM,
runs it, and verifies the results by inspecting memory, registers,
or the LCD framebuffer.  BMP screenshots are saved for visual
verification of LCD drawing.

Usage:
    python3 test_e2e.py                # run all tests
    python3 test_e2e.py lcd            # run LCD tests only
"""

import sys
import os
import struct
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU
from ruk.jcore.display import Display, DISPLAY_WIDTH, DISPLAY_HEIGHT, PRDR_ADDR, DISPLAY_IFACE_ADDR
from ruk.jcore.mmio import MMIODevice
from ruk.tools.assembler import assemble


# ============================================================================
# Bitmap export helpers
# ============================================================================

def _rgb565_to_rgb888(pixel: int) -> tuple:
    r5 = (pixel >> 11) & 0x1F
    g6 = (pixel >> 5) & 0x3F
    b5 = pixel & 0x1F
    r8 = (r5 * 255) // 31
    g8 = (g6 * 255) // 63
    b8 = (b5 * 255) // 31
    return (b8, g8, r8)


def save_display_bmp(display: Display, filepath: str):
    width = DISPLAY_WIDTH
    height = DISPLAY_HEIGHT
    row_size = ((width * 3 + 3) // 4) * 4
    padding = row_size - (width * 3)
    pixel_data_size = row_size * height

    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        for x in range(width):
            val = display.get_pixel(x, y)
            pixels.extend(_rgb565_to_rgb888(val))
        pixels.extend(b'\x00' * padding)

    file_header = struct.pack('<2sIHHI', b'BM', 14 + 40 + pixel_data_size, 0, 0, 14 + 40)
    dib_header = struct.pack('<IIIHHIIIIII', 40, width, height, 1, 24, 0, pixel_data_size, 2835, 2835, 0, 0)

    with open(filepath, 'wb') as f:
        f.write(file_header)
        f.write(dib_header)
        f.write(pixels)
    print(f"  BMP saved: {filepath}")


# ============================================================================
# Test infrastructure
# ============================================================================

def make_cpu(start_pc=0x8C000000, sr=0x40001000, with_display=True, with_rtc=False):
    mem = Memory(0x1000000)
    mmap = MemoryMap()
    mmap.add(0x8C000000, mem, name="RAM", perms="RWX")

    display = None
    if with_display:
        display = Display()
        prdr_dev = MMIODevice(PRDR_ADDR, 1, display, name="PRDR")
        mmap.add(PRDR_ADDR, prdr_dev, name="PRDR")
        disp_dev = MMIODevice(DISPLAY_IFACE_ADDR, 0x10000, display, name="DISP")
        mmap.add(DISPLAY_IFACE_ADDR, disp_dev, name="DISP")

    if with_rtc:
        from ruk.jcore.rtc import RTC, RTC_BASE, RTC_SIZE
        rtc = RTC()
        rtc_dev = MMIODevice(RTC_BASE, RTC_SIZE, rtc, name="RTC")
        mmap.add(RTC_BASE, rtc_dev, name="RTC")

    mmio_catch = Memory(0x100000)
    mmap.add(0xA4000000, mmio_catch, name="MMIO", perms="RW")

    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr
    cpu.regs['vbr'] = 0
    cpu.regs['r15'] = 0x8C080000
    return cpu, mem, display


def load_and_run(cpu, mem, program, start_pc=0x8C000000, max_steps=1000000):
    ram_offset = start_pc - 0x8C000000
    for i, b in enumerate(program):
        if ram_offset + i < len(mem._mem):
            mem._mem[ram_offset + i] = b

    last_pc = 0
    loop_count = 0
    for step in range(max_steps):
        cpu.step()
        if cpu.pc == last_pc:
            loop_count += 1
            if loop_count > 100:
                break
        else:
            last_pc = cpu.pc
            loop_count = 0
    return step + 1


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================================
# LCD helper: set register via assembly preamble
# ============================================================================

# Common LCD setup preamble: loads PRDR/disp addresses, sets H/V addr to 0,
# selects GRAM, sets RS=1 for pixel data.
LCD_SETUP_PREAMBLE = """
    mov.l prdr_addr, r14
    mov.l disp_addr, r13

    ! RS=0, set H addr = 0 (reg 0x200)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    mov.w r0, @r13

    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14
    mov #0, r0
    mov.w r0, @r13

    ! RS=0, set V addr = 0 (reg 0x201)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    or #0x01, r0
    mov.w r0, @r13

    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14
    mov #0, r0
    mov.w r0, @r13

    ! RS=0, select GRAM (0x202)
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
"""

LCD_CONST_POOL = """
    .align 2
    prdr_addr:
    .long 0xA405013C
    disp_addr:
    .long 0xB4000000
"""


# ============================================================================
# LCD E2E Tests
# ============================================================================

class TestE2E_LCD(unittest.TestCase):
    """E2E tests for LCD drawing via assembled programs."""

    def test_draw_single_pixel(self):
        """Draw a single red pixel at (0,0)."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP_PREAMBLE + """
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13
            bra end
            nop
            end:
            bra end
            nop
        """ + LCD_CONST_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program)
        self.assertEqual(display.get_pixel(0, 0), 0xF800)
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'lcd_single_pixel.bmp'))

    def test_draw_color_bars(self):
        """Draw 5 colored pixels on the first row."""
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP_PREAMBLE + """
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
        """ + LCD_CONST_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, program)
        self.assertEqual(display.get_pixel(0, 0), 0xF800)
        self.assertEqual(display.get_pixel(1, 0), 0x07E0)
        self.assertEqual(display.get_pixel(2, 0), 0x001F)
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'lcd_color_bars.bmp'))

    def test_lcd_full_screen_gradient(self):
        """Fill the entire 360x640 screen with a color gradient.

        Uses a pixel counter (0..230399) and computes:
          red   = (counter >> 8) & 0xF8  (changes every 8 pixels)
          green = (counter >> 4) & 0xFC  (changes every 4 pixels)
          blue  =  counter & 0x1F        (changes every pixel)
        This produces a smooth full-screen gradient.
        """
        cpu, mem, display = make_cpu()
        # We can't fit 230400 iterations in a simple loop with 8-bit immediates,
        # so we use a nested loop: outer loop 640 rows, inner loop 360 cols.
        # color = (row << 2) << 11 | (col << 1) << 5  -- simplified gradient
        program = assemble(LCD_SETUP_PREAMBLE + """
            ! Pre-compute loop limits ONCE before the loops
            ! r7 = 360 (col limit)
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            ! r8 = 640 (row limit) = 5 << 7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8

            mov #0, r2

            row_loop:
            mov #0, r3

            col_loop:
            ! Compute a full-screen gradient that covers the full width:
            ! red = (row * 255 / 639) & 0xF8  -- full red range across rows
            ! green = (col * 255 / 359) & 0xFC  -- full green range across cols
            ! blue = ((row + col) * 255 / (639+359)) & 0x1F
            !
            ! Since we can't do division in assembly, approximate:
            ! red = (row >> 2) << 3  -- row/4 * 8, gives 0..504 in steps of 8
            ! green = (col << 1) & 0xFC  -- col*2, gives 0..718 masked to 0..252
            ! blue = ((row ^ col) & 0x1F)  -- XOR pattern for visual variety

            ! Red: (row >> 2) << 11 = ((row >> 2) & 0x1F) << 11
            ! This gives 5 bits of red (0-31), covering 0-639 rows nicely
            mov r2, r0
            shlr2 r0          ! r0 = row >> 2
            and #0x1F, r0     ! 5 bits
            shll8 r0          ! shift to red position (bits 15-11)
            shll2 r0
            shll r0           ! now in bits 15-11

            ! Green: (col >> 1) << 5 = ((col >> 1) & 0x3F) << 5
            ! This gives 6 bits of green (0-63), covering 0-359 cols
            mov r3, r1
            shlr r1           ! r1 = col >> 1
            and #0x3F, r1     ! 6 bits
            shll2 r1
            shll2 r1
            shll r1           ! shift to green position (bits 10-5)

            or r1, r0         ! combine red + green

            ! Blue: (row + col) & 0x1F for variation
            mov r2, r1
            add r3, r1
            and #0x1F, r1
            or r1, r0         ! add blue

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
        """ + LCD_CONST_POOL, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program, max_steps=5000000)

        # Count non-default pixels
        fb = display.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF)
        print(f"  Full screen gradient: {non_default} non-default pixels (expected ~230400)")
        self.assertGreater(non_default, 200000,
                           "Should have filled most of the screen")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'lcd_full_gradient.bmp'))

    def test_lcd_diagonal_pattern(self):
        """Fill screen with a diagonal color pattern.

        color = f(x+y) where f produces a rainbow diagonal.
        """
        cpu, mem, display = make_cpu()
        program = assemble(LCD_SETUP_PREAMBLE + """
            ! Pre-compute limits
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
            ! bra end2
            nop
        """ + LCD_CONST_POOL, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program, max_steps=5000000)
        fb = display.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF)
        print(f"  Diagonal pattern: {non_default} non-default pixels")
        self.assertGreater(non_default, 200000, "Should fill the screen")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'lcd_diagonal.bmp'))

    def test_lcd_triangle_gradient(self):
        """Draw a GL-style triangle with gradient.

        Draws a filled triangle using a simple scanline approach:
        - Top vertex at (180, 50)
        - Bottom-left at (50, 550)
        - Bottom-right at (310, 550)
        For each row, interpolate left and right edges and fill between them
        with a gradient color that varies horizontally and vertically.
        """
        cpu, mem, display = make_cpu()

        # Instead of complex assembly interpolation, we'll use a simpler
        # approach: draw a triangle by computing for each pixel whether it's
        # inside the triangle using barycentric-like checks.
        # Since assembly can't easily do division, we'll pre-compute the
        # triangle in Python and write the pixel data via the display API,
        # but still use the CPU to set up the LCD registers.

        # Set up LCD via assembly
        program = assemble(LCD_SETUP_PREAMBLE + """
            ! Pre-compute limits
            ! r7 = 360 (col limit)
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            ! r8 = 640 (row limit) = 5 << 7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8
            ! r9 = 180 (center column) = 90 << 1
            ! (can't use mov #0xB4, sign-extends to -76)
            mov #90, r9
            shll r9

            mov #0, r2
            row_loop3:
            mov #0, r3
            col_loop3:

            ! Check row < 600 (0x258 = 600 = 0x02 << 8 | 0x58)
            ! Can't use or #0x58, r1 (only works with R0)
            ! Build 600 in r10: 600 = 75 * 8 = 75 << 3
            mov #75, r10
            shll2 r10
            shll r10
            cmp/ge r10, r2
            bt outside

            ! half_width = row >> 4 (triangle gets wider toward bottom)
            mov r2, r5
            shlr2 r5
            shlr2 r5

            ! left_edge = 180 - half_width (r6)
            mov r9, r6
            sub r5, r6

            ! right_edge = 180 + half_width (r11, don't clobber r7)
            mov r9, r11
            add r5, r11

            ! Check col >= left_edge
            cmp/hs r6, r3
            bf outside

            ! Check col < right_edge
            cmp/ge r11, r3
            bt outside

            ! Inside triangle: gradient color
            ! red = (row >> 2) & 0xF8
            mov r2, r0
            shlr2 r0
            and #0xF8, r0
            shll8 r0
            ! green = (col >> 1) & 0xFC
            mov r3, r1
            shlr r1
            and #0xFC, r1
            or r1, r0
            ! blue = ((row + col) >> 3) & 0x1F
            mov r2, r1
            add r3, r1
            shlr2 r1
            shlr r1
            and #0x1F, r1
            or r1, r0
            bra write_px
            nop

            outside:
            mov #0, r0

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
        """ + LCD_CONST_POOL, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program, max_steps=5000000)
        fb = display.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF and px != 0)
        non_black = sum(1 for row in fb for px in row if px != 0)
        print(f"  Triangle gradient: {non_black} non-black pixels, {non_default} colored")
        self.assertGreater(non_black, 20000, "Triangle should cover significant area")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'lcd_triangle_gradient.bmp'))

    def test_lcd_resolution(self):
        """Display should be 360x640."""
        self.assertEqual(DISPLAY_WIDTH, 360)
        self.assertEqual(DISPLAY_HEIGHT, 640)
        display = Display()
        fb = display.get_framebuffer()
        self.assertEqual(len(fb), 640)
        self.assertEqual(len(fb[0]), 360)


# ============================================================================
# Memory E2E Tests
# ============================================================================

class TestE2E_Memory(unittest.TestCase):
    def test_store_load_roundtrip(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0x42, r0
            mov.l r0, @(0, r15)
            mov.l @(0, r15), r1
            bra end
            nop
            end:
            bra end
            nop
        """, start_addr=0x8C000000)
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 0x42)

    def test_store_array(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0x50, r0
            mov.l r0, @(0, r15)
            mov #0x60, r0
            mov.l r0, @(4, r15)
            mov #0x70, r0
            mov.l r0, @(8, r15)
            bra end
            nop
            end:
            bra end
            nop
        """, start_addr=0x8C000000)
        load_and_run(cpu, mem, program)
        ram_offset = 0x8C080000 - 0x8C000000
        val0 = int.from_bytes(mem._mem[ram_offset:ram_offset+4], 'big')
        val1 = int.from_bytes(mem._mem[ram_offset+4:ram_offset+8], 'big')
        val2 = int.from_bytes(mem._mem[ram_offset+8:ram_offset+12], 'big')
        self.assertEqual(val0, 0x50)
        self.assertEqual(val1, 0x60)
        self.assertEqual(val2, 0x70)


# ============================================================================
# Arithmetic E2E Tests
# ============================================================================

class TestE2E_Arithmetic(unittest.TestCase):
    def test_add(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("mov #5, r0\nmov #3, r1\nadd r0, r1\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 8)

    def test_sub(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("mov #3, r0\nmov #10, r1\nsub r0, r1\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 7)

    def test_shift_left(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("mov #0x01, r0\nshll8 r0\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 0x100)

    def test_shift_left_16(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("mov #0x01, r0\nshll16 r0\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 0x10000)


# ============================================================================
# Branch E2E Tests
# ============================================================================

class TestE2E_Branch(unittest.TestCase):
    def test_bra_forward(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("bra skip\nnop\nmov #99, r0\nskip:\nmov #42, r0\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42)

    def test_bt_taken(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("sett\nbt target\nmov #99, r0\ntarget:\nmov #42, r0\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42)

    def test_bt_not_taken(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("clrt\nbt target\nmov #42, r0\nbra end\nnop\ntarget:\nmov #99, r0\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42)

    def test_loop_counter(self):
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("mov #0, r0\nmov #5, r1\nloop:\nadd #1, r0\ncmp/ge r1, r0\nbf loop\nbra end\nnop\nend:\nbra end\nnop")
        load_and_run(cpu, mem, program, max_steps=500)
        self.assertEqual(cpu.regs['r0'], 5)


# ============================================================================
# DSP E2E Tests
# ============================================================================

class TestE2E_DSP(unittest.TestCase):
    def test_dsp_padd(self):
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['a0'] = 0x10000000
        cpu.regs['x1'] = 0x20000000
        handle_dsp_instruction(cpu, 0xF0B0)
        self.assertEqual(cpu.regs['y0'], 0x30000000)

    def test_dsp_psub(self):
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['a0'] = 0x50000000
        cpu.regs['x0'] = 0x20000000
        handle_dsp_instruction(cpu, 0xF0A1)
        self.assertEqual(cpu.regs['m0'], 0x30000000)

    def test_dsp_pclr(self):
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['m0'] = 0xDEADBEEF
        handle_dsp_instruction(cpu, 0xF08D)
        self.assertEqual(cpu.regs['m0'], 0)

    def test_dsp_pmuls_padd(self):
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['y1'] = 0x20000000
        cpu.regs['x1'] = 0x30000000
        handle_dsp_instruction(cpu, 0xF070)
        self.assertEqual(cpu.regs['y0'], 0x50000000)
        expected_product = 2 * 0x2000 * 0x3000
        self.assertEqual(cpu.regs['x0'], expected_product)

    def test_dsp_movs_load_store(self):
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        struct.pack_into('>i', mem._mem, 0, 0x12345678)
        cpu.regs['r4'] = 0x8C000000
        handle_dsp_instruction(cpu, 0x005E)
        self.assertEqual(cpu.regs['a1'], 0x12345678)
        self.assertEqual(cpu.regs['r4'], 0x8C000004)


# ============================================================================
# RTC E2E Tests
# ============================================================================

class TestE2E_RTC(unittest.TestCase):
    def test_rtc_read_r64cnt(self):
        cpu, mem, display = make_cpu(with_display=False, with_rtc=True)
        program = assemble("""
            mov.l rtc_base, r14
            mov.b @r14, r0
            mov.l result, r15
            mov.b r0, @r15
            bra end
            nop
            end:
            bra end
            nop
            .align 2
            rtc_base: .long 0xA413FEC0
            result: .long 0x8C003000
        """, start_addr=0x8C000000)
        load_and_run(cpu, mem, program, max_steps=500)
        ram_offset = 0x8C003000 - 0x8C000000
        val = mem._mem[ram_offset]
        self.assertLess(val, 128, f"R64CNT = {val}, should be < 128")


# ============================================================================
# Main
# ============================================================================

def run_all_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestE2E_LCD, TestE2E_Memory, TestE2E_Arithmetic,
                TestE2E_Branch, TestE2E_DSP, TestE2E_RTC]:
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
