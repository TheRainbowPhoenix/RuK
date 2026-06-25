# SH4AL-DSP (SH7305) DSP Instruction Reference

This file collects all the DSP instruction reference data extracted
from libCPU73050.dylib and Casio's CPU73050.dll decompilations.  It
is intended as a single-file reference for future DSP implementation
work on the RuK emulator.

The implementation lives in `ruk/jcore/dsp.py`.  Tests live in
`test_dsp_movs.py`.

---

## 1. SR.DSP Bit

DSP instructions are only dispatched when SR bit 12 (0x1000) is set.
When SR.DSP = 0, the same encodings decode as standard SH-4
instructions (NOP / PREF / ICBI / etc.).

The libCPU73050 functions check SR.DSP at entry:
```c
if ( (SR & 0x1000) == 0 )
    return CPU_INVALID(a1, a2);
```

---

## 2. DSP Instruction Encoding Summary

| Range          | Family       | Dispatcher (libCPU73050)       | Handler (Python)         |
|----------------|--------------|--------------------------------|--------------------------|
| 0x0000-0x03FF  | MOVS single  | CPU_DSP_SINGLE_DATA @ 0x28FB4  | `_handle_movs`           |
| 0xF000-0xF0FF  | DSP ops      | CPU_DSP_OPERATION @ 0x28FD2    | `_handle_dsp_operation`  |
| 0xF400-0xF5FF  | MOVX/MOVY    | CPU_DSP_DOUBLE_DATA @ 0x28F96  | `_handle_movx_movy`      |

---

## 3. MOVS Single Memory Instructions

### Encoding
```
0000_00aa_dddd_mmmm
  aa    = As index (0-3)   -> DSPSingleAddrReg_Table
  dddd  = Ds index (0-15)  -> DSPSingleDataReg_Table
  mmmm  = mode (0-15)
```

### The 16 Modes (from DSPSingleInstr_Table @ 0xA0218)

| Mode | Mnemonic           | LibCPU73050 handler             |
|------|--------------------|---------------------------------|
|  0   | MOVS.W @As+Ix, Ds  | CPU_DSP_MOVSW_IDAS_DS           |
|  1   | MOVS.W Ds, @As+Ix  | CPU_DSP_MOVSW_DS_IDAS           |
|  2   | MOVS.L @As+Ix, Ds  | CPU_DSP_MOVSL_IDAS_DS           |
|  3   | MOVS.L Ds, @As+Ix  | CPU_DSP_MOVSL_DS_IDAS           |
|  4   | MOVS.W @As, Ds     | CPU_DSP_MOVSW_IAS_DS            |
|  5   | MOVS.W Ds, @As     | CPU_DSP_MOVSW_DS_IAS            |
|  6   | MOVS.L @As, Ds     | CPU_DSP_MOVSL_IAS_DS            |
|  7   | MOVS.L Ds, @As     | CPU_DSP_MOVSL_DS_IAS            |
|  8   | MOVS.W @-As, Ds    | CPU_DSP_MOVSW_IASI_DS           |
|  9   | MOVS.W Ds, @-As    | CPU_DSP_MOVSW_DS_IASI           |
| 10   | MOVS.L @-As, Ds    | CPU_DSP_MOVSL_IASI_DS           |
| 11   | MOVS.L Ds, @-As    | CPU_DSP_MOVSL_DS_IASI           |
| 12   | MOVS.W @As+, Ds    | CPU_DSP_MOVSW_IASIX_DS          |
| 13   | MOVS.W Ds, @As+    | CPU_DSP_MOVSW_DS_IASIX          |
| 14   | MOVS.L @As+, Ds    | CPU_DSP_MOVSL_IASIX_DS          |
| 15   | MOVS.L Ds, @As+    | CPU_DSP_MOVSL_DS_IASIX          |

### Register Tables (from libCPU73050 @ 0xA0298, 0xA02D9, 0xA02A8)

```c
// DSPSingleAddrReg_Table[4] @ 0xA02D9
db 4, 5, 2, 3       // As index 0-3 -> R4, R5, R2, R3

// DSPSingleDataReg_Table[16] @ 0xA0298
db 5 dup(0), 28h, 0, 27h, 2Dh, 2Eh, 2Fh, 30h, 2Bh, 2Ah, 2Ch, 29h
// Ds index -> internal index -> RuK register name
//   0  -> 0   (invalid)
//   1  -> 0   (invalid)
//   2  -> 0   (invalid)
//   3  -> 0   (invalid)
//   4  -> 0   (invalid)
//   5  -> 40  -> 'a1'
//   6  -> 0   (invalid)
//   7  -> 39  -> 'a0'
//   8  -> 45  -> 'y0'
//   9  -> 46  -> 'y1'
//  10  -> 47  -> 'm0'
//  11  -> 48  -> 'm1'
//  12  -> 43  -> 'x0'
//  13  -> 42  -> 'a1g'
//  14  -> 44  -> 'x1'
//  15  -> 41  -> 'a0g'

// DSPStoreMode_Table[49] @ 0xA02A8
db 27h dup(0), 2 dup(1), 2 dup(2), 6 dup(0)
// Index 39 (a0)  -> mode 1 (word store writes upper 16 bits)
// Index 40 (a1)  -> mode 1
// Index 41 (a0g) -> mode 2 (byte access)
// Index 42 (a1g) -> mode 2
// All others     -> mode 0 (default word store: upper 16 bits)
```

### Word Load/Store Semantics (from CPU_DSPInstructionSingle LABEL_7)

```
LABEL_7 (post-load behavior):
  v9 = DSPStoreMode_Table[Ds]
  if (v9 == 1) {  // A0 / A1
    result = v7 << 16;              // value in upper 16 bits, lower 16 = 0
    Ds = result;
    Ds_guard = -(result < 0);       // 0xFFFFFFFF if negative, else 0
  } else if (v9 > 1) {  // A0G / A1G
    result = (char)v7;              // sign-extended byte in lower 8 bits
    Ds = result;
  } else {  // X0/X1/Y0/Y1/M0/M1
    result = v7 << 16;              // value in upper 16 bits, lower 16 = 0
    Ds = result;
  }
```

**Key insight:** Word loads to A0/A1 put the value in the UPPER 16 bits
(same as X0/X1/Y0/Y1/M0/M1), NOT the lower 16 bits.  The accumulator
guard bit (A0G/A1G) is updated to the sign of the result.

Word stores (case 5) always read the upper 16 bits of the register
slot (offset +2 in the 8-byte struct entry), regardless of register
type.

---

## 4. DSP Operation Instructions (0xF0xx)

### Encoding
```
1111_0000_xxxx_xxxx
  bits 0-3 : sub-opcode / dest register selector
  bits 4-5 : SY register index (DSPOperationSYReg_Table)
  bits 6-7 : SX register index (DSPOperationSXReg_Table)
```

The operation is dispatched through the 256-entry
`DSPOperationInstr_Table` at 0xA0500 in libCPU73050, indexed by
`HIBYTE(opcode)` (i.e., bits 8-15) -- which is always 0xF0 for this
family, so the dispatch is actually on the low byte combined with
the SX/SY indices.

### Register Tables

```c
// DSPOperationSXReg_Table[4] @ 0xA0D10
db 2Dh, 2Eh, 27h, 28h       // SX index 0-3 -> y0, y1, a0, a1

// DSPOperationSYReg_Table[4] @ 0xA0D34
db 2Fh, 30h, 2Bh, 2Ch       // SY index 0-3 -> m0, m1, x0, x1

// DSPOperationDGReg_Table[4] @ 0xA0D58
db 2Bh, 2Ch, 27h, 28h       // DG index 0-3 -> x0, x1, a0, a1

// DSPOperationDUReg_Table[4] @ 0xA0D5C
db 2Dh, 2Fh, 27h, 28h       // DU index 0-3 -> y0, m0, a0, a1

// DSPOperationDataReg_Table[16] @ 0xA0D00
db 5 dup(0), 28h, 0, 27h, 2Dh, 2Eh, 2Fh, 30h, 2Bh, 0, 2Ch, 0
// Same as DSPSingleDataReg_Table but with index 13 and 15 set to 0
// (PSTS/PLDS use specific dest regs, not the full set)
```

### Operation Dispatch Table (DSPOperationInstr_Table @ 0xA0500)

The table has 256 entries (32 rows x 8 columns), indexed by
`(opcode >> 4) & 0xFF` (i.e., the low byte shifted right by 4).
Wait, actually it's indexed by `HIBYTE(opcode)` after the opcode
has been pre-processed -- the exact indexing is complex.

The valid (non-`CPU_INVALID_DSPO`) entries implement these operations:

| Operation class       | Handler examples                           |
|-----------------------|--------------------------------------------|
| PSHL #imm, Dz         | CPU_DSP_PSHL_IMM                           |
| PSHA #imm, Dz         | CPU_DSP_PSHA_IMM                           |
| PMULS Sx, Sy, Dg      | CPU_DSP_PMULS_X0_Y0_PCLR (and 15 variants) |
| PMULS+PSUB            | CPU_DSP_PMULS_X0_Y0_PSUB (and 15 variants) |
| PMULS+PADD            | CPU_DSP_PMULS_X0_Y0_PADD (and 15 variants) |
| PSHL Sx, Sy, Dz       | CPU_DSP_PSHL_SX_SY_DZ                      |
| DCT PSHL              | CPU_DSP_DCT_PSHL_SX_SY_DZ                  |
| DCF PSHL              | CPU_DSP_DCF_PSHL_SX_SY_DZ                  |
| PCMP Sx, Sy           | CPU_DSP_PCMP_SX_SY                         |
| PSUB Sx, Sy, Dz       | CPU_DSP_PSUB_SX_SY_DZ                      |
| DCT PSUB              | CPU_DSP_DCT_PSUB_SY_SX_DZ                  |
| DCF PSUB              | CPU_DSP_DCF_PSUB_SY_SX_DZ                  |
| PABS Sx, Dz           | CPU_DSP_PABS_SX_DZ                         |
| PDEC Sx, Dz           | CPU_DSP_PDEC_SX_DZ                         |
| DCT PDEC/PABS         | CPU_DSP_DCT_PDEC_PABS_SX_DZ                |
| DCF PDEC/PABS         | CPU_DSP_DCF_PDEC_PABS_SX_DZ                |
| PCLR Dz               | CPU_DSP_PCLR_DZ                            |
| DCT PCLR              | CPU_DSP_DCT_PCLR_DZ                        |
| DCF PCLR              | CPU_DSP_DCF_PCLR_DZ                        |
| PSHA Sx, Sy, Dz       | CPU_DSP_PSHA_SX_SY_DZ                      |
| DCT PSHA              | CPU_DSP_DCT_PSHA_SX_SY_DZ                  |
| DCF PSHA              | CPU_DSP_DCF_PSHA_SX_SY_DZ                  |
| PAND Sx, Sy, Dz       | CPU_DSP_PAND_SX_SY_DZ                      |
| DCT PAND              | CPU_DSP_DCT_PAND_SX_SY_DZ                  |
| DCF PAND              | CPU_DSP_DCF_PAND_SX_SY_DZ                  |
| PRND Sx, Dz           | CPU_DSP_PRND_SX_DZ                         |
| PINC Sx, Dz           | CPU_DSP_PINC_SX_DZ                         |
| DCT PINC/PRND         | CPU_DSP_DCT_PINC_PRND_SX_DZ                |
| DCF PINC/PRND         | CPU_DSP_DCF_PINC_PRND_SX_DZ                |
| PDMSB/PSWAP Sx, Dz    | CPU_DSP_PDMSB_PSWAP_SX_DZ                  |
| DCT PDMSB/PSWAP       | CPU_DSP_DCT_PDMSB_PSWAP_SX_DZ              |
| DCF PDMSB/PSWAP       | CPU_DSP_DCF_PDMSB_PSWAP_SX_DZ              |
| PSUBC Sx, Sy, Dz      | CPU_DSP_PSUBC_SX_SY_DZ                     |
| PSUB Sx, Sy, Dz       | CPU_DSP_PSUB_SX_SY_DZ                      |
| DCT PSUB              | CPU_DSP_DCT_PSUB_SX_SY_DZ                  |
| DCF PSUB              | CPU_DSP_DCF_PSUB_SX_SY_DZ                  |
| PXOR Sx, Sy, Dz       | CPU_DSP_PXOR_SX_SY_DZ                      |
| DCT PXOR              | CPU_DSP_DCT_PXOR_SX_SY_DZ                  |
| DCF PXOR              | CPU_DSP_DCF_PXOR_SX_SY_DZ                  |
| PABS Sy, Dz           | CPU_DSP_PABS_SY_DZ                         |
| PDEC Sy, Dz           | CPU_DSP_PDEC_SY_DZ                         |
| DCT PDEC/PABS Sy      | CPU_DSP_DCT_PDEC_PABS_SY_DZ                |
| DCF PDEC/PABS Sy      | CPU_DSP_DCF_PDEC_PABS_SY_DZ                |
| PADDC Sx, Sy, Dz      | CPU_DSP_PADDC_SX_SY_DZ                     |
| PADD Sx, Sy, Dz       | CPU_DSP_PADD_SX_SY_DZ                      |
| DCT PADD              | CPU_DSP_DCT_PADD_SX_SY_DZ                  |
| DCF PADD              | CPU_DSP_DCF_PADD_SX_SY_DZ                  |
| POR Sx, Sy, Dz        | CPU_DSP_POR_SX_SY_DZ                       |
| DCT POR               | CPU_DSP_DCT_POR_SX_SY_DZ                   |
| DCF POR               | CPU_DSP_DCF_POR_SX_SY_DZ                   |
| PRND Sy, Dz           | CPU_DSP_PRND_SY_DZ                         |
| PINC Sy, Dz           | CPU_DSP_PINC_SY_DZ                         |
| DCT PINC/PRND Sy      | CPU_DSP_DCT_PINC_PRND_SY_DZ                |
| DCF PINC/PRND Sy      | CPU_DSP_DCF_PINC_PRND_SY_DZ                |
| PDMSB/PSWAP Sy, Dz    | CPU_DSP_PDMSB_PSWAP_SY_DZ                  |
| DCT PDMSB/PSWAP Sy    | CPU_DSP_DCT_PDMSB_PSWAP_SY_DZ              |
| DCF PDMSB/PSWAP Sy    | CPU_DSP_DCF_PDMSB_PSWAP_SY_DZ              |
| PNEG Sx, Dz           | CPU_DSP_PNEG_SX_DZ                         |
| DCT PNEG              | CPU_DSP_DCT_PNEG_SX_DZ                     |
| DCF PNEG              | CPU_DSP_DCF_PNEG_SX_DZ                     |
| PSTS MACH, Dz         | CPU_DSP_PSTS_MACH_DZ                       |
| DCT PSTS MACH         | CPU_DSP_DCT_PSTS_MACH_DZ                   |
| DCF PSTS MACH         | CPU_DSP_DCF_PSTS_MACH_DZ                   |
| PCOPY Sx, Dz          | CPU_DSP_PCOPY_SX_DZ                        |
| DCT PCOPY             | CPU_DSP_DCT_PCOPY_SX_DZ                    |
| DCF PCOPY             | CPU_DSP_DCF_PCOPY_SX_DZ                    |
| PSTS MACL, Dz         | CPU_DSP_PSTS_MACL_DZ                       |
| DCT PSTS MACL         | CPU_DSP_DCT_PSTS_MACL_DZ                   |
| DCF PSTS MACL         | CPU_DSP_DCF_PSTS_MACL_DZ                   |
| PNEG Sy, Dz           | CPU_DSP_PNEG_SY_DZ                         |
| DCT PNEG Sy           | CPU_DSP_DCT_PNEG_SY_DZ                     |
| DCF PNEG Sy           | CPU_DSP_DCF_PNEG_SY_DZ                     |
| PLDS Dz, MACH         | CPU_DSP_PLDS_DZ_MACH                       |
| DCT PLDS MACH         | CPU_DSP_DCT_PLDS_DZ_MACH                   |
| DCF PLDS MACH         | CPU_DSP_DCF_PLDS_DZ_MACH                   |
| PCOPY Sy, Dz          | CPU_DSP_PCOPY_SY_DZ                        |
| DCT PCOPY Sy          | CPU_DSP_DCT_PCOPY_SY_DZ                    |
| DCF PCOPY Sy          | CPU_DSP_DCF_PCOPY_SY_DZ                    |
| PLDS Dz, MACL         | CPU_DSP_PLDS_DZ_MACL                       |
| DCT PLDS MACL         | CPU_DSP_DCT_PLDS_DZ_MACL                   |
| DCF PLDS MACL         | CPU_DSP_DCF_PLDS_DZ_MACL                   |

### DCT / DCF (Decrement-Counter-True / -False)

DCT variants execute only if the repeat counter (RC) is non-zero
after decrementing.  DCF variants execute only if RC reaches zero.
These are used in zero-overhead loops set up by LDS Rn, RC + LDRS /
LDRE / LDRC.

### CPU_DSP_OPERATION Wrapper (libCPU73050 @ 0x28FD2)

```
1. Check SR.DSP (0x1000).  If 0, raise CPU_INVALID.
2. If (dword_BA900 & 0x10) && (dword_BA900 & 0x2000): dword_BA858 += 2.
   (Increments the repeat-loop PC when in a repeat block.)
3. Call qword_5F4190 (pre-processing).
4. Call CPU_DSPInstructionOperation -> fills 6 result-slot globals:
     dword_BA944 = dest reg 1 index (or 255 = no dest)
     dword_BA948 = value for dest 1
     dword_BA94C = guard value for dest 1 (only if dest is a0/a1)
     dword_BA950 = dest reg 2 index (or 255 = no dest)
     dword_BA954 = value for dest 2
     dword_BA958 = guard value for dest 2
5. Call CPU_DSPInstructionDouble -> parallel MOVX/MOVY memory access.
6. Writeback: for each dest slot, if index < 0x31 (49):
     - Write value to register at offset 8 * index
     - Set dirty flag at offset 8 * index + 4
     - If dest is 39 (a0) or 40 (a1), also write guard value to
       offset 8 * index + 16 and set its dirty flag.
```

---

## 5. MOVX / MOVY Double Memory Instructions (0xF4xx, 0xF5xx)

### Encoding
```
1111_01xx_xxxx_xxxx
  bit 10: 0 = MOVX (X-bus access), 1 = MOVY (Y-bus access)
  bits 9-8: address register pair selection (DSPDoubleRegAxy_Table / DSPDoubleRegAyx_Table)
  bits 7-4: source/dest DSP register selection (DSPDoubleRegDxy_Table)
  bits 3-0: addressing mode (similar to MOVS but for both buses)
```

### Memory Buses on SH7305

- X-bus: XRAM at 0xE5000000 (512 KB)
- Y-bus: YRAM at 0xE5010000 (512 KB, often aliased as 0xE5007000)

### Register Tables

```c
// DSPDoubleRegAxy_Table[4] @ 0xA04DD
db 4, 0, 5, 1       // Axy index 0-3 -> R4/R0/R5/R1

// DSPDoubleRegAyx_Table[4] @ 0xA04E1
db 6, 7, 2, 3       // Ayx index 0-3 -> R6/R7/R2/R3

// DSPDoubleRegDxy_Table[4] @ 0xA04E5
db 2Dh, 2Fh, 2Eh, 30h  // Dxy index 0-3 -> y0/m0/y1/m1
```

### Double Instruction Table (DSPDoubleInstr_Table @ 0xA02DD)

64 entries, dispatched by `(opcode >> 4) & 0x3F` (bits 4-9 of opcode).
The handlers combine X-bus and Y-bus memory accesses with various
addressing modes (direct, indexed, pre-decrement, post-increment).

Handler naming convention:
- `IAX`  = Index Address X-bus       (X-bus access only)
- `IAY`  = Index Address Y-bus       (Y-bus access only)
- `IAXY` = Index Address X+Y buses   (both buses, same address reg)
- `IAXYIX` = ... post-increment X-bus only
- `DAX`  = Direct Address X-bus
- `DAY`  = Direct Address Y-bus
- `DXY`  = Direct X+Y (both buses, no address modification)
- `DYX`  = same, Y-bus word first
- `NOPX` = no X-bus operation
- `NOPY` = no Y-bus operation

Example handlers from the table:
- `CPU_DSP_NOPX_NOPY`                 - no memory access (parallel op only)
- `CPU_DSP_MOVYW_IAYX_DYX`            - MOVY.W @Ay+Ix, Dy
- `CPU_DSP_MOVXW_IAXY_DXY`            - MOVX.W @Ax+Ix, Dx (and Y-bus too)
- `CPU_DSP_MOVXW_IAX_DX_MOVYW_IAY_DY` - parallel MOVX.W @Ax, Dx + MOVY.W @Ay, Dy
- `CPU_DSP_MOVXL_IAXY_DXY`            - MOVX.L @Ax+Ix, Dx (long version)

### Implementation Status

Stubbed as NOP for now.  MOVX/MOVY are only used in DSP filter code
(audio codecs, signal processing), not during OS boot.

---

## 6. DSP Register File

### Internal Index → RuK Register Name

| Index | Register | Description                          |
|-------|----------|--------------------------------------|
| 39    | a0       | Accumulator 0 (32-bit)               |
| 40    | a1       | Accumulator 1 (32-bit)               |
| 41    | a0g      | Accumulator 0 guard bits (8-bit sgn) |
| 42    | a1g      | Accumulator 1 guard bits             |
| 43    | x0       | X-bus data register 0                |
| 44    | x1       | X-bus data register 1                |
| 45    | y0       | Y-bus data register 0                |
| 46    | y1       | Y-bus data register 1                |
| 47    | m0       | Multiplier register 0                |
| 48    | m1       | Multiplier register 1                |

The libCPU73050 CPU state struct stores each register in an 8-byte
slot: 4 bytes for the value, 1 byte for the dirty flag, 3 bytes
padding.  The guard bits for A0/A1 are at offset +16 from the A0/A1
slot (i.e., at internal indices 41/42 in the parallel layout).

In RuK, all DSP registers are stored in `cpu.regs` dict with the
names above (no internal index indirection).

### Special Registers (not in the data reg table)

| Register | Description                              |
|----------|------------------------------------------|
| DSR      | DSP status register (dword_BA890)        |
| MACH     | MAC register high (dword_BA848)          |
| MACL     | MAC register low (dword_BA850)          |
| RS       | Repeat start address (dword_BA7E0 area) |
| RE       | Repeat end address                      |
| RC       | Repeat count                            |
| MOD      | DSP mode register (dword_BA900)         |

---

## 7. CPU_DSPInstructionOperation Case Map (Partial)

The full switch in CPU_DSPInstructionOperation (libCPU73050 @ 0x5DCC)
has 256 cases.  Here are the most common ones, mapped to their
operations:

| BYTE1(_EAX) | Operation             | Notes                              |
|--------------|-----------------------|------------------------------------|
| 0x00-0x07    | PSHL #imm, Dz         | bits 4-9 = shift amount            |
| 0x10-0x17    | PSHA #imm, Dz         | arithmetic shift by immediate      |
| 0x40-0x4F    | PMULS Sx, Sy, Dg+PCLR | 16 source-pair combos              |
| 0x60-0x6F    | PMULS Sx, Sy, Dg+PSUB | 16 source-pair combos              |
| 0x70-0x7F    | PMULS Sx, Sy, Dg+PADD | 16 source-pair combos              |
| 0x81         | PSHL Sx, Sy, Dz       |                                    |
| 0x84         | PCMP Sx, Sy           | compare, set SR.T                  |
| 0x85         | PSUB Sy, Sx, Dz       |                                    |
| 0x88-0x89    | PABS Sx, Dz           |                                    |
| 0x8A-0x8B    | PDEC Sx, Dz           |                                    |
| 0x8D         | PCLR Dz               |                                    |
| 0x8E-0x8F    | PDMSB/PSWAP Sx, Dz    |                                    |
| 0x91         | PSHA Sx, Sy, Dz       |                                    |
| 0x95         | PAND Sx, Sy, Dz       |                                    |
| 0x98-0x99    | PRND Sx, Dz           |                                    |
| 0x9A-0x9B    | PINC Sx, Dz           |                                    |
| 0x9D         | PSUBC Sx, Sy, Dz      |                                    |
| 0xA0         | PSUB Sx, Sy, Dz + carry |                                  |
| 0xA1         | PSUB Sx, Sy, Dz       |                                    |
| 0xA5         | PXOR Sx, Sy, Dz       |                                    |
| 0xA8-0xA9    | PNEG Sx, Dz           |                                    |
| 0xB0         | PADD Sx, Sy, Dz + carry |                                  |
| 0xB1         | PADD Sx, Sy, Dz       |                                    |
| 0xB5         | POR Sx, Sy, Dz        |                                    |
| 0xB8-0xB9    | PADDC Sx, Sy, Dz      |                                    |
| 0xBD         | PCOPY Sx, Dz          |                                    |
| 0xCD         | PSTS MACH, Dz         |                                    |
| 0xD9         | PSTS MACL, Dz         |                                    |
| 0xED         | PLDS Dz, MACH         |                                    |
| 0xFD         | PLDS Dz, MACL         |                                    |

DCT variants: 0x82, 0x86, 0x8A, 0x8E, 0x92, 0x96, 0x9A, 0x9E,
0xA2, 0xA6, 0xAA, 0xAE, 0xB2, 0xB6, 0xBA, 0xBE, 0xC2, 0xC6, 0xCA,
0xCE, 0xD2, 0xD6, 0xDA, 0xDE, 0xE2, 0xE6, 0xEA, 0xEE, 0xF2, 0xF6,
0xFA, 0xFE.

DCF variants: 0x83, 0x87, 0x8B, 0x8F, 0x93, 0x97, 0x9B, 0x9F,
0xA3, 0xA7, 0xAB, 0xAF, 0xB3, 0xB7, 0xBB, 0xBF, 0xC3, 0xC7, 0xCB,
0xCF, 0xD3, 0xD7, 0xDB, 0xDF, 0xE3, 0xE7, 0xEB, 0xEF, 0xF3, 0xF7,
0xFB, 0xFF.

---

## 8. Test Program (SigmaDelta2 from user)

The user provided this DSP test program (SigmaDelta2 audio codec):

```asm
! r4 - int32_t *state
! r5 - int16_t k[2]
! r6 - uint16_t sample

MOVS.L @R4+, A1     ! DSP-LS  (post-inc long load, mode 14)
shll16 r6           ! EX
MOVS.W @R5+, X0     ! DSP-LS  (post-inc word load, mode 12)
shlr2 r6            ! EX
MOVS.W @R5, X1      ! DSP-LS  (direct word load, mode 4)
mov.w 3f, r3        ! LS

ldrs 1f             ! LS  (set repeat start)
ldre 2f             ! LS  (set repeat end)
ldrc #32            ! CO  (set repeat count = 32)
lds r6, Y1          ! LS  (load Y1 from R6)

mov.w r3, @r5       ! LS
MOVS.L @R4+, A0     ! DSP-LS  (post-inc long load, mode 14)
MOVX.W @R5, Y0 NOPY ! DSP-LS  (MOVX with NOPY = no Y-bus op)
MOVS.L @R4+, M1     ! DSP-LS  (post-inc long load, mode 14)

! most DSP-CO sad
1: PSUB Y0, A1, Y0
   PSUB A1, Y1, Y0 PMULS X1, Y0, M0
   PADD A1, M0, Y0 PMULS X1, Y0, M0
   PADD A0, M0, A0 PMULS A1, X0, A1
   PADD A0, M1, M1
   DCT PCOPY Y0, A1 MOVX.W @R5, Y0 NOPY
   rotcl r0
2: nop

MOVS.L A1, @R4+     ! DSP-LS  (post-inc long store, mode 15)
mov.l r1, @r3       ! LS
MOVS.L A0, @R4+     ! DSP-LS  (post-inc long store, mode 15)
rts                 ! BR
MOVS.L M1, @R4      ! DSP-LS  (direct long store, mode 7)
```

This program exercises:
- All four post-increment long load/store modes (14, 15)
- The direct word load mode (4)
- The direct long store mode (7)
- PMULS, PSUB, PADD, PCOPY operations
- DCT (decrement-counter-true) variant
- MOVX.W with NOPY (no Y-bus operation)

---

## 9. Implementation Status (as of this commit)

| Component                    | Status      | Notes                              |
|------------------------------|-------------|------------------------------------|
| MOVS single memory (16 modes)| DONE        | All 16 modes implemented + tested  |
| MOVX / MOVY double memory    | STUBBED     | NOP for now                        |
| DSP operations (PADD etc.)   | STUBBED     | NOP for now, dispatcher structure  |
|                              |             | in place (CPU_DSP_OPERATION port)  |
| DCT / DCF variants           | NOT IMPL   | Need RC (repeat counter) modeling  |
| Repeat loop (LDS RC, LDRS,   | NOT IMPL   | Need RS/RE/RC register support     |
|   LDRE, LDRC)                |             |                                    |
| Guard bit (A0G/A1G) updates  | DONE        | Updated on MOVS.W loads to A0/A1   |
| SR.T updates from PCMP       | NOT IMPL   | Need DSP_SR_TSet call table        |

### Test Coverage

44 tests in `test_dsp_movs.py`:
- Encoding / dispatch (6 tests)
- Direct load/store modes 4-7 (10 tests)
- Pre-decrement modes 8-11 (4 tests)
- Post-increment modes 12-15 (6 tests)
- Indexed modes 0-3 (4 tests)
- All 4 As registers (1 test)
- All 10 Ds registers, word load (1 test)
- All 10 Ds registers, long load (1 test)
- SigmaDelta2 user example (2 tests: load + store sequences)
- DSP operation stub (3 tests)
- MOVX/MOVY stub (3 tests)
- SR.DSP gate (3 tests)

All 44 tests pass.

---

## 10. Files

| File                              | Purpose                              |
|-----------------------------------|--------------------------------------|
| `ruk/jcore/dsp.py`                | DSP instruction handlers             |
| `test_dsp_movs.py`                | MOVS + DSP operation tests           |
| `scratches/DSP_REFERENCE.md`      | This file                            |
| `upload/libCPU73050.dylib.c.txt`  | Source decomp of libCPU73050 (Mac)   |
| `upload/CPU73050.dll.txt`         | Source decomp of CPU73050.dll (Win)  |
