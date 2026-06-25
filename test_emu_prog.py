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
from ruk.gui.window import DebuggerWindow

from ruk.tools.elf import ELFFile


def main():
    parser = argparse.ArgumentParser(description='Run print_HelloWorld_and_exit.bin headlessly')
    parser.add_argument('--max-steps', type=int, default=10000,
                        help='Maximum number of CPU steps before giving up')
    parser.add_argument('--trace', action='store_true',
                        help='Print each instruction as it executes')
    parser.add_argument('--rom', default='cp400/3070.bin',
                        help='Path to the OS ROM (default: cp400/3070.bin)')
    parser.add_argument('--addin', default='bare_metal/100px.bin',
                        help='Path to the add-in binary')
    parser.add_argument('--start-pc', type=lambda x: int(x, 0),
                        default=0x8C000000,
                        help='Start PC for the add-in (default: 0x8CFF0000)')
    parser.add_argument('--sr', type=lambda x: int(x, 0),
                        default=0x400001F0,
                        help='Initial SR value (default: 0x400001F0)')
    args = parser.parse_args()


    start_pc = None
    # Reading some ELF, for testing
    # elf = ELFFile()
    # elf.read("elfs/17/00017.elf")
    # rom = elf.P

    # elf = ELFFile()
    # elf.read("elfs/ifm.elf")
    # rom = elf.P

    # Load the OS ROM
    rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.rom)
    if not os.path.exists(rom_path):
        print(f"ROM file not found: {rom_path}")
        print("Download from: https://github.com/TheRainbowPhoenix/RuK/releases/download/0.0.1/3070.bin")
        return 1

    # Reading raw bytes
    with open(rom_path, 'rb') as f:
        rom = f.read()
    print(f"Loaded OS ROM: {rom_path} ({len(rom)} bytes)")


    """
    0xA0000000 to 0xA1FFFFFF - Cached
    0x80000000 to 0x81FFFFFF - Same, but non-cached
    Addins are executed from the ROM, with the executable code virtually mapped to 0x00300000 by the MMU.
    """
    # Load the add-in
    # Reading actual bootrom
    # with open("elfs/bootrom_1511.bin", 'rb') as f:
    #     bootrom = f.read()
    #     start_pc = 0x0000_0000
    #     # start_pc = 0x8000_0340

    addin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.addin)
    if not os.path.exists(addin_path):
        print(f"Add-in file not found: {addin_path}")
        return 1
    with open(addin_path, 'rb') as f:
        addin = f.read()
    print(f"Loaded add-in: {addin_path} ({len(addin)} bytes)")


    # with open("cp400/print_HelloWorld_and_exit.hhk", 'rb') as f:
    #     print_HelloWorld_and_exit = f.read()
    #     start_pc = 0x8cff_0938  # entry0



    # Reading test opcodes file
    # with open("scratches/all_opcodes.bin", 'rb') as f:
    #     rom = f.read()

    cp = Classpad(rom, debug=False, start_pc=args.start_pc,
                  with_tmu=True, with_rtc=True, with_dma=True, with_display=True,
                  with_ubc=True)
    cp.cpu.regs['sr'] = args.sr

    # Write the add-in into RAM at 0x8CFF0000
    cp.ram.write_bin(0x8C000000 - 0x8C000000, addin)
    print(f"Add-in loaded at 0x{args.start_pc:08X}")
    print(f"CPU state: PC=0x{cp.cpu.pc:08X} R15=0x{cp.cpu.regs[15]:08X} "
          f"VBR=0x{cp.cpu.regs['vbr']:08X} SR=0x{cp.cpu.regs['sr']:08X}")
    print()
    # cp.add_rom(print_HelloWorld_and_exit, 0x8cff_0000)

    # r2 = 0xa44b000a
    # r3 = 0xffff
    # r14 = 0x178000
    # r15 = 0x178000

    # init = """
    # sts.l pr, @-r15
    # mov.l main_bootstrap_addr, r0
    # jsr @r0
    # nop
    # lds.l @r15+, pr
    # rts
    # nop
    # """
    # cp.cpu.regs[15] = cp.cpu.regs['pr']
    # cp.cpu.regs[0] = 0x8cff_0000

    

    # Run the CPU
    step_count = 0
    trace = args.trace
    max_steps = args.max_steps

    dbg_win = DebuggerWindow()
    dbg_win.attach(cp)
    dbg_win.show()

    # TODO: run trigger cp.run()
    # cp.run()


if __name__ == '__main__':
    sys.exit(main())