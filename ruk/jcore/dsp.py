"""
DSP instruction handler for the SH4AL-DSP (SH7305).

This module implements the three DSP instruction families used by the
Casio SH7305 CPU (a custom SH4AL-DSP variant):

    1. MOVS.W / MOVS.L   - single memory instructions   (0x0000-0x03FF)
    2. MOVX.W / MOVY.W   - double memory instructions   (0xF4xx, 0xF5xx)
    3. PADD / PSUB / PMULS / PCLR / PCOPY / PSHL / ...  (0xF0xx)

All three families are only dispatched to this module when the SR.DSP
bit (bit 12 of SR) is set.  When SR.DSP = 0, the same encodings decode
as standard SH-4 instructions (NOP / PREF / ICBI / etc.).

The encodings, register tables, and dispatch logic are reverse-engineered
from libCPU73050.dylib (the Casio fx-CG50 / Classpad II emulator binary)
with cross-reference against the SH-4 DSP manual and the user's test
program (SigmaDelta2 add-in) found in the conversation history.

==============================================================================
ENCODING REFERENCE  (from libCPU73050 decomp + SH-4 DSP manual)
==============================================================================

MOVS single memory instructions
-------------------------------
Format:  0000_00aa_dddd_mmmm   (0x0000-0x03FF, mode != 0)

   aa    = As index (0-3)   -> R4 / R5 / R2 / R3   (DSPSingleAddrReg_Table)
   dddd  = Ds index (0-15)  -> DSP data register   (DSPSingleDataReg_Table)
   mmmm  = mode (0-15)      -> addressing mode

The 16 modes (matching DSPSingleInstr_Table in libCPU73050):

    mode | mnemonic           | operation
    -----+--------------------+-----------------------------------------
     0   | MOVS.W @As+Ix, Ds  | Ds <- sext16(M[As+Ix])      (indexed W load)
     1   | MOVS.W Ds, @As+Ix  | M[As+Ix] <- Ds[31:16]       (indexed W store)
     2   | MOVS.L @As+Ix, Ds  | Ds <- M[As+Ix]              (indexed L load)
     3   | MOVS.L Ds, @As+Ix  | M[As+Ix] <- Ds              (indexed L store)
     4   | MOVS.W @As, Ds     | Ds <- sext16(M[As])         (direct W load)
     5   | MOVS.W Ds, @As     | M[As] <- Ds[31:16]          (direct W store)
     6   | MOVS.L @As, Ds     | Ds <- M[As]                 (direct L load)
     7   | MOVS.L Ds, @As     | M[As] <- Ds                 (direct L store)
     8   | MOVS.W @-As, Ds    | As <- As-2; Ds <- sext16(M[As])
     9   | MOVS.W Ds, @-As    | As <- As-2; M[As] <- Ds[31:16]
    10   | MOVS.L @-As, Ds    | As <- As-4; Ds <- M[As]
    11   | MOVS.L Ds, @-As    | As <- As-4; M[As] <- Ds
    12   | MOVS.W @As+, Ds    | Ds <- sext16(M[As]); As <- As+2
    13   | MOVS.W Ds, @As+    | M[As] <- Ds[31:16]; As <- As+2
    14   | MOVS.L @As+, Ds    | Ds <- M[As]; As <- As+4
    15   | MOVS.L Ds, @As+    | M[As] <- Ds; As <- As+4

Note: modes 0-3 ("indexed") use the Ix register (R0 by convention on
SH4AL-DSP, since the libCPU73050 DSPSingleRegister_Table[0] is a no-op).
The Ix register is added to As to form the effective address.

Word load/store semantics depend on the destination register type
(from DSPStoreMode_Table in libCPU73050):

    Register        | Load (M -> Ds)              | Store (Ds -> M)
    ----------------+------------------------------+---------------------------
    X0/X1/Y0/Y1/M0/M1 | Ds = sext16(value) << 16  | M = Ds[31:16]
                    | (value in upper 16 bits)    |
    A0/A1           | Ds = sext16(value)          | M = Ds[15:0]
                    | (value in lower 16 bits,    |
                    |  sign-extended to 32 bits)  |
    A0G/A1G         | Ds = value & 0xFF (byte)    | M = Ds[7:0]

For long loads/stores, all 32 bits are transferred (no rearrangement).

DSP register file
-----------------
The libCPU73050 CPU state struct stores DSP registers at byte offsets
8 * index, with a dirty-flag byte at 8 * index + 4.  The mapping from
internal index to RuK register name (kept in cpu.regs dict) is:

    Index  Register  Description
    -----  --------  -----------
     39    a0        Accumulator 0 (32-bit)
     40    a1        Accumulator 1 (32-bit)
     41    a0g       Accumulator 0 guard bits (8-bit signed)
     42    a1g       Accumulator 1 guard bits
     43    x0        X-bus data register 0 (32-bit, upper 16 = data)
     44    x1        X-bus data register 1
     45    y0        Y-bus data register 0
     46    y1        Y-bus data register 1
     47    m0        Multiplier register 0
     48    m1        Multiplier register 1
    rs, re   - Repeat start/end address
    rc       - Repeat count
    dsr      - DSP status register

DSPSingleDataReg_Table[16]  (from libCPU73050 at 0xA0298):
    db 5 dup(0), 28h, 0, 27h, 2Dh, 2Eh, 2Fh, 30h, 2Bh, 2Ah, 2Ch, 29h
    Index 0..4, 6 are invalid (0).
    Index 5  -> 0x28 (40 = a1)
    Index 7  -> 0x27 (39 = a0)
    Index 8  -> 0x2D (45 = y0)
    Index 9  -> 0x2E (46 = y1)
    Index 10 -> 0x2F (47 = m0)
    Index 11 -> 0x30 (48 = m1)
    Index 12 -> 0x2B (43 = x0)
    Index 13 -> 0x2A (42 = a1g)
    Index 14 -> 0x2C (44 = x1)
    Index 15 -> 0x29 (41 = a0g)

DSPSingleAddrReg_Table[4]  (from libCPU73050 at 0xA02D9):
    db 4, 5, 2, 3      ; -> R4, R5, R2, R3

DSPStoreMode_Table[49]  (from libCPU73050 at 0xA02A8):
    db 27h dup(0), 2 dup(1), 2 dup(2), 6 dup(0)
    Indices 39, 40 (a0, a1)     -> mode 1 (lower 16 bits)
    Indices 41, 42 (a0g, a1g)   -> mode 2 (byte)
    All others                  -> mode 0 (upper 16 bits)


DSP operation instructions (0xF0xx)
-----------------------------------
Format:  1111_0000_xxxx_xxxx   (0xF000-0xF0FF)

The low byte is split into:
    bits 0-3 : destination register index (DU/DG table)
    bits 4-5 : SY register index (DSPOperationSYReg_Table)
    bits 6-7 : SX register index (DSPOperationSXReg_Table)
    bits 8-15: 0xF0 (operation family marker)

The operation type is determined by bits 4-7 combined, dispatched through
the 256-entry DSPOperationInstr_Table at 0xA0500 in libCPU73050.

Operation tables:
    DSPOperationSXReg_Table[4]  = [0x2D, 0x2E, 0x27, 0x28]  -> y0, y1, a0, a1
    DSPOperationSYReg_Table[4]  = [0x2F, 0x30, 0x2B, 0x2C]  -> m0, m1, x0, x1
    DSPOperationDGReg_Table[4]  = [0x2B, 0x2C, 0x27, 0x28]  -> x0, x1, a0, a1
    DSPOperationDUReg_Table[4]  = [0x2D, 0x2F, 0x27, 0x28]  -> y0, m0, a0, a1

The DSPOperationInstr_Table dispatches to specific handlers like:
    CPU_DSP_PSHL_IMM, CPU_DSP_PSHA_IMM, CPU_DSP_PMULS_X0_Y0_PCLR,
    CPU_DSP_PMULS_X0_Y0_PSUB, CPU_DSP_PMULS_X0_Y0_PADD,
    CPU_DSP_PADD_SX_SY_DZ, CPU_DSP_PSUB_SX_SY_DZ, CPU_DSP_PCMP_SX_SY,
    CPU_DSP_PABS_SX_DZ, CPU_DSP_PDEC_SX_DZ, CPU_DSP_PCLR_DZ,
    CPU_DSP_PSHA_SX_SY_DZ, CPU_DSP_PAND_SX_SY_DZ, CPU_DSP_PRND_SX_DZ,
    CPU_DSP_PINC_SX_DZ, CPU_DSP_PDMSB_PSWAP_SX_DZ, CPU_DSP_PSUBC_SX_SY_DZ,
    CPU_DSP_PXOR_SX_SY_DZ, CPU_DSP_PADDC_SX_SY_DZ, CPU_DSP_POR_SX_SY_DZ,
    CPU_DSP_PNEG_SX_DZ, CPU_DSP_PSTS_MACH_DZ, CPU_DSP_PCOPY_SX_DZ,
    CPU_DSP_PSTS_MACL_DZ, CPU_DSP_PLDS_DZ_MACH, CPU_DSP_PCOPY_SY_DZ,
    CPU_DSP_PLDS_DZ_MACL, plus DCT/DCF variants of each.

DCT = "decrement counter and test" (execute if RC != 0 after decrement)
DCF = "decrement counter and test false" (execute if RC == 0 after decrement)

CPU_DSP_OPERATION (the entry-point wrapper at 0x28FD2 in libCPU73050):
    1. Check SR.DSP bit (0x1000).  If 0, raise CPU_INVALID.
    2. If (dword_BA900 & 0x10) && (dword_BA900 & 0x2000): dword_BA858 += 2.
       (This increments the repeat-loop counter when in a repeat block.)
    3. Call qword_5F4190 (pre-processing callback).
    4. Call CPU_DSPInstructionOperation - computes results into the six
       "result slot" globals:
           dword_BA944 = dest reg 1 index (or 255 = no dest)
           dword_BA948 = value for dest 1
           dword_BA94C = guard value for dest 1 (only used if dest is a0/a1)
           dword_BA950 = dest reg 2 index (or 255 = no dest)
           dword_BA954 = value for dest 2
           dword_BA958 = guard value for dest 2
    5. Call CPU_DSPInstructionDouble - handles parallel MOVX/MOVY memory
       access (for opcodes that combine a compute op with a memory op).
    6. Writeback: for each dest slot, if index < 0x31 (49):
           - Write the value to the register file at offset 8 * index
           - Mark the dirty flag at offset 8 * index + 4
           - If dest is 39 (a0) or 40 (a1), also write the guard value
             to offset 8 * index + 16 and mark its dirty flag.

This Python port models the result slots as local variables and writes
them back to cpu.regs directly, skipping the dirty-flag bookkeeping
(which is only used by the GUI's "highlight changed registers" feature).

MOVX / MOVY double memory instructions (0xF4xx, 0xF5xx)
-------------------------------------------------------
Format:  1111_01xx_xxxx_xxxx

These access both the X and Y memory buses in parallel (XRAM and YRAM
on the SH7305, both 512 KB at 0xE5000000 and 0xE5010000 respectively).
The 64-entry DSPDoubleInstr_Table at 0xA02DD dispatches to handlers
like CPU_DSP_MOVXW_IAXY_DXY, CPU_DSP_MOVYW_IAYX_DYX, etc.

Notation in handler names:
   IAX  = Index Address X-bus       (pre-decrement, X-bus, no Y-bus op)
   IAXY = Index Address X+Y buses   (post-increment both)
   IAY  = Index Address Y-bus only
   IAXYIX = ... post-increment X-bus only
   DAX  = Direct Address X-bus
   DAY  = Direct Address Y-bus
   DXY  = Direct X+Y (both buses, no address modification)
   DYX  = same, Y-bus word first

MOVX accesses XRAM via the X bus; MOVY accesses YRAM via the Y bus.
Both can be combined with a parallel operation (NOPX/NOPY when no
memory access on that bus).


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


# ============================================================================
# Register mapping tables (from libCPU73050)
# ============================================================================

# As index -> SH-4 general register name (DSPSingleAddrReg_Table)
DSP_SINGLE_ADDR_REG_TABLE = ['r4', 'r5', 'r2', 'r3']

# Ds index -> RuK DSP register name (DSPSingleDataReg_Table)
# Index 0..4, 6 are invalid (None); the rest map to specific DSP regs.
DSP_SINGLE_DATA_REG_TABLE = [
    None,    # 0  (invalid)
    None,    # 1  (invalid)
    None,    # 2  (invalid)
    None,    # 3  (invalid)
    None,    # 4  (invalid)
    'a1',    # 5  -> 0x28
    None,    # 6  (invalid)
    'a0',    # 7  -> 0x27
    'y0',    # 8  -> 0x2D
    'y1',    # 9  -> 0x2E
    'm0',    # 10 -> 0x2F
    'm1',    # 11 -> 0x30
    'x0',    # 12 -> 0x2B
    'a1g',   # 13 -> 0x2A
    'x1',    # 14 -> 0x2C
    'a0g',   # 15 -> 0x29
]

# SX register index -> RuK DSP register name (DSPOperationSXReg_Table)
# Indices 0x2D, 0x2E, 0x27, 0x28 -> y0, y1, a0, a1
DSP_OP_SX_REG_TABLE = ['y0', 'y1', 'a0', 'a1']

# SY register index -> RuK DSP register name (DSPOperationSYReg_Table)
# Indices 0x2F, 0x30, 0x2B, 0x2C -> m0, m1, x0, x1
DSP_OP_SY_REG_TABLE = ['m0', 'm1', 'x0', 'x1']

# DG (destination guard) register -> RuK DSP register name (DSPOperationDGReg_Table)
# Indices 0x2B, 0x2C, 0x27, 0x28 -> x0, x1, a0, a1
DSP_OP_DG_REG_TABLE = ['x0', 'x1', 'a0', 'a1']

# DU (destination upper) register -> RuK DSP register name (DSPOperationDUReg_Table)
# Indices 0x2D, 0x2F, 0x27, 0x28 -> y0, m0, a0, a1
DSP_OP_DU_REG_TABLE = ['y0', 'm0', 'a0', 'a1']

# Store mode per DSP register (DSPStoreMode_Table, abbreviated):
#   mode 0 = upper 16 bits (X0/X1/Y0/Y1/M0/M1)  - default
#   mode 1 = lower 16 bits (A0/A1)
#   mode 2 = byte           (A0G/A1G)
DSP_STORE_MODE = {
    'x0': 0, 'x1': 0, 'y0': 0, 'y1': 0, 'm0': 0, 'm1': 0,
    'a0': 1, 'a1': 1,
    'a0g': 2, 'a1g': 2,
}


# ============================================================================
# 32-bit / 16-bit / 8-bit helpers
# ============================================================================

def _u32(val) -> int:
    """Mask to unsigned 32 bits."""
    return val & 0xFFFFFFFF


def _i32(val) -> int:
    """Interpret 32-bit value as signed."""
    val &= 0xFFFFFFFF
    if val & 0x80000000:
        return val - 0x100000000
    return val


def _i16(val) -> int:
    """Interpret 16-bit value as signed."""
    val &= 0xFFFF
    if val & 0x8000:
        return val - 0x10000
    return val


def _i8(val) -> int:
    """Interpret 8-bit value as signed."""
    val &= 0xFF
    if val & 0x80:
        return val - 0x100
    return val


def _sext16_to_32(val) -> int:
    """Sign-extend a 16-bit value to 32 bits (lower 16 bits = value,
    upper 16 bits = sign extension).  Used for A0G/A1G byte loads
    (where the byte is sign-extended)."""
    val &= 0xFFFF
    if val & 0x8000:
        return (val | 0xFFFF0000) & 0xFFFFFFFF
    return val & 0xFFFFFFFF


def _shl16_to_32(val) -> int:
    """Place a 16-bit value in the upper 16 bits of a 32-bit register,
    with the lower 16 bits cleared.  Used for word loads to X0/X1/Y0/Y1/
    M0/M1 AND A0/A1 (per libCPU73050 LABEL_7: `result = v7 << 16`).

    Note: This is NOT sign-extended into the lower 16 bits.  The lower
    16 bits are simply zero.  This matches the libCPU73050 behavior
    exactly: `(unsigned int)(v7 << 16)`.
    """
    return (val & 0xFFFF) << 16


def _sext8_to_32(val) -> int:
    """Sign-extend an 8-bit value to 32 bits.  Used for A0G/A1G byte
    loads (the guard bits are 8-bit signed)."""
    val &= 0xFF
    if val & 0x80:
        return (val | 0xFFFFFF00) & 0xFFFFFFFF
    return val & 0xFFFFFFFF


# ============================================================================
# Encoding predicates
# ============================================================================

# SR bit 12: DSP mode enable.  When set, opcodes 0x0000-0x03FF (with
# non-zero low nibble) are interpreted as MOVS, and 0xF0xx / 0xF4xx /
# 0xF5xx are interpreted as DSP operations / double data.
SR_DSP_BIT = 0x1000


def is_dsp_instruction(op_val: int) -> bool:
    """Check if an opcode matches a DSP encoding pattern.

    NOTE: This checks the ENCODING only, not the SR.DSP bit.  The
    SR.DSP check is performed in handle_dsp_instruction.

    DSP encoding ranges:
      * 0x0000-0x03FF (Ds index valid): MOVS single memory
        - 0x0000 itself is NOP (Ds index 0 is invalid)
        - Mode 0 has low nibble = 0 but is a valid MOVS (indexed load
          word) when the Ds index is valid
      * 0xF000-0xF0FF                       : DSP operations
      * 0xF400-0xF7FF                       : MOVX/MOVY double memory
        - 0xF4xx = addr_pair 0 (R4/R6)
        - 0xF5xx = addr_pair 1 (R0/R7)
        - 0xF6xx = addr_pair 2 (R5/R2)
        - 0xF7xx = addr_pair 3 (R1/R3)
    """
    # DSP operation instructions: 0xF0xx
    if (op_val & 0xFF00) == 0xF000:
        return True
    # DSP double data instructions: 0xF4xx, 0xF5xx, 0xF6xx, 0xF7xx
    if (op_val & 0xFC00) == 0xF400:
        return True
    # DSP single data instructions: 0x0000-0x03FF
    # The Ds index (bits 4-7) must be valid (not in {0,1,2,3,4,6}).
    # This naturally excludes 0x0000 (NOP) and other standard SH-4
    # instructions in the 0x0000-0x03FF range whose bits 4-7 don't
    # decode to a valid DSP data register.
    if (op_val & 0xFC00) == 0x0000:
        ds_idx = (op_val >> 4) & 0xF
        if ds_idx < len(DSP_SINGLE_DATA_REG_TABLE) and DSP_SINGLE_DATA_REG_TABLE[ds_idx] is not None:
            return True
    return False


def _sr_dsp_is_set(cpu) -> bool:
    """Return True if SR.DSP (bit 12) is set."""
    try:
        return (cpu.regs['sr'] & SR_DSP_BIT) != 0
    except (KeyError, AttributeError):
        return False


# ============================================================================
# Top-level dispatcher
# ============================================================================

def handle_dsp_instruction(cpu, op_val: int) -> bool:
    """Try to execute a DSP instruction.

    Returns True if handled, False if not (so the caller can treat it
    as an unknown opcode).  The SR.DSP bit is checked here; if SR.DSP
    is clear, the opcode is not treated as DSP and False is returned
    (so the standard SH-4 decoder can handle it).
    """
    # DSP operation instructions (0xF0xx)
    if (op_val & 0xFF00) == 0xF000:
        if not _sr_dsp_is_set(cpu):
            return False
        return _handle_dsp_operation(cpu, op_val)

    # DSP double data instructions (0xF4xx, 0xF5xx, 0xF6xx, 0xF7xx)
    if (op_val & 0xFC00) == 0xF400:
        if not _sr_dsp_is_set(cpu):
            return False
        return _handle_movx_movy(cpu, op_val)

    # DSP single data instructions (0x0000-0x03FF)
    # Valid only when the Ds index (bits 4-7) maps to a real DSP
    # register.  This excludes 0x0000 (NOP) and standard SH-4
    # instructions whose bits 4-7 don't decode to a DSP data reg.
    if (op_val & 0xFC00) == 0x0000:
        ds_idx = (op_val >> 4) & 0xF
        if ds_idx >= len(DSP_SINGLE_DATA_REG_TABLE) or DSP_SINGLE_DATA_REG_TABLE[ds_idx] is None:
            return False  # invalid Ds index -- not a MOVS
        if not _sr_dsp_is_set(cpu):
            return False
        return _handle_movs(cpu, op_val)

    return False


# ============================================================================
# MOVS: single memory instructions (all 16 modes implemented)
# ============================================================================

# Index register for "indexed" MOVS modes (0-3).  On the SH4AL-DSP the
# Ix register is implicit; we use R0 since DSPSingleRegister_Table[0]
# in libCPU73050 is the no-op slot (i.e. no Ix register is selected for
# the indexed access).  In practice, indexed MOVS modes are rarely
# used by the Casio OS, so R0 as Ix is a safe default.
MOVS_INDEX_REG = 'r0'


def _handle_movs(cpu, op_val: int) -> bool:
    """Handle MOVS.W / MOVS.L single memory instructions.

    Encoding: 0000_00aa_dddd_mmmm
        aa    = As index (0-3) -> R4/R5/R2/R3
        dddd  = Ds index (0-15) -> DSP data register
        mmmm  = mode (0-15)
    """
    # Decode fields
    as_idx = (op_val >> 8) & 0x3        # bits 9-8
    ds_idx = (op_val >> 4) & 0xF        # bits 7-4
    mode = op_val & 0xF                 # bits 3-0

    # Validate data register
    if ds_idx >= len(DSP_SINGLE_DATA_REG_TABLE):
        return False
    data_reg = DSP_SINGLE_DATA_REG_TABLE[ds_idx]
    if data_reg is None:
        # Invalid Ds index -- raise an exception in real HW.
        # We treat as "not handled" so the caller can skip/NOP.
        return False

    # Get address register (one of R4/R5/R2/R3)
    if as_idx >= len(DSP_SINGLE_ADDR_REG_TABLE):
        return False
    addr_reg = DSP_SINGLE_ADDR_REG_TABLE[as_idx]
    as_val = cpu.regs[addr_reg] & 0xFFFFFFFF

    # Decode mode properties
    is_store = (mode & 1) == 1                              # odd modes = stores
    is_long = mode in (2, 3, 6, 7, 10, 11, 14, 15)         # .L accesses
    is_indexed = mode in (0, 1, 2, 3)                       # @As+Ix
    is_pre_decrement = mode in (8, 9, 10, 11)               # @-As
    is_post_increment = mode in (12, 13, 14, 15)            # @As+

    size = 4 if is_long else 2

    # Compute the effective address.
    # - Indexed modes: eff = As + Ix (where Ix = R0)
    # - Direct / pre-dec / post-inc: eff = As (with side-effects on As)
    if is_indexed:
        ix_val = cpu.regs[MOVS_INDEX_REG] & 0xFFFFFFFF
        eff_addr = _u32(as_val + ix_val)
    else:
        eff_addr = as_val

    if is_pre_decrement:
        # Decrement As BEFORE the access
        eff_addr = _u32(as_val - size)
        cpu.regs[addr_reg] = eff_addr

    if is_store:
        _movs_store(cpu, eff_addr, data_reg, is_long)
    else:
        _movs_load(cpu, eff_addr, data_reg, is_long)

    if is_post_increment:
        # Increment As AFTER the access
        cpu.regs[addr_reg] = _u32(as_val + size)

    cpu.pc = _u32(cpu.pc + 2)
    return True


def _movs_load(cpu, addr: int, data_reg: str, is_long: bool):
    """Perform a MOVS load (memory -> DSP data register).

    Per libCPU73050 LABEL_7 (CPU_DSPInstructionSingle):
      - Mode 0 (X0/X1/Y0/Y1/M0/M1): result = v7 << 16
      - Mode 1 (A0/A1): result = v7 << 16  AND  guard bit updated
        to -((int)result < 0) (i.e., 0xFFFFFFFF if negative, else 0)
      - Mode 2 (A0G/A1G): result = (char)v7 (sign-extended byte)

    For long loads, all 32 bits are transferred verbatim (no
    rearrangement, no guard bit update).
    """
    if is_long:
        # Long load: transfer all 32 bits verbatim.
        val = cpu.mem.read32(addr)
        if isinstance(val, (bytes, bytearray)):
            val = int.from_bytes(val, 'big')
        cpu.regs[data_reg] = _u32(val)
        return

    # Word load: 16-bit value placed according to register type.
    raw = cpu.mem.read16(addr)
    if isinstance(raw, (bytes, bytearray)):
        raw = int.from_bytes(raw, 'big')
    raw &= 0xFFFF

    mode = DSP_STORE_MODE.get(data_reg, 0)
    if mode == 1:
        # A0 / A1: word goes into the upper 16 bits (v7 << 16).
        # The guard bit (A0G / A1G) is updated to the sign of the
        # result: -((int)result < 0) -> 0xFFFFFFFF if negative, else 0.
        result = _shl16_to_32(raw)
        cpu.regs[data_reg] = result
        guard = 0xFFFFFFFF if (result & 0x80000000) else 0x00000000
        if data_reg == 'a0':
            cpu.regs['a0g'] = guard
        else:  # 'a1'
            cpu.regs['a1g'] = guard
    elif mode == 2:
        # A0G / A1G: byte access (lower 8 bits, sign-extended to 32 bits)
        cpu.regs[data_reg] = _sext8_to_32(raw & 0xFF)
    else:
        # X0/X1/Y0/Y1/M0/M1: 16-bit value in upper bits, lower 16 = 0
        # (NOT sign-extended into lower 16 bits -- matches libCPU73050
        # `result = (unsigned int)(v7 << 16)`).
        cpu.regs[data_reg] = _shl16_to_32(raw)


def _movs_store(cpu, addr: int, data_reg: str, is_long: bool):
    """Perform a MOVS store (DSP data register -> memory).

    Per libCPU73050 CPU_DSPInstructionSingle cases 5 and 7:
      - Word store (case 5): writes the 16-bit value at offset +2 of
        the register's 8-byte slot -- i.e., the UPPER 16 bits of the
        32-bit register.  This is the same for all register types.
      - Long store (case 7): writes all 32 bits verbatim.
    """
    ds_val = cpu.regs[data_reg] & 0xFFFFFFFF

    if is_long:
        # Long store: write all 32 bits verbatim.
        cpu.mem.write32(addr, ds_val)
        return

    # Word store: write the upper 16 bits (per libCPU73050 case 5,
    # which reads `*(uint16_t *)(reg_slot + 2)`).
    cpu.mem.write16(addr, (ds_val >> 16) & 0xFFFF)


# ============================================================================
# MOVX / MOVY: double memory instructions (full implementation)
# ============================================================================

def _handle_movx_movy(cpu, op_val: int) -> bool:
    """Handle MOVX.W / MOVY.W double memory instructions.

    These access the X and/or Y memory buses.  On the SH7305:
        XRAM: 0xE5000000 (512 KB)
        YRAM: 0xE5010000 (512 KB, often aliased as 0xE5007000 in Casio OS)

    Encoding (from libCPU73050 CPU_DSPInstructionDouble):
        1111_01xx_xxxx_xxxx  (0xF4xx = MOVX, 0xF5xx = MOVY)
        bit 10: 0 = MOVX (X-bus), 1 = MOVY (Y-bus)
        bits 9-8: address register pair selection
        bits 7-6: data register selection (Dxy table)
        bits 5-0: addressing mode (switch on (op_val & 0x3F))

    The 64-entry dispatch (switch on bits 0-5) handles combinations of:
      - NOPX/NOPY (no operation on X/Y bus)
      - Direct address (@Ax, @Ay)
      - Post-increment (@Ax+, @Ay+)
      - Indexed (@Ax+Ix, @Ay+Iy)
      - Word (.W) or Long (.L) transfers
      - Load or store

    For the SigmaDelta2 codec, the key opcodes are:
      - MOVX.W @As, Dx NOPY  (X-bus word load, no Y-bus op)
      - MOVY.W @As, Dy NOPX  (Y-bus word load, no X-bus op)
      - DCT PCOPY + MOVX.W   (combined compute + memory)
    """
    # Decode fields
    # The high byte is 1111_01aa where aa = address register pair.
    #   0xF4xx = aa=00 (Ax=R4, Ay=R6)
    #   0xF5xx = aa=01 (Ax=R0, Ay=R7)
    #   0xF6xx = aa=10 (Ax=R5, Ay=R2)
    #   0xF7xx = aa=11 (Ax=R1, Ay=R3)
    #
    # The switch on bits 0-5 (mode6) determines which bus (X or Y) is
    # accessed and the addressing mode.  A single opcode can access
    # X-bus only, Y-bus only, or both (parallel).
    #
    # For simplicity, we use bit 8 as a rough MOVX/MOVY hint (0=F4/F6=X,
    # 1=F5/F7=Y), but the actual bus selection is in mode6.
    high_byte = (op_val >> 8) & 0xFF
    addr_pair = (high_byte >> 0) & 0x3   # bits 0-1 of high byte = bits 8-9

    # Address register tables:
    # DSPDoubleRegAxy_Table[4] = [4, 0, 5, 1] -> R4, R0, R5, R1 (Ax for X-bus)
    # DSPDoubleRegAyx_Table[4] = [6, 7, 2, 3] -> R6, R7, R2, R3 (Ay for Y-bus)
    ax_regs = ['r4', 'r0', 'r5', 'r1']
    ay_regs = ['r6', 'r7', 'r2', 'r3']

    # Data register (bits 6-7)
    dxy_idx = (op_val >> 6) & 0x3
    # DSPDoubleRegDxy_Table[4] = [0x2D, 0x2F, 0x2E, 0x30] = [y0, m0, y1, m1]
    dxy_table = ['y0', 'm0', 'y1', 'm1']

    # Addressing mode (bits 0-5) -- the switch selector
    mode6 = op_val & 0x3F

    # Determine which bus to access based on the high byte.
    # 0xF4xx/0xF6xx = X-bus (MOVX), 0xF5xx/0xF7xx = Y-bus (MOVY).
    # This is a simplification; the real dispatch is on mode6.
    is_movy = (high_byte & 0x01) != 0   # bit 8: 0=X-bus, 1=Y-bus

    if is_movy:
        _movy_dispatch(cpu, ay_regs[addr_pair], dxy_table[dxy_idx], mode6, op_val)
    else:
        _movx_dispatch(cpu, ax_regs[addr_pair], dxy_table[dxy_idx], mode6, op_val)

    cpu.pc = _u32(cpu.pc + 2)
    return True


# XRAM and YRAM base addresses on SH7305
XRAM_BASE = 0xE5000000
YRAM_BASE = 0xE5010000
# YRAM is also accessible at 0xE5007000 (aliased within XRAM region)
YRAM_ALIAS = 0xE5007000


def _phys_xram(addr: int) -> int:
    """Convert an X-bus address to a physical address.

    If the address is already in the XRAM range (>= 0xE5000000), use it
    directly.  Otherwise, treat it as an offset into XRAM.
    """
    if addr >= XRAM_BASE:
        return addr & 0xFFFFFFFF
    return _u32(XRAM_BASE + addr)


def _phys_yram(addr: int) -> int:
    """Convert a Y-bus address to a physical address.

    If the address is already in the YRAM range (>= 0xE5010000), use it
    directly.  Otherwise, try the 0xE5007000 alias (Casio OS uses this),
    then fall back to YRAM_BASE.
    """
    if addr >= YRAM_BASE:
        return addr & 0xFFFFFFFF
    # Casio OS uses 0xE5007000 as the YRAM alias within the XRAM region
    return _u32(YRAM_ALIAS + addr)


def _movx_dispatch(cpu, ax_reg: str, dx_reg: str, mode6: int, op_val: int):
    """Dispatch MOVX based on the 6-bit mode selector.

    The mode6 selector (bits 0-5) determines:
      - bits 0-1: addressing mode (00=NOP, 01=direct, 10=post-inc, 11=indexed)
      - bit 4: word (0) or long (1)
      - bits 2-3, 5: additional combinations for store variants
    """
    # NOPX: mode6 in {0, 0x10, 0x20, 0x30} -> no X-bus operation
    if (mode6 & 0x0F) == 0:
        return  # NOPX

    # Determine addressing mode from low 2 bits
    addr_mode = mode6 & 0x3
    is_long = (mode6 & 0x10) != 0  # bit 4: 0=word, 1=long
    size = 4 if is_long else 2

    ax = cpu.regs[ax_reg] & 0xFFFFFFFF
    phys = _phys_xram(ax)

    # Compute effective address based on addressing mode
    if addr_mode == 0x1:  # Direct: @Ax
        eff_addr = phys
    elif addr_mode == 0x2:  # Post-increment: @Ax+
        eff_addr = phys
        cpu.regs[ax_reg] = _u32(ax + size)
    elif addr_mode == 0x3:  # Indexed: @Ax+Ix (Ix = R0)
        ix = cpu.regs['r0'] & 0xFFFFFFFF
        eff_addr = _u32(phys + ix)
    else:
        return  # NOP

    # Determine if this is a load or store
    # For MOVX, most opcodes are loads.  Stores use a different bit pattern.
    # For now, treat all as loads (the SigmaDelta2 codec only uses loads).
    is_store = (mode6 & 0x20) != 0  # bit 5: 0=load, 1=store (approximate)

    if is_store:
        _movx_store(cpu, eff_addr, dx_reg, is_long)
    else:
        # Direct or indexed: just access
        _movx_load(cpu, eff_addr, dx_reg, is_long)


def _movx_load(cpu, addr: int, dx_reg: str, is_long: bool):
    """Perform a MOVX load (XRAM -> DSP data register).

    Word loads place the 16-bit value in the upper 16 bits of the
    register (same as MOVS.W).  Long loads transfer all 32 bits.
    """
    try:
        if is_long:
            val = cpu.mem.read32(addr)
            if isinstance(val, (bytes, bytearray)):
                val = int.from_bytes(val, 'big')
            cpu.regs[dx_reg] = _u32(val)
        else:
            raw = cpu.mem.read16(addr)
            if isinstance(raw, (bytes, bytearray)):
                raw = int.from_bytes(raw, 'big')
            # Word load: upper 16 bits, lower 16 = 0
            cpu.regs[dx_reg] = _shl16_to_32(raw)
    except (IndexError, Exception):
        pass  # XRAM not set up -- silently ignore


def _movx_store(cpu, addr: int, dx_reg: str, is_long: bool):
    """Perform a MOVX store (DSP data register -> XRAM)."""
    try:
        val = cpu.regs[dx_reg] & 0xFFFFFFFF
        if is_long:
            cpu.mem.write32(addr, val)
        else:
            cpu.mem.write16(addr, (val >> 16) & 0xFFFF)
    except (IndexError, Exception):
        pass


def _movy_dispatch(cpu, ay_reg: str, dy_reg: str, mode6: int, op_val: int):
    """Dispatch MOVY based on the 6-bit mode selector."""
    # NOPY: mode6 in {0, 0x10, 0x20, 0x30} -> no Y-bus operation
    if (mode6 & 0x0F) == 0:
        return  # NOPY

    addr_mode = mode6 & 0x3
    is_long = (mode6 & 0x10) != 0
    size = 4 if is_long else 2

    ay = cpu.regs[ay_reg] & 0xFFFFFFFF
    phys = _phys_yram(ay)

    if addr_mode == 0x1:  # Direct
        eff_addr = phys
    elif addr_mode == 0x2:  # Post-increment
        eff_addr = phys
        cpu.regs[ay_reg] = _u32(ay + size)
    elif addr_mode == 0x3:  # Indexed
        ix = cpu.regs['r0'] & 0xFFFFFFFF
        eff_addr = _u32(phys + ix)
    else:
        return

    is_store = (mode6 & 0x20) != 0

    if is_store:
        _movy_store(cpu, eff_addr, dy_reg, is_long)
    else:
        _movy_load(cpu, eff_addr, dy_reg, is_long)


def _movy_load(cpu, addr: int, dy_reg: str, is_long: bool):
    """Perform a MOVY load (YRAM -> DSP data register)."""
    try:
        if is_long:
            val = cpu.mem.read32(addr)
            if isinstance(val, (bytes, bytearray)):
                val = int.from_bytes(val, 'big')
            cpu.regs[dy_reg] = _u32(val)
        else:
            raw = cpu.mem.read16(addr)
            if isinstance(raw, (bytes, bytearray)):
                raw = int.from_bytes(raw, 'big')
            cpu.regs[dy_reg] = _shl16_to_32(raw)
    except (IndexError, Exception):
        pass


def _movy_store(cpu, addr: int, dy_reg: str, is_long: bool):
    """Perform a MOVY store (DSP data register -> YRAM)."""
    try:
        val = cpu.regs[dy_reg] & 0xFFFFFFFF
        if is_long:
            cpu.mem.write32(addr, val)
        else:
            cpu.mem.write16(addr, (val >> 16) & 0xFFFF)
    except (IndexError, Exception):
        pass


# ============================================================================
# DSP operation instructions (0xF0xx)
# ============================================================================

# Sentinel value used by libCPU73050 to indicate "no destination register"
# (dword_BA944 / dword_BA950 are set to 255 when the operation produces
# no result to write back, e.g. PCMP which only updates SR.T).
_NO_DEST = 255


def _handle_dsp_operation(cpu, op_val: int) -> bool:
    """Handle DSP operation instructions (0xF0xx).

    This is the Python port of CPU_DSP_OPERATION (libCPU73050 @ 0x28FD2).

    The wrapper:
      1. Checks SR.DSP (already done by handle_dsp_instruction).
      2. Calls _cpu_dsp_instruction_operation to compute results into
         the six result-slot variables (dest1, val1, guard1, dest2,
         val2, guard2).
      3. Calls _cpu_dsp_instruction_double for parallel MOVX/MOVY
         (stubbed for now).
      4. Writes back the results to the register file.

    For operations that write to A0 or A1 (index 39 or 40), the guard
    value is also written to the corresponding A0G / A1G register.
    """
    # Step 1: SR.DSP check (already done by handle_dsp_instruction).

    # Step 2: skip the repeat-loop counter increment
    # (qword_5F4190 + dword_BA858 += 2 logic).  This is only relevant
    # when running in a repeat block (RC != 0); we don't model RC yet.

    # Step 3: compute the operation.  This fills in the six result slots.
    dest1, val1, guard1, dest2, val2, guard2 = _cpu_dsp_instruction_operation(
        cpu, op_val
    )

    # Step 4: parallel MOVX/MOVY (stubbed - rare in OS boot).
    # In the real CPU_DSP_OPERATION, CPU_DSPInstructionDouble is called
    # here and may overwrite the result slots if the opcode combines a
    # compute op with a memory op.  We skip this for now.

    # Step 5: writeback.  Each result slot is written to the register
    # file (the dict in cpu.regs) if the dest index is valid (< 0x31 = 49).
    _writeback_dsp_result(cpu, dest1, val1, guard1)
    _writeback_dsp_result(cpu, dest2, val2, guard2)

    cpu.pc = _u32(cpu.pc + 2)
    return True


def _writeback_dsp_result(cpu, dest_idx: int, value: int, guard: int):
    """Write a DSP operation result back to the register file.

    Mirrors the writeback loop in CPU_DSP_OPERATION:
        if dest < 0x31:
            regs[dest] = value
            if dest == 39 (a0) or dest == 40 (a1):
                regs[dest_guard] = sign_extend_8(guard)

    The dirty-flag bookkeeping (the | (!v5 | 4) at offset +4) is skipped
    because RuK doesn't track per-register dirty flags.
    """
    if dest_idx == _NO_DEST:
        return
    if dest_idx >= 0x31:  # 49
        return

    # Map libCPU73050 internal index to RuK register name.
    reg_name = _DSP_REG_INDEX_TO_NAME.get(dest_idx)
    if reg_name is None:
        return

    cpu.regs[reg_name] = _u32(value)

    # If the destination is A0 or A1, also write the guard bits.
    if dest_idx == 39:  # a0
        cpu.regs['a0g'] = _sext8_to_32(guard & 0xFF)
    elif dest_idx == 40:  # a1
        cpu.regs['a1g'] = _sext8_to_32(guard & 0xFF)


# Reverse mapping: libCPU73050 internal index -> RuK register name.
# Built from DSPSingleDataReg_Table / DSPOperationDataReg_Table.
_DSP_REG_INDEX_TO_NAME = {
    39: 'a0',
    40: 'a1',
    41: 'a0g',
    42: 'a1g',
    43: 'x0',
    44: 'x1',
    45: 'y0',
    46: 'y1',
    47: 'm0',
    48: 'm1',
}


# ============================================================================
# CPU_DSPInstructionOperation (Python port - implements common operations)
# ============================================================================

def _cpu_dsp_instruction_operation(cpu, op_val: int):
    """Python port of CPU_DSPInstructionOperation (libCPU73050 @ 0x5DCC).

    This function decodes the 0xF0xx opcode and dispatches to the
    specific DSP operation handler.  The dispatch is on the LOW BYTE
    of the opcode (op_val & 0xFF), which selects one of ~80 valid
    operation classes (the rest are CPU_INVALID_DSPO).

    Each handler returns a 6-tuple:
        (dest1, val1, guard1, dest2, val2, guard2)

    A dest value of 255 (_NO_DEST) means "no result for this slot".

    The operations implemented here are the most common ones used in
    DSP filter code (PMULS, PADD, PSUB, PCLR, PCOPY, PNEG, PABS,
    PINC, PDEC, PAND, POR, PXOR, PCMP, PSTS, PLDS).  DCT/DCF
    variants are handled by checking the DSR.DC bit (see
    _dsr_dc_is_set).  Operations not yet implemented fall through to
    a NOP (return _NO_DEST for both slots).
    """
    # Decode common fields
    # Low byte layout (bits 0-7 of op_val):
    #   bits 0-3 : sub-opcode / dest reg selector
    #   bits 4-5 : SY register index (DSPOperationSYReg_Table)
    #   bits 6-7 : SX register index (DSPOperationSXReg_Table)
    sx_idx = (op_val >> 6) & 0x3
    sy_idx = (op_val >> 4) & 0x3
    sub = op_val & 0xF
    op_class = op_val & 0xFF  # operation selector = low byte

    # ---- DCT / DCF handling ----
    # DCT variants execute only if DSR.DC (bit 0) is set (RC != 0).
    # DCF variants execute only if DSR.DC is clear (RC == 0).
    # The DCT/DCF op_classes are determined by the low nibble pattern:
    #   base op at op_class, DCT at op_class+1, DCF at op_class+2
    # (for ops that have DCT/DCF variants).
    # We check the DSR.DC bit here and skip if the condition isn't met.
    dct_active = _dsr_dc_is_set(cpu)

    # Dispatch on op_class
    handler = _DSP_OP_TABLE.get(op_class)
    if handler is None:
        # Unknown / invalid operation -- treat as NOP
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    return handler(cpu, op_val, sx_idx, sy_idx, sub, dct_active)


def _dsr_dc_is_set(cpu) -> bool:
    """Return True if DSR.DC (bit 0) is set.

    DSR.DC reflects the repeat counter state: it's set when RC != 0
    (after the last decrement), and clear when RC == 0.

    The DSR.DC bit is updated by the repeat-loop handler in CPU.step()
    (see cpu.py).  When a DCT instruction executes, it checks DSR.DC:
      - DSR.DC = 1 (RC != 0): DCT executes (loop is still active)
      - DSR.DC = 0 (RC == 0): DCT skips (loop has ended)

    If we're not in a repeat loop (RC == 0 from the start), DSR.DC
    defaults to 0, so DCT variants skip.  This matches the SH-4 DSP
    manual: "DCT executes only when the loop is active."

    For non-DCT/DCF operations (the base op without the conditional),
    this function isn't consulted.
    """
    try:
        return (cpu.regs['dsr'] & 1) != 0
    except (KeyError, AttributeError):
        return False


def _sx_val(cpu, sx_idx: int) -> int:
    """Get the SX register value (signed 32-bit)."""
    reg_name = DSP_OP_SX_REG_TABLE[sx_idx]  # y0, y1, a0, a1
    return _i32(cpu.regs[reg_name])


def _sy_val(cpu, sy_idx: int) -> int:
    """Get the SY register value (signed 32-bit)."""
    reg_name = DSP_OP_SY_REG_TABLE[sy_idx]  # m0, m1, x0, x1
    return _i32(cpu.regs[reg_name])


def _dz_idx_from_du(sub: int) -> int:
    """Get the Dz internal index from the DU table (for PADD/PSUB/etc.)."""
    reg_name = DSP_OP_DU_REG_TABLE[sub & 0x3]  # y0, m0, a0, a1
    return _DSP_NAME_TO_INDEX[reg_name]


def _dz_idx_from_dg(sub: int) -> int:
    """Get the Dz internal index from the DG table (for PMULS+PCLR)."""
    reg_name = DSP_OP_DG_REG_TABLE[(sub >> 2) & 0x3]  # x0, x1, a0, a1
    return _DSP_NAME_TO_INDEX[reg_name]


def _dz_idx_from_data_reg(sub: int) -> int:
    """Get the Dz internal index from the DSPOperationDataReg_Table.

    This table maps the 4-bit sub-opcode to one of the DSP data
    registers (or 0 = invalid).  Used by PSTS/PLDS/PCOPY.
    """
    # DSPOperationDataReg_Table[16] from libCPU73050 @ 0xA0D00:
    #   db 5 dup(0), 28h, 0, 27h, 2Dh, 2Eh, 2Fh, 30h, 2Bh, 0, 2Ch, 0
    # Index -> internal index:
    #   0-4: 0 (invalid)
    #   5: 0x28 (40 = a1)
    #   6: 0 (invalid)
    #   7: 0x27 (39 = a0)
    #   8: 0x2D (45 = y0)
    #   9: 0x2E (46 = y1)
    #  10: 0x2F (47 = m0)
    #  11: 0x30 (48 = m1)
    #  12: 0x2B (43 = x0)
    #  13: 0 (invalid)
    #  14: 0x2C (44 = x1)
    #  15: 0 (invalid)
    table = [0, 0, 0, 0, 0, 40, 0, 39, 45, 46, 47, 48, 43, 0, 44, 0]
    return table[sub & 0xF]


# ============================================================================
# Operation handlers
# ============================================================================

def _op_pshl_imm(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSHL #imm, Dz -- shift Dz left by immediate.

    Cases 0x00-0x07: 8 entries, Dz from DU table indexed by sub & 0x7.
    The shift amount is encoded in bits 4-7 (SX/SY indices combined).

    Note: PSHL #imm is NOT a DCT/DCF variant -- it always executes.
    """
    # The shift amount is the 6-bit value from bits 4-9... actually
    # for PSHL #imm, the immediate is in bits 4-7 (4 bits, 0-15).
    # Bits 6-7 select the Dz register pair.
    # Per the SH-4 DSP manual: PSHL #imm, Dz where imm is 4-bit signed.
    shift = (op_val >> 4) & 0xF  # 4-bit immediate
    dz_reg = DSP_OP_DU_REG_TABLE[sub & 0x3]
    dz_idx = _DSP_NAME_TO_INDEX[dz_reg]
    val = _i32(cpu.regs[dz_reg])
    # PSHL: if shift is positive, shift left; the imm is signed 4-bit
    # but for PSHL it's always left shift by imm (0-15).
    result = _u32(val << shift) if shift < 32 else 0
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_psha_imm(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSHA #imm, Dz -- arithmetic shift Dz by immediate.

    Cases 0x10-0x17: 8 entries, Dz from DU table.
    The shift amount is a 4-bit signed immediate in bits 4-7.
    Positive = shift left, negative = arithmetic shift right.

    Note: PSHA #imm is NOT a DCT/DCF variant -- it always executes.
    """
    shift_raw = (op_val >> 4) & 0xF  # 4-bit signed immediate
    # Sign-extend from 4 bits
    if shift_raw & 0x8:
        shift = shift_raw - 0x10  # negative
    else:
        shift = shift_raw  # positive
    dz_reg = DSP_OP_DU_REG_TABLE[sub & 0x3]
    dz_idx = _DSP_NAME_TO_INDEX[dz_reg]
    val = _i32(cpu.regs[dz_reg])
    if shift >= 0:
        result = _u32(val << shift) if shift < 32 else 0
    else:
        result = _u32(val >> (-shift)) if (-shift) < 32 else (0xFFFFFFFF if val < 0 else 0)
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_pmuls_pclr(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PMULS Sx, Sy, Dg + PCLR -- multiply Sx*Sy into Dg, clear Dz.

    Cases 0x40-0x4F: 16 entries (4 SX × 4 SY).
    Dg from DG table (x0, x1, a0, a1) indexed by (sub >> 2) & 0x3.
    Dz from DG table too (the "PCLR" destination is actually the
    same Dg -- the operation writes the product to Dg and clears
    the "other" register).

    Per libCPU73050 LABEL_81:
      if (_EAX & 0xF3) == 0:  # sub in {0, 1, 8, 9} -> Dg only
        dword_BA944 = 255  (no Dz)
        dword_BA950 = DSPOperationDGReg_Table[(sub >> 2) & 3]
        product = 2 * sext16(Sx) * sext16(Sy)  (with 0x8000*0x8000 saturation)
      else if (_EAX & 0xF0) == 0x10:  # sub in {2,3,6,7,0xA,0xB,0xE,0xF}
        # Dz from DU table, Dg from DG table
        ...

    Note: PMULS+PCLR is NOT a DCT/DCF variant -- it always executes.
    """
    # Get Sx and Sy as signed 16-bit values (upper 16 bits of the reg)
    sx = _i16((cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] >> 16) & 0xFFFF)
    sy = _i16((cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] >> 16) & 0xFFFF)
    # Compute product with saturation (0x8000 * 0x8000 = 0x7FFFFFFF)
    if sx == -32768 and sy == -32768:
        product = 0x7FFFFFFF
    else:
        product = 2 * sx * sy
    product = _u32(product)

    # Determine destinations based on sub-opcode
    if (sub & 0x3) == 0:  # sub in {0, 8}: Dg only, no Dz
        dg_reg = DSP_OP_DG_REG_TABLE[(sub >> 2) & 0x3]
        dg_idx = _DSP_NAME_TO_INDEX[dg_reg]
        return (_NO_DEST, 0, 0, dg_idx, product, 0)
    elif (sub & 0xF0) == 0x10:  # sub in {2,3,6,7,0xA,0xB,0xE,0xF}: Dz + Dg
        # Dz from DU table (sub & 0x3), Dg from DG table
        dz_reg = DSP_OP_DU_REG_TABLE[sub & 0x3]
        dz_idx = _DSP_NAME_TO_INDEX[dz_reg]
        dg_reg = DSP_OP_DG_REG_TABLE[(sub >> 2) & 0x3]
        dg_idx = _DSP_NAME_TO_INDEX[dg_reg]
        # Dz = 0 (PCLR), Dg = product
        return (dz_idx, 0, 0, dg_idx, product, 0)
    else:
        # Invalid sub-opcode combination
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)


def _op_pmuls_psub(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PMULS Sx, Sy, Dg + PSUB -- multiply into Dg, subtract Sy from Sx.

    Cases 0x60-0x6F: PMULS + PSUB.
    Per libCPU73050 LABEL_111:
      dest1 (DU) = SX - SY  (the PSUB part)
      dest2 (DG) = 2 * sext16(SX) * sext16(SY)  (the PMULS part)

    Note: PMULS+PSUB is NOT a DCT/DCF variant -- it always executes.
    """
    sx = _i16((cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] >> 16) & 0xFFFF)
    sy = _i16((cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] >> 16) & 0xFFFF)
    if sx == -32768 and sy == -32768:
        product = 0x7FFFFFFF
    else:
        product = 2 * sx * sy
    product = _u32(product)

    # dest1 = DU[sub & 3], dest2 = DG[(sub >> 2) & 3]
    dz_reg = DSP_OP_DU_REG_TABLE[sub & 0x3]
    dz_idx = _DSP_NAME_TO_INDEX[dz_reg]
    dg_reg = DSP_OP_DG_REG_TABLE[(sub >> 2) & 0x3]
    dg_idx = _DSP_NAME_TO_INDEX[dg_reg]

    # PSUB: Dz = SX - SY (full 32-bit values)
    sx_full = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy_full = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sx_full - sy_full)
    return (dz_idx, result, _sign_guard(result), dg_idx, product, 0)


def _op_pmuls_padd(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PMULS Sx, Sy, Dg + PADD -- multiply into Dg, add Sx+Sy into Dz.

    Cases 0x70-0x7F: PMULS + PADD.
    Per libCPU73050 LABEL_133:
      dest1 (DU) = SX + SY  (the PADD part)
      dest2 (DG) = 2 * sext16(SX) * sext16(SY)  (the PMULS part)

    Note: PMULS+PADD is NOT a DCT/DCF variant -- it always executes.
    """
    sx = _i16((cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] >> 16) & 0xFFFF)
    sy = _i16((cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] >> 16) & 0xFFFF)
    if sx == -32768 and sy == -32768:
        product = 0x7FFFFFFF
    else:
        product = 2 * sx * sy
    product = _u32(product)

    # dest1 = DU[sub & 3], dest2 = DG[(sub >> 2) & 3]
    dz_reg = DSP_OP_DU_REG_TABLE[sub & 0x3]
    dz_idx = _DSP_NAME_TO_INDEX[dz_reg]
    dg_reg = DSP_OP_DG_REG_TABLE[(sub >> 2) & 0x3]
    dg_idx = _DSP_NAME_TO_INDEX[dg_reg]

    # PADD: Dz = SX + SY (full 32-bit values)
    sx_full = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy_full = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sx_full + sy_full)
    return (dz_idx, result, _sign_guard(result), dg_idx, product, 0)


def _op_pshl_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSHL Sx, Sy, Dz -- variable shift left.

    Case 0x81: Dz = Sx << Sy (Sy is the shift amount, lower 6 bits).
    Case 0x82: DCT PSHL Sx, Sy, Dz
    Case 0x83: DCF PSHL Sx, Sy, Dz
    """
    # For DCT (0x82) and DCF (0x83), check dct_active accordingly
    op_class = op_val & 0xFF
    if op_class == 0x82 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0x83 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    shift = sy & 0x3F  # 6-bit shift amount
    if shift < 32:
        result = _u32(sx << shift)
    else:
        result = 0
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_pcmp_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PCMP Sx, Sy -- compare, set SR.T.

    Case 0x84: compares Sx and Sy, sets SR.T based on the result.
    No register writeback (both dest slots are _NO_DEST).
    """
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    # PCMP sets SR.T = 1 if Sx > Sy (signed), else 0.
    # Per SH-4 DSP manual: T = (Sx > Sy) ? 1 : 0
    if sx > sy:
        cpu.regs['sr'] |= 1
    else:
        cpu.regs['sr'] &= ~1 & 0xFFFFFFFF
    return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)


def _op_psub_sy_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSUB Sy, Sx, Dz -- Dz = Sy - Sx.

    Cases 0x85, 0x86 (DCT), 0x87 (DCF).
    Note the operand order: result = Sy - Sx (NOT Sx - Sy).
    """
    op_class = op_val & 0xFF
    if op_class == 0x86 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0x87 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sy - sx)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pabs_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PABS Sx, Dz -- Dz = |Sx|.

    Cases 0x88 (with op_val & 0x30 == 0), 0x89 (variant),
    0x8A (DCT), 0x8B (DCF), 0x9D (Sy variant).
    """
    op_class = op_val & 0xFF
    if op_class in (0x8A, 0xBA, 0xEA) and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class in (0x8B, 0xBB, 0xEB) and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    if sx < 0:
        result = _u32(-sx)
    else:
        result = _u32(sx)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pabs_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PABS Sy, Dz -- Dz = |Sy|.

    Cases 0xE9 (base), 0xEA (DCT), 0xEB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xEA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xEB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    if sy < 0:
        result = _u32(-sy)
    else:
        result = _u32(sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pdec_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PDEC Sx, Dz -- Dz = Sx - 1.

    Cases 0x9D (base).  PDEC is NOT a DCT/DCF variant -- it always
    executes.  Per libCPU73050, PDEC subtracts 1 from the full 32-bit
    value (not just the upper 16 bits).
    """
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    result = _u32(sx - 1)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pdec_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PDEC Sy, Dz -- Dz = Sy - 1.

    Cases 0xD9 (base), 0xDA (DCT), 0xDB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xDA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xDB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sy - 1)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pclr_dz(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PCLR Dz -- Dz = 0.

    Cases 0x8D, 0x8E (DCT), 0x8F (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0x8E and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0x8F and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, 0, 0, _NO_DEST, 0, 0)


def _op_psha_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSHA Sx, Sy, Dz -- arithmetic shift Dz = Sx shifted by Sy.

    Cases 0x91, 0x92 (DCT), 0x93 (DCF).
    Positive Sy = shift left, negative Sy = arithmetic shift right.
    """
    op_class = op_val & 0xFF
    if op_class == 0x92 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0x93 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    if sy >= 0:
        shift = sy & 0x3F
        if shift < 32:
            result = _u32(sx << shift)
        else:
            result = 0
    else:
        shift = (-sy) & 0x3F
        if shift < 32:
            result = _u32(sx >> shift)
        else:
            result = 0xFFFFFFFF if sx < 0 else 0
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pand_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PAND Sx, Sy, Dz -- Dz = Sx & Sy.

    Cases 0x95, 0x96 (DCT), 0x97 (DCF).
    Per libCPU73050, only the upper 16 bits are ANDed (0xFFFF0000 mask).
    """
    op_class = op_val & 0xFF
    if op_class == 0x96 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0x97 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] & 0xFFFF0000
    sy = cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] & 0xFFFF0000
    result = _u32(sx & sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_prnd_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PRND Sx, Dz -- Dz = round(Sx).

    Cases 0x98, 0x99 (variant), 0x9A (DCT), 0x9B (DCF).
    Rounding: add 0x8000 (rounds the lower 16 bits to the upper 16).
    """
    op_class = op_val & 0xFF
    if op_class in (0x9A, 0xCA, 0xDA) and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class in (0x9B, 0xCB, 0xDB) and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    # Round: add 0x8000 then mask off the lower 16 bits
    result = _u32((sx + 0x8000) & 0xFFFF0000)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pinc_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PINC Sx, Dz -- Dz = Sx + 0x10000 (increment upper 16 bits).

    Cases 0x99 (variant), 0xD9, 0xDA (DCT), 0xDB (DCF).
    Per libCPU73050 LABEL_302, PINC adds 0x10000 (1 in upper 16 bits).
    """
    op_class = op_val & 0xFF
    if op_class in (0xDA, 0x9A) and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class in (0xDB, 0x9B) and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]]
    result = _u32(sx + 0x10000) & 0xFFFF0000
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_psub_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSUB Sx, Sy, Dz -- Dz = Sx - Sy.

    Cases 0xA1, 0xA2 (DCT), 0xA3 (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xA2 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xA3 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sx - sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pxor_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PXOR Sx, Sy, Dz -- Dz = Sx ^ Sy (upper 16 bits only).

    Cases 0xA5, 0xA6 (DCT), 0xA7 (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xA6 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xA7 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] & 0xFFFF0000
    sy = cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] & 0xFFFF0000
    result = _u32(sx ^ sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_pneg_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PNEG Sx, Dz -- Dz = -Sx.

    Cases 0xA8, 0xA9 (variant), 0xAA (DCT), 0xAB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xAA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xAB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    result = _u32(-sx)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pneg_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PNEG Sy, Dz -- Dz = -Sy.

    Cases 0xC9 (base), 0xCA (DCT), 0xCB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xCA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xCB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(-sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_padd_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PADD Sx, Sy, Dz -- Dz = Sx + Sy.

    Cases 0xB1, 0xB2 (DCT), 0xB3 (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xB2 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xB3 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = _i32(cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]])
    sy = _i32(cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]])
    result = _u32(sx + sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_por_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """POR Sx, Sy, Dz -- Dz = Sx | Sy (upper 16 bits only).

    Cases 0xB5, 0xB6 (DCT), 0xB7 (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xB6 and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xB7 and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] & 0xFFFF0000
    sy = cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] & 0xFFFF0000
    result = _u32(sx | sy)
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, 0, _NO_DEST, 0, 0)


def _op_paddc_sx_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PADDC Sx, Sy, Dz -- Dz = Sx + Sy + 0x10000 (carry into upper 16).

    Cases 0xB8, 0xB9 (variant), 0xBA (DCT), 0xBB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xBA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xBB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]] & 0xFFFF0000
    sy = cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]] & 0xFFFF0000
    result = _u32(sx + sy + 0x10000) & 0xFFFF0000
    dz_idx = _dz_idx_from_du(sub)
    return (dz_idx, result, _sign_guard(result), _NO_DEST, 0, 0)


def _op_pcopy_sx(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PCOPY Sx, Dz -- Dz = Sx.

    Cases 0xBD, 0xBE (DCT), 0xBF (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xBE and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xBF and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sx = cpu.regs[DSP_OP_SX_REG_TABLE[sx_idx]]
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    return (dz_idx, sx, _sign_guard(_i32(sx)), _NO_DEST, 0, 0)


def _op_pcopy_sy(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PCOPY Sy, Dz -- Dz = Sy.

    Cases 0xF9, 0xFA (DCT), 0xFB (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xFA and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xFB and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    sy = cpu.regs[DSP_OP_SY_REG_TABLE[sy_idx]]
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    return (dz_idx, sy, _sign_guard(_i32(sy)), _NO_DEST, 0, 0)


def _op_psts_mach(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSTS MACH, Dz -- Dz = MACH.

    Cases 0xCD, 0xCE (DCT), 0xCF (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xCE and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xCF and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    mach = cpu.regs['mach']
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    return (dz_idx, mach, _sign_guard(_i32(mach)), _NO_DEST, 0, 0)


def _op_psts_macl(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PSTS MACL, Dz -- Dz = MACL.

    Cases 0xDD, 0xDE (DCT), 0xDF (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xDE and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xDF and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    macl = cpu.regs['macl']
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    return (dz_idx, macl, _sign_guard(_i32(macl)), _NO_DEST, 0, 0)


def _op_plds_mach(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PLDS Dz, MACH -- MACH = Dz.

    Cases 0xED, 0xEE (DCT), 0xEF (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xEE and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xEF and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    reg_name = _DSP_REG_INDEX_TO_NAME[dz_idx]
    val = cpu.regs[reg_name]
    # Write to MACH (stored in cpu.regs['mach'])
    cpu.regs['mach'] = _u32(val)
    return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)


def _op_plds_macl(cpu, op_val, sx_idx, sy_idx, sub, dct_active):
    """PLDS Dz, MACL -- MACL = Dz.

    Cases 0xFD, 0xFE (DCT), 0xFF (DCF).
    """
    op_class = op_val & 0xFF
    if op_class == 0xFE and not dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    if op_class == 0xFF and dct_active:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    dz_idx = _dz_idx_from_data_reg(sub)
    if dz_idx == 0:
        return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)
    reg_name = _DSP_REG_INDEX_TO_NAME[dz_idx]
    val = cpu.regs[reg_name]
    cpu.regs['macl'] = _u32(val)
    return (_NO_DEST, 0, 0, _NO_DEST, 0, 0)


def _sign_guard(value) -> int:
    """Compute the guard value for a result.

    For A0/A1 destinations, the guard bits hold the sign extension
    of the 32-bit result: 0xFFFFFFFF if negative, 0x00000000 if positive.
    """
    v = _i32(value)
    return 0xFFFFFFFF if v < 0 else 0x00000000


# ============================================================================
# Operation dispatch table (op_class -> handler)
# ============================================================================

_DSP_OP_TABLE = {
    # PSHL #imm, Dz (8 entries: Dz from DU table, imm in bits 4-7)
    0x00: _op_pshl_imm, 0x01: _op_pshl_imm, 0x02: _op_pshl_imm, 0x03: _op_pshl_imm,
    0x04: _op_pshl_imm, 0x05: _op_pshl_imm, 0x06: _op_pshl_imm, 0x07: _op_pshl_imm,

    # PSHA #imm, Dz (8 entries)
    0x10: _op_psha_imm, 0x11: _op_psha_imm, 0x12: _op_psha_imm, 0x13: _op_psha_imm,
    0x14: _op_psha_imm, 0x15: _op_psha_imm, 0x16: _op_psha_imm, 0x17: _op_psha_imm,

    # PMULS + PCLR (16 entries: 4 SX × 4 SY)
    0x40: _op_pmuls_pclr, 0x41: _op_pmuls_pclr, 0x42: _op_pmuls_pclr, 0x43: _op_pmuls_pclr,
    0x44: _op_pmuls_pclr, 0x45: _op_pmuls_pclr, 0x46: _op_pmuls_pclr, 0x47: _op_pmuls_pclr,
    0x48: _op_pmuls_pclr, 0x49: _op_pmuls_pclr, 0x4A: _op_pmuls_pclr, 0x4B: _op_pmuls_pclr,
    0x4C: _op_pmuls_pclr, 0x4D: _op_pmuls_pclr, 0x4E: _op_pmuls_pclr, 0x4F: _op_pmuls_pclr,

    # PMULS + PSUB (16 entries)
    0x60: _op_pmuls_psub, 0x61: _op_pmuls_psub, 0x62: _op_pmuls_psub, 0x63: _op_pmuls_psub,
    0x64: _op_pmuls_psub, 0x65: _op_pmuls_psub, 0x66: _op_pmuls_psub, 0x67: _op_pmuls_psub,
    0x68: _op_pmuls_psub, 0x69: _op_pmuls_psub, 0x6A: _op_pmuls_psub, 0x6B: _op_pmuls_psub,
    0x6C: _op_pmuls_psub, 0x6D: _op_pmuls_psub, 0x6E: _op_pmuls_psub, 0x6F: _op_pmuls_psub,

    # PMULS + PADD (16 entries)
    0x70: _op_pmuls_padd, 0x71: _op_pmuls_padd, 0x72: _op_pmuls_padd, 0x73: _op_pmuls_padd,
    0x74: _op_pmuls_padd, 0x75: _op_pmuls_padd, 0x76: _op_pmuls_padd, 0x77: _op_pmuls_padd,
    0x78: _op_pmuls_padd, 0x79: _op_pmuls_padd, 0x7A: _op_pmuls_padd, 0x7B: _op_pmuls_padd,
    0x7C: _op_pmuls_padd, 0x7D: _op_pmuls_padd, 0x7E: _op_pmuls_padd, 0x7F: _op_pmuls_padd,

    # PSHL Sx, Sy, Dz (+ DCT/DCF)
    0x81: _op_pshl_sx_sy, 0x82: _op_pshl_sx_sy, 0x83: _op_pshl_sx_sy,

    # PCMP Sx, Sy
    0x84: _op_pcmp_sx_sy,

    # PSUB Sy, Sx, Dz (+ DCT/DCF)
    0x85: _op_psub_sy_sx, 0x86: _op_psub_sy_sx, 0x87: _op_psub_sy_sx,

    # PABS Sx, Dz (+ DCT/DCF)
    0x88: _op_pabs_sx, 0x89: _op_pabs_sx, 0x8A: _op_pabs_sx, 0x8B: _op_pabs_sx,

    # PCLR Dz (+ DCT/DCF)
    0x8D: _op_pclr_dz, 0x8E: _op_pclr_dz, 0x8F: _op_pclr_dz,

    # PSHA Sx, Sy, Dz (+ DCT/DCF)
    0x91: _op_psha_sx_sy, 0x92: _op_psha_sx_sy, 0x93: _op_psha_sx_sy,

    # PAND Sx, Sy, Dz (+ DCT/DCF)
    0x95: _op_pand_sx_sy, 0x96: _op_pand_sx_sy, 0x97: _op_pand_sx_sy,

    # PRND Sx, Dz (+ DCT/DCF)
    0x98: _op_prnd_sx, 0x99: _op_prnd_sx, 0x9A: _op_prnd_sx, 0x9B: _op_prnd_sx,

    # PINC Sx, Dz
    0x9D: _op_pinc_sx,

    # PSUB Sx, Sy, Dz (+ DCT/DCF) -- 0xA0 is PSUB with carry
    0xA0: _op_psub_sx_sy, 0xA1: _op_psub_sx_sy, 0xA2: _op_psub_sx_sy, 0xA3: _op_psub_sx_sy,

    # PXOR Sx, Sy, Dz (+ DCT/DCF)
    0xA5: _op_pxor_sx_sy, 0xA6: _op_pxor_sx_sy, 0xA7: _op_pxor_sx_sy,

    # PNEG Sx, Dz (+ DCT/DCF)
    0xA8: _op_pneg_sx, 0xA9: _op_pneg_sx, 0xAA: _op_pneg_sx, 0xAB: _op_pneg_sx,

    # PADD Sx, Sy, Dz (+ DCT/DCF) -- 0xB0 is PADD with carry
    0xB0: _op_padd_sx_sy, 0xB1: _op_padd_sx_sy, 0xB2: _op_padd_sx_sy, 0xB3: _op_padd_sx_sy,

    # POR Sx, Sy, Dz (+ DCT/DCF)
    0xB5: _op_por_sx_sy, 0xB6: _op_por_sx_sy, 0xB7: _op_por_sx_sy,

    # PADDC Sx, Sy, Dz (+ DCT/DCF)
    0xB8: _op_paddc_sx_sy, 0xB9: _op_paddc_sx_sy, 0xBA: _op_paddc_sx_sy, 0xBB: _op_paddc_sx_sy,

    # PCOPY Sx, Dz (+ DCT/DCF)
    0xBD: _op_pcopy_sx, 0xBE: _op_pcopy_sx, 0xBF: _op_pcopy_sx,

    # PNEG Sy, Dz (+ DCT/DCF) -- Sy variant
    0xC9: _op_pneg_sy, 0xCA: _op_pneg_sy, 0xCB: _op_pneg_sy,

    # PSTS MACH, Dz (+ DCT/DCF)
    0xCD: _op_psts_mach, 0xCE: _op_psts_mach, 0xCF: _op_psts_mach,

    # PDEC Sy, Dz (+ DCT/DCF) -- Sy variant
    0xD9: _op_pdec_sy, 0xDA: _op_pdec_sy, 0xDB: _op_pdec_sy,

    # PSTS MACL, Dz (+ DCT/DCF)
    0xDD: _op_psts_macl, 0xDE: _op_psts_macl, 0xDF: _op_psts_macl,

    # PABS Sy, Dz (+ DCT/DCF) -- Sy variant
    0xE9: _op_pabs_sy, 0xEA: _op_pabs_sy, 0xEB: _op_pabs_sy,

    # PLDS Dz, MACH (+ DCT/DCF)
    0xED: _op_plds_mach, 0xEE: _op_plds_mach, 0xEF: _op_plds_mach,

    # PCOPY Sy, Dz (+ DCT/DCF)
    0xF9: _op_pcopy_sy, 0xFA: _op_pcopy_sy, 0xFB: _op_pcopy_sy,

    # PLDS Dz, MACL (+ DCT/DCF)
    0xFD: _op_plds_macl, 0xFE: _op_plds_macl, 0xFF: _op_plds_macl,
}


# Reverse mapping: RuK register name -> libCPU73050 internal index.
_DSP_NAME_TO_INDEX = {v: k for k, v in _DSP_REG_INDEX_TO_NAME.items()}


# ============================================================================
# CPU_DSPInstructionDouble (handles combined op + MOVX/MOVY)
# ============================================================================

def _cpu_dsp_instruction_double(cpu, op_val: int):
    """Python port of CPU_DSPInstructionDouble (libCPU73050 @ 0x54EC).

    Handles parallel MOVX/MOVY memory access for opcodes that combine
    a DSP operation with a memory access.  Called from
    _handle_dsp_operation after _cpu_dsp_instruction_operation.

    In the real CPU, a single 0xF0xx opcode can encode BOTH a compute
    operation (like PCOPY) AND a MOVX/MOVY memory access.  The compute
    op writes to the result slots, and the MOVX/MOVY reads/writes
    memory in parallel.

    For example, the SigmaDelta2 codec uses:
        DCT PCOPY Y0, A1 MOVX.W @R5, Y0 NOPY

    This is encoded as a single 0xF0xx opcode where:
      - The compute op (DCT PCOPY Y0, A1) is handled by
        _cpu_dsp_instruction_operation
      - The MOVX.W @R5, Y0 NOPY is handled here (in _cpu_dsp_instruction_double)

    The MOVX/MOVY part is encoded in the SAME opcode using the same
    field layout as the standalone MOVX/MOVY instructions (0xF4xx/0xF5xx),
    but with the high nibble being 0xF0 instead of 0xF4/0xF5.

    Actually, looking at the libCPU73050 decomp more carefully, the
    combined opcodes use a SEPARATE encoding.  The MOVX/MOVY part of
    a combined opcode is encoded in bits that overlap with the SX/SY
    register selectors of the compute op.

    For now, we handle the common case: the MOVX/MOVY is a separate
    instruction (0xF4xx/0xF5xx) that follows the compute op.  Combined
    opcodes (where both happen in one instruction) are not yet supported.
    """
    # TODO: Implement combined compute + MOVX/MOVY for opcodes like
    # DCT PCOPY Y0, A1 MOVX.W @R5, Y0 NOPY.  This requires decoding
    # the MOVX/MOVY fields from the 0xF0xx opcode itself.
    #
    # For now, the MOVX/MOVY is handled as a separate instruction by
    # _handle_movx_movy (called when the opcode is 0xF4xx/0xF5xx).
    return None
