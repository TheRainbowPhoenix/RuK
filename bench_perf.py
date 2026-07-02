#!/usr/bin/env python3
"""Measure steps/s without redirecting stdout (since print is now gated)."""
import sys, os, time

import test_lcd_r61523 as t

cpu, mem, d = t.make_cpu()
prog = t.assemble(t.LCD_SETUP + """
    mov #0x01, r7
    shll8 r7
    mov #0x68, r0
    or r0, r7
    mov #5, r8
    shll2 r8
    shll2 r8
    shll2 r8
    shll r8
    mov #0, r2
    row_loop:
    mov #0, r3
    col_loop:
    mov r2, r0
    shlr2 r0
    and #0x1F, r0
    shll8 r0
    shll2 r0
    shll r0
    mov r3, r1
    shlr r1
    and #0x3F, r1
    shll2 r1
    shll2 r1
    shll r1
    or r1, r0
    mov r2, r1
    add r3, r1
    and #0x1F, r1
    or r1, r0
    mov.w r0, @r13
    add #1, r3
    cmp/ge r7, r3
    bf col_loop
    add #1, r2
    cmp/ge r8, r2
    bf row_loop
    bra end
    nop
    end: bra end
    nop
""" + t.LCD_POOL, start_addr=0x8C000000)

off = 0
for i, b in enumerate(prog):
    if off + i < len(mem._mem):
        mem._mem[off + i] = b

for N in (5000, 50000, 200000, 500000):
    # Reset CPU
    cpu.pc = 0x8C000000
    cpu._step_count = 0
    cpu.regs['sr'] = 0x40001000
    cpu.regs['vbr'] = 0
    cpu.regs['r15'] = 0x8C080000
    cpu.ebreak = False
    last = 0; lc = 0
    t0 = time.perf_counter()
    s = 0
    for s in range(N):
        cpu.step()
        if cpu.pc == last:
            lc += 1
            if lc > 100: break
        else:
            last = cpu.pc; lc = 0
    t1 = time.perf_counter()
    print(f"{s+1:,} steps in {t1-t0:.3f}s  ->  {(s+1)/(t1-t0):,.0f} steps/s  pc=0x{cpu.pc:08X}")