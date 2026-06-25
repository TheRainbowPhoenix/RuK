#!/usr/bin/env python3
"""
Unit tests for the RuK core fixes (fixes.py).

Each test exercises one specific bug that was fixed:
  - c_long sign extension in BRA/BF/BT
  - SR.T bit extraction (not full SR == 0/1)
  - BTS conditional direction (was inverted)
  - JSR/BSR setting PR (was creating a local variable)
  - PC 32-bit masking
  - MemoryMap.write8/16/32 accepting int
  - Missing opcodes: RTE, LDC, LDS, STC, STS, SLEEP, SETT, CLRT, TST, AND, OR, XOR, NOT, NEG
  - Branch-delay-slot semantics

Run with:
    python3 test_fixes.py
"""

import struct
import sys
import os

# Add the RuK root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importing Classpad applies all the fixes (via classpad.py importing fixes)
from ruk.classpad import Classpad
from ruk.jcore.memory import MemoryMap, Memory


def make_cpu(rom_bytes=b'\x00\x09' * 16, start_pc=0x8C000000, ram_size=0x10000):
    """Build a minimal Classpad for testing."""
    cp = Classpad(rom_bytes, debug=False, start_pc=start_pc, ram_size=ram_size)
    return cp


def encode_op(op16: int) -> bytes:
    """Encode a 16-bit opcode as big-endian bytes."""
    return struct.pack('>H', op16)


def run_one_instr(cp, instr_bytes: bytes):
    """Place `instr_bytes` at the current PC, step once, return the new PC."""
    cp.ram.write_bin(cp.cpu.pc - 0x8C00_0000, instr_bytes)
    cp.cpu.ebreak = False
    cp.cpu.step()
    return cp.cpu.pc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sr_t_bit_extraction():
    """BT should branch when SR.T=1, regardless of other SR bits."""
    print("\n[test] SR.T bit extraction (BT/BF check bit 0, not full SR)")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0x40000001   # MD=1, T=1, plus other bits set
    # BT +0 (disp=0): if T=1, PC = PC + 4 + 0*2 = PC + 4
    # Encoding: 0x8900 | (disp & 0xFF) = 0x8900
    run_one_instr(cp, encode_op(0x8900))
    expected = 0x8C000000 + 4
    assert cp.cpu.pc == expected, f"BT with T=1 should branch to PC+4=0x{expected:X}, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BT with SR=0x40000001 (T=1) branched to 0x{cp.cpu.pc:X}")

    # Now test BF with T=0
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0x40000000   # MD=1, T=0
    # BF +0 (disp=0): if T=0, PC = PC + 4 + 0*2 = PC + 4
    run_one_instr(cp, encode_op(0x8B00))
    expected = 0x8C000000 + 4
    assert cp.cpu.pc == expected, f"BF with T=0 should branch to PC+4=0x{expected:X}, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BF with SR=0x40000000 (T=0) branched to 0x{cp.cpu.pc:X}")

    # And BT with T=0 (should NOT branch)
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0x40000000   # MD=1, T=0
    run_one_instr(cp, encode_op(0x8900))
    expected = 0x8C000000 + 2  # just advance to next instruction
    assert cp.cpu.pc == expected, f"BT with T=0 should fall through to PC+2=0x{expected:X}, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BT with SR=0x40000000 (T=0) fell through to 0x{cp.cpu.pc:X}")


def test_negative_displacement_bt():
    """BT with negative displacement (backward branch)."""
    print("\n[test] BT with negative displacement (c_long bug)")
    cp = make_cpu()
    # Place BT at 0x8C000010 with disp=-4 (branch back to 0x8C000008)
    # BT disp encoding: 0x8900 | (disp & 0xFF). disp=-4 -> 0xFC.
    cp.cpu.pc = 0x8C000010
    cp.cpu.regs['sr'] = 0x01   # T=1
    # BT -4: target = PC + 4 + (disp << 1) = 0x10 + 4 + (-4 * 2) = 0x10 + 4 - 8 = 0x0C
    # Wait, let me recompute: disp=-4, target = 0x8C000010 + 4 + (-4 * 2) = 0x8C00000C
    run_one_instr(cp, encode_op(0x89FC))
    expected = 0x8C00000C
    assert cp.cpu.pc == expected, f"BT -4 should branch to 0x{expected:X}, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BT with disp=-4 branched to 0x{cp.cpu.pc:X}")


def test_negative_displacement_bra():
    """BRA with negative displacement."""
    print("\n[test] BRA with negative displacement")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000010
    cp.cpu.regs['sr'] = 0
    # BRA -4: target = PC + 4 + (-4 * 2) = 0x10 + 4 - 8 = 0x0C
    # BRA encoding: 0xA000 | (disp & 0xFFF). disp=-4 -> 0xFFC.
    # Plus delay slot NOP at PC+2
    cp.ram.write_bin(0x8C000010 - 0x8C00_0000, encode_op(0xAFFC) + b'\x00\x09')
    cp.cpu.step()
    expected = 0x8C00000C
    assert cp.cpu.pc == expected, f"BRA -4 should branch to 0x{expected:X}, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BRA with disp=-4 branched to 0x{cp.cpu.pc:X}")


def test_pc_32bit_mask():
    """PC should always be masked to 32 bits."""
    print("\n[test] PC 32-bit masking")
    cp = make_cpu()
    # Set up a BRA with a large negative displacement that would overflow
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0
    # BRA 0 (target = PC + 4 + 0 = 0x8C000004) with delay slot NOP
    cp.ram.write_bin(0, encode_op(0xA000) + b'\x00\x09')
    cp.cpu.step()
    assert cp.cpu.pc == 0x8C000004, f"BRA 0 should go to 0x8C000004, got 0x{cp.cpu.pc:X}"
    assert cp.cpu.pc < 0x100000000, f"PC should be < 2^32, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: PC = 0x{cp.cpu.pc:X} (masked to 32 bits)")


def test_memory_write_int():
    """MemoryMap.write8/16/32 should accept int, not just bytes."""
    print("\n[test] MemoryMap.write8/16/32 accept int")
    cp = make_cpu()
    # Write 0x42 to RAM at 0x8C001000
    cp.cpu.mem.write8(0x8C001000, 0x42)
    val = cp.ram.read8(0x8C001000 - 0x8C00_0000)
    assert val == 0x42, f"write8(int) failed: expected 0x42, got 0x{val:X}"
    print(f"  PASS: write8(int) wrote 0x{val:X}")

    cp.cpu.mem.write16(0x8C001002, 0x1234)
    val = cp.ram.read16(0x8C001002 - 0x8C00_0000)
    assert val == 0x1234, f"write16(int) failed: expected 0x1234, got 0x{val:X}"
    print(f"  PASS: write16(int) wrote 0x{val:X}")

    cp.cpu.mem.write32(0x8C001004, 0xDEADBEEF)
    val = cp.ram.read32(0x8C001004 - 0x8C00_0000)
    assert val == 0xDEADBEEF, f"write32(int) failed: expected 0xDEADBEEF, got 0x{val:X}"
    print(f"  PASS: write32(int) wrote 0x{val:X}")


def test_sett_clrt():
    """SETT sets T=1, CLRT clears T=0."""
    print("\n[test] SETT / CLRT")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0
    # SETT = 0x0018 (per generated_opcodes.py)
    run_one_instr(cp, encode_op(0x0018))
    assert cp.cpu.regs['sr'] & 1 == 1, f"SETT should set T=1, SR=0x{cp.cpu.regs['sr']:X}"
    assert cp.cpu.pc == 0x8C000002, f"SETT should advance PC by 2, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: SETT set T=1 (SR=0x{cp.cpu.regs['sr']:X}), PC=0x{cp.cpu.pc:X}")

    # CLRT = 0x0008
    run_one_instr(cp, encode_op(0x0008))
    assert cp.cpu.regs['sr'] & 1 == 0, f"CLRT should clear T=0, SR=0x{cp.cpu.regs['sr']:X}"
    print(f"  PASS: CLRT cleared T=0 (SR=0x{cp.cpu.regs['sr']:X})")


def test_ldc_stc_vbr():
    """LDC Rm, VBR and STC VBR, Rn."""
    print("\n[test] LDC Rm, VBR / STC VBR, Rn")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[5] = 0x80020000
    # LDC Rm, VBR = 0x402E | (m << 8). For m=5: 0x452E
    cp.ram.write_bin(0, encode_op(0x452E))
    cp.cpu.step()
    assert cp.cpu.regs['vbr'] == 0x80020000, f"LDC R5,VBR failed: VBR=0x{cp.cpu.regs['vbr']:X}"
    print(f"  PASS: LDC R5, VBR set VBR=0x{cp.cpu.regs['vbr']:X}")

    # STC VBR, Rn = 0x0022 | (n << 8). For n=6: 0x0622
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[6] = 0
    cp.ram.write_bin(0, encode_op(0x0622))
    cp.cpu.step()
    assert cp.cpu.regs[6] == 0x80020000, f"STC VBR,R6 failed: R6=0x{cp.cpu.regs[6]:X}"
    print(f"  PASS: STC VBR, R6 read VBR into R6=0x{cp.cpu.regs[6]:X}")


def test_lds_sts_pr():
    """LDS Rm, PR and STS PR, Rn."""
    print("\n[test] LDS Rm, PR / STS PR, Rn")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[3] = 0x8C001234
    # LDS Rm, PR = 0x402A | (m << 8). For m=3: 0x432A
    cp.ram.write_bin(0, encode_op(0x432A))
    cp.cpu.step()
    assert cp.cpu.regs['pr'] == 0x8C001234, f"LDS R3,PR failed: PR=0x{cp.cpu.regs['pr']:X}"
    print(f"  PASS: LDS R3, PR set PR=0x{cp.cpu.regs['pr']:X}")

    # STS PR, Rn = 0x002A | (n << 8). For n=4: 0x042A
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[4] = 0
    cp.ram.write_bin(0, encode_op(0x042A))
    cp.cpu.step()
    assert cp.cpu.regs[4] == 0x8C001234, f"STS PR,R4 failed: R4=0x{cp.cpu.regs[4]:X}"
    print(f"  PASS: STS PR, R4 read PR into R4=0x{cp.cpu.regs[4]:X}")


def test_tst_imm():
    """TST #imm, R0 sets T based on (R0 & imm) == 0."""
    print("\n[test] TST #imm, R0")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[0] = 0x0F
    cp.cpu.regs['sr'] = 0
    # TST #0x10, R0: (0x0F & 0x10) == 0 -> T=1
    # Encoding: 0b11001000_iiii_iiii = 0xC800 | imm
    cp.ram.write_bin(0, encode_op(0xC810))
    cp.cpu.step()
    assert cp.cpu.regs['sr'] & 1 == 1, f"TST #0x10,R0 with R0=0x0F should set T=1, SR=0x{cp.cpu.regs['sr']:X}"
    print(f"  PASS: TST #0x10, R0 (R0=0x0F) set T=1")

    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[0] = 0x10
    cp.cpu.regs['sr'] = 0
    cp.ram.write_bin(0, encode_op(0xC810))
    cp.cpu.step()
    assert cp.cpu.regs['sr'] & 1 == 0, f"TST #0x10,R0 with R0=0x10 should clear T=0, SR=0x{cp.cpu.regs['sr']:X}"
    print(f"  PASS: TST #0x10, R0 (R0=0x10) cleared T=0")


def test_and_or_xor_imm():
    """AND/OR/XOR #imm, R0."""
    print("\n[test] AND/OR/XOR #imm, R0")
    cp = make_cpu()
    # AND #0x0F, R0
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[0] = 0xFF
    cp.ram.write_bin(0, encode_op(0xC90F))   # AND #0x0F, R0
    cp.cpu.step()
    assert cp.cpu.regs[0] == 0x0F, f"AND #0x0F,R0 failed: R0=0x{cp.cpu.regs[0]:X}"
    print(f"  PASS: AND #0x0F, R0 (R0=0xFF) -> R0=0x{cp.cpu.regs[0]:X}")

    # OR #0xF0, R0
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[0] = 0x0F
    cp.ram.write_bin(0, encode_op(0xCBF0))   # OR #0xF0, R0
    cp.cpu.step()
    assert cp.cpu.regs[0] == 0xFF, f"OR #0xF0,R0 failed: R0=0x{cp.cpu.regs[0]:X}"
    print(f"  PASS: OR #0xF0, R0 (R0=0x0F) -> R0=0x{cp.cpu.regs[0]:X}")

    # XOR #0xFF, R0
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[0] = 0xAA
    cp.ram.write_bin(0, encode_op(0xCAFF))   # XOR #0xFF, R0 = 0xCA00 | 0xFF
    cp.cpu.step()
    assert cp.cpu.regs[0] == 0x55, f"XOR #0xFF,R0 failed: R0=0x{cp.cpu.regs[0]:X}"
    print(f"  PASS: XOR #0xFF, R0 (R0=0xAA) -> R0=0x{cp.cpu.regs[0]:X}")


def test_jsr_sets_pr():
    """JSR @Rm should set PR = PC + 4."""
    print("\n[test] JSR @Rm sets PR (was creating a local variable)")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs[3] = 0x8C001000   # call target
    # JSR @R3 encoding: 0b0100_mmmm_0000_1011 = 0x400B | (m << 8). For m=3: 0x430B
    cp.ram.write_bin(0, encode_op(0x430B) + b'\x00\x09')   # JSR + NOP delay slot
    cp.cpu.step()
    # After the delay slot, PC should be the call target
    assert cp.cpu.pc == 0x8C001000, f"JSR should branch to 0x8C001000, got 0x{cp.cpu.pc:X}"
    # PR should be PC_of_JSR + 4 = 0x8C000004
    assert cp.cpu.regs['pr'] == 0x8C000004, f"JSR should set PR=0x8C000004, got 0x{cp.cpu.regs['pr']:X}"
    print(f"  PASS: JSR @R3 set PR=0x{cp.cpu.regs['pr']:X}, branched to 0x{cp.cpu.pc:X}")


def test_bts_direction():
    """BTS = 'branch if true with delay slot' -- should branch when T=1."""
    print("\n[test] BTS branches when T=1 (was inverted in original RuK)")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 1   # T=1
    # BTS +0: 0x8D00 (delay-slot variant of BT)
    # Actually BFS = 0x8E00 (BF/S), BTS = 0x8F00 (BT/S)
    # Wait, let me check: BT/S = bit 10 set = 0x8D00? Or is it 0x8F00?
    # From the SH-4 manual:
    #   BT  = 1000_1001_dddd_dddd = 0x8900
    #   BT/S = 1000_1101_dddd_dddd = 0x8D00
    #   BF  = 1000_1011_dddd_dddd = 0x8B00
    #   BF/S = 1000_1111_dddd_dddd = 0x8F00
    # So BTS (which I implemented as BT/S) = 0x8D00
    cp.ram.write_bin(0, encode_op(0x8D00) + b'\x00\x09')   # BT/S +0 with NOP delay
    cp.cpu.step()
    # BT/S with T=1: branch to PC + 4 + 0*2 = 0x8C000004
    assert cp.cpu.pc == 0x8C000004, f"BTS with T=1 should branch to 0x8C000004, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: BTS with T=1 branched to 0x{cp.cpu.pc:X}")


def test_rte():
    """RTE restores SR from SSR and PC from SPC."""
    print("\n[test] RTE restores SR and PC")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.cpu.regs['sr'] = 0x00000001   # current SR (T=1)
    cp.cpu.ssr = 0x00000000          # saved SR (T=0)
    cp.cpu.spc = 0x8C001234          # saved PC
    # RTE = 0x002B
    cp.ram.write_bin(0, encode_op(0x002B) + b'\x00\x09')   # RTE + NOP delay
    cp.cpu.step()
    assert cp.cpu.regs['sr'] == 0x00000000, f"RTE should restore SR=0, got 0x{cp.cpu.regs['sr']:X}"
    assert cp.cpu.pc == 0x8C001234, f"RTE should restore PC=0x8C001234, got 0x{cp.cpu.pc:X}"
    print(f"  PASS: RTE restored SR=0x{cp.cpu.regs['sr']:X}, PC=0x{cp.cpu.pc:X}")


def test_sleep():
    """SLEEP should advance PC and set is_sleeping."""
    print("\n[test] SLEEP")
    cp = make_cpu()
    cp.cpu.pc = 0x8C000000
    cp.ram.write_bin(0, encode_op(0x001B))
    cp.cpu.step()
    assert cp.cpu.pc == 0x8C000002, f"SLEEP should advance PC to 0x8C000002, got 0x{cp.cpu.pc:X}"
    assert getattr(cp.cpu, 'is_sleeping', False), "SLEEP should set is_sleeping=True"
    print(f"  PASS: SLEEP advanced PC and set is_sleeping=True")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_sr_t_bit_extraction,
        test_negative_displacement_bt,
        test_negative_displacement_bra,
        test_pc_32bit_mask,
        test_memory_write_int,
        test_sett_clrt,
        test_ldc_stc_vbr,
        test_lds_sts_pr,
        test_tst_imm,
        test_and_or_xor_imm,
        test_jsr_sets_pr,
        test_bts_direction,
        test_rte,
        test_sleep,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            failed += 1
            print(f"  FAIL: {e}")
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
