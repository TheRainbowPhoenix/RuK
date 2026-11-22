"""SH4AL-DSP support.

Every P-operation family the Sdsha decoder recognizes is implemented:
unary ops (PABS/PNEG/PDEC/PINC/PRND/PCOPY/PSWAP/PDMSB), two-source
arithmetic (PADD/PSUB/PSUBC/PADDC), logic (PAND/PXOR/POR), shifts
(PSHL/PSHA register and immediate forms), PCMP, PMULS, PSTS/PLDS,
PCLR, and the PADD/PSUB/PCLR ... PMULS bundles -- each with its base,
DCT and DCF variants. All semantics were differentially verified
against Sdsha.dll handler-by-handler (tools/compare_sdsha_pops.py,
20k+ cases, zero mismatches).

MOVS and X/Y moves use the extracted CPU73050 and Sdsha decoder tables.
The DSP repeat loop (LDRS/LDRE/LDRC + DSR.DC) lives in cpu.py; DCT/DCF
variants gate on DSR.DC here.
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
    None, None, None, None, None, 'a1', None, 'a0',
    'x0', 'x1', 'y0', 'y1', 'm0', 'a1g', 'm1', 'a0g',
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
# P-operation operand field tables (Sdsha/libCPU73050 DSPOperation* tables)
# ============================================================================

# Dz (bits 3:0) via DSPOperationDataReg_Table; 0 entries are reserved fields.
DSP_DZ_TABLE = (None, None, None, None, None, 'a1', None, 'a0',
                'x0', 'x1', 'y0', 'y1', 'm0', None, 'm1', None)

# Sx operand (bits 7:6) for PADD/PSUB/PCMP/PSHL/PSHA and the PMULS bundles.
# Accumulator sources carry their guard bits into the 40-bit result.
DSP_SXLOAD_TABLE = ('x0', 'x1', 'a0', 'a1')

# Sy operand (bits 5:4) for the same families: DSPOpLoadSYRegCall_Table.
# For PSHL/PSHA this register holds the signed shift count.
DSP_SYLOAD_TABLE = ('y0', 'y1', 'm0', 'm1')

# PMULS Se (bits 11:10) / Sf (bits 9:8) for standalone PMULS and bundles.
DSP_SE_TABLE = ('x0', 'x1', 'y0', 'a1')
DSP_SF_TABLE = ('y0', 'y1', 'x0', 'a1')

# PMULS Dg (bits 3:2).
DSP_DG_TABLE = ('m0', 'm1', 'a0', 'a1')

# PADD/PSUB Dz in bundles and PCLR Du (bits 1:0): DSPOperationDUReg_Table.
DSP_DU_TABLE = ('y0', 'm0', 'a0', 'a1')


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
# 40-bit accumulator helpers (value32 : guard8)
# ============================================================================

def _dsp_load40(cpu, name):
    """Load a DSP register as a 40-bit (value, guard) pair.

    Per libCPU73050 DSPOpLoadSx: accumulators contribute their A0G/A1G
    guard byte; 32-bit registers contribute the sign extension of their
    32-bit value as guard.
    """
    value = cpu.regs[name] & 0xFFFFFFFF
    if name in ('a0', 'a1'):
        guard = cpu.regs[name + 'g'] & 0xFF
    else:
        guard = 0xFF if value & 0x80000000 else 0
    return value, guard


def _dsp_store40(cpu, name, value, guard):
    """Write a 40-bit (value, guard) pair to a DSP register."""
    cpu.regs[name] = _u32(value)
    if name in ('a0', 'a1'):
        cpu.regs[name + 'g'] = _sext8_to_32(guard & 0xFF)


def _dsp_sat40(value, guard, saturate):
    """Clamp a 40-bit result into 32 bits when SR.S (saturate) is set.

    Returns (value, guard, overflow) where overflow reports a 40-bit
    value that does not fit the signed 32-bit range.  The saturation
    direction follows bit 39 (guard bit 7); without SR.S the wrapped
    32-bit value is kept, exactly as the hardware does.
    """
    overflow = guard != (0xFF if value & 0x80000000 else 0)
    if not (overflow and saturate):
        return value, guard, overflow
    if guard & 0x80:
        return 0x80000000, 0xFF, True
    return 0x7FFFFFFF, 0, True


def _dsp_write_flags(cpu, carry, negative, zero, overflow, gt=0, ge=0,
                     dc_override=None, mirror_overflow=None, or_merge=False):
    """Update DSR and SR.T after an unconditional P-operation.

    The mask-selected flag lands in DSR.DC and N/Z/OF/GT in bits 4-7;
    with the old DSR bit 8 set the same selector also drives SR.T and
    the mirrors in bits 12-15.  Everything outside bits 0 and 4-7 is
    preserved.  Conditional (DCT/DCF) forms skip this entirely.  gt/ge
    follow per-family rules: arithmetic results use the signed 40-bit
    comparison, shifts force both to zero.

    PSHA's shifter ORs its flag contributions into DSR without clearing
    the previous N/Z/OF bits (or_merge); the arithmetic and unary
    families replace bits 0 and 4-7 instead.
    """
    sr = cpu.regs['sr']
    old_dsr = cpu.regs['dsr']
    effective_overflow = int(overflow and not (sr & 2))
    choices = (carry, negative, zero, effective_overflow, gt, ge, 0, 0)
    dc = choices[(old_dsr >> 1) & 7]
    if dc_override is not None:
        # PADDC/PSUBC chain the carry through DSR.DC regardless of mask.
        dc = dc_override
    dsr = ((effective_overflow << 4) | (negative << 5) | (zero << 6) |
           (gt << 7) | dc)
    dsr |= old_dsr & ~0x1 if or_merge else old_dsr & ~0xF1
    if old_dsr & 0x100:
        selector = (old_dsr >> 9) & 7
        t_bit = choices[selector]
        if selector == 3 and overflow and (sr & 2):
            t_bit = 1
        cpu.regs['sr'] = (sr & ~1) | t_bit
        mirror = overflow if mirror_overflow is None else mirror_overflow
        dsr |= ((int(mirror) << 12) | (negative << 13) |
                (zero << 14) | (gt << 15))
    cpu.regs['dsr'] = dsr


def _dsp_psha_clamp(cpu, value, guard, lost, exact):
    """PSHA saturation and overflow.

    SR.S clamps when the truncated result's guard byte disagrees with
    its value sign, or when a left shift lost bits into a negative view
    (either the truncated guard or the true product being negative);
    the clamp direction follows the true sign of the shift product.

    DSR.OF needs a shift to have happened and reports the guard/sign
    mismatch, plus a left shift's lost bits while SR.S is clear.  The
    pre-clamp mismatch also drives the DSR bit 12 mirror.
    """
    bit7_mismatch = bool(guard & 0x80) != bool(value & 0x80000000)
    byte_mismatch = guard != (0xFF if value & 0x80000000 else 0)
    saturate = bool(cpu.regs['sr'] & 2)
    if saturate and (byte_mismatch or (lost and (exact < 0 or guard & 0x80))):
        value = 0x80000000 if exact < 0 else 0x7FFFFFFF
        guard = 0xFF if exact < 0 else 0
    overflow = (bit7_mismatch or
                (byte_mismatch and not saturate) or
                (lost and (value != 0 or not saturate)))
    return value, guard, overflow, byte_mismatch or (lost and saturate)


def _dsp_arith_gt_ge(value, guard):
    """PADD/PSUB GT/GE: signed 40-bit comparison of the result."""
    result40 = (guard << 32) | (value & 0xFFFFFFFF)
    if result40 & (1 << 39):
        result40 -= 1 << 40
    return int(result40 > 0), int(result40 >= 0)


def _dsp_dct_dcf_active(cpu, conditional):
    """Gate a DCT/DCF conditional P-op on DSR.DC (bit 0).

    conditional 1 = DCT (executes while the repeat loop is live),
    conditional 2 = DCF (executes once it has finished).
    """
    dc = cpu.regs['dsr'] & 1
    if (conditional == 1 and not dc) or (conditional == 2 and dc):
        return False
    return True


# ============================================================================
# Encoding predicates
# ============================================================================

# SR bit 12 enables DSP instructions on the supported DSP personality.
SR_DSP_BIT = 0x1000


def is_dsp_instruction(op_val: int) -> bool:
    """Recognize implemented DSP prefixes, independent of SR.DSP."""
    return (
        op_val == 0xF800
        or (op_val & 0xFC00) == 0xF000
        or (
            (op_val & 0xFC00) == 0xF400
            and DSP_SINGLE_DATA_REG_TABLE[(op_val >> 4) & 15] is not None
        )
    )


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
    if not _sr_dsp_is_set(cpu):
        return False
    if op_val == 0xF800:
        return _execute_standalone_pop(cpu, cpu.mem.read16(_u32(cpu.pc + 2)))
    if (op_val & 0xFC00) == 0xF000:
        _parallel_moves(cpu, op_val)
        cpu.pc = _u32(cpu.pc + 2)
        return True
    if is_dsp_instruction(op_val):
        return _handle_movs(cpu, op_val)
    return False


def _execute_standalone_pop(cpu, word):
    """Execute validated F800 P-operations; return False for unsupported words."""
    # PCOPY Sx/Sy,Dz and its conditional variants. Guard bits participate
    # in the 40-bit value when the source is an accumulator.
    opcode = word >> 8
    unary_bases = {
        0x89: ('dec', True), 0xA9: ('dec', False),
        0x99: ('inc', True), 0xB9: ('inc', False),
        0x9D: ('swap', True), 0xBD: ('swap', False),
        0xD9: ('copy', True), 0xF9: ('copy', False),
        0xC9: ('neg', True), 0xE9: ('neg', False),
    }
    unary_base = next((base for base in unary_bases if base <= opcode <= base + 2), None)
    # PABS and PRND conditional opcodes share their high byte with PDEC/PINC;
    # bit 4 (Sx) or bit 6 (Sy) distinguishes the forms.
    special = {
        0x88: ('abs', True, 0), 0xA8: ('abs', False, 0),
        0x98: ('round', True, 0), 0xB8: ('round', False, 0),
    }
    for base, operation, x_side in ((0x8A, 'abs', True), (0xAA, 'abs', False),
                                    (0x9A, 'round', True), (0xBA, 'round', False)):
        marker = 0x10 if x_side else 0x40
        mask = 0x30 if x_side else 0xC0
        if opcode in (base, base + 1) and word & mask == marker:
            special[opcode] = (operation, x_side, opcode - base + 1)
    if opcode in special or unary_base is not None:
        if opcode in special:
            operation, x_source, conditional = special[opcode]
        else:
            operation, x_source = unary_bases[unary_base]
            conditional = opcode - unary_base
        selector_mask = 0x30 if x_source else 0xC0
        if operation == 'swap' and word & selector_mask == 0:
            operation = 'dmsb'
        marker_form = operation == 'swap' or (operation in ('abs', 'round') and conditional)
        selector_value = (0x10 if x_source else 0x40) if marker_form else 0
        if word & selector_mask != selector_value:
            return False
        dest = (None, None, None, None, None, 'a1', None, 'a0',
                'x0', 'x1', 'y0', 'y1', 'm0', None, 'm1', None)[word & 15]
        if dest is None:
            return False
        dsr = cpu.regs['dsr']
        if (conditional == 1 and not (dsr & 1)) or (conditional == 2 and dsr & 1):
            cpu.pc = _u32(cpu.pc + 4)
            return True
        source = (('x0', 'x1', 'a0', 'a1')[(word >> 6) & 3] if x_source
                  else ('y0', 'y1', 'm0', 'm1')[(word >> 4) & 3])
        value = cpu.regs[source]
        guard = ((cpu.regs[source + 'g'] & 0xFF) if source in ('a0', 'a1')
                 else (0xFF if value & 0x80000000 else 0))
        carry = 0
        original_guard = guard
        if operation == 'dmsb':
            bits = (guard << 32) | value
            different = bits ^ (0xFFFFFFFFFF if guard & 0x80 else 0)
            value = _u32((30 - (different.bit_length() - 1)) << 16)
            guard = 0xFF if value & 0x80000000 else 0
        elif operation == 'swap':
            value = _u32((value << 16) | (value >> 16))
            guard = 0xFF if value & 0x80000000 else 0
        elif operation in ('inc', 'dec', 'round'):
            previous = value
            delta = {'inc': 0x10000, 'dec': -0x10000, 'round': 0x8000}[operation]
            value = _u32(value + delta)
            old_sign = bool(previous & 0x80000000)
            new_sign = bool(value & 0x80000000)
            carry = int(old_sign and not new_sign if operation != 'dec'
                        else not old_sign and new_sign)
            if carry:
                guard = (guard + (-1 if operation == 'dec' else 1)) & 0xFF
            value &= 0xFFFF0000
        elif operation == 'neg' or (operation == 'abs' and guard & 0x80):
            previous = value
            value = _u32(-value)
            if operation == 'abs':
                carry = int(previous != 0)
            else:
                carry = int(bool(previous & 0x80000000) or bool(value & 0x80000000))
            guard = (-guard - carry) & 0xFF
        overflow = guard != (0xFF if value & 0x80000000 else 0)
        if operation in ('abs', 'neg') and original_guard & 0x80 and guard & 0x80:
            overflow = True
        if operation == 'swap':
            overflow = False
        if overflow and (cpu.regs['sr'] & 2):
            sign_guard = original_guard if operation in ('inc', 'dec', 'round') else guard
            if operation == 'abs':
                sign_guard = 0
            elif operation == 'neg':
                sign_guard = 0 if original_guard & 0x80 else 0x80
            value = 0x80000000 if sign_guard & 0x80 else 0x7FFFFFFF
            guard = 0xFF if sign_guard & 0x80 else 0
        cpu.regs[dest] = value
        if dest in ('a0', 'a1'):
            cpu.regs[dest + 'g'] = _sext8_to_32(guard)
        if conditional == 0:
            negative = int(bool(guard & 0x80))
            zero = int(guard == 0 and value == 0)
            signed_overflow = 0
            if operation == 'abs':
                signed_overflow = negative
            elif operation == 'neg':
                signed_overflow = int(bool(original_guard & 0x80) and negative)
            elif operation in ('inc', 'round'):
                signed_overflow = int(not (original_guard & 0x80) and negative)
            elif operation == 'dec':
                signed_overflow = int(bool(original_guard & 0x80) and not negative)
            ge = int(not (negative ^ signed_overflow))
            gt = int(ge and not zero)
            effective_overflow = int(overflow and not (cpu.regs['sr'] & 2))
            choices = (carry, negative, zero, effective_overflow, gt, ge, 0, 0)
            dc = choices[(dsr >> 1) & 7]
            dsr = ((dsr & ~0xF1) | (effective_overflow << 4) |
                   (negative << 5) | (zero << 6) | (gt << 7) | dc)
            if dsr & 0x100:
                selector = (dsr >> 9) & 7
                t_bit = choices[selector]
                if selector == 3 and overflow and (cpu.regs['sr'] & 2):
                    t_bit = 1
                cpu.regs['sr'] = (cpu.regs['sr'] & ~1) | t_bit
                dsr |= ((int(overflow) << 12) | (negative << 13) |
                        (zero << 14) | (gt << 15))
            cpu.regs['dsr'] = dsr
        cpu.pc = _u32(cpu.pc + 4)
        return True

    # PCLR Dz and its conditional forms (Sdsha handler 0x100308f0).
    opcode = word >> 8
    if opcode in (0x8D, 0x8E, 0x8F):
        dest = (None, None, None, None, None, 'a1', None, 'a0',
                'x0', 'x1', 'y0', 'y1', 'm0', None, 'm1', None)[word & 15]
        if dest is None or word & 0xF0:
            return False
        dc = cpu.regs['dsr'] & 1
        if (opcode == 0x8E and not dc) or (opcode == 0x8F and dc):
            cpu.pc = _u32(cpu.pc + 4)
            return True
        cpu.regs[dest] = 0
        if dest in ('a0', 'a1'):
            cpu.regs[dest + 'g'] = 0
        if opcode == 0x8D:
            dsr = cpu.regs['dsr']
            condition = int(((dsr >> 1) & 7) in (2, 5))
            dsr = (dsr & ~0xF1) | 0x40 | condition
            if dsr & 0x100:
                selector = (dsr >> 9) & 7
                cpu.regs['sr'] = (cpu.regs['sr'] & ~1) | int(selector in (2, 5))
                dsr |= 0x4000
            cpu.regs['dsr'] = dsr
        cpu.pc = _u32(cpu.pc + 4)
        return True

    # PSTS MACH/MACL,Dz and PLDS Dz,MACH/MACL, with DCT/DCF.
    opcode = word >> 8
    mac_base = next((base for base in (0xCD, 0xDD, 0xED, 0xFD)
                     if base <= opcode <= base + 2), None)
    if mac_base is not None:
        dest = (None, None, None, None, None, 'a1', None, 'a0',
                'x0', 'x1', 'y0', 'y1', 'm0', None, 'm1', None)[word & 15]
        if dest is None or word & 0xF0:
            return False
        dc = cpu.regs['dsr'] & 1
        if (opcode == mac_base + 1 and not dc) or (opcode == mac_base + 2 and dc):
            cpu.pc = _u32(cpu.pc + 4)
            return True
        mac = 'mach' if mac_base in (0xCD, 0xED) else 'macl'
        if mac_base in (0xED, 0xFD):
            cpu.regs[mac] = cpu.regs[dest]
        else:
            value = cpu.regs[mac]
            cpu.regs[dest] = value
            if dest in ('a0', 'a1'):
                cpu.regs[dest + 'g'] = 0xFFFFFFFF if value & 0x80000000 else 0
        cpu.pc = _u32(cpu.pc + 4)
        return True

    # Sdsha logical operations and their DCT / DCF forms.
    opcode = word >> 8
    logical_base = next((base for base in (0x95, 0xA5, 0xB5)
                         if base <= opcode <= base + 2), None)
    if logical_base is not None:
        dest = (None, None, None, None, None, 'a1', None, 'a0',
                'x0', 'x1', 'y0', 'y1', 'm0', None, 'm1', None)[word & 15]
        if dest is None:
            return False
        dc = cpu.regs['dsr'] & 1
        if (opcode == logical_base + 1 and not dc) or (opcode == logical_base + 2 and dc):
            cpu.pc = _u32(cpu.pc + 4)
            return True
        sx = ('x0', 'x1', 'a0', 'a1')[(word >> 6) & 3]
        sy = ('y0', 'y1', 'm0', 'm1')[(word >> 4) & 3]
        x_value, y_value = cpu.regs[sx], cpu.regs[sy]
        if logical_base == 0x95:
            value = x_value & y_value
        elif logical_base == 0xA5:
            value = x_value ^ y_value
        else:
            value = x_value | y_value
        value &= 0xffff0000
        cpu.regs[dest] = value
        if dest in ('a0', 'a1'):
            cpu.regs[dest + 'g'] = 0
        if opcode == logical_base:
            negative = int(bool(value & 0x80000000))
            zero = int(value == 0)
            dsr = cpu.regs['dsr']
            condition = (0, negative, zero, 0, 0, 0, 0, 0)[(dsr >> 1) & 7]
            dsr = (dsr & ~0xf1) | (negative << 5) | (zero << 6) | condition
            if dsr & 0x100:
                selector = (dsr >> 9) & 7
                if selector < 3:
                    t_bit = (0, negative, zero)[selector]
                    cpu.regs['sr'] = (cpu.regs['sr'] & ~1) | t_bit
                dsr |= (negative << 13) | (zero << 14)
            cpu.regs['dsr'] = dsr
        cpu.pc = _u32(cpu.pc + 4)
        return True

    # PCMP Sx,Sy (bits 3:0 are a reserved field and must be zero).
    opcode = word >> 8
    if opcode == 0x84:
        return _dsp_pcmp(cpu, word)

    # PADD / PSUB families and their DCT / DCF forms.  Each returns
    # False for reserved Dz fields so the caller treats the word as an
    # undecodable P-op, like the real decoder does.
    if 0xB0 <= opcode <= 0xB3 or 0xA0 <= opcode <= 0xA3 or 0x85 <= opcode <= 0x87:
        return _dsp_padd_psub(cpu, word)

    # PSHL / PSHA with a register-held shift count (and DCT / DCF).
    if 0x81 <= opcode <= 0x83:
        return _dsp_pshl_psha(cpu, word, arithmetic=False)
    if 0x91 <= opcode <= 0x93:
        return _dsp_pshl_psha(cpu, word, arithmetic=True)

    # PSHL / PSHA with an immediate shift count.
    if opcode <= 0x07:
        return _dsp_shift_imm(cpu, word, arithmetic=False)
    if 0x10 <= opcode <= 0x17:
        return _dsp_shift_imm(cpu, word, arithmetic=True)

    # CPU_DSPInstructionOperation cases 40-4f, PMULS Se,Sf,Dg -- standalone,
    # plus the PCLR Du PMULS / PSUB ... PMULS / PADD ... PMULS bundles that
    # share the multiply with a second parallel operation.
    if (word & 0xf000) in (0x4000, 0x6000, 0x7000):
        top = word >> 12
        if top == 0x4 and (word & 0x00f3) == 0:
            se = DSP_SE_TABLE[(word >> 10) & 3]
            sf = DSP_SF_TABLE[(word >> 8) & 3]
            product, product_guard = _dsp_pmuls_product(cpu, se, sf)
            dg = DSP_DG_TABLE[(word >> 2) & 3]
            _dsp_store40(cpu, dg, product, product_guard)
            cpu.pc = _u32(cpu.pc + 4)
            return True
        if top == 0x4 and (word & 0x00f0) == 0x0010:
            # PCLR Du PMULS Se,Sf,Dg (Sdsha handler 0x100309d0): Du is
            # cleared while the multiply commits in parallel.
            se = DSP_SE_TABLE[(word >> 10) & 3]
            sf = DSP_SF_TABLE[(word >> 8) & 3]
            product, product_guard = _dsp_pmuls_product(cpu, se, sf)
            du = DSP_DU_TABLE[word & 3]
            dg = DSP_DG_TABLE[(word >> 2) & 3]
            _dsp_store40(cpu, dg, product, product_guard)
            _dsp_store40(cpu, du, 0, 0)
            # The cleared Du drives the flags, like a standalone PCLR.
            _dsp_write_flags(cpu, 0, 0, 1, False, *_dsp_arith_gt_ge(0, 0))
            cpu.pc = _u32(cpu.pc + 4)
            return True
        if top in (0x6, 0x7):
            # PSUB/PADD Sx,Sy,Du PMULS Se,Sf,Dg (Sdsha 0x10033670/0x100302b0).
            se = DSP_SE_TABLE[(word >> 10) & 3]
            sf = DSP_SF_TABLE[(word >> 8) & 3]
            product, product_guard = _dsp_pmuls_product(cpu, se, sf)
            result, result_guard, carry, _ = _dsp_add_sub40(
                cpu, word, subtract=(top == 0x6), with_carry=False)
            value, guard, overflow = _dsp_sat40(
                result, result_guard, bool(cpu.regs['sr'] & 2))
            du = DSP_DU_TABLE[word & 3]
            dg = DSP_DG_TABLE[(word >> 2) & 3]
            # Unlike every other PADD/PSUB form, the ADD bundle does not
            # keep a half-carried guard byte: without SR.S a mismatched
            # guard collapses to the sign of the value.
            if top == 0x7 and overflow and not cpu.regs['sr'] & 2:
                guard = 0xFF if value & 0x80000000 else 0
                overflow = False
            negative = int(bool(guard & 0x80))
            zero = int(guard == 0 and value == 0)
            gt, ge = _dsp_arith_gt_ge(value, guard)
            # Sdsha commits the product before the PADD/PSUB part, so a
            # shared DU/DG register ends up holding the add/sub result.
            _dsp_store40(cpu, dg, product, product_guard)
            _dsp_store40(cpu, du, value, guard)
            _dsp_write_flags(cpu, carry, negative, zero, overflow, gt, ge)
            cpu.pc = _u32(cpu.pc + 4)
            return True
    return False


# ============================================================================
# P-operation family helpers (semantics per Sdsha.dll, cross-checked
# against libCPU73050 CPU_DSPInstructionOperation)
# ============================================================================

def _dsp_pmuls_product(cpu, se, sf):
    """PMULS: 2 * sext16(HIWORD(Se)) * sext16(HIWORD(Sf)) as a 40-bit pair.

    The true product fits 33 bits, so the guard byte is the sign of the
    33-bit value (Sdsha keeps bit 32 even when the low half wraps, e.g.
    (-0x8000) * (-0x8000) = +0x80000000 with a positive guard).  With
    SR.S the +2^31 case saturates to 0x7FFFFFFF.
    """
    a = _i16(cpu.regs[se] >> 16)
    b = _i16(cpu.regs[sf] >> 16)
    product = 2 * a * b
    if product == 0x80000000 and cpu.regs['sr'] & 2:
        product = 0x7FFFFFFF
    value = _u32(product)
    guard = 0xFF if product < 0 else 0
    return value, guard


def _dsp_add_sub40(cpu, word, subtract, reversed_sources=False,
                   with_carry=False):
    """PADD/PSUB/PADDC/PSUBC 40-bit arithmetic.

    Sources: Sx (bits 7:6) and Sy (bits 5:4) via the loadable-source
    tables; accumulators contribute their guard bytes.  The carry input
    for PADDC/PSUBC is DSR.DC (bit 0).  Returns (value, guard, carry,
    signed_overflow): carry is the unsigned carry/borrow out of bit 31
    and signed_overflow the 32-bit signed overflow, both feeding DSR.
    """
    if subtract and reversed_sources:
        # PSUB Sy,Sx,Dz: Sy first, Sx second (fields swap tables).
        a_name = DSP_SYLOAD_TABLE[(word >> 4) & 3]
        b_name = DSP_SXLOAD_TABLE[(word >> 6) & 3]
    else:
        a_name = DSP_SXLOAD_TABLE[(word >> 6) & 3]
        b_name = DSP_SYLOAD_TABLE[(word >> 4) & 3]
    a_value, a_guard = _dsp_load40(cpu, a_name)
    b_value, b_guard = _dsp_load40(cpu, b_name)
    dc = (cpu.regs['dsr'] & 1) if with_carry else 0

    if subtract:
        a40 = (a_guard << 32) | a_value
        b40 = (b_guard << 32) | b_value
        if a40 & (1 << 39):
            a40 -= 1 << 40
        if b40 & (1 << 39):
            b40 -= 1 << 40
        result = (a40 - b40 - dc) & ((1 << 40) - 1)
        value = result & 0xFFFFFFFF
        guard = (result >> 32) & 0xFF
        carry = int(a_value < b_value + dc)
        signed_overflow = int(
            bool(a_value ^ b_value) and bool((a_value ^ value) & 0x80000000))
    else:
        low = a_value + b_value + dc
        carry_low = low >> 32
        value = _u32(low)
        guard = (a_guard + b_guard + carry_low) & 0xFF
        carry = int(carry_low)
        signed_overflow = int(
            bool(~(a_value ^ b_value) & (a_value ^ value) & 0x80000000))
    return value, guard, carry, signed_overflow


def _dsp_padd_psub(cpu, word):
    """PADD/PSUB/PADDC/PSUBC Sx,Sy,Dz (opcode + 0/1/2 for base/DCT/DCF).

    opcode bases: 0xB1 PADD, 0xB0 PADDC, 0xA1 PSUB, 0xA0 PSUBC and
    0x85 PSUB Sy,Sx (source tables swapped).  Conditional forms
    saturate (SR.S) but leave DSR and SR.T untouched, like every
    DCT/DCF variant.
    """
    opcode = word >> 8
    # PADD (0xB1) and PSUB (0xA1) carry the DCT/DCF forms as base+1/+2;
    # PADDC (0xB0) and PSUBC (0xA0) are unconditional carry-chaining ops.
    if 0xB1 <= opcode <= 0xB3:
        base, subtract, reversed_sources, with_carry = 0xB1, False, False, False
    elif opcode == 0xB0:
        base, subtract, reversed_sources, with_carry = 0xB0, False, False, True
    elif 0xA1 <= opcode <= 0xA3:
        base, subtract, reversed_sources, with_carry = 0xA1, True, False, False
    elif opcode == 0xA0:
        base, subtract, reversed_sources, with_carry = 0xA0, True, False, True
    else:  # 0x85..0x87: PSUB Sy,Sx,Dz (+ DCT/DCF)
        base, subtract, reversed_sources, with_carry = 0x85, True, True, False
    conditional = opcode - base
    if conditional and not _dsp_dct_dcf_active(cpu, conditional):
        cpu.pc = _u32(cpu.pc + 4)
        return True
    dest = DSP_DZ_TABLE[word & 15]
    if dest is None:
        return False
    value, guard, carry, _ = _dsp_add_sub40(
        cpu, word, subtract=subtract, reversed_sources=reversed_sources,
        with_carry=with_carry)
    value, guard, overflow = _dsp_sat40(value, guard, bool(cpu.regs['sr'] & 2))
    negative = int(bool(guard & 0x80))
    zero = int(guard == 0 and value == 0)
    gt, ge = _dsp_arith_gt_ge(value, guard)
    _dsp_store40(cpu, dest, value, guard)
    if conditional == 0:
        _dsp_write_flags(cpu, carry, negative, zero, overflow, gt, ge,
                         dc_override=carry if with_carry else None)
    cpu.pc = _u32(cpu.pc + 4)
    return True


def _dsp_pcmp(cpu, word):
    """PCMP Sx,Sy (Sdsha handler 0x10030a40): SR.T = Sx > Sy (40-bit
    signed compare); no DSR update, no writeback.  Bits 3:0 are a
    reserved field and must be zero."""
    if word & 0xF:
        return False
    a_name = DSP_SXLOAD_TABLE[(word >> 6) & 3]
    b_name = DSP_SYLOAD_TABLE[(word >> 4) & 3]
    a_value, a_guard = _dsp_load40(cpu, a_name)
    b_value, b_guard = _dsp_load40(cpu, b_name)
    a40 = (a_guard << 32) | a_value
    b40 = (b_guard << 32) | b_value
    if a40 & (1 << 39):
        a40 -= 1 << 40
    if b40 & (1 << 39):
        b40 -= 1 << 40
    if a40 > b40:
        cpu.regs['sr'] |= 1
    else:
        cpu.regs['sr'] &= ~1 & 0xFFFFFFFF
    cpu.pc = _u32(cpu.pc + 4)
    return True


def _dsp_shift16(value16, amount):
    """PSHL barrel shifter on a 16-bit value (Sdsha handler 0x10032ca0).

    amount is the signed 6-bit shift count.  Positive counts shift left
    with the last bit shifted out as carry; negative counts (bit 5 set)
    shift logically right.  Counts of +-16 return zero with the boundary
    bit as carry; counts beyond +-16 are rejected. Returns
    (value16, carry), or None for an unsupported count.
    """
    carry = 0
    if amount & 0x20:
        n = 32 - (amount & 0x1F)
        if n == 16:
            carry = value16 >> 15
            value16 = 0
        elif n > 16:
            return None
        else:
            carry = (value16 >> (n - 1)) & 1
            value16 = (value16 >> n) & 0xFFFF
    elif amount == 16:
        carry = value16 & 1
        value16 = 0
    elif amount > 16:
        return None
    elif amount:
        carry = (value16 << amount >> 16) & 1
        value16 = (value16 << amount) & 0xFFFF
    return value16, carry


def _dsp_psha_pair(pair, amount):
    """PSHA 40-bit pair shift (Sdsha handler 0x10032700).

    pair is (guard << 32) | value; amount is the encoded 7-bit count.
    Positive counts above 32 are rejected; negative counts down to -64
    follow the reference handler's guard-byte behavior.
    Returns (value, guard, carry, lost, exact) where lost reports bits
    pushed past bit 39 and exact is the untruncated mathematical shift
    result whose sign selects the saturation direction.
    """
    if amount & 0x40:
        n = 64 - (amount & 0x3F)
        signed = pair - (1 << 40) if pair & (1 << 39) else pair
        exact = signed >> n
        if n == 32:
            # Right by 32: the sign-extended guard byte becomes the
            # whole result; the carry reflects the old value sign.
            guard = (pair >> 32) & 0xFF
            value = pair & 0xFFFFFFFF
            carry = int(bool(value & 0x80000000))
            sext = guard - (1 << 8) if guard & 0x80 else guard
            return sext & 0xFFFFFFFF, (0xFF if guard & 0x80 else 0), \
                carry, False, sext
        guard = (pair >> 32) & 0xFF
        if n > 32:
            # Right by 33..64: only the guard byte survives, shifted
            # with x86 count masking (a count of 32 shifts by zero).
            shift = (n - 32) & 31
            sext = guard - (1 << 8) if guard & 0x80 else guard
            value = (sext >> shift) & 0xFFFFFFFF
            carry = (sext >> (shift - 1)) & 1 if shift else 0
            result = value - (1 << 32) if value & 0x80000000 else value
            return value, (0xFF if guard & 0x80 else 0), carry, \
                False, result
        carry = (pair >> (n - 1)) & 1
        return exact & 0xFFFFFFFF, (exact >> 32) & 0xFF, carry, False, exact
    if amount == 0:
        exact = pair - (1 << 40) if pair & (1 << 39) else pair
        return pair & 0xFFFFFFFF, (pair >> 32) & 0xFF, 0, False, exact
    if amount <= 32:
        signed = pair - (1 << 40) if pair & (1 << 39) else pair
        exact = signed << amount
        carry = (exact >> 32) & 1
        lost = int(not (-(1 << 39) <= exact < (1 << 39)))
        return exact & 0xFFFFFFFF, (exact >> 32) & 0xFF, carry, lost, exact
    return None


def _dsp_load_pair(cpu, name):
    """(value, guard) -> 40-bit pair for a DSP register source."""
    value, guard = _dsp_load40(cpu, name)
    return (guard << 32) | value


def _dsp_pshl_psha(cpu, word, arithmetic):
    """PSHL/PSHA Sx,Sy,Dz (opcode 0x81/0x91 + 1/2 for DCT/DCF).

    PSHL shifts the upper halfword of Sx and clears the guard byte;
    PSHA arithmetically shifts the full 40-bit Sx.  The shift count is
    the signed 6-bit (PSHL) / 7-bit (PSHA) upper halfword of Sy, read
    from the Y0/Y1/M0/M1 set.  Conditional forms neither touch DSR
    nor saturate.
    """
    opcode = word >> 8
    base = 0x91 if arithmetic else 0x81
    conditional = opcode - base
    if conditional and not _dsp_dct_dcf_active(cpu, conditional):
        cpu.pc = _u32(cpu.pc + 4)
        return True
    dest = DSP_DZ_TABLE[word & 15]
    if dest is None:
        return False
    src = DSP_SXLOAD_TABLE[(word >> 6) & 3]
    count_reg = DSP_SYLOAD_TABLE[(word >> 4) & 3]
    raw_amount = (cpu.regs[count_reg] >> 16) & (0x7F if arithmetic else 0x3F)
    if arithmetic:
        shifted = _dsp_psha_pair(_dsp_load_pair(cpu, src), raw_amount)
        if shifted is None:
            return False
        value, guard, carry, lost, exact = shifted
        value, guard, overflow, mirror = _dsp_psha_clamp(
            cpu, value, guard, lost, exact)
    else:
        # PSHL never saturates and never reports overflow.
        shifted = _dsp_shift16((cpu.regs[src] >> 16) & 0xFFFF, raw_amount)
        if shifted is None:
            return False
        value16, carry = shifted
        value = value16 << 16
        guard = 0
        overflow = False
        mirror = False
    _dsp_store40(cpu, dest, value, guard)
    if conditional == 0:
        negative = int(bool(guard & 0x80)) if arithmetic \
            else int(bool(value & 0x80000000))
        zero = int(value == 0 and guard == 0)
        _dsp_write_flags(cpu, carry, negative, zero, overflow,
                         mirror_overflow=mirror, or_merge=arithmetic)
    cpu.pc = _u32(cpu.pc + 4)
    return True


def _dsp_shift_imm(cpu, word, arithmetic):
    """PSHL/PSHA #imm,Dz (opcode bases 0x00 / 0x10): shift Dz in place.

    The immediate lives in bits 9:4 (6 bits for PSHL, 7 for PSHA) and
    is signed; negative counts shift right.
    """
    raw_amount = (word >> 4) & (0x7F if arithmetic else 0x3F)
    dest = DSP_DZ_TABLE[word & 15]
    if dest is None:
        return False
    if arithmetic:
        shifted = _dsp_psha_pair(_dsp_load_pair(cpu, dest), raw_amount)
        if shifted is None:
            return False
        value, guard, carry, lost, exact = shifted
        value, guard, overflow, mirror = _dsp_psha_clamp(
            cpu, value, guard, lost, exact)
    else:
        shifted = _dsp_shift16((cpu.regs[dest] >> 16) & 0xFFFF, raw_amount)
        if shifted is None:
            return False
        value16, carry = shifted
        value = value16 << 16
        guard = 0
        overflow = False
        mirror = False
    _dsp_store40(cpu, dest, value, guard)
    negative = int(bool(guard & 0x80)) if arithmetic \
        else int(bool(value & 0x80000000))
    zero = int(value == 0 and guard == 0)
    _dsp_write_flags(cpu, carry, negative, zero, overflow,
                     mirror_overflow=mirror, or_merge=arithmetic)
    cpu.pc = _u32(cpu.pc + 4)
    return True


# Sdsha DSP X/Y slot decode, IDs 323-360; indexed by low six bits.
# IDs are stable references to the extracted instruction-format table.
_XY_SLOTS = (
    (359, 360), (359, 344), (359, 345), (359, 346),
    (326, 360), (323, 341), (323, 342), (323, 343),
    (327, 360), (324, 341), (324, 342), (324, 343),
    (328, 360), (325, 341), (325, 342), (325, 343),
    (359, 360), (359, 350), (359, 351), (359, 352),
    (335, 360), (323, 347), (323, 348), (323, 349),
    (336, 360), (324, 347), (324, 348), (324, 349),
    (337, 360), (325, 347), (325, 348), (325, 349),
    (359, 360), (359, 353), (359, 354), (359, 355),
    (332, 360), (329, 341), (329, 342), (329, 343),
    (333, 360), (330, 341), (330, 342), (330, 343),
    (334, 360), (331, 341), (331, 342), (331, 343),
    (359, 360), (359, 356), (359, 357), (359, 358),
    (338, 360), (329, 347), (329, 348), (329, 349),
    (339, 360), (330, 347), (330, 348), (330, 349),
    (340, 360), (331, 347), (331, 348), (331, 349),
)


def _decode_parallel_slot(axis, ident, word, both):
    """Return address register, data register, direction, size and update mode."""
    select = (word >> 6) & 3
    address_select = (word >> 8) & 3
    if axis == 'x':
        address_reg = 4 + ((word >> 9) & 1) if both else (4, 0, 5, 1)[address_select]
        if ident <= 325:
            data_reg, direction, mode = ('x0', 'x1')[(word >> 7) & 1], 'load', ident - 323
        elif ident <= 328:
            data_reg, direction, mode = ('x0', 'y0', 'x1', 'y1')[select], 'load', ident - 326
        elif ident <= 331:
            data_reg, direction, mode = ('a0', 'a1')[(word >> 7) & 1], 'store', ident - 329
        elif ident <= 334:
            data_reg, direction, mode = ('a0', 'x0', 'a1', 'x1')[select], 'store', ident - 332
        elif ident <= 337:
            data_reg, direction, mode = ('x0', 'y0', 'x1', 'y1')[select], 'load', ident - 335
        else:
            data_reg, direction, mode = ('a0', 'x0', 'a1', 'x1')[select], 'store', ident - 338
        size = 4 if 335 <= ident <= 340 else 2
    else:
        address_reg = 6 + ((word >> 8) & 1) if both else (6, 7, 2, 3)[address_select]
        if ident <= 343:
            data_reg, direction, mode = ('y0', 'y1')[(word >> 6) & 1], 'load', ident - 341
        elif ident <= 346:
            data_reg, direction, mode = ('y0', 'y1', 'x0', 'x1')[select], 'load', ident - 344
        elif ident <= 349:
            data_reg, direction, mode = ('a0', 'a1')[(word >> 6) & 1], 'store', ident - 347
        elif ident <= 352:
            data_reg, direction, mode = ('a0', 'a1', 'y0', 'y1')[select], 'store', ident - 350
        elif ident <= 355:
            data_reg, direction, mode = ('y0', 'y1', 'x0', 'x1')[select], 'load', ident - 353
        else:
            data_reg, direction, mode = ('a0', 'a1', 'y0', 'y1')[select], 'store', ident - 356
        size = 4 if 353 <= ident <= 358 else 2
    return address_reg, data_reg, direction, size, mode


def _parallel_moves(cpu, word):
    """Execute the two DSP memory slots with operands sampled before writes."""
    x_id, y_id = _XY_SLOTS[word & 63]
    both = x_id != 359 and y_id != 360
    before = list(cpu.regs._r)
    sr = cpu.regs['sr']
    mod = cpu.regs['mod']
    updates = []
    loads = []
    stores = []

    for axis, ident in (('x', x_id), ('y', y_id)):
        if ident in (359, 360):
            continue
        reg, data, direction, size, mode = _decode_parallel_slot(axis, ident, word, both)
        increment = before[8] if axis == 'x' else before[9] & 0xFFFF
        modulo = (sr & 0xC00) == 0x400 if axis == 'x' else bool(sr & 0x800)
        address = before[reg]

        if direction == 'load':
            value = cpu.mem.read32(address) if size == 4 else cpu.mem.read16(address) << 16
            loads.append((data, value))
        else:
            value = cpu.regs[data]
            stores.append((address, size, value if size == 4 else value >> 16))

        if mode:
            if modulo and (address & 0xFFFF) == ((mod >> 16) & 0xFFFF):
                after = (address & 0xFFFF0000) | (mod & 0xFFFF)
            else:
                delta = size if mode == 1 else increment
                after = _u32(address + delta)
                if axis == 'y':
                    after = (address & 0xFFFF0000) | (after & 0xFFFF)
            updates.append((reg, after))

    for address, size, value in stores:
        write = cpu.mem.write32 if size == 4 else cpu.mem.write16
        write(address, value)
    for data, value in loads:
        cpu.regs[data] = value
    for reg, value in updates:
        cpu.regs[reg] = value


# ============================================================================
# MOVS: single memory instructions (all 16 modes implemented)
# ============================================================================

# Indexed MOVS transfers at As, then adds R8 to As.
MOVS_INDEX_REG = 'r8'


# CPU73050 I_Table0_7410 / I_Table_Other transfer encodings.
_DATA_TRANSFER = {0x6: 'dsr', 0x7: 'a0', 0x8: 'x0',
                  0x9: 'x1', 0xa: 'y0', 0xb: 'y1'}
_CONTROL_TRANSFER = {0x5: 'mod', 0x6: 'rs', 0x7: 're'}


def classify_dsp_pop(word):
    """Static legality of a P-operation second word.

    Returns 'ok' when the handler executes the word, 'reserved' when it
    decodes to a family but carries a reserved operand field (the real
    decoder rejects it with an operand error), or None when the word is
    not a P-operation at all.
    """
    opcode = word >> 8
    dz = DSP_DZ_TABLE[word & 15]

    if opcode <= 0x07:  # PSHL #imm,Dz
        if dz is None:
            return 'reserved'
        imm = (word >> 4) & 0x3F
        return 'ok' if imm <= 16 or imm >= 48 else 'reserved'
    if 0x10 <= opcode <= 0x17:  # PSHA #imm,Dz
        if dz is None:
            return 'reserved'
        raw = (word >> 4) & 0x7F
        return 'reserved' if 0x21 <= raw <= 0x3F else 'ok'
    if opcode == 0x84:  # PCMP Sx,Sy: bits 3:0 are a reserved field
        return 'ok' if not word & 0xF else 'reserved'
    if 0x81 <= opcode <= 0x83 or 0x91 <= opcode <= 0x93:
        return 'ok' if dz is not None else 'reserved'
    if (0x85 <= opcode <= 0x87 or 0xA0 <= opcode <= 0xA3
            or 0xB0 <= opcode <= 0xB3):
        return 'ok' if dz is not None else 'reserved'
    if (0x95 <= opcode <= 0x97 or 0xA5 <= opcode <= 0xA7
            or 0xB5 <= opcode <= 0xB7):  # PAND/PXOR/POR
        return 'ok' if dz is not None else 'reserved'
    if opcode in (0x8D, 0x8E, 0x8F):  # PCLR Dz
        if word & 0xF0:
            return None
        return 'ok' if dz is not None else 'reserved'
    if 0x88 <= opcode <= 0x8B or 0x98 <= opcode <= 0x9F             or 0xA8 <= opcode <= 0xAB or 0xB8 <= opcode <= 0xBF             or 0xC8 <= opcode <= 0xD3 or 0xD8 <= opcode <= 0xE3             or 0xE8 <= opcode <= 0xEF or 0xF8 <= opcode <= 0xFF:
        # Unary families (PABS/PDEC/PINC/PNEG/PRND/PCOPY/PSWAP/PDMSB/
        # PSTS/PLDS) and the logical trio: Dz validity, plus the
        # selector-marker rules the handler applies.
        if dz is None:
            return 'reserved'
        return 'ok'
    if 0x40 <= opcode <= 0x4F:  # PMULS / PCLR Du PMULS
        return 'ok' if not word & 0xF3 or word & 0xF0 == 0x10 else None
    if 0x60 <= opcode <= 0x7F:  # PSUB/PADD ... PMULS bundles
        return 'ok'
    return None


def handle_dsp_transfer(cpu, word: int) -> bool:
    """Execute register/memory DSP transfers using CPU73050 encodings."""
    if word in (0x0088, 0x0098, 0x00c8):
        if not _sr_dsp_is_set(cpu):
            return False
        mode = {0x0088: 0, 0x0098: 0x400, 0x00c8: 0x800}[word]
        cpu.regs['sr'] = (cpu.regs['sr'] & ~0xc00) | mode
        cpu.pc = _u32(cpu.pc + 2)
        return True
    top = word >> 12
    low = word & 0xff
    n = (word >> 8) & 15
    field, sub = low >> 4, low & 15
    if top == 0 and sub == 0xa:
        name = _DATA_TRANSFER.get(field)
        action = 'store_reg'
    elif top == 0 and sub == 2:
        name = _CONTROL_TRANSFER.get(field)
        action = 'store_reg'
    elif top == 4 and sub in (2, 6, 10):
        name = _DATA_TRANSFER.get(field)
        action = {2: 'store_mem', 6: 'load_mem', 10: 'load_reg'}[sub]
    elif top == 4 and sub in (3, 7, 14):
        name = _CONTROL_TRANSFER.get(field)
        action = {3: 'store_mem', 7: 'load_mem', 14: 'load_reg'}[sub]
    else:
        return False
    if name is None or not _sr_dsp_is_set(cpu):
        return False
    if action == 'store_reg':
        cpu.regs[n] = cpu.regs[name]
    elif action == 'load_reg':
        cpu.regs[name] = cpu.regs[n]
    elif action == 'store_mem':
        address = _u32(cpu.regs[n] - 4)
        cpu.mem.write32(address, cpu.regs[name])
        cpu.regs[n] = address
    else:
        address = cpu.regs[n]
        value = cpu.mem.read32(address)
        cpu.regs[name] = value
        cpu.regs[n] = _u32(address + 4)
    cpu.pc = _u32(cpu.pc + 2)
    return True


def _handle_movs(cpu, op_val: int) -> bool:
    """Handle MOVS.W / MOVS.L single memory instructions.

    Encoding: 1111_01aa_dddd_mmmm
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
    is_indexed = mode in (12, 13, 14, 15)                       # @As+Ix
    is_pre_decrement = mode in (0, 1, 2, 3)               # @-As
    is_post_increment = mode in (8, 9, 10, 11)            # @As+

    size = 4 if is_long else 2

    # Compute the effective address.
    # Indexed, direct and postincrement modes access As; predecrement
    # modes access As - size. Indexed modes update As after the access.
    if is_indexed:
        ix_val = cpu.regs[MOVS_INDEX_REG] & 0xFFFFFFFF
        eff_addr = as_val
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
        cpu.regs[addr_reg] = _u32(as_val + size)
    elif is_indexed:
        cpu.regs[addr_reg] = _u32(as_val + ix_val)

    cpu.pc = _u32(cpu.pc + 2)
    return True


def _movs_load(cpu, addr: int, data_reg: str, is_long: bool):
    """Perform a MOVS load (memory -> DSP data register).

    Per libCPU73050 LABEL_7 (CPU_DSPInstructionSingle):
      - Mode 0 (X0/X1/Y0/Y1/M0/M1): result = v7 << 16
      - Mode 1 (A0/A1): result = v7 << 16  AND  guard bit updated
        to -((int)result < 0) (i.e., 0xFFFFFFFF if negative, else 0)
      - Mode 2 (A0G/A1G): result = (char)v7 (sign-extended byte)

    Long loads transfer all 32 bits; accumulator guard bits are sign extended.
    """
    if is_long:
        # Long load: transfer all 32 bits verbatim.
        val = cpu.mem.read32(addr)
        if isinstance(val, (bytes, bytearray)):
            val = int.from_bytes(val, 'big')
        cpu.regs[data_reg] = _u32(val)
        if data_reg in ('a0', 'a1'):
            cpu.regs[data_reg + 'g'] = 0xFFFFFFFF if val & 0x80000000 else 0
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
