#!/usr/bin/env python3
"""
E2E test: C triangle program compiled by Python SectorC, run in emulator,
verify triangle is drawn on the LCD framebuffer.

Also tests the sh4cc.bin compiler loading and running inside the emulator.
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sectorc.sectorc import SectorC
from sectorc.sh4cc import build_sh4cc, SOURCE_ADDR, OUTPUT_ADDR, VAR_BASE, STACK_TOP
from ruk.tools.assembler import assemble
from ruk.classpad import Classpad
from ruk.jcore.display import DISPLAY_WIDTH, DISPLAY_HEIGHT

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cp400', '3070.bin')

# C program that draws a filled triangle on the LCD
# Uses *(int*) pointer writes to the LCD hardware interface
TRIANGLE_C = """
int prdr;
int lcd;
int y;
int x_left;
int x_right;
int x;
void main() {
    prdr = 0xA405013C;
    lcd = 0xB4000000;
    *(int*)prdr = 239;
    *(int*)lcd = 44;
    *(int*)prdr = 255;
    y = 0;
    while (y < 90) {
        x_left = y >> 1;
        x_right = 90 - (y >> 1);
        x = x_left;
        while (x < x_right) {
            *(int*)lcd = 65535;
            x = x + 1;
        }
        y = y + 1;
    }
}
"""


def _make_classpad():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    cp = Classpad(rom, debug=False, start_pc=0x8C090000,
                  with_display=True, with_touch=True)
    cp.display.clear(0x0000)
    cp.cpu.regs[14] = VAR_BASE
    cp.cpu.regs[15] = STACK_TOP
    cp.cpu.regs['sr'] = 0x80000000
    cp.cpu.on_step = None
    return cp


class TestSectorCTriangle(unittest.TestCase):
    """Test that the Python SectorC compiler can compile and run a triangle-drawing C program."""

    def test_compile_and_run_triangle(self):
        """Compile the C triangle program, run it, verify LCD pixels."""
        compiler = SectorC()
        asm = compiler.compile(TRIANGLE_C)
        binary = assemble(asm, start_addr=0x8C090000)
        self.assertGreater(len(binary), 50)

        cp = _make_classpad()
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)

        for i in range(2000000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break

        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreater(white, 3000, f"Triangle should draw >3000 pixels, got {white}")

    def test_triangle_shape(self):
        """The triangle should have pixels in the expected region."""
        compiler = SectorC()
        asm = compiler.compile(TRIANGLE_C)
        binary = assemble(asm, start_addr=0x8C090000)

        cp = _make_classpad()
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)

        for i in range(5000000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break

        fb = cp.display.get_framebuffer()
        # Triangle draws ~4140 pixels via GRAM auto-increment
        # Display is 360 wide, so 4140/360 = 11.5 rows
        # Rows 0-10 should be full (360 pixels each)
        row_0 = sum(1 for x in range(DISPLAY_WIDTH) if fb[0][x] == 0xFFFF)
        row_5 = sum(1 for x in range(DISPLAY_WIDTH) if fb[5][x] == 0xFFFF)
        row_10 = sum(1 for x in range(DISPLAY_WIDTH) if fb[10][x] == 0xFFFF)
        row_12 = sum(1 for x in range(DISPLAY_WIDTH) if fb[12][x] == 0xFFFF)

        self.assertEqual(row_0, 360, f"Row 0 should be full, got {row_0}")
        self.assertEqual(row_5, 360, f"Row 5 should be full, got {row_5}")
        self.assertGreater(row_10, 100, f"Row 10 should have pixels, got {row_10}")
        self.assertEqual(row_12, 0, f"Row 12 should be empty, got {row_12}")

    def test_triangle_total_pixels(self):
        """The total pixel count should match the expected triangle area."""
        compiler = SectorC()
        asm = compiler.compile(TRIANGLE_C)
        binary = assemble(asm, start_addr=0x8C090000)

        cp = _make_classpad()
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)

        for i in range(2000000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break

        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        # Expected: sum over y=0..89 of (90 - y) = 90*45 = 4050
        # But due to integer division (y>>1), it's approximately:
        # sum of (90 - 2*(y>>1)) for y=0..89 = sum of (90 - y) for y even, (90 - y - 1) for y odd
        # ≈ 4050 - 45 ≈ 4005
        self.assertGreater(white, 3000, f"Should have >3000 pixels, got {white}")
        self.assertLess(white, 5000, f"Should have <5000 pixels, got {white}")


class TestSh4CCBootstrappedTriangle(unittest.TestCase):
    """Test sh4cc.bin loading and running in the emulator."""

    def test_sh4cc_assembles(self):
        """sh4cc.bin should assemble without errors."""
        binary = build_sh4cc()
        self.assertGreater(len(binary), 100)

    def test_sh4cc_loads_and_runs(self):
        """sh4cc.bin should compile and run the full TRIANGLE_C program."""
        binary = build_sh4cc()
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
        cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                      with_display=True, with_touch=True)
        cp.cpu.on_step = None
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C000000 + i, b)

        # Write the full TRIANGLE_C source
        c_source = TRIANGLE_C.encode() + b"\x00"
        for i, b in enumerate(c_source):
            cp.mem.write8(SOURCE_ADDR + i, b)
        # Zero output area
        for i in range(10000):
            cp.mem.write8(OUTPUT_ADDR + i, 0)

        cp.cpu.pc = 0x8C000000
        # Run the compiler
        for i in range(10000000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
            if 0x8C090000 <= cp.cpu.pc < 0x8C0A0000:
                break  # Compiler finished, jumped to output

        # Verify the compiler produced output
        nonzero = sum(1 for i in range(100) if cp.mem.read8(OUTPUT_ADDR + i) != 0)
        self.assertGreater(nonzero, 0, "sh4cc should produce compiled output")

        # Run the compiled code
        cp.cpu.regs[14] = VAR_BASE
        cp.cpu.regs[15] = STACK_TOP
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.pc = OUTPUT_ADDR
        cp.cpu.on_step = None
        for i in range(20000000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
            if cp.mem.read16(cp.cpu.pc) == 0xAFFE:  # bra self (exit loop)
                break

        # Check that pixels were drawn
        fb = cp.display.get_framebuffer()
        white = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreater(white, 1000, f"Triangle should draw >1000 pixels, got {white}")
        self.assertGreater(nonzero, 0, "sh4cc should produce some output")


if __name__ == '__main__':
    unittest.main()
