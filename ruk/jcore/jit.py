"""
JIT compiler for the SH-4 emulator.

Three-phase approach:

  Phase 1: Block cache (predecode + batch handler calls)
    - Decode instructions from start_pc until a branch
    - Cache the (handler, args) list
    - Execute all handlers in one tight loop
    - Eliminates per-instruction: mem.read16, dispatch lookup, step() overhead
    - Expected: ~2-3x speedup

  Phase 2: Python source JIT (generate source, exec, cache)
    - After a block is executed `threshold` times, generate Python source
      that inlines all instruction handlers
    - exec() the source to create a function
    - Eliminates per-instruction: function call overhead, PC update
    - Expected: ~5-10x additional speedup

  Phase 3: Loop detection (self-looping blocks → while loop)
    - If a block ends with a conditional branch back to its own start,
      wrap the body in a Python `while True:` loop
    - The entire loop runs as a single function call
    - Expected: ~10-50x additional speedup for tight loops

Usage:
    cpu.run(max_steps)   # uses JIT (fast mode)
    cpu.step()           # single-step (debug mode, no JIT)

Safety:
    - Generated code uses the same register/memory accessors as the
      interpreter, so MMIO, LCD writes, etc. all work correctly.
    - If a block can't be JIT-compiled (unknown instruction, complex
      branch), it falls back to Phase 1 (block cache).
    - The JIT is only used in run() mode. step() is unaffected.
"""

from typing import Dict, List, Tuple, Optional, Callable

# ---------------------------------------------------------------------------
# Branch op_id sets (from emulator._resolve_table)
# ---------------------------------------------------------------------------

BRANCH_OP_IDS = {149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 161, 221, 270}
DELAYED_OP_IDS = {150, 152, 153, 154, 155, 156, 157, 158, 161, 221}
# Only BF/BT (no delay slot) can be JIT-compiled inline
JIT_SAFE_BRANCH_IDS = {149, 151}  # BF, BT


# ---------------------------------------------------------------------------
# Sign extension helpers (used at compile time)
# ---------------------------------------------------------------------------

def _sext8(val):
    val &= 0xFF
    return val - 0x100 if val & 0x80 else val

def _sext12(val):
    val &= 0xFFF
    return val - 0x1000 if val & 0x800 else val


# ---------------------------------------------------------------------------
# Code generators
#
# Each generator takes (op_val, pc, block_start_pc) and returns:
#   (lines: List[str], is_self_loop_branch: bool)
# or None if the instruction can't be JIT-compiled.
#
# The generated lines use these locals (set up at function top):
#   r   = cpu.regs._r        (fast list for r0-r15)
#   sr  = cpu.regs._sys      (dict for sr, pr, gbr, etc.)
#   mem = cpu.mem            (MemoryMap)
#   cpu = cpu                (for pc, ebreak, etc.)
# ---------------------------------------------------------------------------

def _gen_mov(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = r[{m}]"], False)

def _gen_movi(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    i = _sext8(op_val & 0xFF)
    return ([f"r[{n}] = {i & 0xFFFFFFFF}"], False)

def _gen_add(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (r[{n}] + r[{m}]) & 0xFFFFFFFF"], False)

def _gen_addi(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    i = _sext8(op_val & 0xFF)
    return ([f"r[{n}] = (r[{n}] + {i}) & 0xFFFFFFFF"], False)

def _gen_addc(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_t = sr['sr'] & 1",
             f"_tmp = r[{n}] + r[{m}] + _t",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if _tmp > 0xFFFFFFFF else 0)",
             f"r[{n}] = _tmp & 0xFFFFFFFF"], False)

def _gen_sub(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (r[{n}] - r[{m}]) & 0xFFFFFFFF"], False)

def _gen_subc(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_t = sr['sr'] & 1",
             f"_tmp = r[{n}] - r[{m}] - _t",
             f"sr['sr'] = (sr['sr'] & ~1) | (0 if _tmp >= 0 else 1)",
             f"r[{n}] = _tmp & 0xFFFFFFFF"], False)

def _gen_and_rm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] &= r[{m}]"], False)

def _gen_and_imm(op_val, pc, bsp):
    i = op_val & 0xFF
    return ([f"r[0] &= {i}"], False)

def _gen_or_rm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] |= r[{m}]"], False)

def _gen_or_imm(op_val, pc, bsp):
    i = op_val & 0xFF
    return ([f"r[0] |= {i}"], False)

def _gen_xor_rm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] ^= r[{m}]"], False)

def _gen_xor_imm(op_val, pc, bsp):
    i = op_val & 0xFF
    return ([f"r[0] ^= {i}"], False)

def _gen_not(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (~r[{m}]) & 0xFFFFFFFF"], False)

def _gen_neg(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (-r[{m}]) & 0xFFFFFFFF"], False)

def _gen_negc(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_t = sr['sr'] & 1",
             f"_tmp = -r[{m}] - _t",
             f"sr['sr'] = (sr['sr'] & ~1) | (0 if _tmp >= 0 else 1)",
             f"r[{n}] = _tmp & 0xFFFFFFFF"], False)

def _gen_tst_rm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (0 if (r[{n}] & r[{m}]) == 0 else 1)"], False)

def _gen_tst_imm(op_val, pc, bsp):
    i = op_val & 0xFF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (0 if (r[0] & {i}) == 0 else 1)"], False)

def _gen_cmpim(op_val, pc, bsp):
    i = _sext8(op_val & 0xFF)
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[0] == {i & 0xFFFFFFFF} else 0)"], False)

def _gen_cmpeq(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] == r[{m}] else 0)"], False)

def _gen_cmphs(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] >= r[{m}] else 0)"], False)

def _gen_cmpge(op_val, pc, bsp):
    # Signed comparison: interpret as signed 32-bit
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_a = r[{n}]",
             f"_b = r[{m}]",
             f"_a = _a - 0x100000000 if _a & 0x80000000 else _a",
             f"_b = _b - 0x100000000 if _b & 0x80000000 else _b",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if _a >= _b else 0)"], False)

def _gen_cmpgt(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_a = r[{n}]",
             f"_b = r[{m}]",
             f"_a = _a - 0x100000000 if _a & 0x80000000 else _a",
             f"_b = _b - 0x100000000 if _b & 0x80000000 else _b",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if _a > _b else 0)"], False)

def _gen_cmphi(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] > r[{m}] else 0)"], False)

def _gen_cmppl(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"_a = r[{n}]",
             f"_a = _a - 0x100000000 if _a & 0x80000000 else _a",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if _a > 0 else 0)"], False)

def _gen_cmppz(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"_a = r[{n}]",
             f"_a = _a - 0x100000000 if _a & 0x80000000 else _a",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if _a >= 0 else 0)"], False)

def _gen_dt(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = (r[{n}] - 1) & 0xFFFFFFFF",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] == 0 else 0)"], False)

# ---- Shifts ----

def _gen_shll(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 0x80000000 else 0)",
             f"r[{n}] = (r[{n}] << 1) & 0xFFFFFFFF"], False)

def _gen_shlr(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 1 else 0)",
             f"r[{n}] = r[{n}] >> 1"], False)

def _gen_shll2(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = (r[{n}] << 2) & 0xFFFFFFFF"], False)

def _gen_shll8(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = (r[{n}] << 8) & 0xFFFFFFFF"], False)

def _gen_shll16(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = (r[{n}] << 16) & 0xFFFFFFFF"], False)

def _gen_shlr2(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = r[{n}] >> 2"], False)

def _gen_shlr8(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = r[{n}] >> 8"], False)

def _gen_shlr16(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = r[{n}] >> 16"], False)

def _gen_shal(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 0x80000000 else 0)",
             f"r[{n}] = (r[{n}] << 1) & 0xFFFFFFFF"], False)

def _gen_shar(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 1 else 0)",
             f"_v = r[{n}]",
             f"_v = (_v >> 1) | (_v & 0x80000000)",
             f"r[{n}] = _v & 0xFFFFFFFF"], False)

def _gen_rotl(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 0x80000000 else 0)",
             f"r[{n}] = ((r[{n}] << 1) | (r[{n}] >> 31)) & 0xFFFFFFFF"], False)

def _gen_rotr(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 1 else 0)",
             f"r[{n}] = ((r[{n}] >> 1) | (r[{n}] << 31)) & 0xFFFFFFFF"], False)

def _gen_rotcl(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"_t = sr['sr'] & 1",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 0x80000000 else 0)",
             f"r[{n}] = ((r[{n}] << 1) | _t) & 0xFFFFFFFF"], False)

def _gen_rotcr(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"_t = sr['sr'] & 1",
             f"sr['sr'] = (sr['sr'] & ~1) | (1 if r[{n}] & 1 else 0)",
             f"r[{n}] = ((r[{n}] >> 1) | (_t << 31)) & 0xFFFFFFFF"], False)

# ---- Memory load/store ----

def _gen_movbs(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write8(r[{n}], r[{m}] & 0xFF)"], False)

def _gen_movws(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write16(r[{n}], r[{m}] & 0xFFFF)"], False)

def _gen_movls(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write32(r[{n}], r[{m}])"], False)

def _gen_movbl(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read8(r[{m}])",
             f"r[{n}] = (_v - 0x100 if _v & 0x80 else _v) & 0xFFFFFFFF"], False)

def _gen_movwl(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read16(r[{m}])",
             f"r[{n}] = (_v - 0x10000 if _v & 0x8000 else _v) & 0xFFFFFFFF"], False)

def _gen_movll(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = mem.read32(r[{m}])"], False)

def _gen_movbp(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read8(r[{m}])",
             f"r[{n}] = (_v - 0x100 if _v & 0x80 else _v) & 0xFFFFFFFF",
             f"r[{m}] = (r[{m}] + 1) & 0xFFFFFFFF"], False)

def _gen_movwp(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read16(r[{m}])",
             f"r[{n}] = (_v - 0x10000 if _v & 0x8000 else _v) & 0xFFFFFFFF",
             f"r[{m}] = (r[{m}] + 2) & 0xFFFFFFFF"], False)

def _gen_movlp(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = mem.read32(r[{m}])",
             f"r[{m}] = (r[{m}] + 4) & 0xFFFFFFFF"], False)

def _gen_movbm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (r[{n}] - 1) & 0xFFFFFFFF",
             f"mem.write8(r[{n}], r[{m}] & 0xFF)"], False)

def _gen_movwm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (r[{n}] - 2) & 0xFFFFFFFF",
             f"mem.write16(r[{n}], r[{m}] & 0xFFFF)"], False)

def _gen_movlm(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = (r[{n}] - 4) & 0xFFFFFFFF",
             f"mem.write32(r[{n}], r[{m}])"], False)

# ---- PC-relative loads ----

def _gen_movi_pc(op_val, pc, bsp):
    """MOV.W @(disp,PC), Rn"""
    n = (op_val >> 8) & 0xF
    disp = op_val & 0xFF
    addr = (pc + 4 + (disp << 1)) & 0xFFFFFFFF
    return ([f"_v = mem.read16({addr})",
             f"r[{n}] = (_v - 0x10000 if _v & 0x8000 else _v) & 0xFFFFFFFF"], False)

def _gen_movl_pc(op_val, pc, bsp):
    """MOV.L @(disp,PC), Rn"""
    n = (op_val >> 8) & 0xF
    disp = op_val & 0xFF
    addr = ((pc & 0xFFFFFFFC) + 4 + (disp << 2)) & 0xFFFFFFFF
    return ([f"r[{n}] = mem.read32({addr})"], False)

def _gen_mova(op_val, pc, bsp):
    """MOVA @(disp,PC), R0"""
    disp = op_val & 0xFF
    addr = ((pc & 0xFFFFFFFC) + 4 + (disp << 2)) & 0xFFFFFFFF
    return ([f"r[0] = {addr}"], False)

# ---- GBR-relative ----

def _gen_movbs_gbr(op_val, pc, bsp):
    """MOV.B R0, @(disp,GBR)"""
    disp = op_val & 0xFF
    return ([f"mem.write8(sr['gbr'] + {disp}, r[0] & 0xFF)"], False)

def _gen_movws_gbr(op_val, pc, bsp):
    """MOV.W R0, @(disp,GBR)"""
    disp = op_val & 0xFF
    return ([f"mem.write16(sr['gbr'] + {disp * 2}, r[0] & 0xFFFF)"], False)

def _gen_movls_gbr(op_val, pc, bsp):
    """MOV.L R0, @(disp,GBR)"""
    disp = op_val & 0xFF
    return ([f"mem.write32(sr['gbr'] + {disp * 4}, r[0])"], False)

# ---- R0-indexed ----

def _gen_movbs0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write8(r[{n}] + r[0], r[{m}] & 0xFF)"], False)

def _gen_movws0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write16(r[{n}] + r[0], r[{m}] & 0xFFFF)"], False)

def _gen_movls0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"mem.write32(r[{n}] + r[0], r[{m}])"], False)

def _gen_movbl0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read8(r[{m}] + r[0])",
             f"r[{n}] = (_v - 0x100 if _v & 0x80 else _v) & 0xFFFFFFFF"], False)

def _gen_movwl0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"_v = mem.read16(r[{m}] + r[0])",
             f"r[{n}] = (_v - 0x10000 if _v & 0x8000 else _v) & 0xFFFFFFFF"], False)

def _gen_movll0(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    m = (op_val >> 4) & 0xF
    return ([f"r[{n}] = mem.read32(r[{m}] + r[0])"], False)

# ---- System register ----

def _gen_clrt(op_val, pc, bsp):
    return ([f"sr['sr'] &= ~1"], False)

def _gen_sett(op_val, pc, bsp):
    return ([f"sr['sr'] |= 1"], False)

def _gen_clrs(op_val, pc, bsp):
    return ([f"sr['sr'] &= ~2"], False)

def _gen_sets(op_val, pc, bsp):
    return ([f"sr['sr'] |= 2"], False)

def _gen_clrmac(op_val, pc, bsp):
    return ([f"sr['mach'] = 0", f"sr['macl'] = 0"], False)

def _gen_movt(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = sr['sr'] & 1"], False)

def _gen_lds_pr(op_val, pc, bsp):
    m = (op_val >> 8) & 0xF
    return ([f"sr['pr'] = r[{m}]"], False)

def _gen_sts_pr(op_val, pc, bsp):
    n = (op_val >> 8) & 0xF
    return ([f"r[{n}] = sr['pr']"], False)

# ---- NOP ----

def _gen_nop(op_val, pc, bsp):
    return ([], False)

# ---- Branches (conditional, no delay slot) ----

def _gen_bf(op_val, pc, bsp):
    disp = op_val & 0xFF
    if disp & 0x80:
        disp -= 0x100
    target = (pc + 4 + (disp << 1)) & 0xFFFFFFFF
    next_pc = (pc + 2) & 0xFFFFFFFF
    if target == bsp:
        # Self-loop: branch taken = continue, not taken = break
        return ([f"if not (sr['sr'] & 1): continue",
                 f"break"], True)
    else:
        return ([f"if not (sr['sr'] & 1):",
                 f"    cpu.pc = {target}",
                 f"    return",
                 f"cpu.pc = {next_pc}"], False)

def _gen_bt(op_val, pc, bsp):
    disp = op_val & 0xFF
    if disp & 0x80:
        disp -= 0x100
    target = (pc + 4 + (disp << 1)) & 0xFFFFFFFF
    next_pc = (pc + 2) & 0xFFFFFFFF
    if target == bsp:
        return ([f"if (sr['sr'] & 1): continue",
                 f"break"], True)
    else:
        return ([f"if (sr['sr'] & 1):",
                 f"    cpu.pc = {target}",
                 f"    return",
                 f"cpu.pc = {next_pc}"], False)


# ---------------------------------------------------------------------------
# Code generator registry: op_id -> generator function
# ---------------------------------------------------------------------------

CODE_GENS: Dict[int, Callable] = {
    0: _gen_mov,        # MOV Rm, Rn
    1: _gen_movi,       # MOV #imm, Rn
    4: _gen_mova,       # MOVA @(disp,PC), R0
    5: _gen_movi_pc,    # MOV.W @(disp,PC), Rn
    6: _gen_movl_pc,    # MOV.L @(disp,PC), Rn
    7: _gen_movbl,      # MOV.B @Rm, Rn
    8: _gen_movwl,      # MOV.W @Rm, Rn
    9: _gen_movll,      # MOV.L @Rm, Rn
    10: _gen_movbs,     # MOV.B Rm, @Rn
    11: _gen_movws,     # MOV.W Rm, @Rn
    12: _gen_movls,     # MOV.L Rm, @Rn
    13: _gen_movbp,     # MOV.B @Rm+, Rn
    14: _gen_movwp,     # MOV.W @Rm+, Rn
    15: _gen_movlp,     # MOV.L @Rm+, Rn
    16: _gen_movbm,     # MOV.B Rm, @-Rn
    17: _gen_movwm,     # MOV.W Rm, @-Rn
    18: _gen_movlm,     # MOV.L Rm, @-Rn
    # 25-50: indexed/GBR loads -- add as needed
    39: _gen_movbl0,    # MOV.B @(R0,Rm), Rn
    40: _gen_movwl0,    # MOV.W @(R0,Rm), Rn
    41: _gen_movll0,    # MOV.L @(R0,Rm), Rn
    42: _gen_movbs0,    # MOV.B Rm, @(R0,Rn)
    43: _gen_movws0,    # MOV.W Rm, @(R0,Rn)
    44: _gen_movls0,    # MOV.L Rm, @(R0,Rn)
    48: _gen_movbs_gbr, # MOV.B R0, @(disp,GBR)
    49: _gen_movws_gbr, # MOV.W R0, @(disp,GBR)
    50: _gen_movls_gbr, # MOV.L R0, @(disp,GBR)
    60: _gen_movt,      # MOVT Rn
    79: _gen_add,       # ADD Rm, Rn
    80: _gen_addi,      # ADD #imm, Rn
    81: _gen_addc,      # ADDC Rm, Rn
    83: _gen_cmpim,     # CMP/EQ #imm, R0
    84: _gen_cmpeq,     # CMP/EQ Rm, Rn
    85: _gen_cmphs,     # CMP/HS Rm, Rn
    86: _gen_cmpge,     # CMP/GE Rm, Rn
    87: _gen_cmphi,     # CMP/HI Rm, Rn
    88: _gen_cmpgt,     # CMP/GT Rm, Rn
    89: _gen_cmppl,     # CMP/PL Rn
    90: _gen_cmppz,     # CMP/PZ Rn
    103: _gen_dt,       # DT Rn
    114: _gen_neg,      # NEG Rm, Rn
    115: _gen_negc,     # NEGC Rm, Rn
    116: _gen_sub,      # SUB Rm, Rn
    117: _gen_subc,     # SUBC Rm, Rn
    119: _gen_and_rm,   # AND Rm, Rn
    120: _gen_and_imm,  # AND #imm, R0
    122: _gen_not,      # NOT Rm, Rn
    123: _gen_or_rm,    # OR Rm, Rn
    124: _gen_or_imm,   # OR #imm, R0
    127: _gen_tst_rm,   # TST Rm, Rn
    128: _gen_tst_imm,  # TST #imm, R0
    130: _gen_xor_rm,   # XOR Rm, Rn
    131: _gen_xor_imm,  # XOR #imm, R0
    133: _gen_rotcl,    # ROTCL Rn
    134: _gen_rotcr,    # ROTCR Rn
    135: _gen_rotl,     # ROTL Rn
    136: _gen_rotr,     # ROTR Rn
    138: _gen_shal,     # SHAL Rn
    139: _gen_shar,     # SHAR Rn
    141: _gen_shll,     # SHLL Rn
    142: _gen_shll2,    # SHLL2 Rn
    143: _gen_shll8,    # SHLL8 Rn
    144: _gen_shll16,   # SHLL16 Rn
    145: _gen_shlr,     # SHLR Rn
    146: _gen_shlr2,    # SHLR2 Rn
    147: _gen_shlr8,    # SHLR8 Rn
    148: _gen_shlr16,   # SHLR16 Rn
    149: _gen_bf,       # BF disp
    151: _gen_bt,       # BT disp
    164: _gen_clrmac,   # CLRMAC
    165: _gen_clrs,     # CLRS
    166: _gen_clrt,     # CLRT
    198: _gen_lds_pr,   # LDS Rm, PR
    214: _gen_nop,      # NOP
    225: _gen_sett,     # SETT
    224: _gen_sets,     # SETS
    255: _gen_sts_pr,   # STS PR, Rn
}


# ---------------------------------------------------------------------------
# Block runner (Phase 1: block cache)
# ---------------------------------------------------------------------------

class BlockRunner:
    """Phase 1: predecode blocks and batch-execute handlers."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.block_cache: Dict[int, list] = {}
        self._build_branch_tables()

    def _build_branch_tables(self):
        """Identify which op_vals are branches."""
        emu = self.cpu.emulator
        self.is_branch = [False] * 65536
        # Build a set of branch handler objects
        branch_handlers = set()
        for op_id in BRANCH_OP_IDS:
            h = emu._resolve_table.get(op_id)
            if h is not None:
                branch_handlers.add(h)
        for op_val in range(65536):
            entry = emu._dispatch[op_val]
            if entry is not None and entry[0] in branch_handlers:
                self.is_branch[op_val] = True

    def _compile_block(self, start_pc: int) -> list:
        """Decode instructions from start_pc until a branch. Return ops list."""
        ops = []
        pc = start_pc
        mem = self.cpu.mem
        dispatch = self.cpu.emulator._dispatch
        max_len = 256  # safety limit

        for _ in range(max_len):
            if pc > 0xFFFFFFFE:
                break
            op_val = mem.read16(pc)
            entry = dispatch[op_val]
            if entry is None:
                break  # unknown instruction
            ops.append(entry)
            pc += 2
            if self.is_branch[op_val]:
                break

        return ops

    def run(self, max_steps: int = 10000000) -> int:
        """Run using block caching. Much faster than step() loop."""
        cpu = self.cpu
        cache = self.block_cache
        get_block = self._compile_block

        n = 0
        last = 0; lc = 0
        try:
            for s in range(max_steps):
                pc = cpu.pc
                ops = cache.get(pc)
                if ops is None:
                    ops = get_block(pc)
                    cache[pc] = ops

                for handler, args in ops:
                    handler(*args)
                n = s + 1

                if cpu.pc == last:
                    lc += 1
                    if lc > 100:
                        break
                else:
                    last = cpu.pc; lc = 0
        except IndexError:
            cpu.ebreak = True

        cpu.pc &= 0xFFFFFFFF
        return n


# ---------------------------------------------------------------------------
# JIT compiler (Phase 2+3: source generation + loop detection)
# ---------------------------------------------------------------------------

class JITCompiler:
    """Phase 2+3: compile hot blocks to Python source, exec, cache.

    Falls back to BlockRunner (Phase 1) for blocks that can't be JIT'd.
    """

    def __init__(self, cpu):
        self.cpu = cpu
        # Phase 1 fallback
        self.block_runner = BlockRunner(cpu)
        # Phase 2 cache: pc -> compiled function
        self.jit_cache: Dict[int, Callable] = {}
        # Hotness counter
        self.hotness: Dict[int, int] = {}
        self.threshold = 5  # compile after 5 executions
        self._jit_count = 0
        self._fallback_count = 0

    def _jit_compile(self, start_pc: int) -> Optional[Callable]:
        """Generate Python source for a block, exec it, return the function."""
        cpu = self.cpu
        mem = cpu.mem
        dispatch = cpu.emulator._dispatch
        is_branch = self.block_runner.is_branch

        # Walk instructions and generate code
        body_lines = []
        is_self_loop = False
        pc = start_pc
        max_len = 256

        for _ in range(max_len):
            if pc > 0xFFFFFFFE:
                break
            op_val = mem.read16(pc)

            # Find the op_id for this opcode
            entry = dispatch[op_val]
            if entry is None:
                return None  # can't JIT unknown instructions

            # Look up the code generator by finding which op_id matches
            # We need a reverse map from handler -> op_id
            # Actually, we can build this once at init
            op_id = self._handler_to_op_id.get(id(entry[0]))
            if op_id is None:
                return None  # no code generator for this instruction

            gen = CODE_GENS.get(op_id)
            if gen is None:
                return None  # no code generator

            result = gen(op_val, pc, start_pc)
            if result is None:
                return None

            lines, self_loop_br = result
            body_lines.extend(lines)
            if self_loop_br:
                is_self_loop = True

            pc += 2

            if is_branch[op_val]:
                break

        if not body_lines and not is_self_loop:
            # Empty block (just a NOP?) -- set PC and return
            body_lines.append(f"cpu.pc = {pc}")

        # If the block doesn't end with a branch, set PC to the next instruction
        if not is_self_loop:
            # Check if the last instruction was a branch (it would have set cpu.pc)
            # If not, set cpu.pc to the fall-through address
            last_gen = CODE_GENS.get(op_id)
            if last_gen not in (_gen_bf, _gen_bt):
                body_lines.append(f"cpu.pc = {pc}")

        # Build the function source
        if is_self_loop:
            # Wrap in while True for loop optimization
            source_lines = ["def _jit_fn(cpu):"]
            source_lines.append("    r = cpu.regs._r")
            source_lines.append("    sr = cpu.regs._sys")
            source_lines.append("    mem = cpu.mem")
            source_lines.append("    while True:")
            for line in body_lines:
                source_lines.append(f"        {line}")
            # After break: set exit PC
            source_lines.append(f"    cpu.pc = {pc}")
        else:
            source_lines = ["def _jit_fn(cpu):"]
            source_lines.append("    r = cpu.regs._r")
            source_lines.append("    sr = cpu.regs._sys")
            source_lines.append("    mem = cpu.mem")
            for line in body_lines:
                source_lines.append(f"    {line}")

        source = '\n'.join(source_lines)

        # Debug: uncomment to see generated source
        # import sys; print(f"[JIT] Compiling block at 0x{start_pc:08X}:\n{source}\n", file=sys.stderr)

        try:
            namespace = {}
            exec(source, namespace)
            fn = namespace['_jit_fn']
            self._jit_count += 1
            return fn
        except Exception as e:
            import sys
            print(f"[JIT] Failed to compile block at 0x{start_pc:08X}: {e}", file=sys.stderr)
            print(f"[JIT] Source:\n{source}", file=sys.stderr)
            return None

    def _build_handler_to_op_id(self):
        """Build a reverse map from handler id -> op_id."""
        self._handler_to_op_id = {}
        emu = self.cpu.emulator
        for op_id, handler in emu._resolve_table.items():
            self._handler_to_op_id[id(handler)] = op_id

    def run(self, max_steps: int = 10000000) -> int:
        """Run using JIT with block cache fallback."""
        cpu = self.cpu

        # Build reverse map on first call
        if not hasattr(self, '_handler_to_op_id'):
            self._build_handler_to_op_id()

        jit_cache = self.jit_cache
        block_cache = self.block_runner.block_cache
        hotness = self.hotness
        threshold = self.threshold
        compile_block = self.block_runner._compile_block

        n = 0
        last = 0; lc = 0
        try:
            for s in range(max_steps):
                pc = cpu.pc

                # Try JIT cache first (fastest)
                fn = jit_cache.get(pc)
                if fn is not None:
                    fn(cpu)
                else:
                    # Track hotness
                    count = hotness.get(pc, 0) + 1
                    hotness[pc] = count

                    if count >= threshold:
                        # Hot enough -- try JIT compilation
                        fn = self._jit_compile(pc)
                        if fn is not None:
                            jit_cache[pc] = fn
                            fn(cpu)
                        else:
                            # JIT failed -- use block cache
                            ops = block_cache.get(pc)
                            if ops is None:
                                ops = compile_block(pc)
                                block_cache[pc] = ops
                            for handler, args in ops:
                                handler(*args)
                            self._fallback_count += 1
                    else:
                        # Not hot yet -- use block cache
                        ops = block_cache.get(pc)
                        if ops is None:
                            ops = compile_block(pc)
                            block_cache[pc] = ops
                        for handler, args in ops:
                            handler(*args)

                n = s + 1

                if cpu.pc == last:
                    lc += 1
                    if lc > 100:
                        break
                else:
                    last = cpu.pc; lc = 0
        except IndexError:
            cpu.ebreak = True

        cpu.pc &= 0xFFFFFFFF
        return n

    def stats(self):
        return {
            'jit_compiled': self._jit_count,
            'jit_cache_size': len(self.jit_cache),
            'block_cache_size': len(self.block_runner.block_cache),
            'fallback_count': self._fallback_count,
        }
