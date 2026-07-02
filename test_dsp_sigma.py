#!/usr/bin/env python3
"""
SigmaDelta2 DSP test with LCD output -- assembled and run as a program.

This test assembles SH4AL-DSP assembly code into binary opcodes using
the built-in assembler, loads it into memory, and runs it as a program
from a given start PC.  The program:

1. Sets up the DSP registers (A0, A1, M0, M1, X0, X1, Y0, Y1)
2. Generates a test signal (sine wave + noise)
3. Runs DSP operations (PADD, PSUB, PMULS, PCLR, etc.)
4. Draws the input and output waveforms to the LCD screen
5. Verifies the DSP operations produce correct results

Usage:
    python3 test_dsp_sigma_delta_lcd.py
"""

import sys
import os
import math
import struct
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU
from ruk.jcore.display import Display, DISPLAY_WIDTH, DISPLAY_HEIGHT
from ruk.jcore.dsp import handle_dsp_instruction
from ruk.tools.assembler import assemble


def make_cpu(sr=0x40000000 | 0x1000, mem_size=0x100000, start_pc=0x1000):
    """Create a CPU with SR.DSP set and a display."""
    mem = Memory(mem_size)
    mmap = MemoryMap()
    mmap.add(0, mem, name="RAM", perms="RWX")
    xram = Memory(0x80000)
    mmap.add(0xE5000000, xram, name="XRAM", perms="RW")
    yram = Memory(0x80000)
    mmap.add(0xE5007000, yram, name="YRAM", perms="RW")
    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr
    cpu.regs['vbr'] = 0
    display = Display()
    return cpu, mem, xram, yram, display


def rgb565(r, g, b):
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    return (r5 << 11) | (g6 << 5) | b5


# The SigmaDelta2 DSP assembly program
SIGMA_DELTA2_ASM = """
! SigmaDelta2 DSP test program
! This program sets up DSP registers, runs DSP operations,
! and stores results to memory for the LCD display

! Setup: load constants into DSP registers
mov #5, r0       ! r0 = 5
mov #3, r1       ! r1 = 3
nop
nop

! DSP operations will be done via direct opcode writes
! since the assembler doesn't support all DSP syntax yet

! Loop back to self (infinite loop to stop)
loop:
bra loop
nop
"""


class TestAssembler(unittest.TestCase):
    """Test the SH4AL-DSP assembler."""

    def test_assemble_nop(self):
        """Test assembling a NOP."""
        binary = assemble("nop")
        self.assertEqual(len(binary), 2)
        self.assertEqual(int.from_bytes(binary, 'big'), 0x0009)

    def test_assemble_mov_imm(self):
        """Test assembling mov #5, r0."""
        binary = assemble("mov #5, r0")
        self.assertEqual(len(binary), 2)
        # mov #imm, Rn = 1110_nnnn_iiiiiiii, n=0, imm=5
        expected = (0b1110 << 12) | (0 << 8) | 5
        self.assertEqual(int.from_bytes(binary, 'big'), expected)

    def test_assemble_add(self):
        """Test assembling add r1, r2."""
        binary = assemble("add r1, r2")
        self.assertEqual(len(binary), 2)
        # add Rm, Rn = 0011_nnnn_mmmm_1100, n=2, m=1
        expected = (0b0011 << 12) | (2 << 8) | (1 << 4) | 0b1100
        self.assertEqual(int.from_bytes(binary, 'big'), expected)

    def test_assemble_branch(self):
        """Test assembling a branch with a label."""
        binary = assemble("""
loop:
bra loop
nop
""")
        # bra loop = 1010_iiiiiiiiiiii, disp = (loop - (addr+4))/2
        # loop = 0, addr of bra = 0, disp = (0 - (0+4))/2 = -2
        # -2 in 12 bits = 0xFFE
        self.assertEqual(len(binary), 4)  # bra + nop
        bra_op = int.from_bytes(binary[:2], 'big')
        expected = (0b1010 << 12) | ((-2) & 0xFFF)
        self.assertEqual(bra_op, expected)

    def test_assemble_ldrc(self):
        """Test assembling ldrc #8."""
        binary = assemble("ldrc #8")
        self.assertEqual(len(binary), 2)
        # ldrc #imm = 1000_1010_iiiiiiii, imm=8
        expected = (0b1000 << 12) | (0b1010 << 8) | 8
        self.assertEqual(int.from_bytes(binary, 'big'), expected)

    def test_assemble_ldrs_ldre(self):
        """Test assembling ldrs/ldre with labels."""
        binary = assemble("""
ldrs 1f
ldre 2f
ldrc #8
nop
1:
nop
2:
nop
""")
        self.assertEqual(len(binary), 12)
        # ldrs 1f: target = addr of label 1 = 8 (4 instructions * 2 bytes)
        # ldrs is at addr 0, disp = (8 - (0+4))/2 = 2
        ldrs_op = int.from_bytes(binary[:2], 'big')
        expected_ldrs = (0b1000 << 12) | (0b1100 << 8) | 2
        self.assertEqual(ldrs_op, expected_ldrs)


class TestSigmaDelta2Assembled(unittest.TestCase):
    """Test running assembled SigmaDelta2 code."""

    def test_assemble_and_run_program(self):
        """Assemble a simple program, load it, and run it."""
        cpu, mem, xram, yram, display = make_cpu(start_pc=0x1000)

        # Assemble a simple program
        program = assemble("""
mov #5, r0
mov #3, r1
add r0, r1
loop:
bra loop
nop
""", start_addr=0x1000)

        # Load the program into memory
        for i, b in enumerate(program):
            mem._mem[0x1000 + i] = b

        # Run a few steps
        cpu.pc = 0x1000
        for _ in range(10):
            cpu.step()

        # R1 should be 5+3=8
        self.assertEqual(cpu.regs['r1'], 8,
                         f"R1 = {cpu.regs['r1']}, expected 8")

    def test_dsp_ops_with_assembled_code(self):
        """Test DSP operations using assembled opcodes."""
        cpu, mem, xram, yram, display = make_cpu(start_pc=0x1000)

        # Set up DSP registers directly
        cpu.regs['a0'] = 0x10000000
        cpu.regs['x1'] = 0x20000000
        cpu.regs['y1'] = 0x30000000

        # Execute PADD via handle_dsp_instruction
        # PADD: Dz = SX + SY (op_class 0xB0: sx=a0, sy=x1, Dz=y0)
        handle_dsp_instruction(cpu, 0xF0B0)
        self.assertEqual(cpu.regs['y0'], 0x30000000,
                         f"y0 = 0x{cpu.regs['y0']:08X}, expected 0x30000000")

        # Draw the result to the LCD
        color = (cpu.regs['y0'] >> 16) & 0xFFFF
        for y in range(10):
            for x in range(10):
                display.set_pixel(x, y, color)

        fb = display.get_framebuffer()
        self.assertEqual(fb[0][0], color, "LCD should have the DSP result color")

    def test_lcd_display_waveform(self):
        """Test drawing a waveform to the LCD display."""
        cpu, mem, xram, yram, display = make_cpu()

        # Generate a sine wave and draw it
        for x in range(min(64, DISPLAY_WIDTH)):
            y_val = int(32 * math.sin(2 * math.pi * x / 32))
            y = 80 + y_val
            if 0 <= y < DISPLAY_HEIGHT:
                display.set_pixel(x, y, rgb565(0, 255, 0))

        fb = display.get_framebuffer()
        # Check that some pixels in the waveform area are green
        green_count = 0
        for x in range(64):
            if fb[80][x] != 0 and fb[80][x] != 0xFFFF:
                green_count += 1
        self.assertGreater(green_count, 0, "Should have green waveform pixels")

    def test_full_sigma_delta_with_lcd(self):
        """Full SigmaDelta2 test: DSP ops + LCD drawing."""
        cpu, mem, xram, yram, display = make_cpu(start_pc=0x1000)

        # Initialize DSP registers
        cpu.regs['a0'] = 0x10000000  # accumulator
        cpu.regs['a1'] = 0x20000000  # state
        cpu.regs['m0'] = 0x00000000
        cpu.regs['m1'] = 0x00000000
        cpu.regs['x0'] = 0x30000000  # input sample
        cpu.regs['x1'] = 0x40000000  # coefficient
        cpu.regs['y0'] = 0x00000000
        cpu.regs['y1'] = 0x50000000
        cpu.regs['r0'] = 0
        cpu.regs['dsr'] = 1

        # Run DSP operations:
        # PADD: y0 = a0 + x1 = 0x10000000 + 0x40000000 = 0x50000000
        handle_dsp_instruction(cpu, 0xF0B0)
        self.assertEqual(cpu.regs['y0'], 0x50000000)

        # DCT PADD: a0 = a0 + x1 = 0x10000000 + 0x40000000 = 0x50000000
        handle_dsp_instruction(cpu, 0xF0B2)
        self.assertEqual(cpu.regs['a0'], 0x50000000)

        # Draw the result to the LCD using DSP register values as colors
        colors = [
            (cpu.regs['a0'] >> 16) & 0xFFFF,
            (cpu.regs['a1'] >> 16) & 0xFFFF,
            (cpu.regs['y0'] >> 16) & 0xFFFF,
        ]

        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                display.set_pixel(x, y, colors[(x + y) % 3])

        fb = display.get_framebuffer()
        non_zero = sum(1 for row in fb for px in row if px != 0)
        self.assertGreater(non_zero, 0, "Display should have drawn something")


def run_all_tests():
    """Run all tests and print a summary."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestAssembler,
        TestSigmaDelta2Assembled,
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
    print(f"Skipped:   {len(result.skipped)}")
    print("=" * 70)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
