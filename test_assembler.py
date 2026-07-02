#!/usr/bin/env python3
"""Comprehensive assembler tests for SH-4 and SH4AL-DSP instructions.

Tests:
  - All common SH-4 instructions (verified against SH-4 manual encodings)
  - DSP instructions (MOVS.W/L, PADD, PSUB, PMULS, PCLR, etc.)
  - LDRS/LDRE/LDRC
  - Labels (named, numeric 1f/1b, forward/backward)
  - Addressing modes (@Rn, @Rn+, @-Rn, @(disp,Rn), @(R0,Rn), @(disp,GBR))
  - Directives (.word, .long, .align, .byte, .space)
  - shlr4/shll4 (expands to two instructions)
  - Expressions (label+offset)
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.tools.assembler import assemble


class TestBasicInstructions(unittest.TestCase):
    """Test basic SH-4 instruction encodings."""

    def _asm(self, code):
        return assemble(code, start_addr=0)

    def _op(self, code, offset=0):
        bin = self._asm(code)
        return struct.unpack('>H', bin[offset:offset+2])[0]

    def test_nop(self):
        self.assertEqual(self._op('nop'), 0x0009)

    def test_sleep(self):
        self.assertEqual(self._op('sleep'), 0x001B)

    def test_rts(self):
        self.assertEqual(self._op('rts'), 0x000B)

    def test_rte(self):
        self.assertEqual(self._op('rte'), 0x002B)

    def test_synco(self):
        self.assertEqual(self._op('synco'), 0x00AB)

    def test_clrt(self):
        self.assertEqual(self._op('clrt'), 0x0008)

    def test_sett(self):
        self.assertEqual(self._op('sett'), 0x0018)

    def test_clrs(self):
        self.assertEqual(self._op('clrs'), 0x0048)

    def test_sets(self):
        self.assertEqual(self._op('sets'), 0x0058)

    def test_clrmac(self):
        self.assertEqual(self._op('clrmac'), 0x0028)


class TestMOV(unittest.TestCase):
    """Test MOV instruction variants."""

    def _asm(self, code):
        return assemble(code, start_addr=0)

    def _op(self, code, offset=0):
        return struct.unpack('>H', self._asm(code)[offset:offset+2])[0]

    def test_mov_imm(self):
        self.assertEqual(self._op('mov #0x10, r0'), 0xE010)
        self.assertEqual(self._op('mov #5, r3'), 0xE305)
        self.assertEqual(self._op('mov #-1, r7'), 0xE7FF)

    def test_mov_reg(self):
        self.assertEqual(self._op('mov r1, r2'), 0x6213)

    def test_mov_b_store(self):
        self.assertEqual(self._op('mov.b r0, @r1'), 0x2100)

    def test_mov_w_store(self):
        self.assertEqual(self._op('mov.w r0, @r1'), 0x2101)

    def test_mov_l_store(self):
        self.assertEqual(self._op('mov.l r0, @r1'), 0x2102)

    def test_mov_b_load(self):
        # MOV.B @Rm, Rn: 0110_nnnn_mmmm_0000, n=0, m=1 -> 0x6010
        self.assertEqual(self._op('mov.b @r1, r0'), 0x6010)

    def test_mov_w_load(self):
        # MOV.W @Rm, Rn: 0110_nnnn_mmmm_0001, n=0, m=1 -> 0x6011
        self.assertEqual(self._op('mov.w @r1, r0'), 0x6011)

    def test_mov_l_load(self):
        # MOV.L @Rm, Rn: 0110_nnnn_mmmm_0010, n=0, m=1 -> 0x6012
        self.assertEqual(self._op('mov.l @r1, r0'), 0x6012)

    def test_mov_l_postinc(self):
        # MOV.L @Rm+, Rn: 0110_nnnn_mmmm_0110, n=0, m=1 -> 0x6016
        self.assertEqual(self._op('mov.l @r1+, r0'), 0x6016)

    def test_mov_l_predec(self):
        self.assertEqual(self._op('mov.l r0, @-r1'), 0x2106)

    def test_mov_l_disp_indexed(self):
        # mov.l r0, @(4, r1) -> 0001_nnnn_mmmm_dddd, n=1, m=0, d=4/4=1
        bin = self._asm('mov.l r0, @(4, r1)')
        op = struct.unpack('>H', bin[:2])[0]
        # Encoding: 0001_nnnn_mmmm_dddd where dddd = disp/4 = 1
        self.assertEqual(op, 0x1101)


class TestArithmetic(unittest.TestCase):
    """Test arithmetic instructions."""

    def _op(self, code):
        return struct.unpack('>H', assemble(code, 0)[:2])[0]

    def test_add_imm(self):
        self.assertEqual(self._op('add #5, r3'), 0x7305)
        self.assertEqual(self._op('add #-1, r0'), 0x70FF)

    def test_add_reg(self):
        self.assertEqual(self._op('add r1, r2'), 0x321C)

    def test_sub_reg(self):
        self.assertEqual(self._op('sub r1, r2'), 0x3218)

    def test_neg(self):
        self.assertEqual(self._op('neg r1, r2'), 0x621B)


class TestLogic(unittest.TestCase):
    """Test logic instructions."""

    def _op(self, code):
        return struct.unpack('>H', assemble(code, 0)[:2])[0]

    def test_and_imm(self):
        self.assertEqual(self._op('and #0xFF, r0'), 0xC9FF)

    def test_or_imm(self):
        self.assertEqual(self._op('or #0xFF, r0'), 0xCBFF)

    def test_xor_imm(self):
        self.assertEqual(self._op('xor #0xFF, r0'), 0xCAFF)

    def test_and_reg(self):
        self.assertEqual(self._op('and r1, r2'), 0x2219)

    def test_tst_imm(self):
        self.assertEqual(self._op('tst #0x20, r0'), 0xC820)

    def test_tst_reg(self):
        self.assertEqual(self._op('tst r1, r2'), 0x2218)


class TestCompare(unittest.TestCase):
    """Test compare instructions."""

    def _op(self, code):
        return struct.unpack('>H', assemble(code, 0)[:2])[0]

    def test_cmp_eq_imm(self):
        self.assertEqual(self._op('cmp/eq #5, r0'), 0x8805)

    def test_cmp_eq_reg(self):
        self.assertEqual(self._op('cmp/eq r1, r2'), 0x3210)

    def test_cmp_ge(self):
        self.assertEqual(self._op('cmp/ge r1, r2'), 0x3213)

    def test_cmp_hs(self):
        self.assertEqual(self._op('cmp/hs r1, r2'), 0x3212)

    def test_cmp_gt(self):
        self.assertEqual(self._op('cmp/gt r1, r2'), 0x3217)

    def test_cmp_hi(self):
        self.assertEqual(self._op('cmp/hi r1, r2'), 0x3216)


class TestShifts(unittest.TestCase):
    """Test shift instructions."""

    def _asm(self, code):
        return assemble(code, 0)

    def test_shll(self):
        self.assertEqual(struct.unpack('>H', self._asm('shll r0')[:2])[0], 0x4000)

    def test_shlr(self):
        self.assertEqual(struct.unpack('>H', self._asm('shlr r0')[:2])[0], 0x4001)

    def test_shll2(self):
        self.assertEqual(struct.unpack('>H', self._asm('shll2 r0')[:2])[0], 0x4008)

    def test_shlr2(self):
        self.assertEqual(struct.unpack('>H', self._asm('shlr2 r0')[:2])[0], 0x4009)

    def test_shll8(self):
        self.assertEqual(struct.unpack('>H', self._asm('shll8 r0')[:2])[0], 0x4018)

    def test_shlr8(self):
        self.assertEqual(struct.unpack('>H', self._asm('shlr8 r0')[:2])[0], 0x4019)

    def test_shll16(self):
        self.assertEqual(struct.unpack('>H', self._asm('shll16 r0')[:2])[0], 0x4028)

    def test_shlr16(self):
        self.assertEqual(struct.unpack('>H', self._asm('shlr16 r0')[:2])[0], 0x4029)

    def test_shlr4_emits_two_instructions(self):
        """shlr4 should expand to two shlr2 (4 bytes)."""
        binary = self._asm('shlr4 r3')
        self.assertEqual(len(binary), 4)
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x4309)  # shlr2 r3
        self.assertEqual(struct.unpack('>H', binary[2:4])[0], 0x4309)  # shlr2 r3

    def test_shll4_emits_two_instructions(self):
        """shll4 should expand to two shll2 (4 bytes)."""
        binary = self._asm('shll4 r5')
        self.assertEqual(len(binary), 4)
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x4508)  # shll2 r5
        self.assertEqual(struct.unpack('>H', binary[2:4])[0], 0x4508)  # shll2 r5


class TestBranches(unittest.TestCase):
    """Test branch instructions with label resolution."""

    def _asm(self, code):
        return assemble(code, 0)

    def test_bra(self):
        binary = self._asm('bra target\nnop\ntarget: nop')
        # bra at 0, target at 4, disp = (4-4)/2 = 0
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xA000)

    def test_bra_backward(self):
        binary = self._asm('target: nop\nbra target\nnop')
        # target at 0, bra at 2, disp = (0 - (2+4))/2 = -3 = 0xFFD
        self.assertEqual(struct.unpack('>H', binary[2:4])[0], 0xAFFD)

    def test_bt(self):
        binary = self._asm('bt target\nnop\ntarget: nop')
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x8D00)

    def test_bf(self):
        binary = self._asm('bf target\nnop\ntarget: nop')
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x8B00)

    def test_bts(self):
        binary = self._asm('bt.s target\nnop\ntarget: nop')
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x8E00)

    def test_bfs(self):
        binary = self._asm('bf.s target\nnop\ntarget: nop')
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x8F00)

    def test_bra_long_displacement(self):
        """BRA with a large displacement."""
        code = 'bra far\nnop\n' + 'nop\n' * 100 + 'far: nop'
        binary = self._asm(code)
        op = struct.unpack('>H', binary[:2])[0]
        # bra at 0, far at 2 + 2 + 100*2 = 204, disp = (204-4)/2 = 100
        self.assertEqual(op & 0xF000, 0xA000)
        self.assertEqual(op & 0x0FFF, 100)


class TestLabels(unittest.TestCase):
    """Test label resolution (named, numeric, expressions)."""

    def test_named_label_forward(self):
        code = 'bra end\nnop\nend: rts\nnop'
        binary = assemble(code, 0)
        self.assertEqual(len(binary), 8)

    def test_named_label_backward(self):
        code = 'loop: nop\nbra loop\nnop'
        binary = assemble(code, 0)
        self.assertEqual(len(binary), 6)

    def test_numeric_label_forward(self):
        code = '1: bra 1f\nnop\n1: rts\nnop'
        binary = assemble(code, 0)
        # bra at 0, 1f = next 1: at addr 4, disp = 0
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xA000)

    def test_numeric_label_backward(self):
        code = '1: nop\nbra 1b\nnop'
        binary = assemble(code, 0)
        # 1: at 0, bra at 2, 1b = 0, disp = (0-(2+4))/2 = -3
        self.assertEqual(struct.unpack('>H', binary[2:4])[0], 0xAFFD)

    def test_multiple_numeric_labels(self):
        """Multiple numeric labels with the same number."""
        code = '1: nop\nbra 1f\nnop\n1: bra 1b\nnop'
        binary = assemble(code, 0)
        # First 1: at 0, first bra at 2, 1f = second 1: at 6
        # disp = (6 - (2+4)) / 2 = 0
        self.assertEqual(struct.unpack('>H', binary[2:4])[0], 0xA000)
        # Second 1: at 6, second bra at 8, 1b = first 1: at 0
        # Wait, second 1: is at 6, bra is on the same line... let me check:
        # code layout: 1:(0) nop(0) | bra 1f(2) | nop(4) | 1:(6) bra 1b(6) | nop(8)
        # Actually: "1: bra 1b" means label 1: at addr 6, then bra at addr 6
        # bra 1b: 1b = last 1: before addr 6 = 0
        # disp = (0 - (6+4)) / 2 = -5 = 0xFFB
        self.assertEqual(struct.unpack('>H', binary[6:8])[0], 0xAFFB)

    def test_label_offset_expression(self):
        """label+4 expression in .long."""
        code = 'start: nop\n.long start+4'
        binary = assemble(code, 0)
        # start = 0, start+4 = 4
        self.assertEqual(binary[2:6], bytes([0, 0, 0, 4]))

    def test_movl_pc_relative(self):
        """mov.l label, Rn generates PC-relative load."""
        code = 'mov.l table, r1\nnop\nnop\n.align 4\ntable: .long 0x12345678'
        binary = assemble(code, 0)
        # mov.l at 0, table at 8 (4 instr + align), disp = (8-4)/4 = 1
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xD101)
        # table value
        self.assertEqual(binary[8:12], bytes([0x12, 0x34, 0x56, 0x78]))


class TestDirectives(unittest.TestCase):
    """Test assembler directives."""

    def test_long(self):
        binary = assemble('.long 0x12345678', 0)
        self.assertEqual(binary, bytes([0x12, 0x34, 0x56, 0x78]))

    def test_word(self):
        binary = assemble('.word 0x1234', 0)
        self.assertEqual(binary, bytes([0x12, 0x34]))

    def test_byte(self):
        binary = assemble('.byte 1, 2, 3', 0)
        self.assertEqual(binary, bytes([1, 2, 3]))

    def test_align(self):
        binary = assemble('nop\n.align 4\nnop', 0)
        self.assertEqual(len(binary), 6)
        self.assertEqual(binary[2:4], bytes([0, 0]))

    def test_space(self):
        binary = assemble('.space 8', 0)
        self.assertEqual(len(binary), 8)
        self.assertEqual(binary, bytes(8))

    def test_multiple_long(self):
        binary = assemble('.long 1, 2, 3', 0)
        self.assertEqual(len(binary), 12)
        self.assertEqual(binary[:4], bytes([0, 0, 0, 1]))


class TestDSPInstructions(unittest.TestCase):
    """Test SH4AL-DSP instruction encodings."""

    def _asm(self, code):
        return assemble(code, 0)

    def _op(self, code):
        return struct.unpack('>H', self._asm(code)[:2])[0]

    def test_ldrs(self):
        """LDRS @(disp,PC) -- load repeat start."""
        code = 'ldrs target\nnop\ntarget: nop'
        op = self._op(code)
        # ldrs at 0, target at 4, disp = (4-4)/2 = 0
        self.assertEqual(op, 0x8C00)

    def test_ldre(self):
        """LDRE @(disp,PC) -- load repeat end."""
        code = 'ldre target\nnop\ntarget: nop'
        op = self._op(code)
        self.assertEqual(op, 0x8E00)

    def test_ldrc_imm(self):
        """LDRC #imm -- load repeat count."""
        self.assertEqual(self._op('ldrc #8'), 0x8A08)
        self.assertEqual(self._op('ldrc #255'), 0x8AFF)

    def test_ldrc_reg(self):
        """LDRC Rm -- load repeat count from register."""
        self.assertEqual(self._op('ldrc r3'), 0x4334)

    def test_movs_w_direct(self):
        """MOVS.W @As, Ds (direct addressing)."""
        # @r4, a0 -> As=0, Ds=7, mode=4 (word direct)
        # Encoding: 0000_00aa_dddd_mmmm = 0x0074
        op = self._op('movs.w @r4, a0')
        self.assertEqual(op, 0x0074)

    def test_movs_w_postinc(self):
        """MOVS.W @As+, Ds (post-increment)."""
        # @r5+, y0 -> As=1, Ds=8, mode=12
        # Encoding: 0x18C = 0x018C
        op = self._op('movs.w @r5+, y0')
        self.assertEqual(op, 0x018C)

    def test_movs_l_direct(self):
        """MOVS.L @As, Ds (direct, long)."""
        # @r2, x0 -> As=2, Ds=12, mode=6
        # Encoding: 0x2C6 = 0x02C6
        op = self._op('movs.l @r2, x0')
        self.assertEqual(op, 0x02C6)

    def test_movs_l_predec(self):
        """MOVS.L @-As, Ds (pre-decrement, long)."""
        # @-r3, a1 -> As=3, Ds=5, mode=10
        # Encoding: 0x35A = 0x035A
        op = self._op('movs.l @-r3, a1')
        self.assertEqual(op, 0x035A)

    def test_nopx(self):
        self.assertEqual(self._op('nopx'), 0xF400)

    def test_nopy(self):
        self.assertEqual(self._op('nopy'), 0xF500)

    def test_padd(self):
        """PADD -- DSP add."""
        self.assertEqual(self._op('padd'), 0xF0B1)

    def test_psub(self):
        self.assertEqual(self._op('psub'), 0xF0A1)

    def test_pmuls(self):
        self.assertEqual(self._op('pmuls'), 0xF040)

    def test_pclr(self):
        self.assertEqual(self._op('pclr'), 0xF08D)

    def test_pcopy(self):
        self.assertEqual(self._op('pcopy'), 0xF0BD)

    def test_pabs(self):
        self.assertEqual(self._op('pabs'), 0xF088)

    def test_pneg(self):
        self.assertEqual(self._op('pneg'), 0xF0A8)

    def test_pand(self):
        self.assertEqual(self._op('pand'), 0xF095)

    def test_por(self):
        self.assertEqual(self._op('por'), 0xF0B5)

    def test_pxor(self):
        self.assertEqual(self._op('pxor'), 0xF0A5)

    def test_pshl(self):
        self.assertEqual(self._op('pshl'), 0xF000)

    def test_psha(self):
        self.assertEqual(self._op('psha'), 0xF010)

    def test_psts(self):
        self.assertEqual(self._op('psts'), 0xF0CD)

    def test_plds(self):
        self.assertEqual(self._op('plds'), 0xF0ED)

    def test_padd_dct(self):
        """PADD with DCT prefix (conditional on repeat counter true)."""
        self.assertEqual(self._op('padd dct'), 0xF0B2)

    def test_padd_dcf(self):
        """PADD with DCF prefix (conditional on repeat counter false)."""
        self.assertEqual(self._op('padd dcf'), 0xF0B3)

    def test_movs_all_data_regs(self):
        """MOVS.W with all valid DSP data registers."""
        for reg, ds_idx in [('a1', 5), ('a0', 7), ('y0', 8), ('y1', 9),
                            ('m0', 10), ('m1', 11), ('x0', 12),
                            ('a1g', 13), ('x1', 14), ('a0g', 15)]:
            op = self._op(f'movs.w @r4, {reg}')
            expected = (0 << 8) | (ds_idx << 4) | 4  # As=0, mode=4
            self.assertEqual(op, expected, f"MOVS.W @r4, {reg} = 0x{expected:04X}")

    def test_movs_all_addr_regs(self):
        """MOVS.W with all DSP address registers."""
        for reg, as_idx in [('r4', 0), ('r5', 1), ('r2', 2), ('r3', 3)]:
            op = self._op(f'movs.w @{reg}, a0')
            expected = (as_idx << 8) | (7 << 4) | 4  # Ds=7, mode=4
            self.assertEqual(op, expected, f"MOVS.W @{reg}, a0 = 0x{expected:04X}")

    def test_dsp_repeat_loop(self):
        """Assemble a complete DSP repeat loop."""
        code = """
            ldrs loop_start
            ldre loop_end
            ldrc #8
            loop_start:
            movs.w @r4+, x0
            padd
            loop_end:
            nopx
            nop
        """
        binary = self._asm(code)
        self.assertGreater(len(binary), 10)
        # Verify LDRS, LDRE, LDRC are present
        ops = [struct.unpack('>H', binary[i:i+2])[0]
               for i in range(0, len(binary), 2)]
        # LDRS = 0x8Cxx
        self.assertTrue(any((o & 0xFF00) == 0x8C00 for o in ops))
        # LDRE = 0x8Exx
        self.assertTrue(any((o & 0xFF00) == 0x8E00 for o in ops))
        # LDRC #8 = 0x8A08
        self.assertIn(0x8A08, ops)
        # PADD = 0xF0B1
        self.assertIn(0xF0B1, ops)


class TestAddressingModes(unittest.TestCase):
    """Test all SH-4 addressing modes."""

    def _op(self, code):
        return struct.unpack('>H', assemble(code, 0)[:2])[0]

    def test_reg_direct(self):
        self.assertEqual(self._op('mov r1, r2'), 0x6213)

    def test_reg_indirect(self):
        # MOV.L @Rm, Rn: 0110_nnnn_mmmm_0010, n=0, m=1 -> 0x6012
        self.assertEqual(self._op('mov.l @r1, r0'), 0x6012)

    def test_postinc(self):
        # MOV.L @Rm+, Rn: 0110_nnnn_mmmm_0110, n=0, m=1 -> 0x6016
        self.assertEqual(self._op('mov.l @r1+, r0'), 0x6016)

    def test_predec(self):
        # MOV.L Rm, @-Rn: 0010_nnnn_mmmm_0110, n=1, m=0 -> 0x2106
        self.assertEqual(self._op('mov.l r0, @-r1'), 0x2106)

    def test_disp_indexed(self):
        # mov.l r0, @(0, r1) -> 0001_nnnn_mmmm_dddd, n=1, m=0, d=0
        op = self._op('mov.l r0, @(0, r1)')
        self.assertEqual(op, 0x1100)

    def test_r0_indexed(self):
        # mov.l r0, @(r0, r1) -> 0000_nnnn_mmmm_0110, n=1, m=0
        op = self._op('mov.l r0, @(r0, r1)')
        self.assertEqual(op, 0x0106)

    def test_immediate(self):
        self.assertEqual(self._op('mov #0x42, r5'), 0xE542)


class TestCommentStripping(unittest.TestCase):
    """Test that comments are correctly stripped."""

    def test_semicolon_comment(self):
        binary = assemble('nop ; this is a comment', 0)
        self.assertEqual(len(binary), 2)

    def test_slash_comment(self):
        binary = assemble('nop // this is a comment', 0)
        self.assertEqual(len(binary), 2)

    def test_comment_only_line(self):
        binary = assemble('; just a comment\nnop', 0)
        self.assertEqual(len(binary), 2)


class TestErrorHandling(unittest.TestCase):
    """Test assembler error handling."""

    def test_unknown_instruction(self):
        with self.assertRaises(ValueError):
            assemble('frobnicate r0, r1', 0)

    def test_unknown_register(self):
        with self.assertRaises(ValueError):
            assemble('mov r99, r0', 0)

    def test_undefined_label(self):
        with self.assertRaises(ValueError):
            assemble('bra nowhere', 0)


if __name__ == '__main__':
    unittest.main()
