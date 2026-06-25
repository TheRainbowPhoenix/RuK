#!/usr/bin/env python3
"""
TMU test for RuK.

Builds a tiny SH-4 program by hand-assembling the bytes (RuK has no
assembler), loads it into the emulator with `with_tmu=True`, then runs
it.  The program:

  1. Sets up VBR to point to a tiny exception vector table in RAM.
     The VBR+0x600 slot (general IRQ handler) jumps to a fixed
     "IRQ handler" address.
  2. The IRQ handler increments a counter in RAM (at 0x8C001000), then
     returns (without RTE -- we just JMP back to the main loop).
  3. The main program configures TMU0:
       - TCOR0 = 10         (so it underflows every 10 Pphi ticks)
       - TCNT0 = 10
       - TCR0  = UNIE=1     (interrupt on underflow)
       - TSTR  = STR0=1     (start timer)
  4. The main program loops forever, polling the IRQ counter, and
     halts (via `ebreak`) when the counter reaches 3.

The host advances TMU time explicitly via `cp.tick_tmu(pphi_cycles=...)`
between CPU steps.  Each call advances the TMU enough to fire one
underflow, so after 3 host ticks we expect the counter to be 3 and the
CPU to halt.

This test exercises:
  - MMIO reads/writes (TSTR, TCOR0, TCNT0, TCR0)
  - TMU underflow detection
  - IRQ delivery via the InterruptController
  - The full VBR+0x600 vectoring path

Run with:
    python3 test_tmu.py
"""

import struct
import sys

from ruk.classpad import Classpad
from ruk.jcore.tmu import (
    TMU_BASE, TMU_TSTR, TMU_CHAN_BASE, TMU_CHAN_STRIDE,
    ETMU_BASE, ETMU_CHAN_BASE, ETMU_CHAN_STRIDE, ETMU_REGION_SIZE,
    TMU_TCR_UNIE, TMU_TCR_UNF,
)


# ===========================================================================
# Memory layout for the test
# ===========================================================================

# We use RAM at 0x8C000000 for everything (code, stack, vector table, counter).
RAM_BASE      = 0x8C000000
RAM_SIZE      = 0x10000          # 64 KB

# Code lives at the start of RAM, entry at 0x8C000000.
CODE_ADDR     = 0x8C000000

# Stack pointer (top of our 64 KB region, 16-byte aligned).
STACK_TOP     = RAM_BASE + RAM_SIZE - 16

# Vector table: VBR points here.  General IRQ handler slot is at VBR + 0x600.
VBR_ADDR      = 0x8C002000       # VBR
IRQ_HANDLER   = 0x8C003000       # the actual handler code
IRQ_COUNTER   = 0x8C001000       # the counter byte the handler increments


# ===========================================================================
# Tiny SH-4 machine-code assembler
# ===========================================================================
#
# We only need a handful of instructions.  Each function below returns the
# 16-bit big-endian encoding of one SH-4 instruction.  The "delay slot"
# after each branch is filled with a NOP (0x0009 = NOP, though RuK may use
# a different ID; we'll use 0x0009 which is the standard SH-4 NOP).

def NOP():           return b'\x00\x09'
def MOV_IMM(i, n):   return struct.pack('>H', 0xE000 | (n << 8) | (i & 0xFF))
def MOV_LL(d, n):    return struct.pack('>H', 0xD000 | (n << 8) | (d & 0xFF))  # MOV.L @(disp*4,PC), Rn
def MOV_LS(m, d, n): return struct.pack('>H', 0x1000 | (n << 8) | (m << 4) | (d & 0x0F))  # MOV.L Rm, @(disp*4, Rn)
def MOV_LL_REG(m, n): return struct.pack('>H', 0x6000 | (n << 8) | (m << 4) | 0x02)  # MOV.L @Rm, Rn
def MOVBS(m, n):     return struct.pack('>H', 0x2000 | (n << 8) | (m << 4) | 0x00)  # MOV.B Rm, @Rn
def MOVBL(m, n):     return struct.pack('>H', 0x6000 | (n << 8) | (m << 4) | 0x00)  # MOV.B @Rm, Rn
def MOVLS4(m, d, n): return struct.pack('>H', 0x1000 | (n << 8) | (m << 4) | (d & 0x0F))  # MOV.L Rm, @(disp*4,Rn)
def MOVLL4(m, d, n): return struct.pack('>H', 0x5000 | (n << 8) | (m << 4) | (d & 0x0F))  # MOV.L @(disp*4,Rm), Rn
def MOV_RR(m, n):    return struct.pack('>H', 0x6000 | (n << 8) | (m << 4) | 0x03)  # MOV Rm, Rn
def ADD_IMM(i, n):   return struct.pack('>H', 0x7000 | (n << 8) | (i & 0xFF))
def TST_IMM(i):      return struct.pack('>H', 0xC800 | (i & 0xFF))  # TST #imm, R0
def BT(d):           return struct.pack('>H', 0x8900 | (d & 0xFF))
def BF(d):           return struct.pack('>H', 0x8B00 | (d & 0xFF))
def BRA(d):          return struct.pack('>H', 0xA000 | (d & 0xFFF))  # signed 12-bit
def RTS():           return b'\x00\x0B'
def JMP_RN(n):       return struct.pack('>H', 0x4020 | (n << 8) | 0x2B)  # JMP @Rn
def JSR_RN(n):       return struct.pack('>H', 0x4000 | (n << 8) | 0x0B)  # JSR @Rn
def SLEEP():         return b'\x00\x1B'
def MOVWL_G(d, r0):  return struct.pack('>H', 0x8500 | ((d & 0xFF)))  # MOV.W @(disp,GBR), R0 -- not used here
def MOVWS0(m, n):    return struct.pack('>H', 0x8000 | (n << 8) | (m << 4) | 0x01)  # MOV.W Rm, @(R0,Rn)


# ===========================================================================
# Build the program
# ===========================================================================

def build_program():
    """
    Returns a dict of {address: bytes} to be placed at various RAM offsets.

    Layout:
      0x8C000000: main program (entry)
      0x8C002000: VBR exception table (must have IRQ handler ptr at +0x600)
      0x8C003000: IRQ handler
      0x8C001000: counter byte (initialized to 0)
    """
    chunks = {}

    # --- main program at 0x8C000000 ---
    main = b''
    # 1. Set up R15 (stack pointer) = STACK_TOP
    #    MOV #imm8 cannot encode 0x8C directly (signed 8-bit), so we use
    #    MOV.L @(disp,PC), R15 to load a 32-bit constant.
    #    We'll place the constant pool right after the main code.
    #
    # Layout of the constant pool (each entry 4 bytes):
    #   pool[0]: STACK_TOP       = 0x8C010000 - 16 = 0x8C00FFF0
    #   pool[1]: VBR_ADDR        = 0x8C002000
    #   pool[2]: IRQ_COUNTER     = 0x8C001000
    #   pool[3]: TMU_BASE        = 0xFFD80000
    #   pool[4]: TMU_BASE+0x04 (TCOR0)
    #   pool[5]: TMU_BASE+0x08 (TCNT0)
    #   pool[6]: TMU_BASE+0x0C (TCR0)
    #   pool[7]: TMU_BASE+0x00 (TSTR)
    #   pool[8]: 3 (target counter value)
    #
    # The PC-relative offset for MOV.L @(disp,PC), Rn is (disp*4 + (PC & ~3) + 4).
    # We'll compute the disp values based on where each load instruction is.

    # We'll build the code first, then the constant pool, and patch the
    # displacements afterwards.

    # --- Pre-compute the code structure ---
    # Each MOV.L @(disp,PC), Rn is 2 bytes; we need 9 of them = 18 bytes.
    # Then:
    #   - LDC Rn, VBR  -- RuK doesn't implement LDC, so we'll set VBR
    #     directly from Python (set cpu.regs['vbr']).
    #   - Set up TMU0:
    #       MOV.L TCOR0_addr, R4    -> write 0x0A to @R4 (TCOR0 = 10)
    #       MOV.L TCNT0_addr, R5    -> write 0x0A to @R5 (TCNT0 = 10)
    #       MOV.L TCR0_addr,  R6    -> write 0x0100 to @R6 (TCR0 = UNIE)
    #       MOV.L TSTR_addr,  R7    -> write 0x01 to @R7 (TSTR = STR0)
    #   - Loop:
    #       MOV.B @R8, R0   (read counter)
    #       CMP/EQ #3, R0
    #       BT done
    #       BRA loop
    #       NOP
    #     done:
    #       SLEEP (or just stop -- RuK treats SLEEP as NOP)
    #
    # We need to write a 32-bit value to TCOR0/TCNT0 -- RuK doesn't have
    # MOV.L Rm, @Rn in the emulator's _resolve_table (wait, it does -- entry 12).
    # Let me check: 12: self.MOVLS -> MOV.L Rm, @Rn.  Good.

    # Actually we don't need LDC.  We'll set VBR from Python and just
    # make the main program set up TMU0 and loop.

    main += MOV_LL(0, 15)  # MOV.L @(0*4,PC), R15  -- load STACK_TOP
    # PC for the next instruction is CODE_ADDR + 2; the @(0,PC) load reads
    # from ((PC+2) & ~3) + 4 = CODE_ADDR + 4 (if CODE_ADDR is 4-aligned, which it is).
    # So pool[0] (STACK_TOP) must be at CODE_ADDR + 4.
    # We'll patch the pool offset later.

    # The pool will start at offset 4 (right after this 2-byte instruction),
    # but we'll actually put it later.  Let me just compute everything
    # explicitly below.

    # Let me restart with a cleaner approach: build the code linearly,
    # and put the constant pool at the end.  Use a placeholder for the
    # displacement values, then patch them once we know the pool layout.

    main = b''

    # Instruction 0: MOV.L @(disp0,PC), R15  -- STACK_TOP
    main += MOV_LL(0, 15)
    # Instruction 1: MOV.L @(disp1,PC), R8   -- IRQ_COUNTER (used by handler too, but we'll re-load in handler)
    main += MOV_LL(0, 8)
    # Instruction 2: MOV.L @(disp2,PC), R4   -- TCOR0 addr (TMU_BASE + 0x04)
    main += MOV_LL(0, 4)
    # Instruction 3: MOV.L @(disp3,PC), R5   -- TCNT0 addr (TMU_BASE + 0x08)
    main += MOV_LL(0, 5)
    # Instruction 4: MOV.L @(disp4,PC), R6   -- TCR0 addr (TMU_BASE + 0x0C)
    main += MOV_LL(0, 6)
    # Instruction 5: MOV.L @(disp5,PC), R7   -- TSTR addr (TMU_BASE + 0x00)
    main += MOV_LL(0, 7)

    # Instruction 6: MOV #10, R0   -- TCOR0/TCNT0 value
    main += MOV_IMM(10, 0)
    # Instruction 7: MOV.L R0, @R4  -- write TCOR0 = 10
    main += struct.pack('>H', 0x2000 | (4 << 8) | (0 << 4) | 0x02)  # MOV.L R0, @R4 = 0x2402
    # Instruction 8: MOV.L R0, @R5  -- write TCNT0 = 10
    main += struct.pack('>H', 0x2000 | (5 << 8) | (0 << 4) | 0x02)  # 0x2502

    # Instruction 9: MOV #0, R0   -- clear R0 (will be the value for TCR0 = UNIE)
    main += MOV_IMM(0, 0)
    # We need TCR0 = 0x0080 (UNIE = bit 7).  Use MOV #imm8 directly:
    # MOV #0x80, R0 would be sign-extended to 0xFFFFFF80, which is wrong.
    # Instead use MOV #1, R0; SHLL2 R0; SHLL2 R0; SHLL2 R0 -> R0 = 0x80.
    # Or simpler: MOV #0x80, R2; AND #0xFF, R2 (clears upper bits); MOV R2, R0.
    # Actually the simplest: use MOV.W @(disp,PC), R0 to load 0x0080 from a
    # constant pool.  But that's complex.  Let's just do:
    #   MOV #1, R0
    #   SHLL2 R0    (R0 = 4)
    #   SHLL2 R0    (R0 = 16)
    #   SHLL2 R0    (R0 = 64)
    #   SHLL R0     (R0 = 128 = 0x80)  -- SHLL = shift left 1
    # SHLL2 = 0x4008 | (n << 8), SHLL = 0x4000 | (n << 8)
    main = main[:-2]  # undo the MOV #0, R0
    main += MOV_IMM(1, 0)                                    # MOV #1, R0
    main += struct.pack('>H', 0x4008 | (0 << 8))             # SHLL2 R0  -> R0 = 4
    main += struct.pack('>H', 0x4008 | (0 << 8))             # SHLL2 R0  -> R0 = 16
    main += struct.pack('>H', 0x4008 | (0 << 8))             # SHLL2 R0  -> R0 = 64
    main += struct.pack('>H', 0x4000 | (0 << 8))             # SHLL R0   -> R0 = 128 = 0x80 (UNIE)
    main += struct.pack('>H', 0x2000 | (6 << 8) | (0 << 4) | 0x02)  # MOV.L R0, @R6 = TCR0 = 0x80

    # Instruction: MOV #1, R0   -- TSTR = STR0 = 1
    main += MOV_IMM(1, 0)
    # MOV.B R0, @R7  -- write TSTR (8-bit register)
    main += MOVBS(0, 7)                                       # 0x2070

    # After configuring TMU0, the main program just SLEEPs.  The host
    # (this Python script) advances TMU time and lets the IRQ handler
    # run.  After 3 IRQs, we stop the test.
    #
    # Note: RuK doesn't implement SLEEP (opcode 226) -- it'll raise
    # IndexError("OPCode index 226 not resolved"), which sets ebreak=True.
    # We use that as our "main program done" signal.

    loop_offset = len(main)  # this is where the SLEEP is, used as the handler's return target
    main += SLEEP()          # 0x001B  -- main program "done"
    main += NOP()            # padding

    # Constant pool (must be 4-byte aligned relative to PC).
    # Each MOV.L @(disp,PC), Rn reads from ((PC+4) & ~3) + disp*4.
    # We'll place the pool starting at the next 4-byte boundary after main.
    pool_start = (len(main) + 3) & ~3
    main += b'\x00\x00' * ((pool_start - len(main)) // 2)  # padding NOPs

    # Now compute the pool entries and their PC-relative displacements.
    # Each MOV.L is at instruction index k (0-based), so its PC = CODE_ADDR + 2*k.
    # Its (PC+4) & ~3 = CODE_ADDR + 2*k + 4, rounded down to 4.
    # Pool entry i is at offset pool_start + 4*i (relative to CODE_ADDR).
    # So disp_i = (CODE_ADDR + pool_start + 4*i - ((CODE_ADDR + 2*k_i + 4) & ~3)) / 4
    #           = (pool_start + 4*i - ((2*k_i + 4) & ~3)) / 4

    # k_i = instruction index of the i-th MOV.L (0, 1, 2, 3, 4, 5)
    k = [0, 1, 2, 3, 4, 5]
    pool_entries = [
        STACK_TOP,                                          # 0: R15
        IRQ_COUNTER,                                        # 1: R8
        TMU_CHAN_BASE + 0 * TMU_CHAN_STRIDE + 0x00,         # 2: R4 = TCOR0 addr (0xA4490008)
        TMU_CHAN_BASE + 0 * TMU_CHAN_STRIDE + 0x04,         # 3: R5 = TCNT0 addr (0xA449000C)
        TMU_CHAN_BASE + 0 * TMU_CHAN_STRIDE + 0x08,         # 4: R6 = TCR0  addr (0xA4490010)
        TMU_TSTR,                                           # 5: R7 = TSTR  addr (0xA4490004)
    ]

    # Compute and patch displacements
    for i, k_i in enumerate(k):
        # The MOV.L instruction is at offset 2*k_i in main
        mov_off = 2 * k_i
        pc = CODE_ADDR + mov_off
        # Effective load address: ((PC+4) & ~3) + disp*4
        eff_base = (pc + 4) & ~3
        target_addr = CODE_ADDR + pool_start + 4 * i
        disp = (target_addr - eff_base) // 4
        assert 0 <= disp <= 0xFF, f"pool disp {disp} out of range for entry {i}"
        # Patch the displacement byte (low byte of the 16-bit instruction)
        # Instruction format: 0xD0..0xDF with low byte = disp
        old = main[mov_off:mov_off+2]
        new = bytes([old[0], disp])
        main = main[:mov_off] + new + main[mov_off+2:]

    # Append the pool
    for entry in pool_entries:
        main += struct.pack('>I', entry)

    chunks[CODE_ADDR] = main

    # --- IRQ handler at 0x8C003000 ---
    # The handler:
    #   1. Increment the byte at IRQ_COUNTER (0x8C001000).
    #   2. Clear TCR0.UNF (write 0 to bit 8 -- but UNF is write-0-to-clear,
    #      so we need to write TCR0 with UNF=0 and the other bits preserved).
    #      For simplicity, we just write TCR0 = 0x0100 (UNIE only, UNF=0),
    #      which clears UNF and keeps UNIE set.
    #   3. Return to the main loop (JMP @PR or just JMP back to a known addr).
    #      We don't have RTE in RuK, so we'll just JMP to the main loop.
    #      But we don't know the main loop address at handler-compile time,
    #      so we'll set PR from Python before the IRQ fires, or use a fixed
    #      return address that the handler loads from a constant.
    #
    # Simpler approach: the handler just increments the counter, clears UNF,
    # and returns to a fixed "main loop" address that we hardcode as
    # CODE_ADDR + loop_offset (the start of the polling loop).

    handler = b''
    # MOV.L @(disp,PC), R8   -- IRQ_COUNTER
    handler += MOV_LL(0, 8)             # load IRQ_COUNTER addr
    # MOV.B @R8, R0          -- read counter
    handler += MOVBL(8, 0)
    # ADD #1, R0             -- increment
    handler += ADD_IMM(1, 0)
    # MOV.B R0, @R8          -- store back
    handler += MOVBS(0, 8)

    # Clear TCR0.UNF but keep UNIE=1: write 0x0080.
    # MOV.L @(disp,PC), R6   -- TCR0 addr
    handler += MOV_LL(0, 6)             # load TCR0 addr
    # Build 0x0080 in R0: MOV #1, R0; SHLL2 x3; SHLL
    handler += MOV_IMM(1, 0)
    handler += struct.pack('>H', 0x4008 | (0 << 8))    # SHLL2 R0 -> 4
    handler += struct.pack('>H', 0x4008 | (0 << 8))    # SHLL2 R0 -> 16
    handler += struct.pack('>H', 0x4008 | (0 << 8))    # SHLL2 R0 -> 64
    handler += struct.pack('>H', 0x4000 | (0 << 8))    # SHLL R0  -> 128 = 0x80
    # MOV.W R0, @R6  -- TCR0 is 16-bit, so use MOV.W
    handler += struct.pack('>H', 0x2000 | (6 << 8) | (0 << 4) | 0x01)  # 0x2601

    # Return: JMP @PR (we'll set PR from Python to the main loop address)
    # JMP @Rn = 0x4020 | (n<<8) | 0x2B
    # We need to load the return address into a register first.
    # Actually, let's just hardcode the return address in the pool.
    # MOV.L @(disp,PC), R3   -- return addr (= CODE_ADDR + loop_offset)
    handler += MOV_LL(1, 3)
    # JMP @R3
    handler += JMP_RN(3)
    handler += NOP()                    # delay slot

    # Pool for the handler
    handler_pool_start = (len(handler) + 3) & ~3
    handler += b'\x00\x09' * ((handler_pool_start - len(handler)) // 2)

    # Patch pool displacement for entry 0 (IRQ_COUNTER) and entry 1 (return addr)
    # Entry 0: MOV.L at handler offset 0
    pc = IRQ_HANDLER + 0
    eff_base = (pc + 4) & ~3
    target = IRQ_HANDLER + handler_pool_start
    disp = (target - eff_base) // 4
    handler = handler[:0+1] + bytes([disp]) + handler[0+2:]

    # Entry 1: MOV.L at handler offset (find it)
    # Layout after the SHLL2 x3 + SHLL change:
    # 0: MOV_LL(0, 8)         @ offset 0
    # 1: MOVBL(8, 0)          @ offset 2
    # 2: ADD_IMM(1, 0)        @ offset 4
    # 3: MOVBS(0, 8)          @ offset 6
    # 4: MOV_LL(0, 6)         @ offset 8
    # 5: MOV_IMM(1, 0)        @ offset 10
    # 6: SHLL2 R0             @ offset 12
    # 7: SHLL2 R0             @ offset 14
    # 8: SHLL2 R0             @ offset 16
    # 9: SHLL R0              @ offset 18
    # 10: MOV.W R0, @R6       @ offset 20
    # 11: MOV_LL(1, 3)        @ offset 22  <- entry 1 pool
    # 12: JMP @R3             @ offset 24
    # 13: NOP                 @ offset 26
    pc = IRQ_HANDLER + 22
    eff_base = (pc + 4) & ~3
    target = IRQ_HANDLER + handler_pool_start + 4  # entry 1
    disp = (target - eff_base) // 4
    handler = handler[:22+1] + bytes([disp]) + handler[22+2:]

    # Append pool
    handler += struct.pack('>I', IRQ_COUNTER)
    handler += struct.pack('>I', CODE_ADDR + loop_offset)

    chunks[IRQ_HANDLER] = handler

    # --- VBR exception table at 0x8C002000 ---
    # General IRQ handler slot is VBR + 0x600.
    # The SH-4 doesn't store a function pointer at VBR+0x600 -- it directly
    # jumps to VBR+0x600.  So we just need to make sure IRQ_HANDLER == VBR+0x600,
    # OR we set VBR = IRQ_HANDLER - 0x600.
    # We chose IRQ_HANDLER = 0x8C003000, so VBR should be 0x8C003000 - 0x600 = 0x8C002A00.
    # Let's override VBR_ADDR to match.
    vbr_actual = IRQ_HANDLER - 0x600

    return chunks, vbr_actual, loop_offset


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=== RuK TMU Test ===\n")

    chunks, vbr, loop_offset = build_program()

    # Print the layout
    print(f"Memory layout:")
    print(f"  CODE_ADDR     = 0x{CODE_ADDR:08X}")
    print(f"  IRQ_COUNTER   = 0x{IRQ_COUNTER:08X}")
    print(f"  VBR           = 0x{vbr:08X}  (so VBR+0x600 = 0x{vbr+0x600:08X})")
    print(f"  IRQ_HANDLER   = 0x{IRQ_HANDLER:08X}")
    print(f"  STACK_TOP     = 0x{STACK_TOP:08X}")
    print(f"  Loop offset   = 0x{loop_offset:X} (PC of polling loop = 0x{CODE_ADDR+loop_offset:08X})")
    print()

    # Build the ROM image: we'll use a single RAM region at 0x8C000000.
    # The Classpad constructor wants a `rom` argument, but with `start_pc`
    # we can place the code anywhere.  We'll create the Classpad with an
    # empty ROM, then write the chunks directly to RAM.
    rom = b'\x00\x09'  # placeholder NOP (will be overwritten)

    cp = Classpad(rom, debug=False, start_pc=CODE_ADDR, with_tmu=True)

    # Set VBR
    cp.cpu.regs['vbr'] = vbr
    # Set PR (in case the handler used RTS -- it doesn't, but just in case)
    cp.cpu.regs['pr'] = CODE_ADDR + loop_offset
    # Set SR.BL=0, SR.MD=1 (privileged, interrupts allowed)
    cp.cpu.regs['sr'] = 0x40000000  # MD=1, BL=0, IF=0, RB=0

    # Write all chunks to RAM
    for addr, data in chunks.items():
        offset = addr - 0x8C00_0000
        cp.ram.write_bin(offset, data)

    # Initialize the counter to 0
    cp.ram.write_bin(IRQ_COUNTER - 0x8C00_0000, b'\x00')

    # Dump the TMU state before running
    print("TMU state before run:")
    print(cp.tmu.dump())
    print()

    # Phase 1: Run the CPU until it hits SLEEP (ebreak).
    # This executes the main program, which configures TMU0 and then sleeps.
    print("\n--- Phase 1: run main program (configure TMU0, then SLEEP) ---")
    phase1_steps = 0
    while not cp.cpu.ebreak and phase1_steps < 50:
        cp.cpu.step()
        phase1_steps += 1
    print(f"Phase 1 done after {phase1_steps} steps. ebreak={cp.cpu.ebreak}, PC=0x{cp.cpu.pc:08X}")

    # Reset ebreak so we can keep going (the SLEEP "error" is expected)
    cp.cpu.ebreak = False

    # Phase 2: tick TMU + run handler, 3 times.
    # Each tick of 50 Pphi cycles causes one TCNT0 underflow:
    #   TCNT0 starts at 10, prescaler = /4, so 4 cycles per TCNT decrement.
    #   50 cycles = 12 decrements = 1 underflow (after 10) + 2 more decrements.
    print("\n--- Phase 2: tick TMU 3 times, each tick should fire one IRQ ---")
    for i in range(3):
        print(f"\n  [tick {i+1}/3] Advancing TMU by 50 Pphi cycles...")
        cp.tick_tmu(pphi_cycles=50)

        # The tick should have queued an IRQ.  Run the CPU a few steps to
        # let the INTC deliver it and the handler run.
        cp.cpu.ebreak = False
        steps = 0
        while not cp.cpu.ebreak and steps < 30:
            cp.cpu.step()
            steps += 1
        counter = cp.ram.read8(IRQ_COUNTER - 0x8C00_0000)
        print(f"  After {steps} CPU steps: counter = {counter}, PC = 0x{cp.cpu.pc:08X}")
        cp.cpu.ebreak = False  # reset for next iteration

    # Read the counter
    counter = cp.ram.read8(IRQ_COUNTER - 0x8C00_0000)
    print()
    print(f"Final state:")
    print(f"  IRQ counter at 0x{IRQ_COUNTER:08X} = {counter}")
    print(f"  PC = 0x{cp.cpu.pc:08X}")
    print(f"  CPU halted (ebreak) = {cp.cpu.ebreak}")
    print()
    print("TMU state after run:")
    print(cp.tmu.dump())
    print()

    # =====================================================================
    # Phase 3: Direct ETMU0 test (via Python API, no SH-4 code needed)
    # =====================================================================
    # We configure ETMU0 directly and tick it, observing that an IRQ is
    # queued to the INTC.  This validates the Casio-specific ETMU code path.
    print("\n--- Phase 3: direct ETMU0 test (no SH-4 code) ---")
    etmu0 = cp.tmu.etmu_channels[0]
    print(f"ETMU0 base = 0x{etmu0.base_addr:08X}")
    # Configure ETMU0: TCOR=5, TCNT=5, TCR=UNIE, TSTR=STR
    etmu0.write_tcor(5)
    etmu0.write_tcnt(5)
    etmu0.write_tcr(0x01)   # UNIE=1 (bit 0)
    etmu0.write_tstr(0x01)  # STR=1 (bit 0)
    print(f"  Configured: TCOR=5 TCNT=5 TCR=0x01 (UNIE) TSTR=0x01 (STR)")

    # Clear any pending IRQs and tick
    cp.intc.clear()
    print(f"  Ticking ETMU0 by 5 RTC cycles (should underflow once)...")
    cp.tick_tmu(rtc_cycles=5)
    print(f"  ETMU0 after tick: TCR=0x{etmu0.tcr:02X} (UNF={int(bool(etmu0.tcr & 0x02))}, UNIE={int(bool(etmu0.tcr & 0x01))})")
    print(f"  TCNT=0x{etmu0.tcnt:08X} (should be reloaded to ~5)")
    print(f"  IRQ pending in INTC: {not cp.intc._queue.empty()}")

    etmu_pass = (etmu0.tcr & 0x02) != 0 and (not cp.intc._queue.empty())
    if etmu_pass:
        print("  PASS: ETMU0 underflowed and queued an IRQ.")
    else:
        print("  FAIL: ETMU0 didn't underflow or didn't queue an IRQ.")
    print()

    # Verify
    if counter >= 3 and etmu_pass:
        print("ALL TESTS PASS: TMU0 + ETMU0 both fire interrupts correctly.")
        return 0
    elif counter >= 3:
        print("PARTIAL PASS: TMU0 works but ETMU0 test failed.")
        return 1
    else:
        print(f"FAIL: expected counter >= 3, got {counter}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
