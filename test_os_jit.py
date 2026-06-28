#!/usr/bin/env python3
"""Test OS boot with JIT enabled."""
import sys, os, time

from ruk.classpad import Classpad

# Load OS ROM
with open('cp400/3070.bin', 'rb') as f:
    rom = f.read()

print(f"Loaded 3070.bin: {len(rom):,} bytes")

# Create Classpad with all peripherals
cp = Classpad(
    rom,
    debug=False,
    with_tmu=True,    # TMU + ETMU + CMT
    with_rtc=True,    # RTC
    with_ubc=False,   # no UBC for now
    with_dma=True,    # DMA
    with_display=True,  # R61523 LCD
    with_bsc=True,
    with_cpg=True,
)

# Reset state
cp.cpu.pc = 0x80000000
cp.cpu.ebreak = False

# Try JIT run for 60 seconds
print(f"\nStarting JIT run for 60 seconds...")
print(f"Initial PC: 0x{cp.cpu.pc:08X}")

t0 = time.perf_counter()
try:
    steps = cp.cpu.run(max_steps=500_000_000)
except Exception as e:
    print(f"Exception: {e!r}")
    import traceback; traceback.print_exc()
    steps = cp.cpu._step_count
t1 = time.perf_counter()

print(f"\n--- Results ---")
print(f"Wall time:    {t1-t0:.2f}s")
print(f"Steps:        {steps:,}")
print(f"Throughput:   {steps/(t1-t0):,.0f} steps/s")
print(f"Final PC:     0x{cp.cpu.pc:08X}")
print(f"ebreak:       {cp.cpu.ebreak}")
print(f"JIT stats:    {cp.cpu.jit_stats()}")

# Dump some state
print(f"\n--- CPU State ---")
r = cp.cpu.regs
print(f"  R0 =0x{r[0]:08X}  R1 =0x{r[1]:08X}  R2 =0x{r[2]:08X}  R3 =0x{r[3]:08X}")
print(f"  R4 =0x{r[4]:08X}  R5 =0x{r[5]:08X}  R6 =0x{r[6]:08X}  R7 =0x{r[7]:08X}")
print(f"  R8 =0x{r[8]:08X}  R9 =0x{r[9]:08X}  R10=0x{r[10]:08X}  R11=0x{r[11]:08X}")
print(f"  R12=0x{r[12]:08X}  R13=0x{r[13]:08X}  R14=0x{r[14]:08X}  R15=0x{r[15]:08X}")
print(f"  PR =0x{r['pr']:08X}  SR =0x{r['sr']:08X}")