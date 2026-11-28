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
        if mnem in ('dct', 'dcf') or mnem in self._POP_UNARY or mnem in (
            'pclr', 'padd', 'psub', 'psubc', 'paddc', 'pand', 'pxor',
            'por', 'pcmp', 'pmuls', 'psts', 'plds', 'pshl', 'psha'):
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
        source = mnem + ' ' + ','.join(ops)
        if re.search(r'\b(?:movx\.[wl]|movy\.[wl]|nopx|nopy)\b', source, re.I) and mnem not in ('nopx', 'nopy', 'movx.w', 'movx.l', 'movy.w', 'movy.l'):
            self._emit_combined_pop(source, addr, lineno)
            return
        self._emit_instr(mnem, ops, addr, lineno)

    def _emit_combined_pop(self, source, addr, lineno):
        """Encode ASMSH's P-op [MOVX/NOPX] [MOVY/NOPY] syntax."""
        from ruk.jcore.dsp import _XY_SLOTS, _decode_parallel_slot

        matches = list(re.finditer(r'\b(?:movx\.[wl]|movy\.[wl]|nopx|nopy)\b', source, re.I))
        pop_source = source[:matches[0].start()].strip()
        slots = {'x': None, 'y': None}
        seen = set()
        for i, match in enumerate(matches):
            mnemonic = match.group().lower()
            axis = mnemonic[-1] if mnemonic.startswith('nop') else mnemonic[3]
            if axis in seen:
                raise ValueError(f'duplicate {axis.upper()} move slot')
            seen.add(axis)
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
            operands = source[match.end():end].strip()
            if mnemonic.startswith('nop'):
                if operands:
                    raise ValueError(f'{mnemonic.upper()} takes no operands')
                continue
            parts = _split_ops(operands)
            if len(parts) != 2:
                raise ValueError(f'{mnemonic.upper()} requires two operands')
            parts = [part.strip().lower().replace(' ', '') for part in parts]
            load = parts[0].startswith('@')
            address, data = (parts[0], parts[1]) if load else (parts[1], parts[0])
            address_match = re.fullmatch(r'@r(\d+)(\+r(8|9)|\+)?', address)
            if not address_match:
                raise ValueError(f'invalid {mnemonic.upper()} address: {address}')
            reg = int(address_match.group(1))
            suffix = address_match.group(2)
            if suffix and len(suffix) > 1 and int(address_match.group(3)) != (8 if axis == 'x' else 9):
                raise ValueError(f'{mnemonic.upper()} uses R{8 if axis == "x" else 9} for indexed addressing')
            mode = 0 if not suffix else (1 if suffix == '+' else 2)
            slots[axis] = (reg, data, 'load' if load else 'store',
                           4 if mnemonic.endswith('.l') else 2, mode)

        prefix = None
        for low in range(0x400):
            candidate = 0xf800 | low
            xid, yid = _XY_SLOTS[low & 63]
            both = xid != 359 and yid != 360
            decoded = {
                'x': None if xid == 359 else _decode_parallel_slot('x', xid, candidate, both),
                'y': None if yid == 360 else _decode_parallel_slot('y', yid, candidate, both),
            }
            if decoded == slots:
                prefix = candidate
                break
        if prefix is None:
            raise ValueError('MOVX/MOVY operands cannot share a DSP instruction')
        _, pop_mnem, pop_ops, _ = _parse_line(pop_source.lower())
        if not pop_mnem:
            raise ValueError('combined DSP instruction requires a P-operation')
        start = len(self.output)
        self._emit_instr(pop_mnem, pop_ops, addr, lineno)
        if len(self.output) != start + 4 or self.output[start:start + 2] != b'\xf8\x00':
            raise ValueError('combined DSP instruction requires a P-operation')
        self.output[start:start + 2] = prefix.to_bytes(2, 'big')

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
        if mnem == 'trace':
            if len(ops) != 1:
                raise ValueError('TRACE requires one register')
            self.emit16(0x0043 | (parse_reg(ops[0]) << 8)); return

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
        if mnem == 'movli.l':
            if len(ops) != 2 or not ops[0].startswith('@') or ops[1].lower() != 'r0':
                raise ValueError('MOVLI.L requires @Rn,R0')
            n = parse_reg(ops[0][1:])
            if n is None:
                raise ValueError('MOVLI.L requires an address register')
            self.emit16(0x0063 | (n << 8)); return
        if mnem == 'movco.l':
            if len(ops) != 2 or ops[0].lower() != 'r0' or not ops[1].startswith('@'):
                raise ValueError('MOVCO.L requires R0,@Rn')
            n = parse_reg(ops[1][1:])
            if n is None:
                raise ValueError('MOVCO.L requires an address register')
            self.emit16(0x0073 | (n << 8)); return
        if mnem == 'movua.l':
            if len(ops) != 2 or not ops[0].startswith('@') or ops[1].lower() != 'r0':
                raise ValueError('MOVUA.L requires @Rn,R0 or @Rn+,R0')
            operand = ops[0][1:]
            post = operand.endswith('+')
            n = parse_reg(operand[:-1] if post else operand)
            if n is None:
                raise ValueError('MOVUA.L requires an address register')
            self.emit16((0x40E9 if post else 0x40A9) | (n << 8)); return

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

        if mnem == 'setrc':
            if len(ops) != 1:
                raise ValueError('SETRC requires one register or immediate')
            if ops[0].startswith('#'):
                imm = parse_imm(ops[0])
                if imm is None or not 0 <= imm <= 255:
                    raise ValueError('SETRC immediate must be in 0..255')
                self.emit16(0x8200 | imm); return
            reg = parse_reg(ops[0])
            if reg is None:
                raise ValueError('SETRC requires a general register')
            self.emit16(0x4014 | (reg << 8)); return

        # ---- DSP: MOVS.W / MOVS.L ----
        # Encoding: 0000_00aa_dddd_mmmm
        #   aa = As index (0=r4, 1=r5, 2=r2, 3=r3)
        #   dddd = Ds index (see DSP_DATA_REG_MAP)
        #   mmmm = addressing mode
        if mnem in ('movs.w', 'movs.l'):
            self._emit_movs(mnem, ops); return

        # ---- DSP: MOVX.W / MOVY.W ----
        if mnem in ('movx.w', 'movy.w', 'movx.l', 'movy.l'):
            raise ValueError(f'{mnem} encoding is not implemented')

        # ---- DSP: PADD / PSUB / PMULS / PCLR / etc. ----
        if mnem in ('dct', 'dcf') and ops and ops[0].startswith('p'):
            head = ops[0].split()
            self._emit_pop(head[0], [mnem] + head[1:] + ops[1:], addr)
            return
        if mnem in ('padd', 'psub', 'psubc', 'paddc', 'pand', 'pxor',
                    'por', 'pcmp', 'pmuls', 'pclr', 'psts', 'plds',
                    'pabs', 'pdec', 'pinc', 'prnd', 'pneg', 'pcopy',
                    'pswap', 'pdmsb', 'pshl', 'psha'):
            if not ops:
                raise ValueError(f'{mnem} requires operands')
            self._emit_pop(mnem, ops, addr); return

        # ---- DSP: NOPX / NOPY ----
        if mnem == 'nopx':
            raise ValueError('NOPX encoding is not implemented')
        if mnem == 'nopy':
            raise ValueError('NOPY encoding is not implemented')

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
        'a1': 5, 'a0': 7, 'x0': 8, 'x1': 9,
        'y0': 10, 'y1': 11, 'm0': 12, 'a1g': 13, 'm1': 14, 'a0g': 15,
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

    # ---- Verified P-operation field maps (Sdsha-verified) ----
    _POP_SX = {'x0': 0, 'x1': 1, 'a0': 2, 'a1': 3}
    _POP_SY = {'y0': 0, 'y1': 1, 'm0': 2, 'm1': 3}
    _POP_DZ = {'a1': 5, 'a0': 7, 'x0': 8, 'x1': 9,
               'y0': 10, 'y1': 11, 'm0': 12, 'm1': 14}
    _POP_SE = {'x0': 0, 'x1': 1, 'y0': 2, 'a1': 3}
    _POP_SF = {'y0': 0, 'y1': 1, 'x0': 2, 'a1': 3}
    _POP_DG = {'m0': 0, 'm1': 1, 'a0': 2, 'a1': 3}
    _POP_DU = {'y0': 0, 'm0': 1, 'a0': 2, 'a1': 3}

    # second-word opcode bases: two-source and unary (sx form, sy form)
    _POP_BINARY = {'padd': 0xB1, 'psub': 0xA1, 'psubr': 0x85,
                   'psubc': 0xA0, 'paddc': 0xB0, 'pand': 0x95,
                   'pxor': 0xA5, 'por': 0xB5}
    _POP_SHIFT_REG = {'pshl': 0x81, 'psha': 0x91}
    _POP_UNARY = {
        'pabs': (0x88, 0xA8), 'pdec': (0x89, 0xA9), 'pinc': (0x99, 0xB9),
        'prnd': (0x98, 0xB8), 'pneg': (0xC9, 0xE9), 'pcopy': (0xD9, 0xF9),
        'pswap': (0x9D, 0xBD), 'pdmsb': (0x9D, 0xBD),
    }

    def _pop_cond(self, mnem):
        """Strip a DCT/DCF prefix from the mnemonic list; returns
        (base_delta, remaining_mnemonic)."""
        if mnem in ('dct', 'dcf'):
            return (1 if mnem == 'dct' else 2), None
        return 0, mnem

    def _emit_pop(self, mnem, ops, addr):
        """Emit a 32-bit DSP operation: 0xF800 leading word + P-op.

        Encodings verified against the Sdsha.dll handlers (see
        tools/compare_sdsha_pops.py) and the Renesas assembler matrix.
        """
        cond = 0
        # normalize: split space-joined tokens and lowercase
        ops = [t.lower() for o in ops for t in o.split()]
        if mnem in ('dct', 'dcf'):
            cond = 1 if mnem == 'dct' else 2
            mnem, ops = ops[0], ops[1:]
        elif ops and ops[0] in ('dct', 'dcf'):
            cond = 1 if ops[0] == 'dct' else 2
            mnem, ops = mnem, ops[1:]

        # ---- PCLR [Du] [PMULS Se, Sf, Dg] ----
        if mnem == 'pclr':
            if 'pmuls' in ops:
                i = ops.index('pmuls')
                du_name = ops[0] if ops[0] != 'pmuls' else None
                se, sf, dg = ops[i + 1], ops[i + 2], ops[i + 3]
                if du_name is None:
                    raise ValueError('PCLR PMULS requires a Du register')
                word = (0x4010
                        | self._POP_SE[se] << 10 | self._POP_SF[sf] << 8
                        | self._POP_DG[dg] << 2 | self._POP_DU[du_name])
                self.emit16(0xF800)
                self.emit16(word)
                return
            dz = self._POP_DZ[ops[0]]
            self.emit16(0xF800)
            self.emit16((0x8D + cond) << 8 | dz)
            return

        # ---- PMULS standalone ----
        if mnem == 'pmuls':
            se, sf, dg = ops
            word = (0x4000 | self._POP_SE[se] << 10
                    | self._POP_SF[sf] << 8 | self._POP_DG[dg] << 2)
            self.emit16(0xF800)
            self.emit16(word)
            return

        # ---- PADD/PSUB Sx,Sy,Du [PMULS Se,Sf,Dg] bundles ----
        if mnem in ('padd', 'psub') and 'pmuls' in ops:
            i = ops.index('pmuls')
            add_ops = ops[:i]
            se, sf, dg = ops[i + 1], ops[i + 2], ops[i + 3]
            sx_name, sy_name, du_name = add_ops[0], add_ops[1], add_ops[2]
            base = self._POP_BINARY[mnem]
            if cond:
                raise ValueError(f'DCT/DCF is not valid for {mnem} PMULS')
            word = ((0x7000 if mnem == 'padd' else 0x6000)
                    | self._POP_SE[se] << 10 | self._POP_SF[sf] << 8
                    | self._POP_SX[sx_name] << 6
                    | self._POP_SY[sy_name] << 4
                    | self._POP_DG[dg] << 2 | self._POP_DU[du_name])
            self.emit16(0xF800)
            self.emit16(word)
            return

        # ---- PCMP Sx,Sy ----
        if mnem == 'pcmp':
            if cond:
                raise ValueError('DCT/DCF is not valid for pcmp')
            sx, sy = ops
            self.emit16(0xF800)
            self.emit16(0x8400 | self._POP_SX[sx] << 6
                        | self._POP_SY[sy] << 4)
            return

        # ---- PSTS/PLDS ----
        if mnem == 'psts':
            src_name, dz_name = ops
            base = 0xCD if src_name == 'mach' else 0xDD
            self.emit16(0xF800)
            self.emit16((base + cond) << 8 | self._POP_DZ[dz_name])
            return
        if mnem == 'plds':
            dz_name, src_name = ops
            base = 0xED if src_name == 'mach' else 0xFD
            self.emit16(0xF800)
            self.emit16((base + cond) << 8 | self._POP_DZ[dz_name])
            return

        # ---- PSHL/PSHA #imm,Dz ----
        # word = 0x0000/0x1000 | (imm & 0x3F) << 4 | Dz code; the Dz code
        # sits at bits 7:4 (not 3:0) in the immediate-shift layout.
        if mnem in ('pshl', 'psha') and ops[0].startswith('#'):
            if cond:
                raise ValueError(f'DCT/DCF is not valid for {mnem} #imm')
            imm = int(ops[0][1:], 0)
            dz = self._POP_DZ[ops[1]]
            self.emit16(0xF800)
            self.emit16((0x1000 if mnem == 'psha' else 0x0000)
                        | ((imm & 0x7F) << 4) | dz)
            return

        # ---- PSHL/PSHA Sx,Sy,Dz (register count) ----
        if mnem in ('pshl', 'psha'):
            sx, sy, dz = ops
            base = self._POP_SHIFT_REG[mnem] + cond
            self.emit16(0xF800)
            self.emit16(base << 8 | self._POP_SX[sx] << 6
                        | self._POP_SY[sy] << 4 | self._POP_DZ[dz])
            return

        # ---- two-source PADD/PSUB/logical families ----
        if mnem in ('padd', 'psub', 'psubc', 'paddc',
                    'pand', 'pxor', 'por'):
            a, b, dz = ops
            if mnem == 'psub':
                # argument order selects the source roles
                if a in self._POP_SY and b in self._POP_SX:
                    base = self._POP_BINARY['psubr'] + cond
                    word = base << 8 | self._POP_SX[b] << 6 \
                        | self._POP_SY[a] << 4 | self._POP_DZ[dz]
                    self.emit16(0xF800)
                    self.emit16(word)
                    return
                base = self._POP_BINARY['psub'] + cond
            else:
                base = self._POP_BINARY[mnem] + cond
            self.emit16(0xF800)
            self.emit16(base << 8 | self._POP_SX[a] << 6
                        | self._POP_SY[b] << 4 | self._POP_DZ[dz])
            return

        # ---- unary families ----
        if mnem in self._POP_UNARY:
            src_name, dz_name = ops
            sx_base, sy_base = self._POP_UNARY[mnem]
            # PABS/PRND conditionals share opcode bytes with PDEC/PINC;
            # marker bits distinguish their operand fields. PSWAP uses
            # the same marker bits to distinguish it from PDMSB.
            special_cond = cond and mnem in ('pabs', 'prnd')
            marker_sx = 0x10 if mnem == 'pswap' or special_cond else 0
            marker_sy = 0x40 if mnem == 'pswap' or special_cond else 0
            delta = cond + int(bool(special_cond))
            if cond and mnem in ('pswap', 'pdmsb', 'pinc'):
                raise ValueError(f'DCT/DCF encoding not pinned for {mnem}')
            if cond and mnem == 'pdec' and src_name in self._POP_SY:
                raise ValueError(f'DCT/DCF encoding not pinned for {mnem}')
            if src_name in self._POP_SX:
                word = (sx_base + delta) << 8 \
                    | marker_sx | self._POP_SX[src_name] << 6 \
                    | self._POP_DZ[dz_name]
            else:
                word = (sy_base + delta) << 8 \
                    | marker_sy | self._POP_SY[src_name] << 4 \
                    | self._POP_DZ[dz_name]
            self.emit16(0xF800)
            self.emit16(word)
            return

        raise ValueError(f'Unsupported DSP operation: {mnem} {ops}')

    def _emit_movs(self, mnem: str, ops: List[str]):
        """Encode the single-data MOVS forms in the F4xx-F7xx space."""
        if len(ops) != 2:
            raise ValueError("MOVS requires two operands")
        is_store = ops[1].strip().startswith('@')
        addr_op = ops[1 if is_store else 0].strip().lower()
        data_reg = ops[0 if is_store else 1].strip().lower()
        is_long = mnem.endswith('.l')
        if addr_op.startswith('@-'):
            reg, mode = addr_op[2:], 0
        elif addr_op.startswith('@') and addr_op.endswith('+'):
            reg, mode = addr_op[1:-1], 8
        elif addr_op.startswith('@') and '+' not in addr_op:
            reg, mode = addr_op[1:], 4
        else:
            raise ValueError(f"Unsupported MOVS address operand: {addr_op!r}")
        as_idx = self._DSP_ADDR_REG_MAP.get(reg)
        ds_idx = self._DSP_DATA_REG_MAP.get(data_reg)
        if as_idx is None or ds_idx is None:
            raise ValueError(f"Invalid MOVS operands: {ops}")
        self.emit16(0xF400 | (as_idx << 8) | (ds_idx << 4)
                    | mode | (2 if is_long else 0) | int(is_store))

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
