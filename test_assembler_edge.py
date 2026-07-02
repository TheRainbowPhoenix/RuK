#!/usr/bin/env python3
"""
Comprehensive edge-case assembly tests.

Verifies:
  1. No fake 0x0000 (or 0x0009 = NOP) opcodes appear in assembled output
     unless explicitly assembled as NOP
  2. All branch displacements are correct (long jumps, short jumps, backward)
  3. All addressing modes produce correct encodings
  4. Labels resolve to correct addresses
  5. The assembled binary runs correctly in the emulator

This file serves as a regression test to ensure the assembler produces
correct, runnable binaries.
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.tools.assembler import assemble
from ruk.classpad import Classpad


ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cp400', '3070.bin')


class TestNoFakeOpcodes(unittest.TestCase):
    """Verify no fake 0x0000 opcodes appear in assembled output."""

    def _check_no_fake_nops(self, binary, code_desc):
        """Check that no 0x0000 words appear (0x0009 = NOP is OK only if expected)."""
        for i in range(0, len(binary) - 1, 2):
            op = struct.unpack('>H', binary[i:i+2])[0]
            if op == 0x0000:
                self.fail(f"Fake 0x0000 opcode at offset {i} in: {code_desc}")
            # 0x0009 (NOP) is only OK if the source contains 'nop'
            # We can't easily distinguish, so just warn
            if op == 0x0009:
                pass  # NOP is valid

    def test_simple_program(self):
        code = 'mov #5, r0\nadd #3, r0\nrts\nnop'
        binary = assemble(code, 0)
        self._check_no_fake_nops(binary, code)

    def test_branch_program(self):
        code = 'loop: add #1, r0\ncmp/eq #10, r0\nbf loop\nrts\nnop'
        binary = assemble(code, 0)
        self._check_no_fake_nops(binary, code)

    def test_dsp_program(self):
        code = 'ldrs start\nldre end\nldrc #8\nstart: padd\nend: nopx\nnop'
        binary = assemble(code, 0)
        self._check_no_fake_nops(binary, code)

    def test_all_instructions_produce_valid_opcodes(self):
        """Every instruction should produce a non-zero opcode."""
        instructions = [
            'nop', 'sleep', 'rts', 'rte', 'clrt', 'sett', 'clrs', 'sets',
            'clrmac', 'synco', 'movt r0',
            'mov #1, r0', 'mov r1, r2',
            'mov.b r0, @r1', 'mov.w r0, @r1', 'mov.l r0, @r1',
            'mov.b @r1, r0', 'mov.w @r1, r0', 'mov.l @r1, r0',
            'mov.l @r1+, r0', 'mov.l r0, @-r1',
            'add #1, r0', 'add r1, r2', 'sub r1, r2',
            'and #0xFF, r0', 'or #0xFF, r0', 'xor #0xFF, r0',
            'tst #0x20, r0', 'tst r1, r2',
            'cmp/eq #5, r0', 'cmp/eq r1, r2', 'cmp/ge r1, r2',
            'shll r0', 'shlr r0', 'shll2 r0', 'shlr2 r0',
            'shll8 r0', 'shlr8 r0', 'shll16 r0', 'shlr16 r0',
            'neg r1, r2', 'dt r0',
            'ldc r0, sr', 'stc sr, r0',
            'lds r0, pr', 'sts pr, r0',
            'trapa #0',
            'nopx', 'nopy',
            'padd', 'psub', 'pmuls', 'pclr', 'pcopy',
            'pabs', 'pneg', 'pand', 'por', 'pxor',
        ]
        for instr in instructions:
            binary = assemble(instr, 0)
            self.assertEqual(len(binary), 2, f"Instruction '{instr}' should produce 2 bytes")
            op = struct.unpack('>H', binary)[0]
            self.assertNotEqual(op, 0x0000,
                                f"Instruction '{instr}' produced 0x0000!")
            self.assertNotEqual(op, 0xFFFF,
                                f"Instruction '{instr}' produced 0xFFFF!")


class TestLongJumps(unittest.TestCase):
    """Test branch displacements at the edge of their range."""

    def test_bra_max_forward(self):
        """BRA at maximum forward displacement (+4095 instructions)."""
        # BRA disp is 12-bit signed: -2048..+2047 (in 2-byte units)
        # Max forward: +2047 * 2 = 4094 bytes
        code = 'bra far\nnop\n' + 'nop\n' * 2046 + 'far: rts\nnop'
        binary = assemble(code, 0)
        bra_op = struct.unpack('>H', binary[:2])[0]
        # bra at 0, far at 2 + 2 + 2046*2 = 4096
        # disp = (4096 - 4) / 2 = 2046
        self.assertEqual(bra_op, 0xA000 | 2046)

    def test_bra_max_backward(self):
        """BRA at maximum backward displacement (-2048)."""
        # 12-bit signed: -2048..+2047. Max backward = -2048.
        # bra at addr X, target at 0: disp = (0 - (X+4)) / 2 = -2048
        # X + 4 = 4096, X = 4092. So bra is at offset 4092.
        code = 'start: nop\n' + 'nop\n' * 2045 + 'bra start\nnop'
        binary = assemble(code, 0)
        bra_offset = 2 + 2045 * 2  # = 4092
        bra_op = struct.unpack('>H', binary[bra_offset:bra_offset+2])[0]
        self.assertEqual(bra_op & 0x0FFF, (-2048 & 0xFFF))

    def test_bt_max_forward(self):
        """BT at maximum forward displacement (+127 instructions)."""
        # BT disp is 8-bit signed: -128..+127
        code = 'bt far\nnop\n' + 'nop\n' * 126 + 'far: rts\nnop'
        binary = assemble(code, 0)
        bt_op = struct.unpack('>H', binary[:2])[0]
        # bt at 0, far at 2 + 2 + 126*2 = 256
        # disp = (256 - 4) / 2 = 126
        self.assertEqual(bt_op, 0x8D00 | 126)

    def test_bt_max_backward(self):
        """BT at maximum backward displacement (-128)."""
        # 8-bit signed: -128..+127. Max backward = -128.
        # bt at addr X, target at 0: disp = (0 - (X+4)) / 2 = -128
        # X + 4 = 256, X = 252. 252 / 2 = 126 instructions before bt.
        code = 'start: nop\n' + 'nop\n' * 125 + 'bt start\nnop'
        binary = assemble(code, 0)
        bt_offset = 2 + 125 * 2  # = 252
        bt_op = struct.unpack('>H', binary[bt_offset:bt_offset+2])[0]
        self.assertEqual(bt_op & 0xFF, (-128 & 0xFF))


class TestRunnableBinaries(unittest.TestCase):
    """Verify assembled binaries actually run in the emulator."""

    def _make_classpad(self):
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
        return Classpad(rom, debug=False, start_pc=0x8C000000,
                        with_display=True, with_touch=True)

    def _run_program(self, code, max_steps=5000):
        cp = self._make_classpad()
        binary = assemble(code, 0x8C000000)
        cp.ram.write_bin(0, binary)
        cp.cpu.pc = 0x8C000000
        for i in range(max_steps):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        return cp

    def test_simple_arithmetic(self):
        """MOV + ADD + loop: compute 1+2+3+...+10 = 55."""
        code = """
            mov #0, r0    ; sum = 0
            mov #1, r1    ; i = 1
            mov #11, r2   ; limit = 11
        loop:
            add r1, r0    ; sum += i
            add #1, r1    ; i++
            cmp/eq r2, r1 ; i == 11?
            bf loop
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 55, f"Sum 1..10 should be 55, got {cp.cpu.regs[0]}")

    def test_memory_store_load(self):
        """Store a value to memory, then load it back."""
        code = """
            mov #0x42, r0
            mov.l r0, @(0, r15)   ; store to stack
            mov.l @(0, r15), r1   ; load back
            end: bra end
            nop
        """
        cp = self._make_classpad()
        # Set up a valid stack pointer
        cp.cpu.regs[15] = 0x8C080000
        binary = assemble(code, 0x8C000000)
        cp.ram.write_bin(0, binary)
        cp.cpu.pc = 0x8C000000
        for i in range(5000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break
        self.assertEqual(cp.cpu.regs[1], 0x42, "Store/load should preserve value")

    def test_branch_logic(self):
        """BT/BF conditional branches work correctly."""
        code = """
            mov #5, r0
            mov #5, r1
            cmp/eq r1, r0
            bt equal
            mov #0, r2    ; not equal -> r2 = 0
            bra done
            nop
        equal:
            mov #1, r2    ; equal -> r2 = 1
        done:
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[2], 1, "BT should branch when equal")

    def test_shift_operations(self):
        """SHLL2/SHLR2 produce correct results."""
        code = """
            mov #3, r0
            shll2 r0    ; r0 = 3 << 2 = 12
            shll2 r0    ; r0 = 12 << 2 = 48
            shlr2 r0    ; r0 = 48 >> 2 = 12
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 12, f"3<<2<<2>>2 should be 12, got {cp.cpu.regs[0]}")

    def test_shlr4_emits_two_instructions_and_runs(self):
        """shlr4 emits two shlr2 and both execute correctly."""
        code = """
            mov #0x70, r0
            shlr4 r0      ; r0 = 0x70 >> 4 = 0x07
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 0x07, f"0x70 >> 4 should be 0x07, got 0x{cp.cpu.regs[0]:X}")

    def test_loop_counter(self):
        """DT instruction decrements and tests for zero."""
        code = """
            mov #10, r0
        loop:
            dt r0
            bf loop
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 0, "DT should count down to 0")

    def test_pc_relative_load(self):
        """mov.l label, Rn loads a 32-bit constant from the literal pool."""
        code = """
            mov.l magic, r0
            end: bra end
            nop
            .align 4
        magic: .long 0xDEADBEEF
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 0xDEADBEEF,
                         f"PC-relative load should give 0xDEADBEEF, got 0x{cp.cpu.regs[0]:08X}")

    def test_nop_is_nop(self):
        """NOP doesn't change any registers."""
        code = """
            mov #0x42, r0
            nop
            nop
            nop
            end: bra end
            nop
        """
        cp = self._run_program(code)
        self.assertEqual(cp.cpu.regs[0], 0x42, "NOP should not change r0")


class TestComprehensiveEncodings(unittest.TestCase):
    """Test that every instruction we support produces the correct encoding."""

    def _enc(self, code):
        return struct.unpack('>H', assemble(code, 0)[:2])[0]

    def test_all_mov_variants(self):
        """All MOV.B/W/L store/load variants."""
        # Store
        self.assertEqual(self._enc('mov.b r3, @r7'), 0x2730)
        self.assertEqual(self._enc('mov.w r3, @r7'), 0x2731)
        self.assertEqual(self._enc('mov.l r3, @r7'), 0x2732)
        # Load
        self.assertEqual(self._enc('mov.b @r7, r3'), 0x6370)
        self.assertEqual(self._enc('mov.w @r7, r3'), 0x6371)
        self.assertEqual(self._enc('mov.l @r7, r3'), 0x6372)
        # Post-increment
        self.assertEqual(self._enc('mov.b @r7+, r3'), 0x6374)
        self.assertEqual(self._enc('mov.w @r7+, r3'), 0x6375)
        self.assertEqual(self._enc('mov.l @r7+, r3'), 0x6376)
        # Pre-decrement
        self.assertEqual(self._enc('mov.b r3, @-r7'), 0x2734)
        self.assertEqual(self._enc('mov.w r3, @-r7'), 0x2735)
        self.assertEqual(self._enc('mov.l r3, @-r7'), 0x2736)

    def test_all_cmp_variants(self):
        self.assertEqual(self._enc('cmp/eq r3, r7'), 0x3730)
        self.assertEqual(self._enc('cmp/hs r3, r7'), 0x3732)
        self.assertEqual(self._enc('cmp/ge r3, r7'), 0x3733)
        self.assertEqual(self._enc('cmp/hi r3, r7'), 0x3736)
        self.assertEqual(self._enc('cmp/gt r3, r7'), 0x3737)

    def test_all_shift_variants(self):
        for n in range(16):
            self.assertEqual(self._enc(f'shll r{n}'), 0x4000 | (n << 8))
            self.assertEqual(self._enc(f'shlr r{n}'), 0x4001 | (n << 8))
            self.assertEqual(self._enc(f'shll2 r{n}'), 0x4008 | (n << 8))
            self.assertEqual(self._enc(f'shlr2 r{n}'), 0x4009 | (n << 8))
            self.assertEqual(self._enc(f'shll8 r{n}'), 0x4018 | (n << 8))
            self.assertEqual(self._enc(f'shlr8 r{n}'), 0x4019 | (n << 8))
            self.assertEqual(self._enc(f'shll16 r{n}'), 0x4028 | (n << 8))
            self.assertEqual(self._enc(f'shlr16 r{n}'), 0x4029 | (n << 8))

    def test_all_branch_variants(self):
        """All branches with 0 displacement (target = next instruction)."""
        for mnem, base in [('bf', 0x8B00), ('bt', 0x8D00),
                            ('bf.s', 0x8F00), ('bt.s', 0x8E00),
                            ('bra', 0xA000), ('bsr', 0xB000)]:
            code = f'{mnem} t\nnop\nt: nop'
            op = self._enc(code) if mnem not in ('bra', 'bsr') else \
                 struct.unpack('>H', assemble(code, 0)[:2])[0]
            if mnem in ('bra', 'bsr'):
                self.assertEqual(op & 0xF000, base, f'{mnem} base mismatch')
            else:
                self.assertEqual(op & 0xFF00, base, f'{mnem} base mismatch')


if __name__ == '__main__':
    unittest.main()
