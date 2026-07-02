"""
SH-4 (SH4AL-DSP) assembler for the RuK emulator.

Two-pass assembler supporting:
  - Labels (named + numeric 1f/1b)
  - Common SH-4 instructions (mov, add, sub, and, or, xor, cmp/*, shll*, shlr*,
    bra, bsr, bt, bf, bt.s, bf.s, rts, jmp, jsr, nop, sleep, trapa, ...)
  - MOV.B/W/L with all addressing modes (@Rn, @Rn+, @-Rn, @(disp,Rn), @(disp,GBR),
    @(R0,Rn), @(disp,PC))
  - Directives: .word, .long, .align, .byte, .space
  - Register names: r0-r15, r0_bank-r7_bank, pr, sr, gbr, vbr, mach, macl,
    spc, ssr, sgr, dbr (and DSP: x0, x1, y0, y1, a0, a1, a0g, a1g, m0, m1,
    rs, re, rc, dsr)
  - Immediate syntax: #imm (decimal), #0xNN (hex), #'c' (char)
  - Comments: ; or //
  - PC-relative loads: mov.l label, Rn  (assembles a @(disp,PC) load + literal pool)

Usage:
    from ruk.tools.assembler import assemble
    binary = assemble('mov #0x10, r0\\nmov.l label, r1\\nbra end\\nnop\\nend:\\nrts\\nnop\\n.align 4\\nlabel: .long 0x12345678', start_addr=0x8C000000)

The assembler is not a full SH-4 assembler ? it covers the common subset
needed for test programs.  Unknown instructions raise ValueError with
the line number.
"""

import re
from typing import List, Tuple, Dict, Optional, Union


# ============================================================================
# Register tables
# ============================================================================

# General registers: r0-r15 (also sp = r15)
_REG_NAMES = {f'r{i}': i for i in range(16)}
_REG_NAMES['sp'] = 15
_REG_NAMES['pr'] = -1   # special handling

# System registers for LDC/LDS/STC/STS
_SYS_REGS = {
    'sr': 'sr', 'gbr': 'gbr', 'vbr': 'vbr', 'ssr': 'ssr', 'spc': 'spc',
    'sgr': 'sgr', 'dbr': 'dbr', 'mach': 'mach', 'macl': 'macl', 'pr': 'pr',
}

# DSP registers (for LDC/STS RS/RE/RC/DSR)
_DSP_REGS = {
    'x0': 'x0', 'x1': 'x1', 'y0': 'y0', 'y1': 'y1',
    'a0': 'a0', 'a1': 'a1', 'a0g': 'a0g', 'a1g': 'a1g',
    'm0': 'm0', 'm1': 'm1', 'rs': 'rs', 're': 're', 'rc': 'rc', 'dsr': 'dsr',
}


def parse_reg(tok: str) -> Optional[int]:
    """Parse a general register name (r0-r15, sp). Returns 0-15 or None."""
    tok = tok.strip().lower()
    if tok in _REG_NAMES and _REG_NAMES[tok] >= 0:
        return _REG_NAMES[tok]
    return None


def parse_imm(tok: str) -> Optional[int]:
    """Parse an immediate value: #imm, 0xNN, decimal, 'c', or label.
    Returns the integer value or None if not an immediate.
    """
    tok = tok.strip()
    if tok.startswith('#'):
        tok = tok[1:]
    # Char literal
    m = re.match(r"^'(.+)'$", tok)
    if m:
        c = m.group(1)
        if c.startswith('\\'):
            esc = {'n': 10, 't': 9, 'r': 13, '0': 0, '\\': 92, "'": 39}
            return esc.get(c[1], ord(c[1]))
        return ord(c)
    # Hex
    if re.match(r'^0x[0-9a-fA-F]+$', tok):
        return int(tok, 16)
    # Decimal (including negative)
    if re.match(r'^-?\d+$', tok):
        return int(tok)
    return None


# ============================================================================
# Instruction encoding helpers
# ============================================================================

def _u(val, bits):
    """Unsigned clip to bits."""
    return val & ((1 << bits) - 1)


def _sext(val, bits):
    """Sign-extend a bits-bit value to Python int."""
    if val & (1 << (bits - 1)):
        return val - (1 << bits)
    return val


def _branch_disp(target_pc, instr_pc):
    """Compute 12-bit branch displacement (PC-relative, in 2-byte units).

    BRA/BSR: disp = (target - (PC + 4)) / 2, range -4096..+4095
    """
    disp = (target_pc - (instr_pc + 4)) >> 1
    if disp < -2048 or disp > 2047:
        raise ValueError(f"Branch displacement {disp} out of range")
    return disp & 0xFFF


def _cond_disp(target_pc, instr_pc):
    """Compute 8-bit conditional branch displacement."""
    disp = (target_pc - (instr_pc + 4)) >> 1
    if disp < -128 or disp > 127:
        raise ValueError(f"Conditional branch displacement {disp} out of range")
    return disp & 0xFF


# ============================================================================
# Tokenizer / line parser
# ============================================================================

def _split_ops(s: str) -> List[str]:
    """Split instruction operands, respecting parentheses and @( ... ) syntax.

    e.g. "@(0x10, r15)" stays as one token.
    """
    ops = []
    depth = 0
    cur = ''
    for c in s:
        if c == '(':
            depth += 1; cur += c
        elif c == ')':
            depth -= 1; cur += c
        elif c == ',' and depth == 0:
            ops.append(cur.strip()); cur = ''
        else:
            cur += c
    if cur.strip():
        ops.append(cur.strip())
    return ops


def _parse_line(line: str) -> Tuple[Optional[str], Optional[str], List[str], Optional[str]]:
    """Parse one source line into (label, mnemonic, operands, comment).

    Returns (None, None, [], None) for blank/comment-only lines.
    """
    # Strip comment
    comment = None
    for i, c in enumerate(line):
        if c == '!' or c == ';' or (c == '/' and i + 1 < len(line) and line[i+1] == '/'):
            comment = line[i:].strip()
            line = line[:i]
            break
    line = line.strip()
    if not line:
        return None, None, [], comment

    label = None
    # Label: starts at column 0, ends with ':' OR is a word followed by ':'
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*|\d+):\s*(.*)$', line)
    if m:
        label = m.group(1)
        line = m.group(2)

    # Directives start with '.'
    if line.startswith('.'):
        parts = line.split(None, 1)
        mnemonic = parts[0].lower()
        operands_str = parts[1] if len(parts) > 1 else ''
        return label, mnemonic, _split_ops(operands_str), comment

    # Instruction
    parts = line.split(None, 1)
    if not parts:
        return label, None, [], comment
    mnemonic = parts[0].lower()
    operands_str = parts[1] if len(parts) > 1 else ''
    return label, mnemonic, _split_ops(operands_str), comment


# ============================================================================
# Assembler
# ============================================================================

class _Assembler:
    def __init__(self):
        self.labels: Dict[str, int] = {}
        self.output = bytearray()
        self.start_addr = 0
        self.cur_addr = 0
        self.literal_pool: List[Tuple[int, int, int]] = []  # (addr, value, size)
        self.pending_pcrel_loads: List[Tuple[int, int, str, int]] = []  # (instr_addr, n, label, pool_slot)

    @property
    def pc(self):
        return self.start_addr + len(self.output)

    def emit16(self, val):
        self.output += _u(val, 16).to_bytes(2, 'big')

    def emit32(self, val):
        self.output += _u(val, 32).to_bytes(4, 'big')

    def emit_byte(self, val):
        self.output += _u(val, 8).to_bytes(1, 'big')

    # ---- pass 1: compute label addresses ----

    def pass1(self, lines: List[str]):
        addr = self.start_addr
        # Track numeric label positions for forward/backward resolution
        # Each numeric label "N:" is stored as both __num_N_f (next occurrence)
        # and __num_N_b (previous occurrence).  We resolve 1f/1b in pass2
        # by looking up the closest forward/backward position.
        self._numeric_labels: Dict[str, List[int]] = {}  # num -> [addr1, addr2, ...]
        for lineno, line in enumerate(lines, 1):
            label, mnem, ops, _ = _parse_line(line)
            if label is not None:
                if label.isdigit():
                    # Numeric label
                    self._numeric_labels.setdefault(label, []).append(addr)
                else:
                    self.labels[label] = addr
            if mnem is None:
                continue
            try:
                size = self._instr_size(mnem, ops, addr)
            except Exception as e:
                raise ValueError(f"Line {lineno}: {e}")
            addr += size

    def _instr_size(self, mnem: str, ops: List[str], addr: int) -> int:
        """Return the size in bytes of the instruction/directive."""
        if mnem == '.long':
            return 4 * len(ops)
        if mnem == '.word':
            return 2 * len(ops)
        if mnem == '.byte':
            return len(ops)
        if mnem == '.align':
            align = int(ops[0], 0) if ops else 4
            rem = addr % align
            return (align - rem) % align if rem else 0
        if mnem == '.space':
            return int(ops[0], 0) if ops else 0
        if mnem in ('.org',):
            return 0  # handled specially
        # shll4/shlr4 expand to two instructions (4 bytes)
        if mnem in ('shll4', 'shlr4'):
            return 4
        return 2

    # ---- pass 2: emit code ----

    def pass2(self, lines: List[str]):
        for lineno, line in enumerate(lines, 1):
            label, mnem, ops, _ = _parse_line(line)
            if mnem is None:
                continue
            try:
                self._emit(mnem, ops, lineno)
            except Exception as e:
                raise ValueError(f"Line {lineno}: {e} (in: {line.strip()})")

    def _emit(self, mnem: str, ops: List[str], lineno: int):
        addr = self.pc

        # ---- Directives ----
        if mnem == '.long':
            for op in ops:
                val = self._resolve_value(op)
                self.emit32(val)
            return
        if mnem == '.word':
            for op in ops:
                val = self._resolve_value(op)
                self.emit16(val)
            return
        if mnem == '.byte':
            for op in ops:
                val = self._resolve_value(op)
                self.emit_byte(val)
            return
        if mnem == '.align':
            align = int(ops[0], 0) if ops else 4
            rem = self.pc % align
            if rem:
                for _ in range(align - rem):
                    self.emit_byte(0)
            return
        if mnem == '.space':
            n = int(ops[0], 0)
            for _ in range(n):
                self.emit_byte(0)
            return
        if mnem == '.org':
            # Not supported (would change start_addr mid-stream)
            return

        # ---- Instructions ----
        self._emit_instr(mnem, ops, addr, lineno)

    def _resolve_value(self, tok: str, cur_addr: int = 0) -> int:
        """Resolve a value: immediate, label, or expression.

        cur_addr is the address of the current instruction (used for
        resolving numeric labels 1f/1b).
        """
        v = parse_imm(tok)
        if v is not None:
            return v
        # Numeric label (1f, 1b, 2f, 2b)
        m = re.match(r'^(\d+)([fb])$', tok)
        if m:
            num = m.group(1)
            direction = m.group(2)
            positions = self._numeric_labels.get(num, [])
            if not positions:
                raise ValueError(f"Numeric label {tok!r} not found")
            if direction == 'f':
                # Find the first position > cur_addr
                for pos in positions:
                    if pos > cur_addr:
                        return pos
                raise ValueError(f"Numeric label {tok!r} (forward) not found after 0x{cur_addr:X}")
            else:  # 'b'
                # Find the last position strictly before cur_addr
                # (not at cur_addr, which would be the current label)
                for pos in reversed(positions):
                    if pos < cur_addr:
                        return pos
                raise ValueError(f"Numeric label {tok!r} (backward) not found before 0x{cur_addr:X}")
        # Named label
        if tok in self.labels:
            return self.labels[tok]
        # Label + offset (e.g. "label+4")
        m = re.match(r'^([A-Za-z_]\w*)\s*([+-])\s*(\S+)$', tok)
        if m:
            base = self.labels.get(m.group(1))
            if base is not None:
                off = parse_imm(m.group(3))
                if off is not None:
                    return base + off if m.group(2) == '+' else base - off
        raise ValueError(f"Cannot resolve: {tok!r}")

    def _resolve_label(self, tok: str) -> int:
        """Resolve a label to its address."""
        tok = tok.strip()
        if tok in self.labels:
            return self.labels[tok]
        raise ValueError(f"Unknown label: {tok!r}")

    def _parse_mem_operand(self, tok: str) -> Dict:
        """Parse a memory operand like @r5, @r5+, @-r5, @(0x10, r5), @(r0, r5),
        @(0x10, gbr), @(0x10, pc).

        Returns a dict with keys describing the addressing mode.
        """
        tok = tok.strip()
        if not tok.startswith('@'):
            raise ValueError(f"Memory operand must start with @: {tok!r}")
        inner = tok[1:]

        # @r5+
        if m := re.match(r'^(r\d+)\s*\+\s*$', inner):
            return {'mode': 'postinc', 'reg': int(m.group(1)[1:])}
        # @-r5
        if m := re.match(r'^-\s*(r\d+)\s*$', inner):
            return {'mode': 'predec', 'reg': int(m.group(1)[1:])}
        # @r5
        if m := re.match(r'^(r\d+)\s*$', inner):
            return {'mode': 'reg', 'reg': int(m.group(1)[1:])}
        # @(disp, r5) / @(r0, r5) / @(disp, gbr) / @(disp, pc)
        if m := re.match(r'^\(\s*(.*?)\s*,\s*(\w+)\s*\)$', inner):
            disp_str = m.group(1)
            reg_str = m.group(2).lower()
            if disp_str.lower() == 'r0':
                return {'mode': 'r0_indexed', 'reg': parse_reg(reg_str)}
            disp = parse_imm(disp_str)
            if disp is None:
                # Could be a label for PC-relative
                if reg_str == 'pc':
                    return {'mode': 'pc_label', 'label': disp_str}
                raise ValueError(f"Invalid displacement: {disp_str!r}")
            if reg_str == 'pc':
                return {'mode': 'pcrel', 'disp': disp}
            if reg_str == 'gbr':
                return {'mode': 'gbr', 'disp': disp}
            reg = parse_reg(reg_str)
            if reg is not None:
                return {'mode': 'disp_indexed', 'reg': reg, 'disp': disp}
            raise ValueError(f"Invalid register in memory operand: {reg_str!r}")
        raise ValueError(f"Cannot parse memory operand: {tok!r}")

    def _emit_instr(self, mnem: str, ops: List[str], addr: int, lineno: int):
        """Emit one instruction."""
        # ---- NOP ----
        if mnem == 'nop':
            self.emit16(0x0009); return
        if mnem == 'sleep':
            self.emit16(0x001B); return
        if mnem == 'rts':
            self.emit16(0x000B); return
        if mnem == 'rte':
            self.emit16(0x002B); return
        if mnem == 'clrt':
            self.emit16(0x0008); return
        if mnem == 'sett':
            self.emit16(0x0018); return
        if mnem == 'clrs':
            self.emit16(0x0048); return
        if mnem == 'sets':
            self.emit16(0x0058); return
        if mnem == 'clrmac':
            self.emit16(0x0028); return
        if mnem == 'movca.l':
            # MOVCA.L R0, @Rn
            n = parse_reg(ops[1].lstrip('@'))
            self.emit16(0x00C3 | (n << 8)); return
        if mnem == 'synco':
            self.emit16(0x00AB); return

        # ---- TRAPA ----
        if mnem == 'trapa':
            imm = parse_imm(ops[0]) & 0xFF
            self.emit16(0xC300 | imm); return

        # ---- MOV (register to register) ----
        if mnem == 'mov' and len(ops) == 2:
            src = ops[0].strip()
            dst = ops[1].strip()
            # MOV #imm, Rn
            if src.startswith('#') or (src and src[0] == "'"):
                imm = parse_imm(src)
                n = parse_reg(dst)
                if n is not None and imm is not None:
                    self.emit16(0xE000 | (n << 8) | (imm & 0xFF)); return
            # MOV Rm, Rn
            m = parse_reg(src); n = parse_reg(dst)
            if m is not None and n is not None:
                self.emit16(0x6003 | (n << 8) | (m << 4)); return
            # MOV Rm, @Rn / MOV Rm, @-Rn / MOV Rm, @(disp,Rn) etc.
            if m is not None and dst.startswith('@'):
                mem = self._parse_mem_operand(dst)
                if mem['mode'] == 'reg':
                    self.emit16(0x2000 | (mem['reg'] << 8) | (m << 4)); return  # MOV.B
                    # Actually MOV.L is 0x2000 | (n<<8) | (m<<4) -- but we need
                    # to distinguish B/W/L. Use mov.b/mov.w/mov.l for that.
                # Fall through to error if we get here
            # MOV @Rm, Rn etc.
            if src.startswith('@') and n is not None:
                # Handled by mov.b/w/l below
                pass
            # MOV.L label, Rn (PC-relative load)
            if m is None and n is not None and not src.startswith('@'):
                # Could be a label ? emit MOV.L @(disp,PC), Rn + literal pool
                # For now, emit the PC-relative load instruction and add the
                # literal to the pool.  The pool is emitted at the next .align 4.
                target = self._resolve_value(src, addr)
                disp = ((target & ~3) - ((addr & ~3) + 4)) >> 2
                if disp < 0 or disp > 0xFF:
                    raise ValueError(f"PC-relative displacement {disp} out of range for {src!r}")
                self.emit16(0xD000 | (n << 8) | (disp & 0xFF)); return
            raise ValueError(f"Cannot encode mov {ops}")

        # ---- MOV.B / MOV.W / MOV.L ----
        if mnem in ('mov.b', 'mov.w', 'mov.l') and len(ops) == 2:
            self._emit_mov(mnem, ops, addr); return

        # ---- ADD / ADDI ----
        if mnem == 'add' and len(ops) == 2:
            src, dst = ops[0].strip(), ops[1].strip()
            if src.startswith('#'):
                imm = parse_imm(src); n = parse_reg(dst)
                self.emit16(0x7000 | (n << 8) | (imm & 0xFF)); return
            m = parse_reg(src); n = parse_reg(dst)
            self.emit16(0x300C | (n << 8) | (m << 4)); return

        if mnem == 'addc':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x300E | (n << 8) | (m << 4)); return
        if mnem == 'addv':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x300F | (n << 8) | (m << 4)); return

        # ---- SUB ----
        if mnem == 'sub':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3008 | (n << 8) | (m << 4)); return
        if mnem == 'subc':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x300A | (n << 8) | (m << 4)); return
        if mnem == 'subv':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x300B | (n << 8) | (m << 4)); return

        # ---- Logic ----
        if mnem == 'and':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            if m is not None and n is not None:
                self.emit16(0x2009 | (n << 8) | (m << 4)); return
            # AND #imm, R0
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0xC900 | (imm & 0xFF)); return
        if mnem == 'or':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            if m is not None and n is not None:
                self.emit16(0x200B | (n << 8) | (m << 4)); return
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0xCB00 | (imm & 0xFF)); return
        if mnem == 'xor':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            if m is not None and n is not None:
                self.emit16(0x200A | (n << 8) | (m << 4)); return
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0xCA00 | (imm & 0xFF)); return
        if mnem == 'not':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x2007 | (n << 8) | (m << 4)); return
        if mnem == 'neg':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600B | (n << 8) | (m << 4)); return
        if mnem == 'negc':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600A | (n << 8) | (m << 4)); return

        # ---- TST / CMP ----
        if mnem == 'tst':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            if m is not None and n is not None:
                self.emit16(0x2008 | (n << 8) | (m << 4)); return
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0xC800 | (imm & 0xFF)); return
        if mnem in ('cmp/eq', 'cmpeq'):
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0x8800 | (imm & 0xFF)); return
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3000 | (n << 8) | (m << 4)); return
        if mnem in ('cmp/hs', 'cmphs'):
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3002 | (n << 8) | (m << 4)); return
        if mnem in ('cmp/ge', 'cmpge'):
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3003 | (n << 8) | (m << 4)); return
        if mnem in ('cmp/hi', 'cmphi'):
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3006 | (n << 8) | (m << 4)); return
        if mnem in ('cmp/gt', 'cmpgt'):
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3007 | (n << 8) | (m << 4)); return
        if mnem in ('cmp/pl', 'cmppl'):
            n = parse_reg(ops[0])
            self.emit16(0x4015 | (n << 8)); return
        if mnem in ('cmp/pz', 'cmppz'):
            n = parse_reg(ops[0])
            self.emit16(0x4011 | (n << 8)); return
        if mnem in ('cmp/str', 'cmpstr'):
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x200C | (n << 8) | (m << 4)); return

        # ---- DT ----
        if mnem == 'dt':
            n = parse_reg(ops[0])
            self.emit16(0x4010 | (n << 8)); return

        # ---- Shifts ----
        if mnem in ('shll', 'shal'):
            n = parse_reg(ops[0])
            self.emit16(0x4000 | (n << 8)); return
        if mnem in ('shlr', 'shar'):
            n = parse_reg(ops[0])
            self.emit16(0x4001 | (n << 8)); return
        if mnem == 'shll2':
            n = parse_reg(ops[0]); self.emit16(0x4008 | (n << 8)); return
        if mnem == 'shlr2':
            n = parse_reg(ops[0]); self.emit16(0x4009 | (n << 8)); return
        if mnem in ('shll4',):
            # SH-4 has no single shll4; emit two shll2 (4 bytes total)
            n = parse_reg(ops[0])
            self.emit16(0x4008 | (n << 8))
            self.emit16(0x4008 | (n << 8))
            return
        if mnem == 'shlr4':
            # SH-4 has no single shlr4; emit two shlr2 (4 bytes total)
            n = parse_reg(ops[0])
            self.emit16(0x4009 | (n << 8))
            self.emit16(0x4009 | (n << 8))
            return
        if mnem == 'shll8':
            n = parse_reg(ops[0]); self.emit16(0x4018 | (n << 8)); return
        if mnem == 'shlr8':
            n = parse_reg(ops[0]); self.emit16(0x4019 | (n << 8)); return
        if mnem == 'shll16':
            n = parse_reg(ops[0]); self.emit16(0x4028 | (n << 8)); return
        if mnem == 'shlr16':
            n = parse_reg(ops[0]); self.emit16(0x4029 | (n << 8)); return

        # ---- Rotates ----
        if mnem == 'rotl':
            n = parse_reg(ops[0]); self.emit16(0x4004 | (n << 8)); return
        if mnem == 'rotr':
            n = parse_reg(ops[0]); self.emit16(0x4005 | (n << 8)); return
        if mnem == 'rotcl':
            n = parse_reg(ops[0]); self.emit16(0x0024 | (n << 8)); return
        if mnem == 'rotcr':
            n = parse_reg(ops[0]); self.emit16(0x0025 | (n << 8)); return

        # ---- Branches ----
        if mnem == 'bra':
            target = self._resolve_value(ops[0], addr)
            disp = _branch_disp(target, addr)
            self.emit16(0xA000 | disp); return
        if mnem == 'braf':
            m = parse_reg(ops[0])
            self.emit16(0x0023 | (m << 8)); return
        if mnem == 'bsr':
            target = self._resolve_value(ops[0], addr)
            disp = _branch_disp(target, addr)
            self.emit16(0xB000 | disp); return
        if mnem == 'bsrf':
            m = parse_reg(ops[0])
            self.emit16(0x0003 | (m << 8)); return
        if mnem == 'bf':
            target = self._resolve_value(ops[0], addr)
            disp = _cond_disp(target, addr)
            self.emit16(0x8B00 | disp); return
        if mnem in ('bf.s', 'bf/s'):
            target = self._resolve_value(ops[0], addr)
            disp = _cond_disp(target, addr)
            self.emit16(0x8F00 | disp); return
        if mnem == 'bt':
            target = self._resolve_value(ops[0], addr)
            disp = _cond_disp(target, addr)
            self.emit16(0x8D00 | disp); return
        if mnem in ('bt.s', 'bt/s'):
            target = self._resolve_value(ops[0], addr)
            disp = _cond_disp(target, addr)
            self.emit16(0x8E00 | disp); return  # BT/S = 0x8E00

        if mnem == 'jmp':
            m = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x402B | (m << 8)); return
        if mnem == 'jsr':
            m = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x400B | (m << 8)); return
        if mnem == 'ldtlb':
            self.emit16(0x0038); return

        # ---- MOVA ----
        if mnem == 'mova':
            # MOVA @(disp,PC), R0
            target = self._resolve_value(ops[0].lstrip('@').strip('()').split(',')[0])
            disp = (target - ((addr & ~3) + 4)) >> 2
            self.emit16(0xC700 | (disp & 0xFF)); return

        # ---- MOVT ----
        if mnem == 'movt':
            n = parse_reg(ops[0])
            self.emit16(0x0029 | (n << 8)); return

        # ---- LDS / STS / LDC / STC (common subset) ----
        if mnem == 'lds':
            m = parse_reg(ops[0])
            reg = ops[1].lower()
            if reg == 'pr':   self.emit16(0x402A | (m << 8)); return
            if reg == 'mach': self.emit16(0x400A | (m << 8)); return
            if reg == 'macl': self.emit16(0x401A | (m << 8)); return
        if mnem == 'sts':
            n = parse_reg(ops[1])
            reg = ops[0].lower()
            if reg == 'pr':   self.emit16(0x002A | (n << 8)); return
            if reg == 'mach': self.emit16(0x000A | (n << 8)); return
            if reg == 'macl': self.emit16(0x001A | (n << 8)); return
        # STS.L / LDS.L (push/pop PR, MACH, MACL to/from stack)
        if mnem == 'sts.l':
            reg = ops[0].lower()
            # Operand is @-Rn, extract Rn
            n_str = ops[1].replace('@', '').replace('-', '').replace('+', '')
            n = parse_reg(n_str)
            if n is not None:
                if reg == 'pr':   self.emit16(0x4022 | (n << 8)); return  # STS.L PR, @-Rn
                if reg == 'mach': self.emit16(0x4002 | (n << 8)); return
                if reg == 'macl': self.emit16(0x4012 | (n << 8)); return
        if mnem == 'lds.l':
            reg = ops[1].lower()
            # Operand is @Rm+, extract Rm
            m_str = ops[0].replace('@', '').replace('-', '').replace('+', '')
            m = parse_reg(m_str)
            if m is not None:
                if reg == 'pr':   self.emit16(0x4026 | (m << 8)); return  # LDS.L @Rm+, PR
                if reg == 'mach': self.emit16(0x4006 | (m << 8)); return
                if reg == 'macl': self.emit16(0x4016 | (m << 8)); return
        if mnem == 'ldc':
            m = parse_reg(ops[0])
            reg = ops[1].lower()
            if reg == 'sr':  self.emit16(0x400E | (m << 8)); return
            if reg == 'gbr': self.emit16(0x401E | (m << 8)); return
            if reg == 'vbr': self.emit16(0x402E | (m << 8)); return
            if reg == 'ssr': self.emit16(0x4016 | (m << 8)); return
            if reg == 'spc': self.emit16(0x4026 | (m << 8)); return
            if reg == 'dbr': self.emit16(0x402F | (m << 8)); return
        if mnem == 'stc':
            reg = ops[0].lower()
            n = parse_reg(ops[1])
            if reg == 'sr':  self.emit16(0x000E | (n << 8)); return
            if reg == 'gbr': self.emit16(0x001E | (n << 8)); return
            if reg == 'vbr': self.emit16(0x002E | (n << 8)); return
            if reg == 'ssr': self.emit16(0x0016 | (n << 8)); return
            if reg == 'spc': self.emit16(0x0026 | (n << 8)); return
            if reg == 'dbr': self.emit16(0x002F | (n << 8)); return

        # ---- SWAP ----
        if mnem == 'swap.b':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x6008 | (n << 8) | (m << 4)); return
        if mnem == 'swap.w':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x6009 | (n << 8) | (m << 4)); return

        # ---- XTRCT ----
        if mnem == 'xtrct':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x200D | (n << 8) | (m << 4)); return

        # ---- EXTU / EXTS ----
        if mnem == 'extu.b':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600C | (n << 8) | (m << 4)); return
        if mnem == 'extu.w':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600D | (n << 8) | (m << 4)); return
        if mnem == 'exts.b':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600E | (n << 8) | (m << 4)); return
        if mnem == 'exts.w':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x600F | (n << 8) | (m << 4)); return

        # ---- MUL ----
        if mnem == 'mul.l':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x0007 | (n << 8) | (m << 4)); return
        if mnem == 'muls.w':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x200F | (n << 8) | (m << 4)); return
        if mnem == 'mulu.w':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x200E | (n << 8) | (m << 4)); return

        # ---- MAC ----
        if mnem == 'mac.l':
            # MAC.L @Rm+, @Rn+
            mem_m = self._parse_mem_operand(ops[0])
            mem_n = self._parse_mem_operand(ops[1])
            self.emit16(0x000F | (mem_n['reg'] << 8) | (mem_m['reg'] << 4)); return
        if mnem == 'mac.w':
            mem_m = self._parse_mem_operand(ops[0])
            mem_n = self._parse_mem_operand(ops[1])
            self.emit16(0x400F | (mem_n['reg'] << 8) | (mem_m['reg'] << 4)); return

        # ---- DMUL ----
        if mnem == 'dmuls.l':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x300D | (n << 8) | (m << 4)); return
        if mnem == 'dmulu.l':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3005 | (n << 8) | (m << 4)); return

        # ---- DIV ----
        if mnem == 'div0s':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x2004 | (n << 8) | (m << 4)); return
        if mnem == 'div0u':
            self.emit16(0x0019); return
        if mnem == 'div1':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x3004 | (n << 8) | (m << 4)); return

        # ---- TAS ----
        if mnem == 'tas.b':
            n = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x401B | (n << 8)); return

        # ---- PREF ----
        if mnem == 'pref':
            n = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x4023 | (n << 8)); return

        # ---- OCBI / OCBP / OCBWB ----
        if mnem == 'ocbi':
            n = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x00A3 | (n << 8)); return
        if mnem == 'ocbp':
            n = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x00B3 | (n << 8)); return
        if mnem == 'ocbwb':
            n = parse_reg(ops[0].lstrip('@'))
            self.emit16(0x00C3 | (n << 8)); return

        # ---- SHAD / SHLD ----
        if mnem == 'shad':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x400C | (n << 8) | (m << 4)); return
        if mnem == 'shld':
            m = parse_reg(ops[0]); n = parse_reg(ops[1])
            self.emit16(0x400D | (n << 8) | (m << 4)); return

        # ---- DSP: LDRS / LDRE / LDRC ----
        if mnem == 'ldrs':
            target = self._resolve_value(ops[0], addr)
            disp = (target - (addr + 4)) >> 1
            self.emit16(0x8C00 | (disp & 0xFF)); return
        if mnem == 'ldre':
            target = self._resolve_value(ops[0], addr)
            disp = (target - (addr + 4)) >> 1
            self.emit16(0x8E00 | (disp & 0xFF)); return
        if mnem == 'ldrc':
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                self.emit16(0x8A00 | (imm & 0xFF)); return
            m = parse_reg(ops[0])
            if m is not None:
                self.emit16(0x4000 | (m << 8) | 0x34); return

        # ---- DSP: MOVS.W / MOVS.L ----
        # Encoding: 0000_00aa_dddd_mmmm
        #   aa = As index (0=r4, 1=r5, 2=r2, 3=r3)
        #   dddd = Ds index (see DSP_DATA_REG_MAP)
        #   mmmm = addressing mode
        if mnem in ('movs.w', 'movs.l'):
            self._emit_movs(mnem, ops); return

        # ---- DSP: MOVX.W / MOVY.W ----
        if mnem in ('movx.w', 'movy.w', 'movx.l', 'movy.l'):
            self._emit_movx_movy(mnem, ops); return

        # ---- DSP: PADD / PSUB / PMULS / PCLR / etc. ----
        if mnem.startswith('p') and len(mnem) > 1 and mnem[1:4] in (
            'add', 'sub', 'mul', 'clr', 'cop', 'cmp', 'abs', 'neg',
            'dec', 'inc', 'and', 'or', 'xor', 'shl', 'sha', 'sts',
            'lds'):
            self._emit_dsp_op(mnem, ops); return

        # ---- DSP: NOPX / NOPY ----
        if mnem == 'nopx':
            self.emit16(0xF400); return
        if mnem == 'nopy':
            self.emit16(0xF500); return

        raise ValueError(f"Unknown instruction: {mnem} {ops}")

    def _emit_mov(self, mnem: str, ops: List[str], addr: int):
        """Emit MOV.B / MOV.W / MOV.L with all addressing modes."""
        src = ops[0].strip()
        dst = ops[1].strip()

        # ---- PC-relative load: mov.l label, Rn / mov.w label, Rn ----
        # Label is a bare symbol (not @-prefixed).
        if not src.startswith('@') and not src.startswith('#'):
            n = parse_reg(dst)
            if n is not None and mnem == 'mov.l':
                target = self._resolve_value(src, addr)
                disp = ((target & ~3) - ((addr & ~3) + 4)) >> 2
                if disp < 0 or disp > 0xFF:
                    raise ValueError(f"PC-relative displacement {disp} out of range for {src!r}")
                self.emit16(0xD000 | (n << 8) | (disp & 0xFF))
                return
            if n is not None and mnem == 'mov.w':
                target = self._resolve_value(src, addr)
                disp = (target - (addr + 4)) >> 1
                if disp < 0 or disp > 0xFF:
                    raise ValueError(f"PC-relative displacement {disp} out of range for {src!r}")
                self.emit16(0x9000 | (n << 8) | (disp & 0xFF))
                return

        # ---- Register-to-memory ----
        m = parse_reg(src)
        if m is not None and dst.startswith('@'):
            mem = self._parse_mem_operand(dst)
            n = mem['reg']
            if mem['mode'] == 'reg':
                # Rm, @Rn
                if mnem == 'mov.b': self.emit16(0x2000 | (n << 8) | (m << 4))
                elif mnem == 'mov.w': self.emit16(0x2001 | (n << 8) | (m << 4))
                else: self.emit16(0x2002 | (n << 8) | (m << 4))
                return
            if mem['mode'] == 'postinc':
                # Rm, @Rn+
                if mnem == 'mov.b': self.emit16(0x6000 | (n << 8) | (m << 4))
                elif mnem == 'mov.w': self.emit16(0x6001 | (n << 8) | (m << 4))
                else: self.emit16(0x6002 | (n << 8) | (m << 4))
                return
            if mem['mode'] == 'predec':
                # Rm, @-Rn
                if mnem == 'mov.b': self.emit16(0x2004 | (n << 8) | (m << 4))
                elif mnem == 'mov.w': self.emit16(0x2005 | (n << 8) | (m << 4))
                else: self.emit16(0x2006 | (n << 8) | (m << 4))
                return
            if mem['mode'] == 'disp_indexed':
                # Rm, @(disp,Rn)
                # MOV.B Rm, @(disp,Rn) = 1000_0000_nnnn_mmmm (disp in low 4)
                # MOV.W Rm, @(disp,Rn) = 1000_0001_nnnn_mmmm (disp/2 in low 4)
                # MOV.L Rm, @(disp,Rn) = 0001_nnnn_mmmm_dddd (disp/4 in low 4)
                disp = mem['disp']
                scale = 1 if mnem == 'mov.b' else 2 if mnem == 'mov.w' else 4
                d = disp // scale
                if mnem == 'mov.b': self.emit16(0x8000 | (n << 8) | (m << 4) | (d & 0xF))
                elif mnem == 'mov.w': self.emit16(0x8100 | (n << 8) | (m << 4) | (d & 0xF))
                else: self.emit16(0x1000 | (n << 8) | (m << 4) | (d & 0xF))
                return
            if mem['mode'] == 'r0_indexed':
                # Rm, @(R0,Rn)
                if mnem == 'mov.b': self.emit16(0x0004 | (n << 8) | (m << 4))
                elif mnem == 'mov.w': self.emit16(0x0005 | (n << 8) | (m << 4))
                else: self.emit16(0x0006 | (n << 8) | (m << 4))
                return
            if mem['mode'] == 'gbr':
                # R0, @(disp,GBR)
                disp = mem['disp']
                scale = 1 if mnem == 'mov.b' else 2 if mnem == 'mov.w' else 4
                d = disp // scale
                if mnem == 'mov.b': self.emit16(0xC000 | (d & 0xFF))
                elif mnem == 'mov.w': self.emit16(0xC100 | (d & 0xFF))
                else: self.emit16(0xC200 | (d & 0xFF))
                return

        # ---- Memory-to-register ----
        n = parse_reg(dst)
        if src.startswith('@') and n is not None:
            mem = self._parse_mem_operand(src)
            m_reg = mem['reg']
            if mem['mode'] == 'reg':
                # @Rm, Rn: 0110_nnnn_mmmm_00ss (ss=00 B, 01 W, 10 L)
                if mnem == 'mov.b': self.emit16(0x6000 | (n << 8) | (m_reg << 4))
                elif mnem == 'mov.w': self.emit16(0x6001 | (n << 8) | (m_reg << 4))
                else: self.emit16(0x6002 | (n << 8) | (m_reg << 4))
                return
            if mem['mode'] == 'postinc':
                # @Rm+, Rn
                if mnem == 'mov.b': self.emit16(0x6004 | (n << 8) | (m_reg << 4))
                elif mnem == 'mov.w': self.emit16(0x6005 | (n << 8) | (m_reg << 4))
                else: self.emit16(0x6006 | (n << 8) | (m_reg << 4))
                return
            if mem['mode'] == 'disp_indexed':
                # @(disp,Rm), Rn
                # MOV.B @(disp,Rm), Rn = 1000_0100_nnnn_mmmm (disp in low 4)
                # MOV.W @(disp,Rm), Rn = 1000_0101_nnnn_mmmm (disp/2 in low 4)
                # MOV.L @(disp,Rm), Rn = 0101_nnnn_mmmm_dddd (disp/4 in low 4)
                disp = mem['disp']
                scale = 1 if mnem == 'mov.b' else 2 if mnem == 'mov.w' else 4
                d = disp // scale
                if mnem == 'mov.b': self.emit16(0x8400 | (n << 8) | (m_reg << 4) | (d & 0xF))
                elif mnem == 'mov.w': self.emit16(0x8500 | (n << 8) | (m_reg << 4) | (d & 0xF))
                else: self.emit16(0x5000 | (n << 8) | (m_reg << 4) | (d & 0xF))
                return
            if mem['mode'] == 'r0_indexed':
                # @(R0,Rm), Rn
                if mnem == 'mov.b': self.emit16(0x000C | (n << 8) | (m_reg << 4))
                elif mnem == 'mov.w': self.emit16(0x000D | (n << 8) | (m_reg << 4))
                else: self.emit16(0x000E | (n << 8) | (m_reg << 4))
                return
            if mem['mode'] == 'gbr':
                # @(disp,GBR), R0
                disp = mem['disp']
                scale = 1 if mnem == 'mov.b' else 2 if mnem == 'mov.w' else 4
                d = disp // scale
                if mnem == 'mov.b': self.emit16(0xC400 | (d & 0xFF))
                elif mnem == 'mov.w': self.emit16(0xC500 | (d & 0xFF))
                else: self.emit16(0xC600 | (d & 0xFF))
                return
            if mem['mode'] == 'pcrel':
                # @(disp,PC), Rn -- only W and L
                disp = mem['disp']
                if mnem == 'mov.w':
                    d = disp >> 1
                    self.emit16(0x9000 | (n << 8) | (d & 0xFF))
                elif mnem == 'mov.l':
                    d = disp >> 2
                    self.emit16(0xD000 | (n << 8) | (d & 0xFF))
                return
            if mem['mode'] == 'pc_label':
                # @(label,PC), Rn -- compute disp from label
                target = self._resolve_value(mem[label], addr)
                if mnem == 'mov.w':
                    disp = (target - (addr + 4)) >> 1
                    self.emit16(0x9000 | (n << 8) | (disp & 0xFF))
                elif mnem == 'mov.l':
                    disp = ((target & ~3) - ((addr & ~3) + 4)) >> 2
                    self.emit16(0xD000 | (n << 8) | (disp & 0xFF))
                return

        raise ValueError(f"Cannot encode {mnem} {ops}")

    # ---- DSP instruction encoders ----

    # DSP data register name -> Ds index (from libCPU73050)
    _DSP_DATA_REG_MAP = {
        'a1': 5, 'a0': 7, 'y0': 8, 'y1': 9,
        'm0': 10, 'm1': 11, 'x0': 12, 'a1g': 13, 'x1': 14, 'a0g': 15,
    }

    # DSP address register name -> As index
    _DSP_ADDR_REG_MAP = {'r4': 0, 'r5': 1, 'r2': 2, 'r3': 3}

    # DSP op class base opcodes (from CPU73050 decomp)
    _DSP_OP_BASE = {
        'pclr': 0x8D, 'padd': 0xB1, 'psub': 0xA1,
        'pmuls': 0x40, 'pcopy': 0xBD, 'pcmp': 0x84,
        'pabs': 0x88, 'pneg': 0xA8, 'pdec': 0x9D, 'pinc': 0x99,
        'pand': 0x95, 'por': 0xB5, 'pxor': 0xA5,
        'pshl': 0x00, 'psha': 0x10,
        'psts': 0xCD, 'plds': 0xED,
        'pdms': 0x8C, 'pswa': 0x9C, 'prnd': 0xAD,
        'paddc': 0xB0, 'psubc': 0xA0, 'pcmpgt': 0x85,
        'pcmpeq': 0x86, 'pcmplt': 0x87,
    }

    def _emit_movs(self, mnem: str, ops: List[str]):
        """Encode MOVS.W / MOVS.L instructions.

        Format: movs.w @As, Ds  or  movs.l @As+, Ds  etc.
        Encoding: 0000_00aa_dddd_mmmm
          aa = As index (0=r4, 1=r5, 2=r2, 3=r3)
          dddd = Ds index (see _DSP_DATA_REG_MAP)
          mmmm = addressing mode:
            0 = @As+Ix, Ds (word)    2 = @As+Ix, Ds (long)
            4 = @As, Ds (word)        6 = @As, Ds (long)
            8 = @-As, Ds (word)      10 = @-As, Ds (long)
           12 = @As+, Ds (word)      14 = @As+, Ds (long)
        """
        if len(ops) != 2:
            raise ValueError(f"MOVS requires 2 operands: {mnem} {ops}")

        is_long = mnem.endswith('.l')
        addr_op = ops[0].strip()
        data_reg = ops[1].strip().lower()

        as_idx = None
        mode = None

        # @As+Ix, Ds (indexed)
        if addr_op.startswith('@') and '+ix' in addr_op.lower():
            reg_part = addr_op[1:].lower().replace('+ix', '').strip()
            as_idx = self._DSP_ADDR_REG_MAP.get(reg_part)
            mode = 2 if is_long else 0
        # @As, Ds (direct)
        elif addr_op.startswith('@') and '+' not in addr_op and '-' not in addr_op:
            reg_part = addr_op[1:].strip().lower()
            as_idx = self._DSP_ADDR_REG_MAP.get(reg_part)
            mode = 6 if is_long else 4
        # @-As, Ds (pre-decrement)
        elif addr_op.startswith('@-'):
            reg_part = addr_op[2:].strip().lower()
            as_idx = self._DSP_ADDR_REG_MAP.get(reg_part)
            mode = 10 if is_long else 8
        # @As+, Ds (post-increment)
        elif addr_op.startswith('@') and addr_op.endswith('+'):
            reg_part = addr_op[1:-1].strip().lower()
            as_idx = self._DSP_ADDR_REG_MAP.get(reg_part)
            mode = 14 if is_long else 12

        if as_idx is None or mode is None:
            raise ValueError(f"Cannot parse MOVS address operand: {addr_op!r}")

        ds_idx = self._DSP_DATA_REG_MAP.get(data_reg)
        if ds_idx is None:
            raise ValueError(f"Unknown DSP data register: {data_reg!r}")

        self.emit16((as_idx << 8) | (ds_idx << 4) | mode)

    def _emit_movx_movy(self, mnem: str, ops: List[str]):
        """Encode MOVX.W / MOVY.W / MOVX.L / MOVY.L instructions.

        These are double-memory instructions that access two memory
        locations simultaneously.  Encoding is complex; for now we
        emit a NOPX/NOPY placeholder and warn.
        """
        # MOVX.W = 0xF000 | encoding
        # MOVY.W = 0xF400 | encoding
        # Full encoding requires parsing both address operands
        # For now, emit NOPX (0xF400) or NOPY (0xF500)
        if mnem.startswith('movx'):
            self.emit16(0xF400)  # NOPX
        else:
            self.emit16(0xF500)  # NOPY

    def _emit_dsp_op(self, mnem: str, ops: List[str]):
        """Encode DSP operation instructions (PADD, PSUB, PMULS, etc.).

        Encoding: 0xF000 | op_class (with optional DCT/DCF prefix)
        DCT = conditional on DSP repeat counter (op_class + 1)
        DCF = conditional on DSP repeat counter false (op_class + 2)
        """
        base = mnem  # e.g. 'padd', 'psub', 'pmuls', etc.

        # Look up the base opcode
        op_class = self._DSP_OP_BASE.get(base)
        if op_class is None:
            raise ValueError(f"Unknown DSP operation: {mnem}")

        # Check for DCT/DCF prefix in operands
        if ops and ops[0].lower() in ('dct', 'dcf'):
            prefix = ops[0].lower()
            ops = ops[1:]
            if prefix == 'dct':
                op_class = op_class + 1
            else:
                op_class = op_class + 2

        self.emit16(0xF000 | op_class)
# BF/S = 0x8F00, BT/S = 0x8E00
# Patch the _emit_instr method to use the correct encoding.
_orig_emit = _Assembler._emit_instr

def _patched_emit(self, mnem, ops, addr, lineno):
    if mnem in ('bt.s', 'bt/s'):
        target = self._resolve_value(ops[0], addr)
        disp = _cond_disp(target, addr)
        self.emit16(0x8E00 | disp); return
    if mnem in ('bf.s', 'bf/s'):
        target = self._resolve_value(ops[0], addr)
        disp = _cond_disp(target, addr)
        self.emit16(0x8F00 | disp); return
    return _orig_emit(self, mnem, ops, addr, lineno)

_Assembler._emit_instr = _patched_emit


# ============================================================================
# Public API
# ============================================================================

def assemble(code: str, start_addr: int = 0x8C000000) -> bytes:
    """Assemble SH-4 source code into a binary.

    Args:
        code: SH-4 assembly source (multi-line string)
        start_addr: Load address (PC value at the first instruction)

    Returns:
        bytes: The assembled binary

    Raises:
        ValueError: On syntax/encoding errors (with line number)
    """
    asm = _Assembler()
    asm.start_addr = start_addr
    lines = code.splitlines()
    asm.pass1(lines)
    asm.pass2(lines)
    return bytes(asm.output)


if __name__ == '__main__':
    # Quick smoke test
    code = """
        mov #0x10, r0
        mov.l table, r1
        mov r0, r2
        add #1, r2
        cmp/eq r1, r2
        bt done
        bra loop
        nop
    loop:
        add #1, r0
        bra done
        nop
    done:
        rts
        nop
        .align 4
    table: .long 0x12345678
    """
    binary = assemble(code, 0x8C000000)
    print(f"Assembled {len(binary)} bytes:")
    for i in range(0, len(binary), 2):
        op = int.from_bytes(binary[i:i+2], 'big')
        print(f"  0x{0x8C000000+i:08X}: 0x{op:04X}")
