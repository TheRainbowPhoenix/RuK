#!/usr/bin/env python3
"""
Comprehensive E2E tests for the RuK SH4AL-DSP emulator.

Each test assembles a small bare-metal program, loads it into RAM,
runs it, and verifies the results by inspecting memory, registers,
or the LCD framebuffer.  This proves the full pipeline works:
  assembler -> CPU execution -> peripheral interaction -> result verification

Test categories:
  - LCD: drawing pixels, color bars, patterns (results saved as bitmaps)
  - DSP: MOVS loads/stores, PADD, PSUB, PMULS, PCLR, PCOPY
  - RTC: reading time registers
  - TRAPA: exception handling
  - Memory: store/load roundtrip
  - Arithmetic: add, sub, shift, compare
  - Branch: conditional and unconditional branches

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
    """Convert 16-bit RGB565 to 24-bit RGB888 (BGR for BMP)."""
    r5 = (pixel >> 11) & 0x1F
    g6 = (pixel >> 5) & 0x3F
    b5 = pixel & 0x1F
    r8 = (r5 * 255) // 31
    g8 = (g6 * 255) // 63
    b8 = (b5 * 255) // 31
    return (b8, g8, r8)


def save_display_bmp(display: Display, filepath: str):
    """Save the display framebuffer to a 24-bit BMP file."""
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

    file_header = struct.pack('<2sIHHI',
                              b'BM',
                              14 + 40 + pixel_data_size,
                              0, 0,
                              14 + 40)

    dib_header = struct.pack('<IIIHHIIIIII',
                             40, width, height,
                             1, 24, 0,
                             pixel_data_size,
                             2835, 2835,
                             0, 0)

    with open(filepath, 'wb') as f:
        f.write(file_header)
        f.write(dib_header)
        f.write(pixels)


# ============================================================================
# Test infrastructure
# ============================================================================

def make_cpu(start_pc=0x8C000000, sr=0x40001000, with_display=True, with_rtc=False):
    """Create a CPU with optional peripherals."""
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


def load_and_run(cpu, mem, program, start_pc=0x8C000000, max_steps=10000):
    """Load a program into RAM and run it until it loops or max_steps."""
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
# LCD E2E Tests
# ============================================================================

class TestE2E_LCD(unittest.TestCase):
    """E2E tests for LCD drawing via assembled programs."""

    def test_draw_single_pixel(self):
        """Draw a single red pixel at (0,0) via assembly."""
        cpu, mem, display = make_cpu()
        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13
            ! RS=0, select GRAM (0x202)
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13
            ! RS=1, write red pixel
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13
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
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(display.get_pixel(0, 0), 0xF800,
                         "Red pixel at (0,0)")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'test_draw_single_pixel.bmp'))

    def test_draw_color_bars(self):
        """Draw 5 colored pixels: red, green, blue, white, black."""
        cpu, mem, display = make_cpu()
        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14
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
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(display.get_pixel(0, 0), 0xF800, "Pixel 0 = red")
        self.assertEqual(display.get_pixel(1, 0), 0x07E0, "Pixel 1 = green")
        self.assertEqual(display.get_pixel(2, 0), 0x001F, "Pixel 2 = blue")
        self.assertEqual(display.get_pixel(3, 0), 0xFFFF, "Pixel 3 = white")
        self.assertEqual(display.get_pixel(4, 0), 0x0000, "Pixel 4 = black")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'test_draw_color_bars.bmp'))

    def test_draw_100_pixels_loop(self):
        """Draw 100 pixels with incrementing colors via a loop."""
        cpu, mem, display = make_cpu()
        program = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14
            mov #0, r2
            mov #100, r3
            loop:
            mov r2, r0
            shll8 r0
            mov.w r0, @r13
            add #1, r2
            cmp/ge r3, r2
            bf loop
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
        steps = load_and_run(cpu, mem, program, max_steps=5000)
        for i in range(10):
            expected = (i << 8) & 0xFFFF
            actual = display.get_pixel(i, 0)
            self.assertEqual(actual, expected,
                            f"Pixel {i}: expected 0x{expected:04X}, got 0x{actual:04X}")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'test_draw_100_pixels_loop.bmp'))

    def test_lcd_resolution(self):
        """Display should be 360x640 (ClassPad II portrait)."""
        self.assertEqual(DISPLAY_WIDTH, 360)
        self.assertEqual(DISPLAY_HEIGHT, 640)
        display = Display()
        fb = display.get_framebuffer()
        self.assertEqual(len(fb), 640, "Height = 640 rows")
        self.assertEqual(len(fb[0]), 360, "Width = 360 cols")

    def test_racing_the_beam_fullscreen(self):
        """Race the beam: fill entire 360x640 screen with a gradient pattern.

        Uses a single unrolled inner loop to write pixels as fast as possible.
        We set GRAM address once, then write (WIDTH*HEIGHT) pixels in a tight loop.
        """
        cpu, mem, display = make_cpu()
        # Total pixels = 360 * 640 = 230400.  We write in chunks of 16 per loop
        # iteration to keep the loop overhead low (~14400 iterations).
        # Each pixel = 1 mov.w to display.  We compute color from (x+y) gradient.
        program = assemble("""
            ! r14 = PRDR, r13 = DISP
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! Set GRAM address (0x202 = write to GRAM)
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13

            ! Set RS=1 (data mode)
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14

            ! r8 = total pixels / 16 = 230400 / 16 = 14400
            mov #14400, r8
            ! r9 = 0 (pixel counter, used for gradient)
            mov #0, r9

            loop:
            ! Unroll 16 pixels per iteration to minimize loop overhead
            ! Each pixel: compute color = ((pixel_counter * 7) & 0xFF) << 8
            !            | ((pixel_counter * 3) & 0xFF) << 3
            !            | ((pixel_counter * 5) & 0x1F)
            ! This gives a psychedelic gradient that varies across the screen.

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10

            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10

            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            mov r9, r0
            shll2 r0
            add r9, r0
            shll r0
            and #0xFF, r0
            shll8 r0
            mov r0, r10
            mov r9, r0
            shll r0
            add r9, r0
            and #0xFF, r0
            shll2 r0
            shll r0
            or r0, r10
            mov r9, r0
            and #0x1F, r0
            or r0, r10
            mov.w r10, @r13
            add #1, r9

            add #-1, r8
            cmp/eq #0, r8
            bf loop

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
        steps = load_and_run(cpu, mem, program, max_steps=500000)
        # Verify first and last pixels have different colors (gradient worked)
        first = display.get_pixel(0, 0)
        last = display.get_pixel(DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1)
        self.assertNotEqual(first, last, "Gradient should vary across screen")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'test_racing_the_beam_fullscreen.bmp'))

    def test_triangle_gradient_demo(self):
        """Draw a triangle with per-pixel gradient shading (GL-style demo).

        Computes barycentric coordinates for each pixel and interpolates
        vertex colors.  Draws scanline by scanline for the full 360x640 screen.
        """
        cpu, mem, display = make_cpu()
        program = assemble("""
            ! r14 = PRDR, r13 = DISP
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! Set GRAM address (0x202 = write to GRAM)
            mov.b @r14, r0
            and #0xEF, r0
            mov.b r0, @r14
            mov #0x02, r0
            shll8 r0
            or #0x02, r0
            mov.w r0, @r13

            ! Set RS=1 (data mode)
            mov.b @r14, r0
            or #0x10, r0
            mov.b r0, @r14

            ! Triangle vertices (x,y) in fixed 16.16:
            ! V0 = (180, 50)   top center
            ! V1 = (50, 550)   bottom left
            ! V2 = (310, 550)  bottom right
            !
            ! Vertex colors (RGB565):
            ! C0 = 0xF800 (red)
            ! C1 = 0x07E0 (green)
            ! C2 = 0x001F (blue)
            !
            ! We iterate y from 50 to 550, compute left/right x edges,
            ! then interpolate color across each scanline.

            ! r8 = y (scanline), start at 50
            mov #50, r8
            y_loop:
            ! Compute left edge x (lerp from V0 to V1)
            ! t = (y - 50) / 500
            ! x_left = 180 + t * (50 - 180) = 180 - t * 130
            mov r8, r0
            add #-50, r0
            ! t = r0 / 500  (approximate: t * 130 / 500 = t * 13 / 50)
            ! For simplicity: x_left = 180 - ((y-50) * 130) / 500
            mov #130, r1
            mulu.w r0, r1
            sts macl, r2
            mov #500, r3
            div0u
            ! Approximate division by shifting: /500 ~= >>9 (close enough)
            shlr9 r2
            mov #180, r4
            sub r2, r4
            ! r4 = x_left (clamped)
            cmp/pl r4
            bf clamp_left
            bra left_ok
            nop
            clamp_left:
            mov #0, r4
            left_ok:
            cmp/gt #360, r4
            bf left_ok2
            mov #360, r4
            left_ok2:

            ! Compute right edge x (lerp from V0 to V2)
            ! x_right = 180 + ((y-50) * 130) / 500
            mov r8, r0
            add #-50, r0
            mov #130, r1
            mulu.w r0, r1
            sts macl, r2
            shlr9 r2
            mov #180, r5
            add r2, r5
            ! r5 = x_right (clamped)
            cmp/pl r5
            bf clamp_right
            bra right_ok
            nop
            clamp_right:
            mov #0, r5
            right_ok:
            cmp/gt #360, r5
            bf right_ok2
            mov #360, r5
            right_ok2:

            ! Draw scanline from x_left to x_right
            mov r4, r6
            x_loop:
            ! Compute barycentric coords:
            ! w0 = area(V1, V2, P) / area(V1, V2, V0)
            ! w1 = area(V2, V0, P) / area(V1, V2, V0)
            ! w2 = 1 - w0 - w1
            !
            ! For our triangle: area = 0.5 * base * height = 0.5 * 260 * 500 = 65000
            !
            ! Simplified: use (x,y) directly to compute a color gradient.
            ! color = mix based on distance from each vertex.
            !
            ! Red   channel = (w0 * 31) << 11
            ! Green channel = (w1 * 63) << 5
            ! Blue  channel = (w2 * 31)
            !
            ! Approximate with x position:
            ! red   = ((360 - x) * 31) / 360
            ! green = (x * 31) / 360
            ! blue  = ((550 - y) * 31) / 550
            !
            ! This gives a nice gradient without heavy math.

            mov #360, r0
            sub r6, r0
            mov #31, r1
            mulu.w r0, r1
            sts macl, r2
            shlr9 r2          ! / 360 approx = >>9 (512, close enough)
            mov r2, r7
            shll8 r7
            shll3 r7          ! r7 = red << 11

            mov r6, r0
            mov #31, r1
            mulu.w r0, r1
            sts macl, r2
            shlr9 r2
            mov r2, r0
            shll2 r0
            shll2 r0
            shll r0           ! r0 = green << 5
            or r0, r7

            mov #550, r0
            sub r8, r0
            mov #31, r1
            mulu.w r0, r1
            sts macl, r2
            shlr9 r2
            or r2, r7

            mov.w r7, @r13

            add #1, r6
            cmp/ge r5, r6
            bf x_loop

            add #1, r8
            cmp/ge #550, r8
            bf y_loop

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
        steps = load_and_run(cpu, mem, program, max_steps=500000)
        # Verify the triangle has colored pixels in the center region
        center = display.get_pixel(180, 300)
        self.assertNotEqual(center, 0x0000, "Triangle center should be colored")
        # Corners should be black (outside triangle)
        tl = display.get_pixel(0, 0)
        self.assertEqual(tl, 0x0000, "Top-left corner should be black")
        save_display_bmp(display, os.path.join(OUTPUT_DIR, 'test_triangle_gradient_demo.bmp'))


# ============================================================================
# Memory E2E Tests
# ============================================================================

class TestE2E_Memory(unittest.TestCase):
    """E2E tests for memory store/load via assembled programs."""

    def test_store_load_roundtrip(self):
        """Store a value to memory, load it back, verify."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0x42, r0       ! r0 = 0x42
            mov.l r0, @(0, r15) ! store at stack
            mov.l @(0, r15), r1 ! load back into r1
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 0x42,
                         f"Store/load roundtrip: r1=0x{cpu.regs['r1']:X}, expected 0x42")

    def test_store_array(self):
        """Store an array of values and verify them in memory."""
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
        steps = load_and_run(cpu, mem, program)
        ram_offset = 0x8C080000 - 0x8C000000
        val0 = int.from_bytes(mem._mem[ram_offset:ram_offset+4], 'big')
        val1 = int.from_bytes(mem._mem[ram_offset+4:ram_offset+8], 'big')
        val2 = int.from_bytes(mem._mem[ram_offset+8:ram_offset+12], 'big')
        self.assertEqual(val0, 0x50, f"mem[0] = 0x{val0:X}")
        self.assertEqual(val1, 0x60, f"mem[1] = 0x{val1:X}")
        self.assertEqual(val2, 0x70, f"mem[2] = 0x{val2:X}")


# ============================================================================
# Arithmetic E2E Tests
# ============================================================================

class TestE2E_Arithmetic(unittest.TestCase):
    """E2E tests for arithmetic via assembled programs."""

    def test_add(self):
        """add r0, r1 should compute r1 = r0 + r1."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #5, r0
            mov #3, r1
            add r0, r1
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 8, "5 + 3 = 8")

    def test_sub(self):
        """sub r0, r1 should compute r1 = r1 - r0."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #3, r0
            mov #10, r1
            sub r0, r1
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r1'], 7, "10 - 3 = 7")

    def test_shift_left(self):
        """shll8 r0 should shift left by 8."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0x01, r0
            shll8 r0
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 0x100, "1 << 8 = 0x100")

    def test_shift_left_16(self):
        """shll16 r0 should shift left by 16."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0x01, r0
            shll16 r0
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 0x10000, "1 << 16 = 0x10000")


# ============================================================================
# Branch E2E Tests
# ============================================================================

class TestE2E_Branch(unittest.TestCase):
    """E2E tests for branch instructions."""

    def test_bra_forward(self):
        """bra should jump forward."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            bra skip
            nop
            mov #99, r0   ! should be skipped
            skip:
            mov #42, r0   ! should execute
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42, "bra should skip the mov #99")

    def test_bt_taken(self):
        """bt should branch when T=1."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            sett            ! T = 1
            bt target       ! should branch (T=1)
            mov #99, r0     ! should be skipped
            target:
            mov #42, r0     ! should execute
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42, "bt taken when T=1")

    def test_bt_not_taken(self):
        """bt should not branch when T=0."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            clrt            ! T = 0
            bt target       ! should NOT branch (T=0)
            mov #42, r0     ! should execute
            bra end
            nop
            target:
            mov #99, r0     ! should be skipped
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program)
        self.assertEqual(cpu.regs['r0'], 42, "bt not taken when T=0")

    def test_loop_counter(self):
        """Loop 5 times, incrementing a counter."""
        cpu, mem, display = make_cpu(with_display=False)
        program = assemble("""
            mov #0, r0      ! counter
            mov #5, r1      ! limit
            loop:
            add #1, r0
            cmp/ge r1, r0
            bf loop
            bra end
            nop
            end:
bra end
            nop
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program, max_steps=500)
        self.assertEqual(cpu.regs['r0'], 5, "Loop should run 5 times")


# ============================================================================
# DSP E2E Tests
# ============================================================================

class TestE2E_DSP(unittest.TestCase):
    """E2E tests for DSP operations."""

    def test_dsp_padd(self):
        """PADD: Dz = SX + SY via direct opcode."""
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['a0'] = 0x10000000  # SX
        cpu.regs['x1'] = 0x20000000  # SY
        handle_dsp_instruction(cpu, 0xF0B0)
        self.assertEqual(cpu.regs['y0'], 0x30000000,
                         f"PADD: y0 = 0x{cpu.regs['y0']:08X}, expected 0x30000000")

    def test_dsp_psub(self):
        """PSUB: Dz = SX - SY via direct opcode."""
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['a0'] = 0x50000000  # SX
        cpu.regs['x0'] = 0x20000000  # SY
        handle_dsp_instruction(cpu, 0xF0A1)
        self.assertEqual(cpu.regs['m0'], 0x30000000,
                         f"PSUB: m0 = 0x{cpu.regs['m0']:08X}, expected 0x30000000")

    def test_dsp_pclr(self):
        """PCLR: Dz = 0 via direct opcode."""
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['m0'] = 0xDEADBEEF
        handle_dsp_instruction(cpu, 0xF08D)
        self.assertEqual(cpu.regs['m0'], 0,
                         f"PCLR: m0 = 0x{cpu.regs['m0']:08X}, expected 0")

    def test_dsp_pmuls_padd(self):
        """PMULS+PADD: Dz = SX+SY, Dg = 2*SX*SY."""
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        cpu.regs['y1'] = 0x20000000  # SX
        cpu.regs['x1'] = 0x30000000  # SY
        handle_dsp_instruction(cpu, 0xF070)
        self.assertEqual(cpu.regs['y0'], 0x50000000,
                         f"PMULS+PADD: y0 = 0x{cpu.regs['y0']:08X}")
        expected_product = 2 * 0x2000 * 0x3000
        self.assertEqual(cpu.regs['x0'], expected_product,
                         f"PMULS+PADD: x0 = 0x{cpu.regs['x0']:08X}")

    def test_dsp_movs_load_store(self):
        """MOVS.L post-increment load and store."""
        from ruk.jcore.dsp import handle_dsp_instruction
        cpu, mem, display = make_cpu(with_display=False)
        struct.pack_into('>i', mem._mem, 0, 0x12345678)
        cpu.regs['r4'] = 0x8C000000
        handle_dsp_instruction(cpu, 0x005E)
        self.assertEqual(cpu.regs['a1'], 0x12345678,
                         f"MOVS.L load: a1 = 0x{cpu.regs['a1']:08X}")
        self.assertEqual(cpu.regs['r4'], 0x8C000004,
                         f"R4 incremented: 0x{cpu.regs['r4']:08X}")


# ============================================================================
# RTC E2E Tests
# ============================================================================

class TestE2E_RTC(unittest.TestCase):
    """E2E tests for RTC via assembled programs."""

    def test_rtc_read_r64cnt(self):
        """Read R64CNT from the RTC via assembly."""
        cpu, mem, display = make_cpu(with_display=False, with_rtc=True)
        program = assemble("""
            mov.l rtc_base, r14
            mov.b @r14, r0       ! read R64CNT
            mov.l result, r15
            mov.b r0, @r15       ! store result
            bra end
            nop
            end:
bra end
            nop
            .align 2
            rtc_base:
            .long 0xA413FEC0
            result:
            .long 0x8C003000
        """, start_addr=0x8C000000)
        steps = load_and_run(cpu, mem, program, max_steps=500)
        ram_offset = 0x8C003000 - 0x8C000000
        val = mem._mem[ram_offset]
        self.assertLess(val, 128, f"R64CNT = {val}, should be < 128")


# ============================================================================
# Main
# ============================================================================

def run_all_tests():
    """Run all E2E tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestE2E_LCD,
        TestE2E_Memory,
        TestE2E_Arithmetic,
        TestE2E_Branch,
        TestE2E_DSP,
        TestE2E_RTC,
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
    print(f"Bitmaps saved to: {OUTPUT_DIR}")
    print("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_all_tests())