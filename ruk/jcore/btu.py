"""Experimental SH7305 bytecode translation unit."""
from ruk.jcore.mmio import MMIODevice
from collections import Counter

BASE = 0xFF280000
SIZE = 0x100
MASK = 0xffffffff


class BTUEntryBreakpoint(Exception):
    """Host debugger pause immediately before a J_JP handoff."""

# Java instructions with one operand byte. Other software exits carry two
# operand bytes, except instructions without operands, which carry zero.
ONE = set(range(0x15, 0x1a)) | set(range(0x36, 0x3b)) | {0x10, 0x12, 0xa9, 0xbc}
TWO = {0x11, 0x13, 0x14, 0x84} | set(range(0x99, 0xa9)) | set(range(0xb2, 0xba)) | {0xbb, 0xbd, 0xc0, 0xc1, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca}


def signed(v, bits=32):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class SH7305BTU:
    def __init__(self, cpg=None, max_instructions=1000000):
        self.cpg = cpg
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

    def read8(self, addr):
        return self.regs[addr - BASE]

    def read16(self, addr):
        return int.from_bytes(self.regs[addr-BASE:addr-BASE+2], 'big')

    def read32(self, addr):
        return int.from_bytes(self.regs[addr-BASE:addr-BASE+4], 'big')

    def write8(self, addr, value):
        self.regs[addr-BASE] = value & 255

    def write16(self, addr, value):
        self.regs[addr-BASE:addr-BASE+2] = (value & 0xffff).to_bytes(2, 'big')

    def write32(self, addr, value):
        off = addr - BASE
        self.regs[off:off+4] = (value & MASK).to_bytes(4, 'big')
        if off == 0x18:
            self.regs[0x1c:0x20] = (value & 0x7fffffff).to_bytes(4, 'big')

    def enter(self, cpu, n):
        control = self.read32(BASE)
        self.entries += 1
        self.last_entry = {'pc': cpu.pc, 'register': n, 'java_pc': cpu.regs[n], 'control': control}
        handoff = {'entry': self.last_entry.copy()}
        if len(self.first_handoffs) < 32:
            self.first_handoffs.append(handoff)
        if self.break_on_entry:
            raise BTUEntryBreakpoint(f'J_JP @R{n} at {cpu.pc:#010x}, Java PC {cpu.regs[n]:#010x}')
        if not (control & 0x80000000) or (self.cpg and self.cpg.mstpcr2 & 0x80000000):
            self.exits['disabled'] += 1
            cpu.pc = (cpu.pc + 2) & MASK
            return
        self.enabled_entries += 1
        config = self.read32(BASE + 4)
        loc, spreg, table, jp, scratch = ((config >> shift) & 15 for shift in (16, 12, 8, 4, 0))
        mem, r = cpu.mem, cpu.regs
        pc, sp = r[n], r[spreg]
        # Entry and each exit are architectural boundaries for the guest.
        r[jp] = pc

        def push(v):
            nonlocal sp
            mem.write32(sp, v & MASK)
            sp = (sp + 4) & MASK

        def pop():
            nonlocal sp
            sp = (sp - 4) & MASK
            return mem.read32(sp)

        def exit_to(code, event=False):
            r[jp], r[spreg], r[scratch] = pc & MASK, sp & MASK, 0
            r[0] = code & MASK
            cpu.pc = mem.read32((r[table] - 4 if event else r[table] + op * 4) & MASK)
            kind = 'event' if event else 'software'
            self.exits[kind] += 1
            self.last_exit = {'kind': kind, 'java_pc': pc, 'opcode': op, 'r0': code & MASK, 'stack': sp, 'sh_pc': cpu.pc}
            handoff['exit'] = self.last_exit.copy()

        for _ in range(self.max_instructions):
            op = mem.read8(pc)
            self.bytecodes[op] += 1
            # Keep gated groups in software.
            gates = control & 0x3fff
            execute = not (gates & ~0x40)
            nextpc = (pc + 1) & MASK
            if execute and op == 0x00:
                pass
            elif execute and 0x02 <= op <= 0x08:
                push(op - 3)
            elif execute and op in (0x10, 0x11):
                if op == 0x10:
                    push(signed(mem.read8(pc + 1), 8)); nextpc = pc + 2
                else:
                    push(signed((mem.read8(pc + 1) << 8) | mem.read8(pc + 2), 16)); nextpc = pc + 3
            elif execute and (op == 0x15 or 0x1a <= op <= 0x1d):
                index = mem.read8(pc + 1) if op == 0x15 else op - 0x1a
                push(mem.read32((r[loc] + index * 4) & MASK))
                nextpc = pc + (2 if op == 0x15 else 1)
            elif execute and (op == 0x36 or 0x3b <= op <= 0x3e):
                index = mem.read8(pc + 1) if op == 0x36 else op - 0x3b
                mem.write32((r[loc] + index * 4) & MASK, pop())
                nextpc = pc + (2 if op == 0x36 else 1)
            elif execute and op == 0x57:
                pop()
            elif execute and op == 0x59:
                value = pop(); push(value); push(value)
            elif execute and op in (0x60, 0x64, 0x68, 0x7e, 0x80, 0x82):
                b, a = pop(), pop()
                value = {0x60: lambda: a+b, 0x64: lambda: a-b, 0x68: lambda: a*b,
                         0x7e: lambda: a & b, 0x80: lambda: a | b, 0x82: lambda: a ^ b}[op]()
                push(value)
            elif execute and op == 0x74:
                push(-pop())
            elif execute and op == 0x84:
                index = mem.read8(pc + 1)
                addr = (r[loc] + index * 4) & MASK
                mem.write32(addr, (mem.read32(addr) + signed(mem.read8(pc + 2), 8)) & MASK)
                nextpc = pc + 3
            elif execute and op == 0xa7:
                offset = signed((mem.read8(pc + 1) << 8) | mem.read8(pc + 2), 16)
                nextpc = pc + offset
            else:
                if op in ONE:
                    operand = mem.read8(pc + 1) << 8
                elif op in TWO or op > 0xca:
                    operand = (mem.read8(pc + 1) << 8) | mem.read8(pc + 2)
                else:
                    operand = 0
                exit_to(operand)
                return
            pc = nextpc & MASK
            r[jp], r[spreg] = pc, sp
            if control & 0x40000000:
                count = self.read32(BASE + 0x1c)
                if count <= 1:
                    self.write32(BASE + 0x1c, self.read32(BASE + 0x18) & 0x7fffffff)
                    exit_to(0x10, event=True)
                    return
                self.write32(BASE + 0x1c, count - 1)
        raise RuntimeError('BTU instruction budget exhausted; possible infinite bytecode loop')


def attach_btu(cpu, cpg=None):
    """Attach the SH7305 BTU to a CPU and its memory map."""
    btu = SH7305BTU(cpg)
    cpu.mem.add(BASE, MMIODevice(BASE, SIZE, btu, name='BTU'), name='BTU', perms='RW')
    cpu.btu = btu
    return btu
