#!/usr/bin/env python3
"""
GUI-less version of test_emu_prog.py.

Loads print_HelloWorld_and_exit.bin into RAM at 0x8CFF0000 and runs it
headlessly.  The program prints "My app name" to the serial output and
then calls the OS exit syscall (TRAPA #imm).

The CPU registers (R15, PR, VBR, SR) are initialized to sensible defaults
by the Classpad constructor, matching cp-emu's initialization:
  R15  = 0x8C080000  (top of 8MB RAM)
  PR   = 0xFFFFFFFF  (invalid return -- catches missing RTS)
  VBR  = 0x80020F00  (OS exception vector table)
  SR   = 0x400000F0  (MD=1 privileged, IMASK=0xF)

Usage:
    python3 test_emu_prog.py [--max-steps N] [--trace]
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad


def main():
    parser = argparse.ArgumentParser(description='Run print_HelloWorld_and_exit.bin headlessly')
    parser.add_argument('--max-steps', type=int, default=10000,
                        help='Maximum number of CPU steps before giving up')
    parser.add_argument('--trace', action='store_true',
                        help='Print each instruction as it executes')
    parser.add_argument('--rom', default='cp400/3070.bin',
                        help='Path to the OS ROM (default: cp400/3070.bin)')
    parser.add_argument('--addin', default='cp400/print_HelloWorld_and_exit.bin',
                        help='Path to the add-in binary')
    parser.add_argument('--start-pc', type=lambda x: int(x, 0),
                        default=0x8CFF0000,
                        help='Start PC for the add-in (default: 0x8CFF0000)')
    args = parser.parse_args()

    # Load the OS ROM
    rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.rom)
    if not os.path.exists(rom_path):
        print(f"ROM file not found: {rom_path}")
        print("Download from: https://github.com/TheRainbowPhoenix/RuK/releases/download/0.0.1/3070.bin")
        return 1
    with open(rom_path, 'rb') as f:
        rom = f.read()
    print(f"Loaded OS ROM: {rom_path} ({len(rom)} bytes)")

    # Load the add-in
    addin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.addin)
    if not os.path.exists(addin_path):
        print(f"Add-in file not found: {addin_path}")
        return 1
    with open(addin_path, 'rb') as f:
        addin = f.read()
    print(f"Loaded add-in: {addin_path} ({len(addin)} bytes)")

    # Create the Classpad with TMU+RTC+DMA (full peripheral set)
    cp = Classpad(rom, debug=False, start_pc=args.start_pc,
                  with_tmu=True, with_rtc=True, with_dma=True)

    # Write the add-in into RAM at 0x8CFF0000
    cp.ram.write_bin(0x8CFF0000 - 0x8C000000, addin)
    print(f"Add-in loaded at 0x{args.start_pc:08X}")
    print(f"CPU state: PC=0x{cp.cpu.pc:08X} R15=0x{cp.cpu.regs[15]:08X} "
          f"VBR=0x{cp.cpu.regs['vbr']:08X} SR=0x{cp.cpu.regs['sr']:08X}")
    print()

    # Run the CPU
    step_count = 0
    trace = args.trace
    max_steps = args.max_steps

    while not cp.cpu.ebreak and step_count < max_steps:
        try:
            if trace:
                pc_before = cp.cpu.pc
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

            # Check if CPU is sleeping
            if cp.cpu.is_sleeping:
                print(f"\nCPU entered SLEEP at step {step_count}, PC=0x{cp.cpu.pc:08X}")
                break

        except IndexError as e:
            print(f"\nCPU error at step {step_count}: {e}")
            print(f"  PC=0x{cp.cpu.pc:08X}")
            cp.cpu.stacktrace()
            break
        except Exception as e:
            print(f"\nUnexpected error at step {step_count}: {e}")
            print(f"  PC=0x{cp.cpu.pc:08X}")
            import traceback
            traceback.print_exc()
            break

    print(f"\nExecution finished after {step_count} steps.")
    print(f"  PC=0x{cp.cpu.pc:08X}  ebreak={cp.cpu.ebreak}  sleeping={cp.cpu.is_sleeping}")
    print(f"  R0=0x{cp.cpu.regs[0]:08X}  R1=0x{cp.cpu.regs[1]:08X}  "
          f"R2=0x{cp.cpu.regs[2]:08X}  R3=0x{cp.cpu.regs[3]:08X}")
    print(f"  R15=0x{cp.cpu.regs[15]:08X}  PR=0x{cp.cpu.regs['pr']:08X}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
