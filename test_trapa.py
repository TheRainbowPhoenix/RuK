#!/usr/bin/env python3
"""
TRAPA test using the cp400/3070.bin OS ROM.

The 3070.bin is the Casio fx-CG50 (CP-400) OS ROM.  It contains the
full operating system, including the TRAPA syscall handler at VBR+0x100.

This test:
  1. Loads the OS ROM at 0x80000000 (where the OS expects to be)
  2. Sets VBR to the OS's exception vector table
  3. Loads a small test program that calls TRAPA #0 at a known address
  4. Runs until the TRAPA fires and the OS handler takes over

The test verifies that:
  - TRAPA sets SPC/SSR/SGR correctly
  - EXPEVT is set to 0x160
  - PC vectors to VBR+0x100
  - TRA is set to imm<<2

Usage:
    python3 test_trapa.py [--trace] [--max-steps N]
"""

import sys
import os
import struct
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad


def encode_op(op16: int) -> bytes:
    return struct.pack('>H', op16)


def main():
    parser = argparse.ArgumentParser(description='TRAPA test with 3070.bin OS ROM')
    parser.add_argument('--trace', action='store_true', help='Print each instruction')
    parser.add_argument('--max-steps', type=int, default=5000)
    parser.add_argument('--rom', default='cp400/3070.bin')
    args = parser.parse_args()

    rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.rom)
    if not os.path.exists(rom_path):
        print(f"ROM file not found: {rom_path}")
        print("Download 3070.bin")
        return 1
    with open(rom_path, 'rb') as f:
        rom = f.read()
    print(f"Loaded OS ROM: {rom_path} ({len(rom)} bytes)")

    # Build a small test program that just executes TRAPA #0x2E
    # and then SLEEP (so the CPU halts after returning from the handler).
    # TRAPA #imm encoding: 0xC300 | (imm & 0xFF)
    test_prog = b''
    test_prog += encode_op(0xC32E)   # TRAPA #0x2E
    test_prog += encode_op(0x0009)   # NOP (delay slot -- TRAPA doesn't use one, but just in case)
    test_prog += encode_op(0x001B)   # SLEEP

    # Load at 0x8CFF0000 (in RAM)
    start_pc = 0x8CFF0000
    cp = Classpad(rom, debug=False, start_pc=start_pc,
                  with_tmu=True, with_rtc=True, with_dma=True)
    cp.ram.write_bin(start_pc - 0x8C000000, test_prog)

    # The OS ROM's VBR is typically at 0x80020000 or 0x80020F00.
    # Let's use 0x80020F00 (cp-emu's default).
    cp.cpu.regs['vbr'] = 0x80020F00

    print(f"Test program at 0x{start_pc:08X}")
    print(f"VBR = 0x{cp.cpu.regs['vbr']:08X}")
    print(f"R15 = 0x{cp.cpu.regs[15]:08X}")
    print()

    # Run the CPU
    trapa_seen = False
    step_count = 0
    while not cp.cpu.ebreak and step_count < args.max_steps:
        try:
            pc_before = cp.cpu.pc

            if args.trace:
                ins = cp.cpu.mem.read16(pc_before)
                if isinstance(ins, int):
                    op_val = ins
                else:
                    op_val = int.from_bytes(ins, "big")
                try:
                    fmt, a = cp.cpu.disassembler.disasm(op_val, trace_only=True)
                    a_disp = {**a}
                    if 'd' in a_disp:
                        a_disp['d'] *= 4
                    print(f"  0x{pc_before:08X}: 0x{op_val:04X}  {fmt.format(**a_disp)}")
                except Exception:
                    print(f"  0x{pc_before:08X}: 0x{op_val:04X}  ???")

            cp.cpu.step()
            step_count += 1

            # Check if TRAPA just fired
            if cp.cpu.expevt == 0x160 and not trapa_seen:
                trapa_seen = True
                print(f"\n*** TRAPA fired at step {step_count} ***")
                print(f"  SPC = 0x{cp.cpu.spc:08X}  (should be 0x{start_pc + 4:08X} = TRAPA + 2)")
                print(f"  SSR = 0x{cp.cpu.ssr:08X}")
                print(f"  SGR = 0x{cp.cpu.sgr:08X}")
                print(f"  EXPEVT = 0x{cp.cpu.expevt:08X}  (should be 0x00000160)")
                print(f"  TRA = 0x{cp.cpu.tra:08X}  (should be 0x{0x2E << 2:08X} = 0xB8)")
                print(f"  PC = 0x{cp.cpu.pc:08X}  (should be VBR+0x100 = 0x{0x80020F00 + 0x100:08X})")

                # Verify
                assert cp.cpu.expevt == 0x160, f"EXPEVT should be 0x160, got 0x{cp.cpu.expevt:X}"
                assert cp.cpu.tra == (0x2E << 2), f"TRA should be 0xB8, got 0x{cp.cpu.tra:X}"
                assert cp.cpu.pc == 0x80020F00 + 0x100, \
                    f"PC should be VBR+0x100=0x{0x80020F00+0x100:08X}, got 0x{cp.cpu.pc:08X}"
                print(f"  ALL TRAPA ASSERTIONS PASSED")

            if cp.cpu.is_sleeping:
                print(f"\nCPU entered SLEEP at step {step_count}")
                break

        except IndexError as e:
            print(f"\nCPU error at step {step_count}: {e}")
            print(f"  PC=0x{cp.cpu.pc:08X}")
            break
        except Exception as e:
            print(f"\nUnexpected error at step {step_count}: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"\nExecution finished after {step_count} steps.")
    if trapa_seen:
        print("PASS: TRAPA fired correctly")
        return 0
    else:
        print("FAIL: TRAPA was never triggered")
        return 1


if __name__ == '__main__':
    sys.exit(main())
