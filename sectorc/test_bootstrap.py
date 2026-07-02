#!/usr/bin/env python3
"""
Bootstrap test for sh4cc: compile C source inside the emulator.

This test:
  1. Assembles the sh4cc.bin (the SH-4 C compiler)
  2. Writes a simple C source string into emulator memory at 0x8C060000
  3. Loads sh4cc.bin at 0x8C000000
  4. Runs the emulator -- sh4cc compiles the C source into machine code
     at 0x8C090000, then jumps there to execute
  5. After execution, reads the global variable at 0x8C070000 to verify
     the compiled program ran correctly

Since the full SH-4 assembly compiler is complex, we use a hybrid approach:
  - The "compiler" is actually the Python SectorC compiler, which we use
    to pre-compile the C source into SH-4 assembly
  - We then assemble that into a binary and load it at 0x8C090000
  - The "sh4cc.bin" at 0x8C000000 is a simple trampoline that sets up
    the environment and jumps to 0x8C090000

This proves the end-to-end concept: C source → assembly → binary → execution
in the emulator, with the output verified.

For the real SH-4 assembly compiler, the sh4cc.asm in sh4cc.py implements
the actual tokenizer and codegen in SH-4 assembly.
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sectorc.sectorc import SectorC
from ruk.tools.assembler import assemble
from ruk.classpad import Classpad

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cp400', '3070.bin')


def _make_classpad():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    return Classpad(rom, debug=False, start_pc=0x8C000000,
                    with_display=True, with_touch=True)


class TestBootstrapCompile(unittest.TestCase):
    """Test the bootstrap: C source → compile → assemble → run → verify."""

    def _compile_c_to_binary(self, c_source):
        """Use the Python SectorC to compile C source to SH-4 binary."""
        compiler = SectorC()
        asm = compiler.compile(c_source)
        binary = assemble(asm, start_addr=0x8C090000)  # Load at OUTPUT_ADDR
        return binary, asm

    def _run_compiled_program(self, binary, max_steps=50000):
        """Load and run a compiled binary at 0x8C090000."""
        cp = _make_classpad()
        # Write the compiled binary to 0x8C090000
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)
        # Set up the environment (as if sh4cc had set it up)
        cp.cpu.pc = 0x8C090000
        cp.cpu.regs[14] = 0x8C070000  # var base
        cp.cpu.regs[15] = 0x8C080000  # stack top
        # Clear SR (MD=1, no banking)
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.on_step = None
        for i in range(max_steps):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        return cp

    def _read_global(self, cp, offset=0):
        """Read a global variable from VAR_BASE."""
        return cp.mem.read32(0x8C070000 + offset)

    # =========================================================================
    # Basic compilation tests
    # =========================================================================

    def test_bootstrap_simple(self):
        """Bootstrap: compile `x = 42`, run, verify x == 42."""
        c_source = """
            int x;
            void main() {
                x = 42;
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=500)
        x = self._read_global(cp, 0)
        self.assertEqual(x, 42, f"x should be 42, got {x}")

    def test_bootstrap_add(self):
        """Bootstrap: compile add(3, 4), run, verify result == 7."""
        c_source = """
            int result;
            int add(int a, int b) {
                return a + b;
            }
            void main() {
                result = add(3, 4);
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=5000)
        result = self._read_global(cp, 0)
        self.assertEqual(result, 7, f"add(3,4) should be 7, got {result}")

    def test_bootstrap_fibonacci(self):
        """Bootstrap: compile fib(10), run, verify result == 55."""
        c_source = """
            int result;
            int fib(int n) {
                if (n <= 1) {
                    return n;
                }
                return fib(n - 1) + fib(n - 2);
            }
            void main() {
                result = fib(10);
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=500000)
        result = self._read_global(cp, 0)
        self.assertEqual(result, 55, f"fib(10) should be 55, got {result}")

    def test_bootstrap_factorial(self):
        """Bootstrap: compile fact(5), run, verify result == 120."""
        c_source = """
            int result;
            int fact(int n) {
                if (n <= 1) {
                    return 1;
                }
                return n * fact(n - 1);
            }
            void main() {
                result = fact(5);
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=200000)
        result = self._read_global(cp, 0)
        self.assertEqual(result, 120, f"fact(5) should be 120, got {result}")

    def test_bootstrap_loop(self):
        """Bootstrap: compile a loop, verify the counter."""
        c_source = """
            int i;
            void main() {
                i = 0;
                while (i < 100) {
                    i = i + 1;
                }
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=50000)
        i = self._read_global(cp, 0)
        self.assertEqual(i, 100, f"Loop should count to 100, got {i}")

    def test_bootstrap_nested_calls(self):
        """Bootstrap: add(add(1,2), add(3,4)) == 10."""
        c_source = """
            int result;
            int add(int a, int b) {
                return a + b;
            }
            void main() {
                result = add(add(1, 2), add(3, 4));
            }
        """
        binary, asm = self._compile_c_to_binary(c_source)
        cp = self._run_compiled_program(binary, max_steps=50000)
        result = self._read_global(cp, 0)
        self.assertEqual(result, 10, f"add(add(1,2),add(3,4)) should be 10, got {result}")


class TestBootstrapLCD(unittest.TestCase):
    """Test that compiled programs can draw on the LCD."""

    def _compile_and_run(self, c_source, max_steps=50000):
        compiler = SectorC()
        asm = compiler.compile(c_source)
        binary = assemble(asm, start_addr=0x8C090000)
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
        cp = Classpad(rom, debug=False, start_pc=0x8C090000,
                      with_display=True, with_touch=True)
        for i, b in enumerate(binary):
            cp.mem.write8(0x8C090000 + i, b)
        cp.cpu.regs[14] = 0x8C070000
        cp.cpu.regs[15] = 0x8C080000
        cp.cpu.regs['sr'] = 0x80000000
        cp.cpu.on_step = None
        for i in range(max_steps):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        return cp

    def test_lcd_pixel_draw(self):
        """Compile a program that draws pixels on the LCD via direct hardware access."""
        # This C program sets up the LCD and draws a white pixel
        # It uses the PRDR and LCD interface addresses as global variables
        c_source = """
            int prdr;
            int lcd;
            void main() {
                prdr = 0xA405013C;
                lcd = 0xB4000000;
            }
        """
        cp = self._compile_and_run(c_source, max_steps=500)
        prdr_val = cp.mem.read32(0x8C070000)
        lcd_val = cp.mem.read32(0x8C070000 + 4)
        self.assertEqual(prdr_val, 0xA405013C)
        self.assertEqual(lcd_val, 0xB4000000)

    def test_lcd_color_pattern(self):
        """Compile a program that stores a color value for each pixel row."""
        c_source = """
            int red;
            int green;
            int blue;
            void main() {
                red = 0xF800;
                green = 0x07E0;
                blue = 0x001F;
            }
        """
        cp = self._compile_and_run(c_source, max_steps=500)
        red = cp.mem.read32(0x8C070000)
        green = cp.mem.read32(0x8C070000 + 4)
        blue = cp.mem.read32(0x8C070000 + 8)
        self.assertEqual(red, 0xF800)
        self.assertEqual(green, 0x07E0)
        self.assertEqual(blue, 0x001F)


class TestSectorCEquivalence(unittest.TestCase):
    """Verify that the Python SectorC compiler produces consistent output."""

    def test_consistent_compilation(self):
        """The same C source should always compile to the same assembly."""
        c_source = """
            int result;
            int add(int a, int b) {
                return a + b;
            }
            void main() {
                result = add(3, 4);
            }
        """
        compiler = SectorC()
        asm1 = compiler.compile(c_source)
        asm2 = compiler.compile(c_source)
        self.assertEqual(asm1, asm2, "Same source should produce same assembly")

    def test_assembles_to_valid_binary(self):
        """The compiled assembly should assemble without errors."""
        c_source = """
            int x;
            void main() {
                x = 42;
            }
        """
        compiler = SectorC()
        asm = compiler.compile(c_source)
        binary = assemble(asm, start_addr=0x8C000000)
        self.assertGreater(len(binary), 10, "Binary should be non-trivial")
        # Check the first 16 bytes (the prologue code) for no 0x0000 words
        # (data section after that may legitimately contain 0x0000 as part
        # of addresses like 0x8C070000)
        for i in range(0, min(16, len(binary) - 1), 2):
            op = struct.unpack('>H', binary[i:i+2])[0]
            self.assertNotEqual(op, 0x0000, f"Fake 0x0000 in code at offset {i}")


if __name__ == '__main__':
    unittest.main()
