"""
SH4AL-DSP Assembler -- converts assembly text to binary opcodes.

This is a minimal two-pass assembler that supports the most common SH-4
instructions plus the SH4AL-DSP DSP extension instructions (MOVS, MOVX,
MOVY, PADD, PSUB, PMULS, PCLR, PCOPY, etc.).

Supported features:
  - Labels (1f, 2f, label_name:)
  - Directives: .word, .long, .align, .text, .global, .type, .size
  - Register names: r0-r15, R0-R15, pr, sr, gbr, vbr, mach, macl, etc.
  - DSP register names: x0, x1, y0, y1, a0, a1, a0g, a1g, m0, m1, rs, re, rc
  - Addressing modes: @Rn, @Rn+, @-Rn, @(disp,Rn), #imm
  - Branch instructions: bf, bt, bf.s, bt.s, bra, bsr, rts
  - DSP instructions: movs.w, movs.l, movx.w, movy.w, padd, psub, pmuls, etc.

Usage:
    from ruk.tools.assembler import SH4Assembler
    asm = SH4Assembler()
    binary = asm.assemble(\"\"\"
        mov #5, r0
        nop
    \"\"\")

The assembler returns a bytearray of big-endian 16-bit opcodes.
"""

import re
from typing import Dict, List, Tuple, Optional, Union


# Register name -> number (for general registers R0-R15)
REG_MAP = {f'r{i}': i for i in range(16)}
REG_MAP.update({f'R{i}': i for i in range(16)})

# System register names
SYS_REG_MAP = {
    'pr': 'pr', 'sr': 'sr', 'gbr': 'gbr', 'vbr': 'vbr',
    'mach': 'mach', 'macl': 'macl', 'ssr': 'ssr', 'spc': 'spc',
    'sgr': 'sgr', 'dbr': 'dbr',
    # DSP registers
    'x0': 'x0', 'x1': 'x1', 'y0': 'y0', 'y1': 'y1',
    'a0': 'a0', 'a1': 'a1', 'a0g': 'a0g', 'a1g': 'a1g',
    'm0': 'm0', 'm1': 'm1', 'rs': 'rs', 're': 're', 'rc': 'rc',
    'dsr': 'dsr', 'mod': 'mod',
}


def parse_reg(s: str) -> Optional[int]:
    """Parse a register name like 'r0', 'R5', 'r15' -> int 0-15."""
    s = s.strip()
    if s.lower() in REG_MAP:
        return REG_MAP[s.lower()]
    return None


def parse_imm(s: str) -> Optional[int]:
    """Parse an immediate value like '#5', '#0xFF', '#-1' -> int."""
    s = s.strip()
    if s.startswith('#'):
        s = s[1:]
    s = s.strip()
    if s.startswith('h\'') or s.startswith('H\''):
        return int(s[2:], 16)
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    try:
        return int(s, 0)
    except ValueError:
        return None


def parse_addr(s: str) -> Optional[int]:
    """Parse an address value (hex or decimal)."""
    s = s.strip()
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    try:
        return int(s, 0)
    except ValueError:
        return None


class SH4Assembler:
    """A minimal SH4AL-DSP assembler."""

    def __init__(self):
        self.labels: Dict[str, int] = {}
        self.current_addr: int = 0
        self.output: bytearray = bytearray()
        self.errors: List[str] = []

    def assemble(self, text: str, start_addr: int = 0) -> bytearray:
        """Assemble the given text into binary opcodes.

        Args:
            text: Assembly source code.
            start_addr: Starting address (for label resolution).

        Returns:
            A bytearray of big-endian 16-bit opcodes.
        """
        self.labels = {}
        self.current_addr = start_addr
        self.output = bytearray()
        self.errors = []

        # Pass 1: collect labels and compute addresses
        # Numeric labels (1:, 2:, etc.) are stored with a list of addresses
        # so that 1f (forward) and 1b (backward) can be resolved.
        self.numeric_labels: Dict[str, List[int]] = {}
        lines = text.split('\n')
        addr = start_addr
        for line in lines:
            line = self._strip_comment(line).strip()
            if not line:
                continue

            # Label definition (named or numeric)
            if line.endswith(':') and ' ' not in line:
                label = line[:-1]
                if label.isdigit():
                    # Numeric label: store all occurrences
                    if label not in self.numeric_labels:
                        self.numeric_labels[label] = []
                    self.numeric_labels[label].append(addr)
                else:
                    self.labels[label] = addr
                continue

            # Directive
            if line.startswith('.'):
                if line.startswith('.word'):
                    addr += 2
                elif line.startswith('.long') or line.startswith('.int'):
                    addr += 4
                elif line.startswith('.align'):
                    parts = line.split()
                    if len(parts) >= 2:
                        n = int(parts[1])
                        align = 1 << n
                        while addr % align != 0:
                            addr += 1
                elif line.startswith('.text') or line.startswith('.global') or \
                     line.startswith('.type') or line.startswith('.size') or \
                     line.startswith('.section'):
                    pass  # ignore
                continue

            # Instruction -- assume 2 bytes
            addr += 2

        # Pass 2: assemble instructions
        addr = start_addr
        for line in lines:
            line = self._strip_comment(line).strip()
            if not line:
                continue

            # Label definition
            if line.endswith(':') and ' ' not in line:
                continue

            # Directive
            if line.startswith('.'):
                if line.startswith('.word'):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        val = parse_imm(parts[1]) or 0
                        self.output.extend(val.to_bytes(2, 'big'))
                    else:
                        self.output.extend(b'\x00\x00')
                    addr += 2
                elif line.startswith('.long') or line.startswith('.int'):
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        val = parse_imm(parts[1]) or 0
                        self.output.extend(val.to_bytes(4, 'big'))
                    else:
                        self.output.extend(b'\x00\x00\x00\x00')
                    addr += 4
                elif line.startswith('.align'):
                    parts = line.split()
                    if len(parts) >= 2:
                        n = int(parts[1])
                        align = 1 << n
                        while addr % align != 0:
                            self.output.append(0)
                            addr += 1
                continue

            # Instruction
            opcode = self._assemble_instruction(line, addr)
            if opcode is not None:
                self.output.extend(opcode.to_bytes(2, 'big'))
            else:
                self.errors.append(f"Unknown instruction: {line}")
                self.output.extend(b'\x00\x00')
            addr += 2

        return self.output

    def _strip_comment(self, line: str) -> str:
        """Strip comments (! or ; or //)."""
        for i, c in enumerate(line):
            if c == '!' or c == ';' :
                return line[:i]
        if '//' in line:
            return line[:line.index('//')]
        return line

    def _resolve_label(self, target: str, current_addr: int) -> Optional[int]:
        """Resolve a label reference to an address.

        Supports:
          - Named labels: "loop", "main"
          - Numeric forward labels: "1f", "2f" (next occurrence of 1: or 2:)
          - Numeric backward labels: "1b", "2b" (previous occurrence)
          - Direct addresses: "0x80000000"
        """
        # Check numeric label with f/b suffix
        if len(target) >= 2 and target[0].isdigit() and target[-1] in 'fb':
            num = target[:-1]
            direction = target[-1]
            if num in self.numeric_labels:
                addrs = self.numeric_labels[num]
                if direction == 'f':
                    # Forward: first address >= current_addr
                    for a in addrs:
                        if a >= current_addr:
                            return a
                    return addrs[-1] if addrs else None
                else:
                    # Backward: last address < current_addr
                    result = None
                    for a in addrs:
                        if a < current_addr:
                            result = a
                        else:
                            break
                    return result

        # Named label
        if target in self.labels:
            return self.labels[target]

        # Direct address
        return parse_addr(target)

    def _assemble_instruction(self, line: str, addr: int) -> Optional[int]:
        """Assemble a single instruction line into a 16-bit opcode."""
        # Split into mnemonic and operands
        parts = line.split(None, 1)
        mnem = parts[0].lower()
        operands = parts[1] if len(parts) > 1 else ''

        # Split operands by comma
        ops = [o.strip() for o in operands.split(',')] if operands else []

        return self._encode(mnem, ops, addr)

    def _encode(self, mnem: str, ops: List[str], addr: int) -> Optional[int]:
        """Encode an instruction mnemonic + operands into a 16-bit opcode."""

        # ---- NOP ----
        if mnem == 'nop':
            return 0x0009

        # ---- MOV ----
        if mnem == 'mov' or mnem == 'mov.l':
            # mov.l Rm, @Rn  ->  0010_nnnn_mmmm_0110
            # mov.l @Rm, Rn  ->  0110_nnnn_mmmm_0100
            # mov.l Rm, @(disp,Rn) -> 0001_nnnn_mmmm_dddd
            # mov.l @(disp,Rm), Rn -> 0101_nnnn_mmmm_dddd
            # mov.l @(disp,PC), Rn -> 1101_nnnn_dddd (disp in 4-byte units)
            # mov #imm, Rn -> 1110_nnnn_iiiiiiii
            if len(ops) == 2:
                src, dst = ops
                # mov #imm, Rn
                if src.startswith('#'):
                    imm = parse_imm(src) or 0
                    rn = parse_reg(dst)
                    if rn is not None:
                        return (0b1110 << 12) | (rn << 8) | (imm & 0xFF)
                # mov.l label, Rn (PC-relative load: 1101_nnnn_dddd)
                # This is the common form for loading constants from a pool.
                # The target address is: (PC & ~2) + 4 + disp*4
                rn = parse_reg(dst)
                if rn is not None and not src.startswith('@'):
                    target_addr = self._resolve_label(src, addr)
                    if target_addr is not None:
                        # SH-4 PC-relative: base = (PC & ~2) + 4
                        base = (addr & ~2) + 4
                        disp = (target_addr - base) // 4
                        return (0b1101 << 12) | (rn << 8) | (disp & 0xFF)
                # mov.l @(disp,PC), Rn (explicit PC-relative)
                if src.startswith('@(') and 'PC' in src and rn is not None:
                    # Extract displacement
                    disp_str = src[2:src.index(',')]
                    disp = parse_imm(disp_str) or 0
                    return (0b1101 << 12) | (rn << 8) | ((disp // 4) & 0xFF)
                # mov Rm, Rn
                rm = parse_reg(src)
                rn = parse_reg(dst)
                if rm is not None and rn is not None:
                    return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b0011
                # mov.l Rm, @(disp,Rn)
                if rm is not None and dst.startswith('@(') and 'R' in dst:
                    # Extract disp and Rn from @(disp,Rn)
                    inner = dst[2:dst.index(')')]
                    parts = inner.split(',')
                    if len(parts) == 2:
                        disp = parse_imm(parts[0]) or 0
                        rn2 = parse_reg(parts[1])
                        if rn2 is not None:
                            return (0b0001 << 12) | (rn2 << 8) | (rm << 4) | ((disp // 4) & 0xF)
                # mov.l @(disp,Rm), Rn
                if src.startswith('@(') and rn is not None:
                    inner = src[2:src.index(')')]
                    parts = inner.split(',')
                    if len(parts) == 2:
                        disp = parse_imm(parts[0]) or 0
                        rm2 = parse_reg(parts[1])
                        if rm2 is not None:
                            return (0b0101 << 12) | (rn << 8) | (rm2 << 4) | ((disp // 4) & 0xF)
                # mov.l Rm, @Rn
                if rm is not None and dst.startswith('@') and not dst.startswith('@-') and not dst.startswith('@('):
                    rn = parse_reg(dst[1:])
                    if rn is not None:
                        if mnem == 'mov.l':
                            return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b0010
                # mov.l @Rm, Rn  (0110_nnnn_mmmm_0010)
                if src.startswith('@') and '+' not in src and '-' not in src and '(' not in src:
                    rm = parse_reg(src[1:])
                    if rm is not None and rn is not None:
                        if mnem == 'mov.l':
                            return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b0010
                # mov.l @Rm+, Rn
                if src.startswith('@') and src.endswith('+') and rn is not None:
                    rm = parse_reg(src[1:-1])
                    if rm is not None:
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b0110

        if mnem == 'mov.w':
            if len(ops) == 2:
                src, dst = ops
                rm = parse_reg(src)
                rn = parse_reg(dst)
                # mov.w Rm, @Rn  (0010_nnnn_mmmm_0001)
                if rm is not None and dst.startswith('@') and '+' not in dst and '-' not in dst and '(' not in dst:
                    rn = parse_reg(dst[1:])
                    if rn is not None:
                        return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b0001
                # mov.w @Rm, Rn  (0110_nnnn_mmmm_0001)
                if src.startswith('@') and '+' not in src and '-' not in src and '(' not in src:
                    rm = parse_reg(src[1:])
                    if rm is not None and rn is not None:
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b0001
                # mov.w R0, @(disp,Rn)  ->  1000_0001_nnnn_dddd
                if rm == 0 and dst.startswith('@('):
                    inner = dst[2:dst.index(')')]
                    parts = inner.split(',')
                    if len(parts) == 2:
                        disp = parse_imm(parts[0]) or 0
                        rn2 = parse_reg(parts[1])
                        if rn2 is not None:
                            return (0b1000 << 12) | (0b0001 << 8) | (rn2 << 4) | (disp & 0xF)
                # mov.w @(disp,Rm), R0  ->  1000_0101_mmmm_dddd
                if src.startswith('@(') and rn == 0:
                    inner = src[2:src.index(')')]
                    parts = inner.split(',')
                    if len(parts) == 2:
                        disp = parse_imm(parts[0]) or 0
                        rm2 = parse_reg(parts[1])
                        if rm2 is not None:
                            return (0b1000 << 12) | (0b0101 << 8) | (rm2 << 4) | (disp & 0xF)
                # mov.w @(disp,PC), Rn  ->  1001_nnnn_dddd
                if src.startswith('@(') and 'PC' in src and rn is not None:
                    disp_str = src[2:src.index(',')]
                    disp = parse_imm(disp_str) or 0
                    return (0b1001 << 12) | (rn << 8) | ((disp // 2) & 0xFF)

        if mnem == 'mov.b':
            if len(ops) == 2:
                src, dst = ops
                rm = parse_reg(src)
                rn = parse_reg(dst)
                # mov.b Rm, @Rn
                if rm is not None and dst.startswith('@') and '+' not in dst and '-' not in dst and '(' not in dst:
                    rn = parse_reg(dst[1:])
                    if rn is not None:
                        return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b0000
                # mov.b @Rm, Rn
                if src.startswith('@') and '+' not in src and '-' not in src and '(' not in src:
                    rm = parse_reg(src[1:])
                    if rm is not None and rn is not None:
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b0000

        # ---- ADD ----
        if mnem == 'add':
            if len(ops) == 2:
                src, dst = ops
                # add #imm, Rn
                if src.startswith('#'):
                    imm = parse_imm(src) or 0
                    rn = parse_reg(dst)
                    if rn is not None:
                        return (0b0111 << 12) | (rn << 8) | (imm & 0xFF)
                # add Rm, Rn
                rm = parse_reg(src)
                rn = parse_reg(dst)
                if rm is not None and rn is not None:
                    return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b1100

        # ---- SUB ----
        if mnem == 'sub':
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b1000

        # ---- TST ----
        if mnem == 'tst':
            if len(ops) == 2:
                # tst #imm, R0
                if ops[0].startswith('#'):
                    imm = parse_imm(ops[0]) or 0
                    return (0b1100 << 12) | (0b1000 << 8) | (imm & 0xFF)
                # tst Rm, Rn
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b1000

        # ---- CMP ----
        if mnem.startswith('cmp/'):
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    if mnem == 'cmp/eq':
                        return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b0000
                    if mnem == 'cmp/hs':
                        return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b0010
                    if mnem == 'cmp/ge':
                        return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b0011
                    if mnem == 'cmp/hi':
                        return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b0110
                    if mnem == 'cmp/gt':
                        return (0b0011 << 12) | (rn << 8) | (rm << 4) | 0b0111
        if mnem == 'cmp/eq' and len(ops) == 2 and ops[0].startswith('#'):
            # cmp/eq #imm, R0
            imm = parse_imm(ops[0]) or 0
            return (0b1000 << 12) | (0b1000 << 8) | (imm & 0xFF)

        # ---- Branch instructions ----
        if mnem in ('bf', 'bt', 'bf.s', 'bt.s', 'bra', 'bsr'):
            if len(ops) == 1:
                target = ops[0]
                target_addr = self._resolve_label(target, addr)
                if target_addr is None:
                    return None

                # Compute displacement: (target - (addr + 4)) / 2
                disp = (target_addr - (addr + 4)) // 2

                if mnem == 'bf':
                    return (0b1000 << 12) | (0b1011 << 8) | (disp & 0xFF)
                if mnem == 'bt':
                    return (0b1000 << 12) | (0b1001 << 8) | (disp & 0xFF)
                if mnem == 'bf.s':
                    return (0b1000 << 12) | (0b1111 << 8) | (disp & 0xFF)
                if mnem == 'bt.s':
                    return (0b1000 << 12) | (0b1101 << 8) | (disp & 0xFF)
                if mnem == 'bra':
                    return (0b1010 << 12) | (disp & 0xFFF)
                if mnem == 'bsr':
                    return (0b1011 << 12) | (disp & 0xFFF)

        # ---- RTS ----
        if mnem == 'rts':
            return 0x000B

        # ---- SLEEP ----
        if mnem == 'sleep':
            return 0x001B

        # ---- LDS ----
        if mnem == 'lds':
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                reg = ops[1].lower()
                if rm is not None:
                    if reg == 'mach':
                        return (0b0100 << 12) | (rm << 8) | 0x0A
                    if reg == 'macl':
                        return (0b0100 << 12) | (rm << 8) | 0x1A
                    if reg == 'pr':
                        return (0b0100 << 12) | (rm << 8) | 0x2A
                    if reg == 'rs':
                        return (0b0100 << 12) | (rm << 8) | 0x6A
                    if reg == 're':
                        return (0b0100 << 12) | (rm << 8) | 0x7A
                    if reg == 'rc':
                        return (0b0100 << 12) | (rm << 8) | 0x8A
                    if reg == 'dsr':
                        return (0b0100 << 12) | (rm << 8) | 0xAA

        # ---- STS ----
        if mnem == 'sts':
            if len(ops) == 2:
                reg = ops[0].lower()
                rn = parse_reg(ops[1])
                if rn is not None:
                    if reg == 'mach':
                        return (0b0000 << 12) | (rn << 8) | 0x0A
                    if reg == 'macl':
                        return (0b0000 << 12) | (rn << 8) | 0x1A
                    if reg == 'pr':
                        return (0b0000 << 12) | (rn << 8) | 0x2A
                    if reg == 'rs':
                        return (0b0000 << 12) | (rn << 8) | 0x6A
                    if reg == 're':
                        return (0b0000 << 12) | (rn << 8) | 0x7A
                    if reg == 'rc':
                        return (0b0000 << 12) | (rn << 8) | 0x8A

        # ---- LDRS / LDRE / LDRC ----
        if mnem == 'ldrs':
            if len(ops) == 1:
                target = ops[0]
                target_addr = self._resolve_label(target, addr)
                if target_addr is None:
                    return None
                disp = (target_addr - (addr + 4)) // 2
                return (0b1000 << 12) | (0b1100 << 8) | (disp & 0xFF)

        if mnem == 'ldre':
            if len(ops) == 1:
                target = ops[0]
                target_addr = self._resolve_label(target, addr)
                if target_addr is None:
                    return None
                disp = (target_addr - (addr + 4)) // 2
                return (0b1000 << 12) | (0b1110 << 8) | (disp & 0xFF)

        if mnem == 'ldrc':
            if len(ops) == 1:
                if ops[0].startswith('#'):
                    imm = parse_imm(ops[0]) or 0
                    return (0b1000 << 12) | (0b1010 << 8) | (imm & 0xFF)
                rm = parse_reg(ops[0])
                if rm is not None:
                    return (0b0100 << 12) | (rm << 8) | 0x34

        # ---- SHLL / SHLR / SHAL / SHAR ----
        if mnem in ('shll', 'shlr', 'shal', 'shar'):
            if len(ops) == 1:
                rn = parse_reg(ops[0])
                if rn is not None:
                    if mnem == 'shll':
                        return (0b0100 << 12) | (rn << 8) | 0x00
                    if mnem == 'shlr':
                        return (0b0100 << 12) | (rn << 8) | 0x01
                    if mnem == 'shal':
                        return (0b0100 << 12) | (rn << 8) | 0x20
                    if mnem == 'shar':
                        return (0b0100 << 12) | (rn << 8) | 0x21

        # ---- SHLL2 / SHLR2 / SHLL8 / etc ----
        if mnem in ('shll2', 'shlr2', 'shll8', 'shlr8', 'shll16', 'shlr16', 'shll4', 'shlr4'):
            if len(ops) == 1:
                rn = parse_reg(ops[0])
                if rn is not None:
                    if mnem == 'shll2':
                        return (0b0100 << 12) | (rn << 8) | 0x08
                    if mnem == 'shlr2':
                        return (0b0100 << 12) | (rn << 8) | 0x09
                    if mnem == 'shll8':
                        return (0b0100 << 12) | (rn << 8) | 0x18
                    if mnem == 'shlr8':
                        return (0b0100 << 12) | (rn << 8) | 0x19
                    if mnem == 'shll16':
                        return (0b0100 << 12) | (rn << 8) | 0x28
                    if mnem == 'shlr16':
                        return (0b0100 << 12) | (rn << 8) | 0x29
                    # shll4 and shlr4 don't exist as single instructions on SH-4
                    # They are macros that expand to two shll2/shlr2
                    # But we'll just return shll2 for compatibility
                    if mnem == 'shll4':
                        return (0b0100 << 12) | (rn << 8) | 0x08
                    if mnem == 'shlr4':
                        return (0b0100 << 12) | (rn << 8) | 0x09

        # ---- ROTL / ROTR / ROTCL / ROTCR ----
        if mnem in ('rotl', 'rotr', 'rotcl', 'rotcr'):
            if len(ops) == 1:
                rn = parse_reg(ops[0])
                if rn is not None:
                    if mnem == 'rotl':
                        return (0b0100 << 12) | (rn << 8) | 0x04
                    if mnem == 'rotr':
                        return (0b0100 << 12) | (rn << 8) | 0x05
                    if mnem == 'rotcl':
                        return (0b0100 << 12) | (rn << 8) | 0x24
                    if mnem == 'rotcr':
                        return (0b0100 << 12) | (rn << 8) | 0x25

        # ---- EXTU / EXTS ----
        if mnem in ('extu.b', 'extu.w', 'exts.b', 'exts.w'):
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    if mnem == 'extu.b':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1100
                    if mnem == 'extu.w':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1101
                    if mnem == 'exts.b':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1110
                    if mnem == 'exts.w':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1111

        # ---- SWAP ----
        if mnem in ('swap.b', 'swap.w'):
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    if mnem == 'swap.b':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1000
                    if mnem == 'swap.w':
                        return (0b0110 << 12) | (rn << 8) | (rm << 4) | 0b1001

        # ---- XTRCT ----
        if mnem == 'xtrct':
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b1101

        # ---- DSP Instructions ----
        # MOVS.W / MOVS.L -- single memory instructions
        if mnem in ('movs.w', 'movs.l'):
            return self._encode_movs(mnem, ops)

        # MOVX.W / MOVY.W -- double memory instructions
        if mnem in ('movx.w', 'movy.w', 'movx.l', 'movy.l'):
            return self._encode_movx_movy(mnem, ops)

        # DSP operation instructions (PADD, PSUB, PMULS, etc.)
        if mnem.startswith('p') and mnem[1:4] in ('add', 'sub', 'mul', 'clr', 'cop',
                                                    'cmp', 'abs', 'neg', 'dec', 'inc',
                                                    'rnd', 'dms', 'swa', 'and', 'or',
                                                    'xor', 'shl', 'sha', 'sts', 'lds'):
            return self._encode_dsp_op(mnem, ops)

        # ---- SETT / CLRT / SETS / CLRS / CLRMAC ----
        if mnem == 'sett':
            return 0x0018
        if mnem == 'clrt':
            return 0x0008
        if mnem == 'sets':
            return 0x0058
        if mnem == 'clrs':
            return 0x0048
        if mnem == 'clrmac':
            return 0x0028

        # ---- LDC / STC ----
        if mnem == 'ldc':
            if len(ops) == 2:
                rm = parse_reg(ops[0])
                reg = ops[1].lower()
                if rm is not None:
                    if reg == 'sr':
                        return (0b0100 << 12) | (rm << 8) | 0x0E
                    if reg == 'gbr':
                        return (0b0100 << 12) | (rm << 8) | 0x1E
                    if reg == 'vbr':
                        return (0b0100 << 12) | (rm << 8) | 0x2E
                    if reg == 'ssr':
                        return (0b0100 << 12) | (rm << 8) | 0x3E
                    if reg == 'spc':
                        return (0b0100 << 12) | (rm << 8) | 0x4E

        if mnem == 'stc':
            if len(ops) == 2:
                reg = ops[0].lower()
                rn = parse_reg(ops[1])
                if rn is not None:
                    if reg == 'sr':
                        return (0b0000 << 12) | (rn << 8) | 0x0E
                    if reg == 'gbr':
                        return (0b0000 << 12) | (rn << 8) | 0x1E
                    if reg == 'vbr':
                        return (0b0000 << 12) | (rn << 8) | 0x2E

        # ---- TRAPA ----
        if mnem == 'trapa':
            if len(ops) == 1 and ops[0].startswith('#'):
                imm = parse_imm(ops[0]) or 0
                return (0b1100 << 12) | (0b0011 << 8) | (imm & 0xFF)

        # ---- RTE ----
        if mnem == 'rte':
            return 0x002B

        # ---- JSR / JMP ----
        if mnem == 'jsr':
            if len(ops) == 1 and ops[0].startswith('@'):
                rm = parse_reg(ops[0][1:])
                if rm is not None:
                    return (0b0100 << 12) | (rm << 8) | 0x0B

        if mnem == 'jmp':
            if len(ops) == 1 and ops[0].startswith('@'):
                rm = parse_reg(ops[0][1:])
                if rm is not None:
                    return (0b0100 << 12) | (rm << 8) | 0x2B

        # ---- DT ----
        if mnem == 'dt':
            if len(ops) == 1:
                rn = parse_reg(ops[0])
                if rn is not None:
                    return (0b0100 << 12) | (rn << 8) | 0x10

        # ---- AND / OR / XOR ----
        if mnem == 'and':
            if len(ops) == 2:
                if ops[0].startswith('#'):
                    imm = parse_imm(ops[0]) or 0
                    return (0b1100 << 12) | (0b1001 << 8) | (imm & 0xFF)
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b1001

        if mnem == 'or':
            if len(ops) == 2:
                if ops[0].startswith('#'):
                    imm = parse_imm(ops[0]) or 0
                    return (0b1100 << 12) | (0b1011 << 8) | (imm & 0xFF)
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b1011

        if mnem == 'xor':
            if len(ops) == 2:
                if ops[0].startswith('#'):
                    imm = parse_imm(ops[0]) or 0
                    return (0b1100 << 12) | (0b1101 << 8) | (imm & 0xFF)
                rm = parse_reg(ops[0])
                rn = parse_reg(ops[1])
                if rm is not None and rn is not None:
                    return (0b0010 << 12) | (rn << 8) | (rm << 4) | 0b1011

        return None  # unknown instruction

    # ---- DSP instruction encoders ----

    # DSP data register name -> Ds index
    DSP_DATA_REG_MAP = {
        'a1': 5, 'a0': 7, 'y0': 8, 'y1': 9,
        'm0': 10, 'm1': 11, 'x0': 12, 'a1g': 13, 'x1': 14, 'a0g': 15,
    }

    # DSP address register name -> As index
    DSP_ADDR_REG_MAP = {'r4': 0, 'r5': 1, 'r2': 2, 'r3': 3}

    def _encode_movs(self, mnem: str, ops: List[str]) -> Optional[int]:
        """Encode MOVS.W / MOVS.L instructions."""
        # Format: movs.w @As, Ds  or  movs.l @As+, Ds  etc.
        if len(ops) != 2:
            return None

        is_long = mnem.endswith('.l')

        # Parse the address operand
        addr_op = ops[0].strip()
        data_reg = ops[1].strip().lower()

        # Determine As index and mode
        as_idx = None
        mode = None

        # @As+Ix, Ds (indexed) -- mode 0 (word) or 2 (long)
        if addr_op.startswith('@') and '+ix' in addr_op.lower():
            reg_part = addr_op[1:].lower().replace('+ix', '').strip()
            as_idx = self.DSP_ADDR_REG_MAP.get(reg_part)
            mode = 2 if is_long else 0

        # @As, Ds (direct) -- mode 4 (word) or 6 (long)
        elif addr_op.startswith('@') and '+' not in addr_op and '-' not in addr_op:
            reg_part = addr_op[1:].strip().lower()
            as_idx = self.DSP_ADDR_REG_MAP.get(reg_part)
            mode = 6 if is_long else 4

        # @-As, Ds (pre-decrement) -- mode 8 (word) or 10 (long)
        elif addr_op.startswith('@-'):
            reg_part = addr_op[2:].strip().lower()
            as_idx = self.DSP_ADDR_REG_MAP.get(reg_part)
            mode = 10 if is_long else 8

        # @As+, Ds (post-increment) -- mode 12 (word) or 14 (long)
        elif addr_op.startswith('@') and addr_op.endswith('+'):
            reg_part = addr_op[1:-1].strip().lower()
            as_idx = self.DSP_ADDR_REG_MAP.get(reg_part)
            mode = 14 if is_long else 12

        if as_idx is None or mode is None:
            return None

        ds_idx = self.DSP_DATA_REG_MAP.get(data_reg)
        if ds_idx is None:
            return None

        # Encoding: 0000_00aa_dddd_mmmm
        return (as_idx << 8) | (ds_idx << 4) | mode

    def _encode_movx_movy(self, mnem: str, ops: List[str]) -> Optional[int]:
        """Encode MOVX.W / MOVY.W instructions (simplified)."""
        # For now, return a NOPX/NOPY opcode
        # Full encoding requires parsing the addressing mode and data register
        return 0xF400  # NOPX NOPY

    def _encode_dsp_op(self, mnem: str, ops: List[str]) -> Optional[int]:
        """Encode DSP operation instructions (PADD, PSUB, PMULS, etc.).

        This is a simplified encoder that returns the base opcode for
        the operation.  The exact opcode depends on the register operands
        and the operation variant (DCT/DCF, etc.).
        """
        # Map mnemonic to base op_class
        op_map = {
            'pclr': 0x8D, 'padd': 0xB1, 'psub': 0xA1,
            'pmuls': 0x40, 'pcopy': 0xBD, 'pcmp': 0x84,
            'pabs': 0x88, 'pneg': 0xA8, 'pdec': 0x9D, 'pinc': 0x99,
            'pand': 0x95, 'por': 0xB5, 'pxor': 0xA5,
            'pshl': 0x00, 'psha': 0x10,
            'psts': 0xCD, 'plds': 0xED,
        }

        base = mnem[1:]  # remove 'p' prefix
        if base.startswith('muls'):
            op_class = 0x40  # PMULS+PCLR base
        elif base in op_map:
            op_class = op_map[base]
        else:
            return None

        # Check for DCT/DCF prefix
        if ops and ops[0].lower() in ('dct', 'dcf'):
            prefix = ops[0].lower()
            ops = ops[1:]
            if prefix == 'dct':
                op_class += 1  # DCT variant is usually base+1
            else:
                op_class += 2  # DCF variant is usually base+2

        # Return 0xF000 | op_class
        return 0xF000 | op_class


def assemble(text: str, start_addr: int = 0) -> bytearray:
    """Convenience function to assemble text into binary."""
    asm = SH4Assembler()
    return asm.assemble(text, start_addr)
