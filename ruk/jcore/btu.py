"""SH7305 bytecode translation unit; see docs/sdsha-j-jp.md for evidence."""
from collections import Counter

from ruk.jcore.mmio import MMIODevice
from ruk.jcore.btu_table import OPCODE_GATES, OPCODE_LENGTHS

BASE = 0xFF280000
SH3_BASE = 0xA4170000
SIZE = 0x100
MASK = 0xffffffff

# Sdsha 1000d800/1000d6e0 accepts aligned longword accesses only.
REGISTER_MASKS = {
    0: 0xd180ffff, 4: 0xfffff, 8: 0xffff,
    0x0c: 0xff, 0x10: 0xff, 0x14: 0xff,
    0x18: 0x7fffffff, 0x1c: MASK, 0x44: 0xb000ffff, 0x48: MASK,
}


class BTUEntryBreakpoint(Exception):
    """Host debugger pause immediately before a J_JP handoff."""


def signed(v, bits=32):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class SH7305BTU:
    def __init__(self, cpg=None, max_instructions=1000000, *, byteorder='big'):
        if byteorder not in ('big', 'little'):
            raise ValueError('BTU byteorder must be big or little')
        self.cpg = cpg
        self.byteorder = byteorder
        self.max_instructions = max_instructions
        self.regs = bytearray(SIZE)
        self.break_on_entry = False
        self.entries = 0
        self.enabled_entries = 0
        self.bytecodes = Counter()
        self.exits = Counter()
        self.last_entry = None
        self.last_exit = None
        self.first_handoffs = []
        self.write32(BASE + 4, 0x000edcba)
        self.write32(BASE + 8, 0x7198)
        self.write32(BASE + 0x44, 0xffcc)
        self.write32(BASE + 0x48, 0xcfcdcecb)

    def read8(self, addr):
        return 0

    def read16(self, addr):
        return 0

    def read32(self, addr):
        off = addr - BASE
        if off not in REGISTER_MASKS:
            return 0
        return int.from_bytes(self.regs[off:off+4], 'big') & REGISTER_MASKS[off]

    def write8(self, addr, value):
        pass

    def write16(self, addr, value):
        pass

    def _store32(self, off, value):
        self.regs[off:off+4] = (value & MASK).to_bytes(4, 'big')

    def write32(self, addr, value):
        off = addr - BASE
        if off not in REGISTER_MASKS:
            return
        value &= REGISTER_MASKS[off]
        if off == 8:
            value = (value & 0xf0ff) | 0x100
        self._store32(off, value)
        if off == 0x18:
            self._store32(0x1c, value)

    def enter(self, cpu, n):
        control = self.read32(BASE)
        self.entries += 1
        self.last_entry = {'pc': cpu.pc, 'register': n, 'java_pc': cpu.regs[n], 'control': control}
        handoff = {'entry': self.last_entry.copy()}
        if len(self.first_handoffs) < 32:
            self.first_handoffs.append(handoff)
        if self.break_on_entry:
            raise BTUEntryBreakpoint(f'J_JP @R{n} at {cpu.pc:#010x}, Java PC {cpu.regs[n]:#010x}')
        # Measured SH7305 behavior: disabled J_JP falls through. Sdsha instead
        # reports simulator error 12 when the feature/control bit is clear.
        if not (control & 0x80000000) or (self.cpg and self.cpg.mstpcr2 & 0x80000000):
            self.exits['disabled'] += 1
            cpu.pc = (cpu.pc + 2) & MASK
            return
        self.enabled_entries += 1
        config = self.read32(BASE + 4)
        loc, spreg, table, jp, scratch = ((config >> shift) & 15 for shift in (16, 12, 8, 4, 0))
        mem, r = cpu.mem, cpu.regs
        pc = r[n]
        # Internally keep a next-free cursor. Bit 23 selects an external
        # top-of-stack cursor (Sdsha 1000ef40/1000ef80).
        top_cursor = bool(control & 0x800000)
        sp = (r[spreg] + (4 if top_cursor else 0)) & MASK
        r[jp] = cpu.pc
        countdown = bool(control & 0x40000000)
        branch_countdown = bool(control & 0x10000000)
        quick_control = self.read32(BASE + 0x44)
        quick_mode = (quick_control >> 28) & 3
        remap = {}
        quick_codes = {0xcb, 0xcc, 0xcd, 0xce, 0xcf, 0xd2, 0xd3, 0xd4, 0xd5, 0xef, 0xf0}
        if quick_control & 0x80000000 and quick_mode != 3:
            fields = self.read32(BASE + 0x48)
            sources = [(fields >> (i * 8)) & 255 for i in range(4)]
            sources += [quick_control & 255, (quick_control >> 8) & 255]
            targets = (0xd2, 0xd3, 0xd4, 0xd5, 0xef, 0xf0) if quick_mode == 1 else (0xcb, 0xce, 0xcd, 0xcf, 0xcc, 0xce)
            for i, source in enumerate(sources):
                remap[source] = (targets[i], 8 + i)

        def read32(addr):
            return mem.read32(addr & MASK)

        def write32(addr, value):
            mem.write32(addr & MASK, value & MASK)

        def operand16():
            return (mem.read8((pc + 1) & MASK) << 8) | mem.read8((pc + 2) & MASK)

        def peek(depth=0):
            return read32(sp - 4 * (depth + 1))

        def push(value):
            nonlocal sp
            write32(sp, value)
            sp = (sp + 4) & MASK

        def pop():
            nonlocal sp
            sp = (sp - 4) & MASK
            return read32(sp)

        def push64(value):
            if self.byteorder == 'little':
                push(value)
                push(value >> 32)
            else:
                push(value >> 32)
                push(value)

        def pop64():
            top, bottom = pop(), pop()
            return (top << 32) | bottom if self.byteorder == 'little' else (bottom << 32) | top

        def exit_to(code, event=False):
            external_sp = (sp - (4 if top_cursor else 0)) & MASK
            # Capture the target before clobbering configured registers.
            target = read32(r[table] - 4 if event else r[table] + op * 4)
            r[0] = code & MASK
            r[spreg] = external_sp
            r[scratch] = 0
            r[jp] = pc & MASK
            cpu.pc = target
            kind = 'event' if event else 'software'
            self.exits[kind] += 1
            self.last_exit = {'kind': kind, 'java_pc': pc, 'opcode': op,
                              'r0': code & MASK, 'stack': external_sp, 'sh_pc': target}
            handoff['exit'] = self.last_exit.copy()

        for _ in range(self.max_instructions):
            op = mem.read8(pc)
            self.bytecodes[op] += 1
            count = self.read32(BASE + 0x1c)
            # 1000e3a0 tests signed underflow before the bytecode. Zero
            # still permits execution and becomes -1. Breakpoint wins.
            expired = countdown and not branch_countdown and bool(count & 0x80000000)
            if expired and op != 0xca:
                self._store32(0x1c, self.read32(BASE + 0x18))
                exit_to(0x10, event=True)
                return
            gate = OPCODE_GATES[op]
            decoded = op
            rejected_quick = False
            if quick_control & 0x80000000:
                if op in remap:
                    decoded, gate = remap[op]
                elif op in quick_codes:
                    rejected_quick = True
            elif control & 0x1000000:
                rejected_quick = 0xcb <= op <= 0xcf
            else:
                rejected_quick = op in (0xd2, 0xd3, 0xd4, 0xd5, 0xef, 0xf0)
            execute = not rejected_quick and gate >= 0 and not (control & (1 << gate))
            if expired and op == 0xca:
                execute = False
            quick_operand = operand16() if execute and decoded in quick_codes else None
            if quick_operand is not None and decoded in (0xcb, 0xcc, 0xcd, 0xce, 0xcf):
                # Legacy format selects operand byte 2. Mode 0 rejects a
                # nonzero byte 1 before touching the object or stack.
                if quick_mode == 0 and quick_operand >> 8:
                    execute = False
            old_sp = sp
            backwards = False
            nextpc = (pc + 1) & MASK

            if execute and decoded in quick_codes:
                store = decoded in (0xce, 0xcf, 0xd3, 0xd5, 0xf0)
                wide = decoded in (0xcd, 0xcf, 0xd4, 0xd5)
                value_words = 2 if wide else 1
                ref = peek(value_words if store else 0)
                if ref == 0:
                    exit_to(1, event=True)
                    return
                index = quick_operand & 255 if decoded in (0xcb, 0xcc, 0xcd, 0xce, 0xcf) else quick_operand >> 8
                addr = ref + (self.read32(BASE + 0x14) + index) * 4
                if store:
                    values = [peek(i) for i in reversed(range(value_words))]
                    for i, value in enumerate(values):
                        write32(addr + i * 4, value)
                    sp = (sp - (value_words + 1) * 4) & MASK
                else:
                    values = [read32(addr + i * 4) for i in range(value_words)]
                    pop()
                    for value in values:
                        push(value)
                nextpc = pc + 3
            elif execute and op == 0x00:
                pass
            elif execute and op == 0x01:
                push(0)
            elif execute and 0x02 <= op <= 0x08:
                push(op - 3)
            elif execute and op in (0x09, 0x0a):
                push64(op - 0x09)
            elif execute and 0x0b <= op <= 0x0f:
                if op <= 0x0d:
                    push((0, 0x3f800000, 0x40000000)[op - 0x0b])
                else:
                    push64((0, 0x3ff0000000000000)[op - 0x0e])
            elif execute and op in (0x10, 0x11):
                if op == 0x10:
                    push(signed(mem.read8((pc + 1) & MASK), 8))
                    nextpc = pc + 2
                else:
                    push(signed(operand16(), 16))
                    nextpc = pc + 3
            elif execute and 0x15 <= op <= 0x2d:
                if op <= 0x19:
                    index = mem.read8((pc + 1) & MASK)
                    wide = op in (0x16, 0x18)
                    nextpc = pc + 2
                else:
                    group, index = divmod(op - 0x1a, 4)
                    wide = group in (1, 3)
                addr = r[loc] + index * 4
                values = [read32(addr + i * 4) for i in range(2 if wide else 1)]
                for value in values:
                    push(value)
            elif execute and 0x36 <= op <= 0x4e:
                if op <= 0x3a:
                    index = mem.read8((pc + 1) & MASK)
                    wide = op in (0x37, 0x39)
                    nextpc = pc + 2
                else:
                    group, index = divmod(op - 0x3b, 4)
                    wide = group in (1, 3)
                addr = r[loc] + index * 4
                values = [peek(i) for i in reversed(range(2 if wide else 1))]
                for i, value in enumerate(values):
                    write32(addr + i * 4, value)
                sp = (sp - len(values) * 4) & MASK
            elif execute and (0x2e <= op <= 0x35 or 0x4f <= op <= 0x56 or op == 0xbe):
                # aastore (53) is unavailable in the Sdsha table and never
                # enters here. Object format comes from +0C/+10, in words.
                store = 0x4f <= op <= 0x56
                wide = op in (0x2f, 0x31, 0x50, 0x52)
                value_words = 2 if wide else 1
                ref = peek(value_words + 1 if store else 0 if op == 0xbe else 1)
                if ref == 0:
                    exit_to(1, event=True)
                    return
                length = read32(ref + self.read32(BASE + 0x10) * 4)
                if op == 0xbe:
                    pop()
                    push(length)
                else:
                    index = peek(value_words if store else 0)
                    if index >= length:  # unsigned check rejects negative indices
                        exit_to(2, event=True)
                        return
                    width = 8 if wide else 1 if op in (0x33, 0x54) else 2 if op in (0x34, 0x35, 0x55, 0x56) else 4
                    addr = (ref + self.read32(BASE + 0x0c) * 4 + index * width) & MASK
                    if store:
                        values = [peek(i) for i in reversed(range(value_words))]
                        if width == 1:
                            mem.write8(addr, values[0] & 255)
                        elif width == 2:
                            mem.write16(addr, values[0] & 0xffff)
                        else:
                            for i, value in enumerate(values):
                                write32(addr + i * 4, value)
                        sp = (sp - (value_words + 2) * 4) & MASK
                    else:
                        if width == 1:
                            values = [signed(mem.read8(addr), 8)]
                        elif width == 2:
                            value = mem.read16(addr)
                            values = [signed(value, 16) if op == 0x35 else value]
                        else:
                            values = [read32(addr + i * 4) for i in range(value_words)]
                        sp = (sp - 8) & MASK
                        for value in values:
                            push(value)
            elif execute and op in (0x57, 0x58):
                sp = (sp - (4 if op == 0x57 else 8)) & MASK
            elif execute and op in (0x59, 0x5a, 0x5b, 0x5c, 0x5f):
                depth = {0x59: 1, 0x5a: 2, 0x5b: 3, 0x5c: 2, 0x5f: 2}[op]
                values = [peek(i) for i in reversed(range(depth))]
                order = {0x59: (0, 0), 0x5a: (1, 0, 1), 0x5b: (2, 0, 1, 2),
                         0x5c: (0, 1, 0, 1), 0x5f: (1, 0)}[op]
                sp = (sp - depth * 4) & MASK
                for i in order:
                    push(values[i])
            elif execute and op in (0x60, 0x64, 0x68, 0x6c, 0x70, 0x78, 0x7a, 0x7c, 0x7e, 0x80, 0x82):
                if op in (0x6c, 0x70) and peek() == 0:
                    exit_to(4, event=True)
                    return
                b, a = pop(), pop()
                if op in (0x6c, 0x70):
                    sa, sb = signed(a), signed(b)
                    quotient = (abs(sa) // abs(sb)) * (-1 if (sa < 0) != (sb < 0) else 1)
                    value = quotient if op == 0x6c else sa - quotient * sb
                else:
                    value = {0x60: lambda: a+b, 0x64: lambda: a-b, 0x68: lambda: a*b,
                             0x78: lambda: a << (b & 31), 0x7a: lambda: signed(a) >> (b & 31),
                             0x7c: lambda: a >> (b & 31), 0x7e: lambda: a & b,
                             0x80: lambda: a | b, 0x82: lambda: a ^ b}[op]()
                push(value)
            elif execute and op in (0x61, 0x65, 0x69, 0x7f, 0x81, 0x83, 0x94):
                b, a = pop64(), pop64()
                if op == 0x94:
                    a, b = signed(a, 64), signed(b, 64)
                    push((a > b) - (a < b))
                else:
                    value = {0x61: lambda: a+b, 0x65: lambda: a-b, 0x69: lambda: a*b,
                             0x7f: lambda: a & b, 0x81: lambda: a | b, 0x83: lambda: a ^ b}[op]()
                    push64(value)
            elif execute and op in (0x79, 0x7b, 0x7d):
                count_bits, value = pop() & 63, pop64()
                value = value << count_bits if op == 0x79 else (signed(value, 64) if op == 0x7b else value) >> count_bits
                push64(value)
            elif execute and op == 0x74:
                push(-pop())
            elif execute and op == 0x75:
                push64(-pop64())
            elif execute and op == 0x85:
                push64(signed(pop()))
            elif execute and op == 0x88:
                push(pop64() & MASK)
            elif execute and op in (0x91, 0x92, 0x93):
                value = pop()
                push(signed(value & 255, 8) if op == 0x91 else value & 0xffff if op == 0x92 else signed(value & 0xffff, 16))
            elif execute and op == 0x84:
                index = mem.read8((pc + 1) & MASK)
                addr = (r[loc] + index * 4) & MASK
                write32(addr, read32(addr) + signed(mem.read8((pc + 2) & MASK), 8))
                nextpc = pc + 3
            elif execute and (0x99 <= op <= 0xa8 or op in (0xc6, 0xc7)):
                offset = signed(operand16(), 16)
                if op in (0xa7, 0xa8):
                    take = True
                else:
                    b = 0 if op <= 0x9e or op in (0xc6, 0xc7) else signed(pop())
                    a = signed(pop())
                    if op <= 0x9e:
                        comparison = op - 0x99
                    elif op <= 0xa4:
                        comparison = op - 0x9f
                    else:
                        comparison = 0 if op in (0xa5, 0xc6) else 1
                    take = (a == b, a != b, a < b, a >= b, a > b, a <= b)[comparison]
                backwards = take and offset <= 0
                if backwards and countdown and branch_countdown and count & 0x80000000:
                    sp = old_sp
                    self._store32(0x1c, self.read32(BASE + 0x18))
                    exit_to(0x10, event=True)
                    return
                if op == 0xa8:
                    push(pc + 3)
                nextpc = pc + (offset if take else 3)
            elif execute and op == 0xa9:
                index = mem.read8((pc + 1) & MASK)
                nextpc = read32(r[loc] + index * 4)
            else:
                width = 3 if rejected_quick else OPCODE_LENGTHS[decoded]
                if width == 2:
                    operand = mem.read8((pc + 1) & MASK) << 8
                elif width == 3:
                    operand = operand16()
                else:
                    operand = 0
                if countdown and not branch_countdown and op != 0xca:
                    self._store32(0x1c, count - 1)
                exit_to(operand)
                return
            pc = nextpc & MASK
            if countdown and (not branch_countdown or backwards):
                self._store32(0x1c, count - 1)
        raise RuntimeError('BTU instruction budget exhausted; possible infinite bytecode loop')


def attach_btu(cpu, cpg=None, *, base=BASE, byteorder='big'):
    """Attach the BTU; RAM/ROM regions must expose the target's word order.

    MMIODevice translates region offsets to the canonical register block,
    so the same register implementation can be mapped at the SH3 address.
    """
    btu = SH7305BTU(cpg, byteorder=byteorder)
    cpu.mem.add(base, MMIODevice(BASE, SIZE, btu, name='BTU'), name='BTU', perms='RW')
    cpu.btu = btu
    return btu


def attach_sh3_btu(cpu):
    """SH3-DSP JBlend register map and LE slots; no SH3 clock/IRQ model."""
    return attach_btu(cpu, base=SH3_BASE, byteorder='little')
