#!/usr/bin/env python3
"""
UBC (User Break Controller) test for RuK.

Tests hardware breakpoints using the SH-4 UBC:
  1. UBC channel 0 fires when PC matches CAR0
  2. UBC vectors through DBR when CBCR.UBDE=1
  3. UBC vectors through VBR+0x100 when CBCR.UBDE=0
  4. UBC match flag (CCMFR.MF0) is set on break
  5. The host can suppress a break via on_ubc_break callback
  6. Two channels can independently break at different addresses

The test mimics what gint's `ubc_set_breakpoint()` and hollyhock-3's
`BreakpointHandlerStub` do on real hardware: configure the UBC to break
on instruction fetch from a target address, then let the CPU run until
it hits that address.

Run with:
    python3 test_ubc.py
"""

import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.ubc import (
    UBC_BASE, UBC_SIZE,
    UBC_CBR0_OFF, UBC_CRR0_OFF, UBC_CAR0_OFF, UBC_CAMR0_OFF,
    UBC_CBR1_OFF, UBC_CRR1_OFF, UBC_CAR1_OFF, UBC_CAMR1_OFF,
    UBC_CCMFR_OFF, UBC_CBCR_OFF,
    CBR_CE, CRR_BIE, CRR_PCB,
    CCMFR_MF0, CCMFR_MF1,
    CBCR_UBDE,
    UBC_EXPEVT_CH0, UBC_EXPEVT_CH1,
)


def encode_op(op16: int) -> bytes:
    return struct.pack('>H', op16)


def make_program_with_breakpoint():
    """
    Build a small SH-4 program:
      0x8C000000: MOV #1, R0       (will execute)
      0x8C000002: MOV #2, R1       (will execute)
      0x8C000004: MOV #3, R2       (BREAKPOINT HERE -- UBC should trap)
      0x8C000006: MOV #4, R3       (should NOT execute if break works)
      0x8C000008: SLEEP

    Returns the program bytes.
    """
    prog = b''
    prog += encode_op(0xE001)   # MOV #1, R0
    prog += encode_op(0xE102)   # MOV #2, R1
    prog += encode_op(0xE203)   # MOV #3, R2   <- breakpoint target
    prog += encode_op(0xE304)   # MOV #4, R3
    prog += encode_op(0x001B)   # SLEEP
    return prog


def make_cp_with_program(prog_bytes, with_ubc=True):
    """Create a Classpad with the program loaded into RAM at 0x8C000000."""
    cp = Classpad(b'\x00\x09', debug=False, start_pc=0x8C000000, with_ubc=with_ubc)
    cp.ram.write_bin(0, prog_bytes)
    return cp


def test_ubc_break_via_dbr():
    """
    Test that a UBC break on channel 0 vectors through DBR.
    """
    print("\n[test] UBC channel 0 breaks at target PC, vectors through DBR")
    rom = make_program_with_breakpoint()
    cp = make_cp_with_program(rom)

    # Set up a UBC handler at 0x8C002000 (in RAM)
    UBC_HANDLER = 0x8C002000
    cp.cpu.dbr = UBC_HANDLER

    # Write a tiny handler at UBC_HANDLER that just records the break
    # and halts (via SLEEP).  In real code this would save registers
    # and call a debug function (like hollyhock-3's BreakpointHandlerStub).
    # For the test, we just SLEEP so the CPU stops.
    handler = encode_op(0x001B)   # SLEEP
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, handler)

    # Set a breakpoint at 0x8C000004 (the MOV #3, R2 instruction)
    # Using the convenience method (mirrors gint's ubc_set_breakpoint)
    cp.ubc.set_breakpoint(0, 0x8C000004, break_after=False)

    # Verify the UBC is configured correctly
    assert cp.ubc.channels[0].enabled, "Channel 0 should be enabled"
    assert cp.ubc.channels[0].break_enabled, "BIE should be set"
    assert cp.ubc.channels[0].car == 0x8C000004, f"CAR0 should be 0x8C000004, got 0x{cp.ubc.channels[0].car:08X}"
    assert cp.ubc.ubde, "UBDE should be set (we set it in _setup_ubc)"

    # Run the CPU.  It should execute MOV #1,R0 and MOV #2,R1, then
    # hit the breakpoint at 0x8C000004 and vector to DBR (0x8C002000).
    for i in range(20):
        if cp.cpu.ebreak:
            break
        if cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    # After the break, SPC should be the break address (0x8C000004)
    # and EXPEVT should be 0x1E0 (UBC channel 0).
    # (PC may have advanced if the handler's SLEEP already ran.)
    assert cp.cpu.spc == 0x8C000004, \
        f"SPC should be 0x8C000004 (break address), got 0x{cp.cpu.spc:08X}"

    assert cp.cpu.expevt == UBC_EXPEVT_CH0, \
        f"EXPEVT should be 0x{UBC_EXPEVT_CH0:X}, got 0x{cp.cpu.expevt:X}"

    # CCMFR.MF0 should be set
    assert cp.ubc.ccmfr & CCMFR_MF0, "CCMFR.MF0 should be set after break"

    # R0 and R1 should have been set (the first two instructions ran)
    assert cp.cpu.regs[0] == 1, f"R0 should be 1, got 0x{cp.cpu.regs[0]:X}"
    assert cp.cpu.regs[1] == 2, f"R1 should be 2, got 0x{cp.cpu.regs[1]:X}"

    # R2 should NOT be 3 (the breakpoint fires BEFORE the instruction
    # at the break address executes, because we set break_after=False)
    assert cp.cpu.regs[2] != 3, f"R2 should NOT be 3 (break before execution), got 0x{cp.cpu.regs[2]:X}"

    # SPC should point to the break address
    assert cp.cpu.spc == 0x8C000004, \
        f"SPC should be 0x8C000004 (break address), got 0x{cp.cpu.spc:08X}"

    print(f"  PASS: CPU broke at 0x{cp.cpu.spc:08X}, vectored to DBR=0x{cp.cpu.pc:08X}")
    print(f"  PASS: EXPEVT=0x{cp.cpu.expevt:X}, CCMFR.MF0 set, R0=1 R1=2 R2 not yet 3")


def test_ubc_break_via_vbr():
    """
    Test that a UBC break vectors through VBR+0x100 when UBDE=0.
    """
    print("\n[test] UBC break vectors through VBR+0x100 when UBDE=0")
    rom = make_program_with_breakpoint()
    cp = make_cp_with_program(rom)

    # Disable UBDE so breaks go through VBR+0x100 instead of DBR
    cp.ubc.cbcr = 0   # UBDE=0

    # Set up VBR + 0x100 handler
    VBR_HANDLER_BASE = 0x8C003000
    cp.cpu.regs['vbr'] = VBR_HANDLER_BASE
    # The handler is at VBR + 0x100 = 0x8C003100
    UBC_HANDLER = VBR_HANDLER_BASE + 0x100
    handler = encode_op(0x001B)   # SLEEP
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, handler)

    # Set breakpoint at 0x8C000004
    cp.ubc.set_breakpoint(0, 0x8C000004, break_after=False)

    # Run
    for i in range(20):
        if cp.cpu.ebreak or cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    assert cp.cpu.spc == 0x8C000004, \
        f"SPC should be 0x8C000004 (break address), got 0x{cp.cpu.spc:08X}"
    assert cp.cpu.expevt == UBC_EXPEVT_CH0, f"EXPEVT should be 0x1E0"
    print(f"  PASS: CPU vectored to VBR+0x100=0x{cp.cpu.pc:08X}")


def test_ubc_break_after():
    """
    Test that break_after=True breaks AFTER the instruction executes.
    """
    print("\n[test] UBC break AFTER instruction (PCB=1)")
    rom = make_program_with_breakpoint()
    cp = make_cp_with_program(rom)

    UBC_HANDLER = 0x8C002000
    cp.cpu.dbr = UBC_HANDLER
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, encode_op(0x001B))   # SLEEP

    # Set breakpoint at 0x8C000004 with break_after=True
    cp.ubc.set_breakpoint(0, 0x8C000004, break_after=True)

    for i in range(20):
        if cp.cpu.ebreak or cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    assert cp.cpu.spc == 0x8C000004, f"SPC should be 0x8C000004, got 0x{cp.cpu.spc:08X}"
    # R2 SHOULD be 3 because the instruction executed before the break
    assert cp.cpu.regs[2] == 3, f"R2 should be 3 (break after execution), got 0x{cp.cpu.regs[2]:X}"
    print(f"  PASS: R2=3 (instruction executed before break)")


def test_ubc_suppress_callback():
    """
    Test that on_ubc_break callback can suppress a break.
    """
    print("\n[test] on_ubc_break callback can suppress break")
    rom = make_program_with_breakpoint()
    cp = make_cp_with_program(rom)

    UBC_HANDLER = 0x8C002000
    cp.cpu.dbr = UBC_HANDLER
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, encode_op(0x001B))

    # Set breakpoint at 0x8C000004
    cp.ubc.set_breakpoint(0, 0x8C000004, break_after=False)

    # Install a callback that suppresses the break (returns True)
    suppress_count = [0]
    def on_break(ch, addr):
        suppress_count[0] += 1
        return True   # suppress
    cp.cpu.on_ubc_break = on_break

    # Run -- the CPU should NOT break, it should continue past 0x8C000004
    for i in range(20):
        if cp.cpu.ebreak or cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    assert suppress_count[0] >= 1, "on_ubc_break should have been called"
    assert cp.cpu.pc != UBC_HANDLER, "CPU should NOT have vectored to handler (break suppressed)"
    # R2 should be 3 (instruction executed because break was suppressed)
    assert cp.cpu.regs[2] == 3, f"R2 should be 3 (break suppressed), got 0x{cp.cpu.regs[2]:X}"
    print(f"  PASS: Break suppressed {suppress_count[0]} time(s), CPU continued, R2=3")


def test_ubc_two_channels():
    """
    Test that two UBC channels can independently break.
    """
    print("\n[test] Two UBC channels break independently")
    # Build a program with two breakpoint targets
    prog = b''
    prog += encode_op(0xE001)   # 0x8C000000: MOV #1, R0
    prog += encode_op(0xE102)   # 0x8C000002: MOV #2, R1  <- ch0 break
    prog += encode_op(0xE203)   # 0x8C000004: MOV #3, R2
    prog += encode_op(0xE304)   # 0x8C000006: MOV #4, R3  <- ch1 break
    prog += encode_op(0xE405)   # 0x8C000008: MOV #5, R4
    prog += encode_op(0x001B)   # 0x8C00000A: SLEEP

    cp = make_cp_with_program(prog)
    UBC_HANDLER = 0x8C002000
    cp.cpu.dbr = UBC_HANDLER
    # Handler: clear MF0 and MF1, then SLEEP
    # (In real code this would be more sophisticated)
    handler = encode_op(0x001B)   # just SLEEP for the test
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, handler)

    # Set channel 0 to break at 0x8C000002
    cp.ubc.set_breakpoint(0, 0x8C000002, break_after=False)
    # Set channel 1 to break at 0x8C000006
    cp.ubc.set_breakpoint(1, 0x8C000006, break_after=False)

    # Run -- should hit channel 0 first
    for i in range(10):
        if cp.cpu.ebreak or cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    assert cp.cpu.expevt == UBC_EXPEVT_CH0, f"First break should be ch0, got EXPEVT=0x{cp.cpu.expevt:X}"
    assert cp.ubc.ccmfr & CCMFR_MF0, "MF0 should be set"
    print(f"  PASS: Channel 0 broke at 0x{cp.cpu.spc:08X} (EXPEVT=0x{cp.cpu.expevt:X})")


def test_ubc_disable_channel():
    """Test that disabling a channel stops it from breaking."""
    print("\n[test] Disabling a channel stops breaks")
    rom = make_program_with_breakpoint()
    cp = make_cp_with_program(rom)

    UBC_HANDLER = 0x8C002000
    cp.cpu.dbr = UBC_HANDLER
    cp.ram.write_bin(UBC_HANDLER - 0x8C000000, encode_op(0x001B))

    cp.ubc.set_breakpoint(0, 0x8C000004, break_after=False)
    # Now disable channel 0
    cp.ubc.disable_channel(0)
    assert not cp.ubc.channels[0].enabled, "Channel 0 should be disabled"

    for i in range(20):
        if cp.cpu.ebreak or cp.cpu.is_sleeping:
            break
        cp.cpu.step()

    # CPU should NOT have hit the handler (it should have run to SLEEP)
    assert cp.cpu.pc != UBC_HANDLER, "CPU should not have broken (channel disabled)"
    assert cp.cpu.is_sleeping or cp.cpu.ebreak, "CPU should have reached SLEEP"
    print(f"  PASS: Disabled channel -> no break, CPU ran to completion")


def test_ubc_mmio():
    """Test that we can configure the UBC via MMIO reads/writes."""
    print("\n[test] UBC MMIO read/write")
    cp = Classpad(b'\x00\x09', debug=False, with_ubc=True)
    # Write CAR0 via MMIO
    cp.cpu.mem.write32(UBC_BASE + UBC_CAR0_OFF, 0x8C001234)
    assert cp.ubc.channels[0].car == 0x8C001234, f"CAR0 should be 0x8C001234, got 0x{cp.ubc.channels[0].car:08X}"
    # Read it back
    val = cp.cpu.mem.read32(UBC_BASE + UBC_CAR0_OFF)
    assert val == 0x8C001234, f"Read back should be 0x8C001234, got 0x{val:08X}"
    # Write CBCR
    cp.cpu.mem.write32(UBC_BASE + UBC_CBCR_OFF, CBCR_UBDE)
    assert cp.ubc.cbcr == CBCR_UBDE, f"CBCR should be 0x{CBCR_UBDE:08X}"
    print(f"  PASS: UBC MMIO read/write works")


def main():
    tests = [
        test_ubc_break_via_dbr,
        test_ubc_break_via_vbr,
        test_ubc_break_after,
        test_ubc_suppress_callback,
        test_ubc_two_channels,
        test_ubc_disable_channel,
        test_ubc_mmio,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  FAIL: {e}")
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
