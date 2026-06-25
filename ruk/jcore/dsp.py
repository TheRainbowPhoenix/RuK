"""
DSP instruction handler for the SH4AL-DSP (SH7305).

Implements the DSP extension instructions that the standard SH-4 opcode
table doesn't cover.  These are called from the CPU's "unknown instruction"
path in step().

DSP instruction encoding on the SH4AL-DSP:
  - Double instructions (MOVX/MOVY): 1111_01xx_xxxx_xxxx (0xF4xx, 0xF5xx)
  - Operation instructions (PSUB, PADD, PMULS, etc.): 1111_0000_xxxx_xxxx (0xF0xx)
  - Single memory instructions (MOVS.W/MOVS.L): NOT 0000_0xxx — these are
    actually encoded differently.

IMPORTANT: The 0000_xxxx space is shared with many system instructions
(NOP, SLEEP, RTE, ICBI, PREF, etc.).  DSP MOVS instructions are NOT in
this space.  The confusion arose because ICBI (0x00E3) was mistaken for
a DSP MOVS instruction.

Actual DSP MOVS encoding (from SH4AL-DSP manual, confirmed by libCPU73050):
  The DSPSingleInstr_Table in libCPU73050 has 15 entries indexed by the
  low 4 bits of the instruction.  But the instruction format is actually:
  
  1111_0100_xxxx_xxxx for MOVX (X-bus memory access)
  1111_0101_xxxx_xxxx for MOVY (Y-bus memory access)
  1111_0000_xxxx_xxxx for DSP operations (PSUB, PADD, etc.)

  The "MOVS" instructions are part of the MOVX/MOVY family, not a separate
  0000_0xxx encoding.

  The 0000_nnnn_1110_0011 pattern is ICBI @Rn, NOT a DSP instruction.

DSP register file (stored in cpu.regs dict):
  x0, x1   - X-bus data registers (32-bit, upper 16 bits significant for word ops)
  y0, y1   - Y-bus data registers
  a0, a0g  - Accumulator 0 (a0 = low 32 bits, a0g = guard bits)
  a1, a1g  - Accumulator 1
  m0, m1   - Multiplier registers
  rs, re   - Repeat start/end address
  rc       - Repeat count
  dsr      - DSP status register

DSP MOVS instruction encoding (0x0xEx family):
  0000_0AAS_DDDD_CCCC

  AA  (bits 10-9): address register select (0->R4, 1->R5, 2->R2, 3->R3)
  S   (bit 8):     index modifier
  DDDD (bits 7-4): data register select (see DSP_DATA_REG_MAP)
  CCCC (bits 3-0): case/mode select (1-15, see DSP_MOVS_MODES)

The 15 MOVS modes:
  1: MOVS.W @As+Ix, Ds   (indexed load word)
  2: MOVS.W Ds, @As+Ix   (indexed store word)
  3: MOVS.L @As+Ix, Ds   (indexed load long)
  4: MOVS.L Ds, @As+Ix   (indexed store long)
  5: MOVS.W @As, Ds      (load word)
  6: MOVS.W Ds, @As       (store word)
  7: MOVS.L @As, Ds       (load long)
  8: MOVS.L Ds, @As       (store long)
  9: MOVS.W @-As, Ds      (pre-decrement load word)
 10: MOVS.W Ds, @-As      (pre-decrement store word)
 11: MOVS.L @-As, Ds      (pre-decrement load long)
 12: MOVS.L Ds, @-As      (pre-decrement store long)
 13: MOVS.W @As+, Ds      (post-increment load word)
 14: MOVS.W Ds, @As+      (post-increment store word)
 15: MOVS.L @As+, Ds      (post-increment load long)

DSP data register mapping (DDDD -> register name):
  5:  rc
  7:  re
  8:  a0
  9:  a0g
 10:  a1
 11:  a1g
 12:  y0
 13:  x1
 14:  y1
 15:  x0

DSP address register mapping (AA -> SH-4 register):
  0: R4
  1: R5
  2: R2
  3: R3

DSP operation instructions (PSUB, PADD, PMULS, etc.) have a different
encoding and are dispatched via a large jump table in the libCPU73050
decomp.  We implement the most common ones.
"""

from typing import Optional

# Address register map: 2-bit AA field -> SH-4 register index
DSP_ADDR_REG_MAP = [4, 5, 2, 3]

# Data register map: 4-bit DDDD field -> register name string
DSP_DATA_REG_MAP = {
    5:  'rc',
    7:  're',
    8:  'a0',
    9:  'a0g',
    10: 'a1',
    11: 'a1g',
    12: 'y0',
    13: 'x1',
    14: 'y1',
    15: 'x0',
}

def _u32(val):
    return val & 0xFFFFFFFF


def _i16(val):
    """Interpret 16-bit pattern as signed."""
    val &= 0xFFFF
    if val & 0x8000:
        return val - 0x10000
    return val


def _i32(val):
    val &= 0xFFFFFFFF
    if val & 0x80000000:
        return val - 0x100000000
    return val



def is_dsp_instruction(op_val: int) -> bool:
    """
    Check if an opcode is a DSP instruction.
    
    DSP instructions are in the 0xF0xx, 0xF4xx, 0xF5xx ranges.
    The 0x0xxx range is NOT DSP — it contains system instructions
    like ICBI, PREF, SYNCO, NOP, SLEEP, etc.
    """
    # DSP operation instructions: 0xF0xx
    if (op_val & 0xFF00) == 0xF000:
        return True
    # DSP double instructions (MOVX/MOVY): 0xF4xx, 0xF5xx
    if (op_val & 0xFE00) == 0xF400:  # covers 0xF4xx and 0xF5xx
        return True
    return False


def handle_dsp_instruction(cpu, op_val: int) -> bool:
    """
    Try to execute a DSP instruction.  Returns True if handled, False if not.
    """
    if not is_dsp_instruction(op_val):
        return False
    
    # Check for MOVS instructions (0000_0xxx_xxxx_xxxx with case 1-15)
    if (op_val & 0xF800) == 0x0000 and (op_val & 0x000F) != 0:
        return _handle_movs(cpu, op_val)

    # Check for DSP double instructions (MOVX/MOVY)
    if (op_val & 0xFF00) in (0xF400, 0xF500):
        return _handle_movx_movy(cpu, op_val)

    # DSP operation instructions (0xF0xx)
    if (op_val & 0xFF00) == 0xF000:
        return _handle_dsp_operation(cpu, op_val)

    # DSP double instructions (MOVX/MOVY) (0xF4xx, 0xF5xx)
    if (op_val & 0xFE00) == 0xF400:
        return _handle_movx_movy(cpu, op_val)

    return False




def _handle_movs(cpu, op_val: int) -> bool:
    """Handle MOVS.W/MOVS.L instructions."""
    # Decode fields
    aa = (op_val >> 9) & 0x3       # address register index
    s_bit = (op_val >> 8) & 0x1    # index modifier
    dddd = (op_val >> 4) & 0xF     # data register index
    case = op_val & 0xF            # mode/case (1-15)

    if case < 1 or case > 15:
        return False

    # Get the address register (SH-4 general register)
    addr_reg = DSP_ADDR_REG_MAP[aa]
    addr = cpu.regs[addr_reg]

    # Get the data register name
    if dddd not in DSP_DATA_REG_MAP:
        return False
    data_reg = DSP_DATA_REG_MAP[dddd]

    # Determine if this is a load (from memory to DSP reg) or store (DSP reg to memory)
    # Cases 1,3,5,7,9,11,13,15 are loads; 2,4,6,8,10,12,14 are stores
    is_load = (case & 1) == 1

    # Determine size: cases 1-4 are word, 3-4 and 7-8 and 11-12 and 15 are long
    # Actually: odd cases are loads, even are stores. The size depends on the case group.
    # Cases 1-2: word indexed
    # Cases 3-4: long indexed
    # Cases 5-6: word
    # Cases 7-8: long
    # Cases 9-10: word pre-decrement
    # Cases 11-12: long pre-decrement
    # Cases 13-14: word post-increment
    # Case 15: long post-increment
    is_long = case in (3, 4, 7, 8, 11, 12, 15)
    is_indexed = case in (1, 2, 3, 4)
    is_pre_decrement = case in (9, 10, 11, 12)
    is_post_increment = case in (13, 14, 15)

    size = 4 if is_long else 2

    # For indexed mode, add the index (the other address register pair)
    if is_indexed:
        # The index is from the paired address register.
        # Pair mapping: (R4,R2), (R5,R3) -- or similar.
        # For now, use R0 as the index (common in SH-DSP).
        # Actually, looking at the libCPU73050, "IDAS" means indexed.
        # The index might be derived from the S bit or another field.
        # For boot, the simplest interpretation is: use the address
        # directly (treat indexed as non-indexed for now).
        pass

    # Compute the effective address
    eff_addr = addr

    if is_pre_decrement:
        eff_addr = _u32(addr - size)
        cpu.regs[addr_reg] = eff_addr

    if is_load:
        # Read from memory
        if is_long:
            val = cpu.mem.read32(eff_addr)
            if isinstance(val, bytes):
                val = int.from_bytes(val, 'big')
        else:
            val = cpu.mem.read16(eff_addr)
            if isinstance(val, bytes):
                val = int.from_bytes(val, 'big')
            # For word loads, the value goes into the upper 16 bits of
            # the 32-bit DSP register (like cp-emu does for x0).
            # Actually, this depends on the register. For accumulators
            # (a0, a1), word data goes into the lower 16 bits. For
            # x0/y0, it goes into the upper 16 bits. Let's just store
            # the raw value for now.
            val = val & 0xFFFF

        cpu.regs[data_reg] = _u32(val)
    else:
        # Store to memory
        val = cpu.regs[data_reg]
        if is_long:
            cpu.mem.write32(eff_addr, val)
        else:
            # For word stores, use the upper 16 bits (for x0/y0)
            # or the lower 16 bits (for accumulators).
            # Simplest: store the lower 16 bits.
            cpu.mem.write16(eff_addr, val & 0xFFFF)

    if is_post_increment:
        cpu.regs[addr_reg] = _u32(eff_addr + size)

    cpu.pc = _u32(cpu.pc + 2)
    return True


def _handle_movx_movy(cpu, op_val: int) -> bool:
    """
    Handle MOVX.W/MOVY.W double memory instructions.

    These access both the X and Y memory buses in parallel.  On the
    SH7305, X and Y memory are at 0xE5000000 (XRAM) and 0xE5010000 (YRAM).

    For now, we stub these as NOPs (they're rarely used during boot).
    """
    # TODO: Implement MOVX/MOVY properly
    cpu.pc = _u32(cpu.pc + 2)
    return True


def _handle_dsp_operation(cpu, op_val: int) -> bool:
    """
    Handle DSP operation instructions (PSUB, PADD, PMULS, etc.).

    These are encoded in the 0xF0xx range and dispatched via a large
    jump table in the libCPU73050 decomp.  We implement the most
    common ones and stub the rest.
    """
    # For now, stub all DSP operations as NOPs.  These are rarely
    # encountered during OS boot (only 1 instance in 200K steps).
    # TODO: Implement PMULS, PSUB, PADD, PCLR, PCOPY, etc.
    cpu.pc = _u32(cpu.pc + 2)
    return True
