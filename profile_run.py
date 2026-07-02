#!/usr/bin/env python3
"""
Profile test_full_gradient for 60 seconds, then dump cProfile stats.

Strategy:
- Run the actual emulator loop with cProfile enabled.
- Stop after either max_steps reached or a wall-clock deadline.
- Print the top 30 hot functions (cumulative time).
- Save the full stats to /home/z/my-project/scripts/profile.out for pstats analysis.
"""
import sys, os, time, cProfile, pstats, io, signal

# Quiet the disassembler's print() spam during profiling by redirecting stdout
# to /dev/null.  This is part of the *baseline* measurement -- the print is
# currently happening in production code, so we want to measure its impact
# separately by toggling it.
QUIET = True
if QUIET:
    _real_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')

import test_lcd_r61523 as t

if QUIET:
    sys.stdout = _real_stdout  # restore for our own prints

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

off = 0x8C000000 - 0x8C000000
for i, b in enumerate(prog):
    if off + i < len(mem._mem):
        mem._mem[off + i] = b

DEADLINE = 60.0   # seconds
MAX_STEPS = 8_000_000

# Patch step loop into a tight local function for profiling accuracy.
step = cpu.step
pc_get = lambda: cpu.pc
class _Kill(Exception): pass
def alarm_handler(signum, frame):
    raise _Kill()
signal.signal(signal.SIGALRM, alarm_handler)
signal.alarm(int(DEADLINE))

pr = cProfile.Profile()
pr.enable()

n = 0
last = 0; lc = 0
try:
    for s in range(MAX_STEPS):
        step()
        if cpu.pc == last:
            lc += 1
            if lc > 100:
                break
        else:
            last = cpu.pc; lc = 0
        n = s + 1
except _Kill:
    pass
except Exception as e:
    print(f"Stopped early: {e!r}")

pr.disable()
signal.alarm(0)

elapsed = 0  # we don't have wall clock from cProfile directly
print(f"\n=== Profile run: {n:,} steps ===")
print(f"Final PC: 0x{cpu.pc:08X}  (last=0x{last:08X} lc={lc})")

# Cumulative top 30
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
ps.print_stats(30)
print(s.getvalue())

# Time top 30 (self time)
s2 = io.StringIO()
ps2 = pstats.Stats(pr, stream=s2).sort_stats('tottime')
ps2.print_stats(30)
print("--- By tottime (self time) ---")
print(s2.getvalue())

# Callers of step / disasm / resolve
s3 = io.StringIO()
ps3 = pstats.Stats(pr, stream=s3).sort_stats('cumulative')
ps3.print_callers(20, 'disasm|resolve|step|read16|write16|_u32|__getitem__|__setitem__')
print("--- Callers of hot functions ---")
print(s3.getvalue())

# Save full stats for later analysis
pr.dump_stats('profile.out')
print("Full stats saved to profile.out")

# Also print steps/s based on the profile's total time
total_time = ps.total_tt
print(f"\ncProfile total time: {total_time:.3f}s")
print(f"Throughput: {n/total_time:,.0f} steps/s")