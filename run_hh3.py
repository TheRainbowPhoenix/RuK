#!/usr/bin/env python3
"""Standalone hh3 runner.

Usage:
    python3 run_hh3.py <file.hh3> [max_steps] [--btu] [--hle-root DIR] [--single-step]

Loads and runs an .hh3 file on the RuK emulator with all peripherals
attached.  Useful for quick testing without the GUI.
"""
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.hh3 import run_hh3, parse_elf, get_metadata
from ruk.jcore.btu import BTUEntryBreakpoint
from ruk.jcore.hh3_hle import HH3WaitKey, VRAM


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hh3_path')
    parser.add_argument('max_steps', nargs='?', type=int, default=10_000_000)
    parser.add_argument('--btu', action='store_true')
    parser.add_argument('--hle-root', help='read-only directory mounted as fls0')
    parser.add_argument('--hle-font', help='95 RGB565 glyphs extracted from a compatible OS')
    parser.add_argument('--single-step', action='store_true', help='use the instruction interpreter')
    parser.add_argument('--engine', choices=('cached', 'jit', 'step'), help='defaults to cached with HLE, jit otherwise')
    parser.add_argument('--class-name', help='Java main class passed as the first launcher argument')
    parser.add_argument('--stop-at-j-jp', action='store_true', help='pause before the first BTU handoff')
    parser.add_argument('--btu-trace', help='write BTU counters and the first 32 handoffs as JSON')
    parser.add_argument('--screen-output', help='save the final LCD framebuffer as an image (requires Pillow)')
    args = parser.parse_args()
    if args.btu_trace and not args.btu:
        parser.error('--btu-trace requires --btu')
    hh3_path, max_steps = args.hh3_path, args.max_steps

    # 1. Print hh3 metadata
    with open(hh3_path, 'rb') as f:
        data = f.read()
    parsed = parse_elf(data)
    meta = get_metadata(parsed)
    print(f"HH3 file:       {hh3_path}")
    print(f"Entry point:    0x{parsed['e_entry']:08X}")
    print(f"Segments:       {parsed['e_phnum']}")
    for i, phdr in enumerate(parsed['phdrs']):
        if phdr['p_type'] == 1:  # PT_LOAD
            flags = ''
            if phdr['p_flags'] & 4: flags += 'R'
            if phdr['p_flags'] & 2: flags += 'W'
            if phdr['p_flags'] & 1: flags += 'X'
            print(f"  [{i}] LOAD vaddr=0x{phdr['p_vaddr']:08X} "
                  f"filesz=0x{phdr['p_filesz']:X} memsz=0x{phdr['p_memsz']:X} "
                  f"flags={flags}")
    if any(meta.values()):
        print(f"Metadata:")
        for k, v in meta.items():
            if v: print(f"  {k}: {v!r}")

    # 2. Load OS ROM (needed for the memory map)
    rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'cp400', '3070.bin')
    if not os.path.exists(rom_path):
        print(f"\nERROR: OS ROM not found at {rom_path}")
        sys.exit(1)
    with open(rom_path, 'rb') as f:
        rom = f.read()
    print(f"\nOS ROM:         {len(rom):,} bytes")

    # 3. Set up Classpad with all peripherals
    cp = Classpad(
        rom, debug=False,
        with_tmu=True, with_rtc=True, with_dma=True,
        with_display=True, with_bsc=True, with_cpg=True,
        with_btu=args.btu,
    )
    engine = 'step' if args.single_step else args.engine or ('cached' if args.hle_root else 'jit')
    if engine != 'jit':
        cp.cpu.debug = True  # propagate memory/decoder failures to the runner
    if args.stop_at_j_jp:
        if not args.btu:
            parser.error('--stop-at-j-jp requires --btu')
        cp.cpu.btu.break_on_entry = True

    # 4. Load and run the hh3
    print(f"\nLoading {os.path.basename(hh3_path)}...")
    entry = run_hh3(cp, hh3_path,
                    argv=[os.path.basename(hh3_path)] + ([args.class_name] if args.class_name else []),
                    envp=None if args.hle_root else {'HHK_SYMBOL_TABLE': '0',
                          'HHK_SYMBOL_TABLE_LEN': '0'}, hle_root=args.hle_root,
                    hle_font=args.hle_font)
    print(f"PC:             0x{cp.cpu.pc:08X}")
    print(f"R15 (SP):       0x{cp.cpu.regs[15]:08X}")
    print(f"R4 (argc):      {cp.cpu.regs[4]}")
    print(f"R5 (argv):      0x{cp.cpu.regs[5]:08X}")
    print(f"R6 (envp):      0x{cp.cpu.regs[6]:08X}")

    # 5. Run
    print(f"\nRunning ({max_steps:,} steps max)...")
    t0 = time.perf_counter()
    failed = False
    try:
        if engine == 'step':
            steps = 0
            while steps < max_steps and not cp.cpu.ebreak and cp.cpu.pc != 0xffffffff:
                cp.cpu.step()
                steps += 1
        elif engine == 'cached':
            from ruk.jcore.hh3_runner import run_cached
            steps = run_cached(cp.cpu, max_steps)
        else:
            steps = cp.cpu.run(max_steps=max_steps)
    except (BTUEntryBreakpoint, HH3WaitKey) as e:
        print(f'Paused: {e}')
        steps = cp.cpu._step_count
    except Exception as e:
        failed = True
        print(f"Exception: {e!r}")
        import traceback; traceback.print_exc()
        steps = cp.cpu._step_count
    t1 = time.perf_counter()

    print(f"\nResults:")
    print(f"  Wall time:    {t1-t0:.2f}s")
    print(f"  Steps:        {steps:,}")
    print(f"  Throughput:   {steps/(t1-t0):,.0f} steps/s")
    print(f"  Final PC:     0x{cp.cpu.pc:08X}")
    print(f"  ebreak:       {cp.cpu.ebreak}")
    if args.hle_root:
        print(f"  HH3 services: {cp.cpu.hh3_hle.calls}")
    if args.btu:
        btu = cp.cpu.btu
        print(f'  BTU: {btu.entries} J_JP entries, {btu.enabled_entries} enabled; exits {dict(btu.exits)}')
        print(f'  Last BTU entry: {btu.last_entry}; exit: {btu.last_exit}')
        print(f'  Java bytecodes: {dict(sorted(btu.bytecodes.items()))}')
        if args.btu_trace:
            import json
            with open(args.btu_trace, 'w', encoding='utf-8') as f:
                json.dump(dict(entries=btu.entries, enabled_entries=btu.enabled_entries,
                               exits=btu.exits, bytecodes=btu.bytecodes,
                               first_handoffs=btu.first_handoffs,
                               last_entry=btu.last_entry, last_exit=btu.last_exit), f, indent=2)
    if args.screen_output:
        from PIL import Image
        pixels = bytearray()
        for offset in range(0, 0x52800, 2):
            color = cp.mem.read16(VRAM + offset)
            pixels.extend((((color >> 11) & 31) * 255 // 31,
                           ((color >> 5) & 63) * 255 // 63,
                           (color & 31) * 255 // 31))
        Image.frombytes('RGB', (320, 528), bytes(pixels)).save(args.screen_output)
        print(f'  LCD image: {args.screen_output}')
    if hasattr(cp.cpu, 'jit_stats'):
        print(f"  JIT stats:    {cp.cpu.jit_stats()}")

    r = cp.cpu.regs
    print(f"\n  R0 =0x{r[0]:08X}  R1 =0x{r[1]:08X}  R2 =0x{r[2]:08X}  R3 =0x{r[3]:08X}")
    print(f"  R4 =0x{r[4]:08X}  R5 =0x{r[5]:08X}  R6 =0x{r[6]:08X}  R7 =0x{r[7]:08X}")
    print(f"  R8 =0x{r[8]:08X}  R9 =0x{r[9]:08X}  R10=0x{r[10]:08X}  R11=0x{r[11]:08X}")
    print(f"  R12=0x{r[12]:08X}  R13=0x{r[13]:08X}  R14=0x{r[14]:08X}  R15=0x{r[15]:08X}")
    print(f"  PR =0x{r['pr']:08X}  SR =0x{r['sr']:08X}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
