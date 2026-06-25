#!/usr/bin/env python3
"""
GUI-less OS boot test.

Boots the Casio fx-CG50 OS ROM (3070.bin) from address 0x80000000.
The OS initializes hardware, sets up the display, and eventually reaches
the main menu.  This test runs headlessly and prints progress.

The CPU registers and peripherals are auto-ticked via the on_step callback,
so polling loops (RTC R64CNT, CMT CMCSR) advance correctly.

Usage:
    python3 test_emu_prog.py [--max-steps N] [--trace]
    python3 test_emu_prog.py --start-pc 0x8CFF0000  # run add-in instead
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad


def main():
    parser = argparse.ArgumentParser(description='RuK OS boot / add-in test')
    parser.add_argument('--max-steps', type=int, default=50000,
                        help='Maximum number of CPU steps (default: 50000)')
    parser.add_argument('--trace', action='store_true',
                        help='Print each instruction as it executes')
    parser.add_argument('--rom', default='cp400/3070.bin',
                        help='Path to the OS ROM')
    parser.add_argument('--addin', default='cp400/print_HelloWorld_and_exit.bin',
                        help='Path to the add-in binary (loaded at 0x8CFF0000)')
    parser.add_argument('--start-pc', type=lambda x: int(x, 0),
                        default=0x80000000,
                        help='Start PC (default: 0x80000000 for OS boot)')
    parser.add_argument('--sr', type=lambda x: int(x, 0),
                        default=0x400001F0,
                        help='Initial SR value (default: 0x400001F0)')
    args = parser.parse_args()

    # Load the OS ROM
    rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.rom)
    if not os.path.exists(rom_path):
        print(f"ROM file not found: {rom_path}")
        return 1
    with open(rom_path, 'rb') as f:
        rom = f.read()
    print(f"Loaded OS ROM: {rom_path} ({len(rom)} bytes)")

    # Create the Classpad with ALL peripherals
    cp = Classpad(rom, debug=False, start_pc=args.start_pc,
                  with_tmu=True, with_rtc=True, with_dma=True, with_display=True)

    # Override SR for OS boot
    cp.cpu.regs['sr'] = args.sr

    # Load add-in into RAM (for later use by the OS)
    addin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.addin)
    if os.path.exists(addin_path):
        with open(addin_path, 'rb') as f:
            addin = f.read()
        cp.ram.write_bin(0x8CFF0000 - 0x8C000000, addin)
        print(f"Add-in loaded at 0x8CFF0000 ({len(addin)} bytes)")

    print(f"Starting execution at PC=0x{cp.cpu.pc:08X}")
    print(f"  R15=0x{cp.cpu.regs[15]:08X} VBR=0x{cp.cpu.regs['vbr']:08X} "
          f"SR=0x{cp.cpu.regs['sr']:08X}")
    print()

    # Run the CPU
    step_count = 0
    trace = args.trace
    max_steps = args.max_steps
    last_pc = 0
    loop_count = 0

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

            # Detect infinite loops (same PC for too many steps)
            if cp.cpu.pc == last_pc:
                loop_count += 1
                if loop_count > 100000:
                    print(f"\n*** Infinite loop detected at PC=0x{cp.cpu.pc:08X} ***")
                    print(f"    Step {step_count}, looped {loop_count} times")
                    r = cp.cpu.regs
                    print(f"    R0=0x{r[0]:08X} R2=0x{r[2]:08X} R4=0x{r[4]:08X} "
                          f"R5=0x{r[5]:08X} R6=0x{r[6]:08X}")
                    print(f"    SR=0x{r['sr']:08X} (T={r['sr']&1})")
                    break
            else:
                last_pc = cp.cpu.pc
                loop_count = 0

            # Print progress every 100K steps
            if step_count % 100000 == 0:
                print(f"  [{step_count:>7d}] PC=0x{cp.cpu.pc:08X} "
                      f"R15=0x{cp.cpu.regs[15]:08X} SR=0x{cp.cpu.regs['sr']:08X}")

            if cp.cpu.is_sleeping:
                print(f"\nCPU entered SLEEP at step {step_count}, PC=0x{cp.cpu.pc:08X}")
                break

        except IndexError as e:
            print(f"\nCPU error at step {step_count}: {e}")
            print(f"  PC=0x{cp.cpu.pc:08X}")
            r = cp.cpu.regs
            print(f"  R0=0x{r[0]:08X} R1=0x{r[1]:08X} R2=0x{r[2]:08X} R3=0x{r[3]:08X}")
            print(f"  R4=0x{r[4]:08X} R5=0x{r[5]:08X} R6=0x{r[6]:08X} R7=0x{r[7]:08X}")
            print(f"  R14=0x{r[14]:08X} R15=0x{r[15]:08X} SR=0x{r['sr']:08X}")
            break
        except Exception as e:
            print(f"\nUnexpected error at step {step_count}: {e}")
            print(f"  PC=0x{cp.cpu.pc:08X}")
            import traceback
            traceback.print_exc()
            break

    print(f"\nExecution finished after {step_count} steps.")
    print(f"  PC=0x{cp.cpu.pc:08X}  ebreak={cp.cpu.ebreak}  sleeping={cp.cpu.is_sleeping}")
    r = cp.cpu.regs
    print(f"  R0=0x{r[0]:08X} R1=0x{r[1]:08X} R2=0x{r[2]:08X} R3=0x{r[3]:08X}")
    print(f"  R4=0x{r[4]:08X} R5=0x{r[5]:08X} R15=0x{r[15]:08X} PR=0x{r['pr']:08X}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
