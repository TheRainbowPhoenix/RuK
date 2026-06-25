#!/usr/bin/env python3
"""
Tests for the SH4AL-DSP MOVS instruction set (all 16 modes).

The tests verify:
  - All 16 MOVS modes are correctly decoded and executed.
  - Word loads/stores respect the per-register "store mode":
      * X0/X1/Y0/Y1/M0/M1: upper 16 bits hold the data (fixed-point).
      * A0/A1: lower 16 bits hold the data (sign-extended).
      * A0G/A1G: lower 8 bits hold the guard value.
  - Long loads/stores transfer all 32 bits verbatim.
  - Pre-decrement subtracts the size BEFORE the access.
  - Post-increment adds the size AFTER the access.
  - Indexed modes use As + R0 as the effective address.
  - SR.DSP must be set for MOVS to dispatch (otherwise the standard
    SH-4 decoder handles the opcode).

Usage:
    python3 test_dsp_movs.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU, SR_MD
from ruk.jcore.dsp import (
    handle_dsp_instruction,
    is_dsp_instruction,
    _handle_movs,
    DSP_SINGLE_ADDR_REG_TABLE,
    DSP_SINGLE_DATA_REG_TABLE,
    DSP_STORE_MODE,
    _sext16_to_32,
    _shl16_to_32,
    _sext8_to_32,
)


def make_cpu(sr=0x40000000 | 0x1000, mem_size=0x10000, start_pc=0x0):
    """Create a CPU with a small flat memory, SR.DSP set by default.

    Default SR = 0x40001000 (MD=1, DSP=1, all other bits clear).
    """
    mem = Memory(mem_size)
    mmap = MemoryMap()
    mmap.add(0, mem, name="RAM", perms="RWX")
    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr
    cpu.regs['vbr'] = 0
    return cpu, mem


def encode_movs(as_idx, ds_idx, mode):
    """Encode a MOVS instruction.

    Format: 0000_00aa_dddd_mmmm
    """
    assert 0 <= as_idx <= 3
    assert 0 <= ds_idx <= 15
    assert 0 <= mode <= 15
    return ((as_idx & 0x3) << 8) | ((ds_idx & 0xF) << 4) | (mode & 0xF)


# Valid Ds indices (the ones that map to a real DSP register)
VALID_DS_INDICES = [i for i, name in enumerate(DSP_SINGLE_DATA_REG_TABLE) if name is not None]
# Ds index 5 -> a1, 7 -> a0, 8 -> y0, 9 -> y1, 10 -> m0, 11 -> m1,
# 12 -> x0, 13 -> a1g, 14 -> x1, 15 -> a0g


class TestMovsEncoding(unittest.TestCase):
    """Test opcode encoding and is_dsp_instruction detection."""

    def test_encode_decode_fields(self):
        """Verify that the encoding extracts the right fields."""
        # Example: MOVS.L @R4+, A1 = as=0 (R4), ds=5 (A1), mode=14 (post-inc L load)
        op = encode_movs(0, 5, 14)
        self.assertEqual(op & 0xF, 0xE)            # mode is in low nibble
        self.assertEqual((op >> 4) & 0xF, 5)       # Ds index
        self.assertEqual((op >> 8) & 0x3, 0)       # As index

    def test_is_dsp_instruction_recognizes_movs(self):
        """All MOVS opcodes (mode != 0) are detected as DSP."""
        for as_idx in range(4):
            for ds_idx in VALID_DS_INDICES:
                for mode in range(1, 16):
                    op = encode_movs(as_idx, ds_idx, mode)
                    self.assertTrue(is_dsp_instruction(op),
                                   f"MOVS op 0x{op:04X} not detected as DSP")

    def test_is_dsp_instruction_rejects_nop(self):
        """0x0000 is NOP, not a MOVS instruction."""
        self.assertFalse(is_dsp_instruction(0x0000))

    def test_is_dsp_instruction_recognizes_operations(self):
        """0xF0xx opcodes are DSP operations."""
        for op in [0xF000, 0xF040, 0xF080, 0xF0FF]:
            self.assertTrue(is_dsp_instruction(op),
                            f"0x{op:04X} not detected as DSP operation")

    def test_is_dsp_instruction_recognizes_double(self):
        """0xF4xx and 0xF5xx opcodes are DSP double data."""
        for op in [0xF400, 0xF500, 0xF4FF, 0xF5FF]:
            self.assertTrue(is_dsp_instruction(op),
                            f"0x{op:04X} not detected as DSP double")


class TestMovsDispatch(unittest.TestCase):
    """Test that handle_dsp_instruction dispatches correctly."""

    def test_movs_not_handled_when_sr_dsp_clear(self):
        """MOVS is not handled when SR.DSP=0 (falls back to standard SH-4)."""
        cpu, mem = make_cpu(sr=0x40000000)  # MD=1, DSP=0
        op = encode_movs(0, 5, 14)  # MOVS.L @R4+, A1
        self.assertFalse(handle_dsp_instruction(cpu, op),
                         "MOVS should not be handled when SR.DSP=0")

    def test_movs_handled_when_sr_dsp_set(self):
        """MOVS is handled when SR.DSP=1."""
        cpu, mem = make_cpu(sr=0x40001000)  # MD=1, DSP=1
        # Set up memory for the load
        cpu.regs['r4'] = 0x100
        mem.write32(0x100, 0xDEADBEEF)
        op = encode_movs(0, 5, 14)  # MOVS.L @R4+, A1
        self.assertTrue(handle_dsp_instruction(cpu, op),
                        "MOVS should be handled when SR.DSP=1")

    def test_movs_invalid_ds_index_returns_false(self):
        """Invalid Ds indices (0-4, 6) return False (not handled)."""
        cpu, mem = make_cpu()
        for invalid_ds in [0, 1, 2, 3, 4, 6]:
            op = encode_movs(0, invalid_ds, 4)
            self.assertFalse(handle_dsp_instruction(cpu, op),
                             f"Invalid Ds={invalid_ds} should not be handled")


class TestMovsDirectMode(unittest.TestCase):
    """Test direct load/store modes (modes 4-7)."""

    def test_movs_w_load_direct_to_x0(self):
        """MOVS.W @As, X0 (mode 4): load word into X0 upper bits."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x1234)
        op = encode_movs(0, 12, 4)  # As=R4, Ds=X0, mode=4
        self.assertTrue(handle_dsp_instruction(cpu, op))
        # X0 should have 0x1234 in upper 16 bits
        self.assertEqual(cpu.regs['x0'], 0x12340000,
                         f"X0 = 0x{cpu.regs['x0']:08X}, expected 0x12340000")
        # R4 should be unchanged
        self.assertEqual(cpu.regs['r4'], 0x100)
        # PC should advance by 2
        self.assertEqual(cpu.pc, 0x2)

    def test_movs_w_load_direct_negative_to_x0(self):
        """MOVS.W @As, X0 with negative value: upper 16 bits = 0x8000, lower 16 = 0.

        Per libCPU73050 LABEL_7: `result = (unsigned int)(v7 << 16)` -- no
        sign extension into the lower 16 bits.
        """
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x8000)  # -32768
        op = encode_movs(0, 12, 4)  # As=R4, Ds=X0, mode=4
        handle_dsp_instruction(cpu, op)
        # X0 should be 0x80000000 (NOT 0x8000FFFF)
        self.assertEqual(cpu.regs['x0'], 0x80000000,
                         f"X0 = 0x{cpu.regs['x0']:08X}, expected 0x80000000")

    def test_movs_w_load_direct_to_a0(self):
        """MOVS.W @As, A0 (mode 4): load word into A0 upper 16 bits (per libCPU73050)."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x1234)
        op = encode_movs(0, 7, 4)  # As=R4, Ds=A0, mode=4
        handle_dsp_instruction(cpu, op)
        # A0 should have 0x12340000 (value in upper 16 bits, lower 16 = 0)
        # per libCPU73050 LABEL_7: `result = (unsigned int)(v7 << 16)`
        self.assertEqual(cpu.regs['a0'], 0x12340000,
                         f"A0 = 0x{cpu.regs['a0']:08X}, expected 0x12340000")
        # Guard bit A0G should be 0 (positive value)
        self.assertEqual(cpu.regs['a0g'], 0x00000000,
                         f"A0G = 0x{cpu.regs['a0g']:08X}, expected 0x00000000")

    def test_movs_w_load_direct_negative_to_a0(self):
        """MOVS.W @As, A0 with negative value: upper 16 = 0x8000, A0G = 0xFFFFFFFF."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x8000)  # -32768
        op = encode_movs(0, 7, 4)  # As=R4, Ds=A0, mode=4
        handle_dsp_instruction(cpu, op)
        # A0 should be 0x80000000 (value in upper 16 bits, lower 16 = 0)
        self.assertEqual(cpu.regs['a0'], 0x80000000,
                         f"A0 = 0x{cpu.regs['a0']:08X}, expected 0x80000000")
        # Guard bit A0G should be 0xFFFFFFFF (negative sign)
        self.assertEqual(cpu.regs['a0g'], 0xFFFFFFFF,
                         f"A0G = 0x{cpu.regs['a0g']:08X}, expected 0xFFFFFFFF")

    def test_movs_w_load_direct_to_a0g(self):
        """MOVS.W @As, A0G: load byte into A0G (sign-extended)."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x0042)  # 66
        op = encode_movs(0, 15, 4)  # As=R4, Ds=A0G, mode=4
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['a0g'], 0x00000042,
                         f"A0G = 0x{cpu.regs['a0g']:08X}, expected 0x00000042")

    def test_movs_l_load_direct_to_x0(self):
        """MOVS.L @As, X0 (mode 6): load 32 bits verbatim."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write32(0x100, 0xDEADBEEF)
        op = encode_movs(0, 12, 6)  # As=R4, Ds=X0, mode=6
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['x0'], 0xDEADBEEF,
                         f"X0 = 0x{cpu.regs['x0']:08X}, expected 0xDEADBEEF")

    def test_movs_l_load_direct_to_a1(self):
        """MOVS.L @As, A1 (mode 6): load 32 bits verbatim into A1."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write32(0x100, 0xCAFEBABE)
        op = encode_movs(0, 5, 6)  # As=R4, Ds=A1, mode=6
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['a1'], 0xCAFEBABE,
                         f"A1 = 0x{cpu.regs['a1']:08X}, expected 0xCAFEBABE")

    def test_movs_w_store_direct_from_x0(self):
        """MOVS.W X0, @As (mode 5): store upper 16 bits of X0."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['x0'] = 0xABCD1234
        op = encode_movs(0, 12, 5)  # As=R4, Ds=X0, mode=5
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x100), 0xABCD,
                         f"M[0x100] = 0x{mem.read16(0x100):04X}, expected 0xABCD")

    def test_movs_w_store_direct_from_a0(self):
        """MOVS.W A0, @As (mode 5): store upper 16 bits of A0 (per libCPU73050 case 5)."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['a0'] = 0xABCD1234
        op = encode_movs(0, 7, 5)  # As=R4, Ds=A0, mode=5
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x100), 0xABCD,
                         f"M[0x100] = 0x{mem.read16(0x100):04X}, expected 0xABCD")

    def test_movs_w_store_direct_from_a0g(self):
        """MOVS.W A0G, @As (mode 5): store upper 16 bits of A0G slot.

        Per libCPU73050 case 5, word store always reads the upper 16
        bits of the register's slot (offset +2).  For A0G/A1G (8-bit
        sign-extended value), the upper 16 bits hold the sign extension.
        """
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        # A0G = 0x000000AB (positive byte 0xAB)
        # Upper 16 bits = 0x0000 (sign extension of positive byte)
        cpu.regs['a0g'] = 0x000000AB
        op = encode_movs(0, 15, 5)  # As=R4, Ds=A0G, mode=5
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x100), 0x0000,
                         f"M[0x100] = 0x{mem.read16(0x100):04X}, expected 0x0000")

        # Test with a negative byte: A0G = 0xFFFFFF80 (-128)
        # Upper 16 bits = 0xFFFF (sign extension of negative byte)
        cpu.regs['a0g'] = 0xFFFFFF80
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x100), 0xFFFF,
                         f"M[0x100] = 0x{mem.read16(0x100):04X}, expected 0xFFFF")

    def test_movs_l_store_direct_from_x1(self):
        """MOVS.L X1, @As (mode 7): store all 32 bits of X1."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['x1'] = 0x11223344
        op = encode_movs(0, 14, 7)  # As=R4, Ds=X1, mode=7
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read32(0x100), 0x11223344,
                         f"M[0x100] = 0x{mem.read32(0x100):08X}, expected 0x11223344")


class TestMovsPreDecrement(unittest.TestCase):
    """Test pre-decrement modes (modes 8-11)."""

    def test_movs_w_predec_load_to_y0(self):
        """MOVS.W @-As, Y0 (mode 8): decrement As by 2, then load."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x102
        mem.write16(0x100, 0xBEEF)  # 0x100 = 0x102 - 2
        op = encode_movs(0, 8, 8)  # As=R4, Ds=Y0, mode=8
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['r4'], 0x100,
                         f"R4 = 0x{cpu.regs['r4']:08X}, expected 0x100")
        self.assertEqual(cpu.regs['y0'], 0xBEEF0000,
                         f"Y0 = 0x{cpu.regs['y0']:08X}, expected 0xBEEF0000")

    def test_movs_l_predec_load_to_m0(self):
        """MOVS.L @-As, M0 (mode 10): decrement As by 4, then load 32 bits."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x104
        mem.write32(0x100, 0x11223344)  # 0x100 = 0x104 - 4
        op = encode_movs(0, 10, 10)  # As=R4, Ds=M0, mode=10
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['r4'], 0x100,
                         f"R4 = 0x{cpu.regs['r4']:08X}, expected 0x100")
        self.assertEqual(cpu.regs['m0'], 0x11223344,
                         f"M0 = 0x{cpu.regs['m0']:08X}, expected 0x11223344")

    def test_movs_w_predec_store_from_y1(self):
        """MOVS.W Y1, @-As (mode 9): decrement As by 2, then store upper 16 bits."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x102
        cpu.regs['y1'] = 0xCAFED00D
        op = encode_movs(0, 9, 9)  # As=R4, Ds=Y1, mode=9
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['r4'], 0x100)
        self.assertEqual(mem.read16(0x100), 0xCAFE,
                         f"M[0x100] = 0x{mem.read16(0x100):04X}, expected 0xCAFE")

    def test_movs_l_predec_store_from_m1(self):
        """MOVS.L M1, @-As (mode 11): decrement As by 4, then store 32 bits."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x104
        cpu.regs['m1'] = 0xAABBCCDD
        op = encode_movs(0, 11, 11)  # As=R4, Ds=M1, mode=11
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['r4'], 0x100)
        self.assertEqual(mem.read32(0x100), 0xAABBCCDD,
                         f"M[0x100] = 0x{mem.read32(0x100):08X}, expected 0xAABBCCDD")


class TestMovsPostIncrement(unittest.TestCase):
    """Test post-increment modes (modes 12-15)."""

    def test_movs_w_postinc_load_to_x0(self):
        """MOVS.W @As+, X0 (mode 12): load word, then increment As by 2."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0x4242)
        op = encode_movs(0, 12, 12)  # As=R4, Ds=X0, mode=12
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['x0'], 0x42420000,
                         f"X0 = 0x{cpu.regs['x0']:08X}, expected 0x42420000")
        self.assertEqual(cpu.regs['r4'], 0x102,
                         f"R4 = 0x{cpu.regs['r4']:08X}, expected 0x102")

    def test_movs_w_postinc_load_negative_to_a1(self):
        """MOVS.W @As+, A1 (mode 12): negative word goes to upper 16 bits, A1G = 0xFFFFFFFF."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write16(0x100, 0xFF00)  # -256
        op = encode_movs(0, 5, 12)  # As=R4, Ds=A1, mode=12
        handle_dsp_instruction(cpu, op)
        # A1 should have 0xFF000000 (value in upper 16 bits, lower 16 = 0)
        # per libCPU73050 LABEL_7: `result = (unsigned int)(v7 << 16)`
        self.assertEqual(cpu.regs['a1'], 0xFF000000,
                         f"A1 = 0x{cpu.regs['a1']:08X}, expected 0xFF000000")
        # Guard bit A1G should be 0xFFFFFFFF (negative value)
        self.assertEqual(cpu.regs['a1g'], 0xFFFFFFFF,
                         f"A1G = 0x{cpu.regs['a1g']:08X}, expected 0xFFFFFFFF")
        self.assertEqual(cpu.regs['r4'], 0x102)

    def test_movs_l_postinc_load_to_a0(self):
        """MOVS.L @As+, A0 (mode 14): load 32 bits, then increment As by 4."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write32(0x100, 0xDEADBEEF)
        op = encode_movs(0, 7, 14)  # As=R4, Ds=A0, mode=14
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['a0'], 0xDEADBEEF,
                         f"A0 = 0x{cpu.regs['a0']:08X}, expected 0xDEADBEEF")
        self.assertEqual(cpu.regs['r4'], 0x104,
                         f"R4 = 0x{cpu.regs['r4']:08X}, expected 0x104")

    def test_movs_l_postinc_load_to_m1(self):
        """MOVS.L @As+, M1 (mode 14): load 32 bits into M1."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        mem.write32(0x100, 0x12345678)
        op = encode_movs(0, 11, 14)  # As=R4, Ds=M1, mode=14
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['m1'], 0x12345678)
        self.assertEqual(cpu.regs['r4'], 0x104)

    def test_movs_w_postinc_store_from_x0(self):
        """MOVS.W X0, @As+ (mode 13): store upper 16 bits, then increment As by 2."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['x0'] = 0xAAAA0000
        op = encode_movs(0, 12, 13)  # As=R4, Ds=X0, mode=13
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x100), 0xAAAA)
        self.assertEqual(cpu.regs['r4'], 0x102)

    def test_movs_l_postinc_store_from_a1(self):
        """MOVS.L A1, @As+ (mode 15): store 32 bits, then increment As by 4."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['a1'] = 0xCAFEBABE
        op = encode_movs(0, 5, 15)  # As=R4, Ds=A1, mode=15
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read32(0x100), 0xCAFEBABE)
        self.assertEqual(cpu.regs['r4'], 0x104)


class TestMovsIndexedMode(unittest.TestCase):
    """Test indexed modes (modes 0-3).

    The indexed modes use As + R0 as the effective address.
    """

    def test_movs_w_indexed_load_to_x0(self):
        """MOVS.W @As+Ix, X0 (mode 0): load from As + R0."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['r0'] = 0x10  # Ix = R0
        mem.write16(0x110, 0xBEEF)
        op = encode_movs(0, 12, 0)  # As=R4, Ds=X0, mode=0
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['x0'], 0xBEEF0000)
        # R4 should be unchanged (indexed mode doesn't modify As)
        self.assertEqual(cpu.regs['r4'], 0x100)

    def test_movs_l_indexed_load_to_a0(self):
        """MOVS.L @As+Ix, A0 (mode 2): load 32 bits from As + R0."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['r0'] = 0x20
        mem.write32(0x120, 0xDEADBEEF)
        op = encode_movs(0, 7, 2)  # As=R4, Ds=A0, mode=2
        handle_dsp_instruction(cpu, op)
        self.assertEqual(cpu.regs['a0'], 0xDEADBEEF)
        self.assertEqual(cpu.regs['r4'], 0x100)

    def test_movs_w_indexed_store_from_y0(self):
        """MOVS.W Y0, @As+Ix (mode 1): store upper 16 bits to As + R0."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['r0'] = 0x10
        cpu.regs['y0'] = 0x12340000
        op = encode_movs(0, 8, 1)  # As=R4, Ds=Y0, mode=1
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read16(0x110), 0x1234)
        self.assertEqual(cpu.regs['r4'], 0x100)

    def test_movs_l_indexed_store_from_y1(self):
        """MOVS.L Y1, @As+Ix (mode 3): store 32 bits to As + R0."""
        cpu, mem = make_cpu()
        cpu.regs['r4'] = 0x100
        cpu.regs['r0'] = 0x20
        cpu.regs['y1'] = 0xCAFED00D
        op = encode_movs(0, 9, 3)  # As=R4, Ds=Y1, mode=3
        handle_dsp_instruction(cpu, op)
        self.assertEqual(mem.read32(0x120), 0xCAFED00D)
        self.assertEqual(cpu.regs['r4'], 0x100)


class TestMovsAddressRegisters(unittest.TestCase):
    """Test that all four As register indices work (R4, R5, R2, R3)."""

    def test_all_as_registers_work(self):
        """MOVS uses R4, R5, R2, R3 for As indices 0, 1, 2, 3."""
        expected_regs = ['r4', 'r5', 'r2', 'r3']
        for as_idx, reg_name in enumerate(expected_regs):
            cpu, mem = make_cpu()
            cpu.regs[reg_name] = 0x200
            mem.write16(0x200, 0x1111 + as_idx)
            op = encode_movs(as_idx, 12, 4)  # MOVS.W @As, X0
            handle_dsp_instruction(cpu, op)
            expected = (0x1111 + as_idx) << 16
            self.assertEqual(cpu.regs['x0'], expected,
                             f"As={reg_name}: X0 = 0x{cpu.regs['x0']:08X}, "
                             f"expected 0x{expected:08X}")


class TestMovsAllDataRegisters(unittest.TestCase):
    """Test MOVS with all 10 valid DSP data registers."""

    def test_word_load_to_all_data_registers(self):
        """MOVS.W @As, Ds works for all valid Ds indices.

        Per libCPU73050 LABEL_7:
          - mode 0 (X0/X1/Y0/Y1/M0/M1): result = v7 << 16
          - mode 1 (A0/A1): result = v7 << 16, guard bit updated
          - mode 2 (A0G/A1G): result = sext8(v7)
        """
        for ds_idx, reg_name in enumerate(DSP_SINGLE_DATA_REG_TABLE):
            if reg_name is None:
                continue
            cpu, mem = make_cpu()
            cpu.regs['r4'] = 0x100
            test_val = 0x1234  # positive (no sign extension issues)
            mem.write16(0x100, test_val)
            op = encode_movs(0, ds_idx, 4)  # MOVS.W @As, Ds
            ok = handle_dsp_instruction(cpu, op)
            self.assertTrue(ok, f"MOVS.W @As, {reg_name} not handled")

            # Verify expected value based on store mode
            mode = DSP_STORE_MODE.get(reg_name, 0)
            if mode == 0:  # X0/X1/Y0/Y1/M0/M1: upper 16 bits, lower 16 = 0
                expected = _shl16_to_32(test_val)
            elif mode == 1:  # A0/A1: upper 16 bits (same as mode 0), plus guard
                expected = _shl16_to_32(test_val)
            elif mode == 2:  # A0G/A1G: byte (lower 8 bits, sign-extended)
                expected = _sext8_to_32(test_val & 0xFF)

            self.assertEqual(cpu.regs[reg_name], expected,
                             f"Ds={reg_name} (mode {mode}): "
                             f"got 0x{cpu.regs[reg_name]:08X}, "
                             f"expected 0x{expected:08X}")


class TestMovsLongModeAllRegisters(unittest.TestCase):
    """Test MOVS.L with all 10 valid DSP data registers."""

    def test_long_load_to_all_data_registers(self):
        """MOVS.L @As, Ds transfers all 32 bits verbatim."""
        test_val = 0xDEADBEEF
        for ds_idx, reg_name in enumerate(DSP_SINGLE_DATA_REG_TABLE):
            if reg_name is None:
                continue
            cpu, mem = make_cpu()
            cpu.regs['r4'] = 0x100
            mem.write32(0x100, test_val)
            op = encode_movs(0, ds_idx, 6)  # MOVS.L @As, Ds
            ok = handle_dsp_instruction(cpu, op)
            self.assertTrue(ok, f"MOVS.L @As, {reg_name} not handled")
            self.assertEqual(cpu.regs[reg_name], test_val,
                             f"Ds={reg_name}: got 0x{cpu.regs[reg_name]:08X}, "
                             f"expected 0x{test_val:08X}")


class TestMovsUserExample(unittest.TestCase):
    """Reproduce the user's SigmaDelta2 add-in MOVS sequence.

    The user provided this example DSP code in the conversation:

        MOVS.L @R4+, A1     ! post-increment load long, mode 14
        MOVS.W @R5+, X0     ! post-increment load word, mode 12
        MOVS.W @R5, X1      ! direct load word, mode 4
        MOVS.L @R4+, A0     ! post-increment load long, mode 14
        MOVS.L @R4+, M1     ! post-increment load long, mode 14
        ...
        MOVS.L A1, @R4+     ! post-increment store long, mode 15
        MOVS.L A0, @R4+     ! post-increment store long, mode 15
        MOVS.L M1, @R4      ! direct store long, mode 7
    """

    def test_sigma_delta_load_sequence(self):
        """Run the SigmaDelta2 MOVS load sequence from the user's example."""
        cpu, mem = make_cpu()
        # Set up source memory:
        #   R4 -> 0x1000 (long values for A1, A0, M1)
        #   R5 -> 0x2000 (word values for X0, X1)
        cpu.regs['r4'] = 0x1000
        cpu.regs['r5'] = 0x2000
        mem.write32(0x1000, 0x11111111)  # A1
        mem.write16(0x2000, 0x2222)      # X0
        mem.write16(0x2002, 0x3333)      # X1 (at @R5 after X0 load? No, X1 uses @R5 directly)
        # Wait, in the example MOVS.W @R5+, X0 then MOVS.W @R5, X1.
        # So after the first load, R5 advances by 2, and X1 loads from new R5.
        mem.write32(0x1004, 0x33333333)  # A0
        mem.write32(0x1008, 0x44444444)  # M1

        # Step 1: MOVS.L @R4+, A1 (mode 14, As=R4, Ds=A1=idx 5)
        handle_dsp_instruction(cpu, encode_movs(0, 5, 14))
        self.assertEqual(cpu.regs['a1'], 0x11111111)
        self.assertEqual(cpu.regs['r4'], 0x1004)

        # Step 2: MOVS.W @R5+, X0 (mode 12, As=R5, Ds=X0=idx 12)
        handle_dsp_instruction(cpu, encode_movs(1, 12, 12))
        self.assertEqual(cpu.regs['x0'], 0x22220000)
        self.assertEqual(cpu.regs['r5'], 0x2002)

        # Step 3: MOVS.W @R5, X1 (mode 4, As=R5, Ds=X1=idx 14)
        handle_dsp_instruction(cpu, encode_movs(1, 14, 4))
        self.assertEqual(cpu.regs['x1'], 0x33330000)
        self.assertEqual(cpu.regs['r5'], 0x2002)  # unchanged

        # Step 4: MOVS.L @R4+, A0 (mode 14, As=R4, Ds=A0=idx 7)
        handle_dsp_instruction(cpu, encode_movs(0, 7, 14))
        self.assertEqual(cpu.regs['a0'], 0x33333333)
        self.assertEqual(cpu.regs['r4'], 0x1008)

        # Step 5: MOVS.L @R4+, M1 (mode 14, As=R4, Ds=M1=idx 11)
        handle_dsp_instruction(cpu, encode_movs(0, 11, 14))
        self.assertEqual(cpu.regs['m1'], 0x44444444)
        self.assertEqual(cpu.regs['r4'], 0x100C)

    def test_sigma_delta_store_sequence(self):
        """Run the SigmaDelta2 MOVS store sequence from the user's example."""
        cpu, mem = make_cpu()
        # Set up register state
        cpu.regs['r4'] = 0x3000
        cpu.regs['a1'] = 0xAAAAAAAA
        cpu.regs['a0'] = 0xBBBBBBBB
        cpu.regs['m1'] = 0xCCCCCCCC

        # Step 1: MOVS.L A1, @R4+ (mode 15, As=R4, Ds=A1=idx 5)
        handle_dsp_instruction(cpu, encode_movs(0, 5, 15))
        self.assertEqual(mem.read32(0x3000), 0xAAAAAAAA)
        self.assertEqual(cpu.regs['r4'], 0x3004)

        # Step 2: MOVS.L A0, @R4+ (mode 15, As=R4, Ds=A0=idx 7)
        handle_dsp_instruction(cpu, encode_movs(0, 7, 15))
        self.assertEqual(mem.read32(0x3004), 0xBBBBBBBB)
        self.assertEqual(cpu.regs['r4'], 0x3008)

        # Step 3: MOVS.L M1, @R4 (mode 7, As=R4, Ds=M1=idx 11)
        handle_dsp_instruction(cpu, encode_movs(0, 11, 7))
        self.assertEqual(mem.read32(0x3008), 0xCCCCCCCC)
        self.assertEqual(cpu.regs['r4'], 0x3008)  # unchanged


class TestDspOperationStub(unittest.TestCase):
    """Test the DSP operation stub (0xF0xx).

    Since operations are stubbed as NOPs (returning _NO_DEST for both
    result slots), they should not modify any DSP register.  They
    should still advance the PC.
    """

    def test_dsp_operation_advances_pc(self):
        """Any 0xF0xx opcode should advance PC by 2."""
        cpu, mem = make_cpu()
        cpu.pc = 0
        op = 0xF061  # PCLR Dz (in the real implementation)
        ok = handle_dsp_instruction(cpu, op)
        self.assertTrue(ok)
        self.assertEqual(cpu.pc, 2)

    def test_dsp_operation_does_not_modify_regs(self):
        """Stubbed DSP operations should not modify any register."""
        cpu, mem = make_cpu()
        # Save register state
        saved = {k: v for k, v in cpu.regs._regs.items()}
        # Run a few different opcodes
        for op in [0xF000, 0xF040, 0xF061, 0xF080, 0xF0F0]:
            handle_dsp_instruction(cpu, op)
        # Verify no DSP register was modified
        for reg in ['x0', 'x1', 'y0', 'y1', 'a0', 'a1', 'a0g', 'a1g', 'm0', 'm1']:
            self.assertEqual(cpu.regs[reg], saved[reg],
                             f"{reg} modified by stubbed DSP op: "
                             f"0x{saved[reg]:08X} -> 0x{cpu.regs[reg]:08X}")

    def test_dsp_operation_not_handled_when_sr_dsp_clear(self):
        """0xF0xx is not handled when SR.DSP=0."""
        cpu, mem = make_cpu(sr=0x40000000)  # DSP=0
        op = 0xF061
        self.assertFalse(handle_dsp_instruction(cpu, op))


class TestMovxMovyStub(unittest.TestCase):
    """Test the MOVX/MOVY stub (0xF4xx, 0xF5xx)."""

    def test_movx_advances_pc(self):
        """MOVX opcodes should advance PC by 2 (stubbed)."""
        cpu, mem = make_cpu()
        cpu.pc = 0
        op = 0xF400
        ok = handle_dsp_instruction(cpu, op)
        self.assertTrue(ok)
        self.assertEqual(cpu.pc, 2)

    def test_movy_advances_pc(self):
        """MOVY opcodes should advance PC by 2 (stubbed)."""
        cpu, mem = make_cpu()
        cpu.pc = 0
        op = 0xF500
        ok = handle_dsp_instruction(cpu, op)
        self.assertTrue(ok)
        self.assertEqual(cpu.pc, 2)

    def test_movx_not_handled_when_sr_dsp_clear(self):
        """0xF4xx is not handled when SR.DSP=0."""
        cpu, mem = make_cpu(sr=0x40000000)
        self.assertFalse(handle_dsp_instruction(cpu, 0xF400))


def run_all_tests():
    """Run all DSP MOVS tests and print a summary."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestMovsEncoding,
        TestMovsDispatch,
        TestMovsDirectMode,
        TestMovsPreDecrement,
        TestMovsPostIncrement,
        TestMovsIndexedMode,
        TestMovsAddressRegisters,
        TestMovsAllDataRegisters,
        TestMovsLongModeAllRegisters,
        TestMovsUserExample,
        TestDspOperationStub,
        TestMovxMovyStub,
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
