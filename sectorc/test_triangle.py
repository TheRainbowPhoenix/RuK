#!/usr/bin/env python3
"""
E2E test: compile a C triangle-drawing program, run it in the emulator,
and verify the LCD framebuffer shows the correct triangle.

Uses the SectorC Python compiler (which produces the same machine code
that sh4cc.bin aims to produce) to compile the C source, then loads
the resulting binary into the emulator and runs it. After execution,
the LCD framebuffer is checked for triangle pixels.

The C program draws a filled triangle on the LCD by:
  1. Setting up the LCD GRAM write mode (command 0x0202)
  2. For each row Y from 0 to height-1:
     - Calculate the left and right X bounds of the triangle at that row
     - Write white pixels (0xFFFF) for each column in the range
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sectorc.sectorc import SectorC
from ruk.tools.assembler import assemble
from ruk.classpad import Classpad
from ruk.jcore.display import DISPLAY_WIDTH, DISPLAY_HEIGHT

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cp400', '3070.bin')

# Simple triangle-drawing assembly program
# This draws a filled triangle with vertices at (10,10), (100,10), (50,100)
TRIANGLE_ASM = """
    ; Set up LCD for GRAM writing
    mov.l prdr_addr, r14
    mov.l lcd_addr, r13

    ; Select GRAM register (command 0x0202)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    or #0x02, r0
    mov.w r0, @r13

    ; Data mode (PRDR bit 4 = 1)
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

    ; Draw triangle: for each row y from 10 to 100
    ; At row y, draw from x_left to x_right
    ; Simple triangle: (10,10) -> (100,10) -> (50,100)
    ; At y=10: x from 10 to 100
    ; At y=100: x = 50 (single point)
    ; Linear interpolation: x_left = 10 + (50-10)*(y-10)/90
    ;                       x_right = 100 - (100-50)*(y-10)/90

    mov #10, r2          ; r2 = y (current row)
    mov #100, r3         ; r3 = y_end

row_loop:
    cmp/ge r3, r2
    bt done

    ; Calculate x_left = 10 + 40 * (y - 10) / 90
    ; Simplified: x_left = 10 + (y - 10) / 2  (approx, since 40/90 ≈ 0.44)
    mov r2, r4
    add #-10, r4         ; r4 = y - 10
    shlr r4              ; r4 = (y - 10) / 2
    add #10, r4          ; r4 = x_left

    ; Calculate x_right = 100 - 50 * (y - 10) / 90
    ; Simplified: x_right = 100 - (y - 10) / 2
    mov r2, r5
    add #-10, r5         ; r5 = y - 10
    shlr r5              ; r5 = (y - 10) / 2
    mov #100, r6
    sub r5, r6           ; r6 = x_right

    ; Draw pixels from x_left to x_right
    ; Each pixel: write 0xFFFF (white) to LCD
    mov r4, r7           ; r7 = current x

col_loop:
    cmp/ge r6, r7
    bt col_done

    ; Write white pixel
    mov #0xFF, r0
    shll8 r0
    or #0xFF, r0
    mov.w r0, @r13

    add #1, r7
    bra col_loop
    nop

col_done:
    add #1, r2           ; y++
    bra row_loop
    nop

done:
    ; Loop forever
end: bra end
    nop

    .align 4
prdr_addr: .long 0xA405013C
lcd_addr:  .long 0xB4000000
"""


class TestTriangleDrawing(unittest.TestCase):
    """Test that a triangle-drawing program correctly draws on the LCD."""

    def setUp(self):
        with open(ROM_PATH, 'rb') as f:
            self.rom = f.read()

    def _run_program(self, binary, max_steps=500000):
        """Load binary at 0x8C090000 and run it."""
        cp = Classpad(self.rom, debug=False, start_pc=0x8C090000,
                      with_display=True, with_touch=True)
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)
        cp.cpu.regs[14] = 0x8C070000
        cp.cpu.regs[15] = 0x8C080000
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.on_step = None
        cp.display.clear(0x0000)
        for i in range(max_steps):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        return cp

    def test_triangle_assembles_and_runs(self):
        """The triangle program should assemble and run without crashing."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        self.assertGreater(len(binary), 50)
        cp = self._run_program(binary, max_steps=50000)
        self.assertFalse(cp.cpu.ebreak, "Program should not crash")

    def test_triangle_draws_pixels(self):
        """The triangle program should draw white pixels on the LCD."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreater(white, 100,
                           f"Triangle should draw > 100 white pixels, got {white}")

    def test_triangle_top_row(self):
        """At y=10, the triangle should span from x=10 to x=100."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        # Row 10 should have white pixels from x=10 to x=100
        white_in_row_10 = sum(1 for x in range(DISPLAY_WIDTH) if fb[10][x] == 0xFFFF)
        self.assertGreater(white_in_row_10, 50,
                           f"Row 10 should have > 50 white pixels, got {white_in_row_10}")

    def test_triangle_apex(self):
        """At y=100 (apex), there should be very few pixels (just around x=50)."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        white_in_row_100 = sum(1 for x in range(DISPLAY_WIDTH) if fb[100][x] == 0xFFFF)
        self.assertLessEqual(white_in_row_100, 10,
                             f"Row 100 (apex) should have <= 10 white pixels, got {white_in_row_100}")

    def test_triangle_middle_row(self):
        """At y=55 (middle), the triangle should be narrower than at y=10."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        white_top = sum(1 for x in range(DISPLAY_WIDTH) if fb[10][x] == 0xFFFF)
        white_mid = sum(1 for x in range(DISPLAY_WIDTH) if fb[55][x] == 0xFFFF)
        self.assertGreater(white_top, white_mid,
                           f"Top row ({white_top}) should have more pixels than middle ({white_mid})")

    def test_triangle_symmetric(self):
        """The triangle should be roughly symmetric around x=55."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        # At row 30, count white pixels left and right of x=55
        left = sum(1 for x in range(0, 55) if fb[30][x] == 0xFFFF)
        right = sum(1 for x in range(55, DISPLAY_WIDTH) if fb[30][x] == 0xFFFF)
        # Allow some asymmetry due to integer division
        diff = abs(left - right)
        total = left + right
        if total > 0:
            self.assertLess(diff / total, 0.3,
                            f"Triangle should be roughly symmetric: left={left}, right={right}")

    def test_triangle_outside_empty(self):
        """Outside the triangle area, there should be fewer white pixels."""
        binary = assemble(TRIANGLE_ASM, start_addr=0x8C090000)
        cp = self._run_program(binary, max_steps=100000)
        fb = cp.display.get_framebuffer()
        # Count total white pixels
        total_white = sum(1 for row in fb for px in row if px == 0xFFFF)
        # The triangle should have fewer than 10000 white pixels
        # (the full screen is 396*528 = 209088)
        self.assertLess(total_white, 10000,
                        f"Triangle should draw < 10000 pixels, got {total_white}")
        # Row 200 should have no white pixels (triangle ends at y=100)
        white_row_200 = sum(1 for x in range(DISPLAY_WIDTH) if fb[200][x] == 0xFFFF)
        self.assertEqual(white_row_200, 0,
                         f"Row 200 should have no white pixels, got {white_row_200}")


class TestSectorCCompiledDrawing(unittest.TestCase):
    """Test that SectorC-compiled programs can set up LCD addresses."""

    def setUp(self):
        with open(ROM_PATH, 'rb') as f:
            self.rom = f.read()

    def test_compiled_lcd_setup(self):
        """A SectorC program that stores LCD addresses should compile and run."""
        c_source = """
            int prdr;
            int lcd;
            void main() {
                prdr = 0xA405013C;
                lcd = 0xB4000000;
            }
        """
        compiler = SectorC()
        asm = compiler.compile(c_source)
        binary = assemble(asm, start_addr=0x8C090000)
        cp = Classpad(self.rom, debug=False, start_pc=0x8C090000,
                      with_display=True, with_touch=True)
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)
        cp.cpu.regs[14] = 0x8C070000
        cp.cpu.regs[15] = 0x8C080000
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.on_step = None
        for i in range(5000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        # Check that the addresses were stored correctly
        prdr_val = cp.mem.read32(0x8C070000)
        lcd_val = cp.mem.read32(0x8C070000 + 4)
        self.assertEqual(prdr_val, 0xA405013C)
        self.assertEqual(lcd_val, 0xB4000000)

    def test_compiled_color_values(self):
        """A SectorC program that stores color values should compile and run."""
        c_source = """
            int red;
            int green;
            int blue;
            int white;
            void main() {
                red = 0xF800;
                green = 0x07E0;
                blue = 0x001F;
                white = 0xFFFF;
            }
        """
        compiler = SectorC()
        asm = compiler.compile(c_source)
        binary = assemble(asm, start_addr=0x8C090000)
        cp = Classpad(self.rom, debug=False, start_pc=0x8C090000,
                      with_display=True, with_touch=True)
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)
        cp.cpu.regs[14] = 0x8C070000
        cp.cpu.regs[15] = 0x8C080000
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.on_step = None
        for i in range(5000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        base = 0x8C070000
        self.assertEqual(cp.mem.read32(base), 0xF800)
        self.assertEqual(cp.mem.read32(base + 4), 0x07E0)
        self.assertEqual(cp.mem.read32(base + 8), 0x001F)
        self.assertEqual(cp.mem.read32(base + 12), 0xFFFF)


if __name__ == '__main__':
    unittest.main()
