"""SH7305 compatible-mode MMU and CPU virtual-memory interface.

The underlying RuK map uses P1/P2 addresses for physical devices.  Translation
therefore resolves a physical address through those aliases at the bus edge.
"""
from dataclasses import dataclass, replace


class MMUFault(Exception):
    def __init__(self, address, event, vector):
        self.address, self.event, self.vector = address, event, vector
        super().__init__(f'MMU fault {event:#x} at {address:#x}')


@dataclass
class Entry:
    vpn: int = 0
    asid: int = 0
    data: int = 0

    @property
    def offset(self):
        return (0x3ff, 0xfff, 0xffff, 0xfffff)[((self.data >> 6) & 2) | ((self.data >> 4) & 1)]


class MMU:
    REGS = {0xff000000: 'pteh', 0xff000004: 'ptel', 0xff000008: 'ttb',
            0xff00000c: 'tea', 0xff000010: 'mmucr', 0xff000034: 'ptea',
            0xff000070: 'pascr', 0xff000078: 'irmcr'}
    CPU_REGS = {0xff000020: 'tra', 0xff000024: 'expevt', 0xff000028: 'intevt'}

    def __init__(self, cpu, bus):
        self.cpu, self.bus = cpu, bus
        cpu.regs.bank_switching = True
        self.pteh = self.ptel = self.ttb = self.tea = self.mmucr = 0
        self.ptea = self.pascr = self.irmcr = 0
        self.utlb = [Entry() for _ in range(64)]
        self.itlb = [Entry() for _ in range(4)]

    def ldtlb(self):
        self.utlb[(self.mmucr >> 10) & 63] = Entry(self.pteh & 0xfffffc00, self.pteh & 255, self.ptel & 0x1ffffdff)

    def read_reg(self, address):
        return getattr(self, self.REGS[address])

    def write_reg(self, address, value):
        name = self.REGS[address]
        value &= 0xffffffff
        if name == 'mmucr':
            if value & 4:
                for entry in self.utlb + self.itlb:
                    entry.data &= ~0x100
            value &= 0xfcfcff81
        elif name == 'ptea':
            value &= 0x3ff0
        elif name == 'pascr':
            value &= 0xff
        elif name == 'irmcr':
            value &= 0x1f
        setattr(self, name, value)
        if name == 'tea':
            self.cpu.tea = value

    def _match(self, entry, va, privileged):
        return (bool(entry.data & 0x100) and not ((entry.vpn ^ va) & ~entry.offset)
                and (entry.data & 2 or privileged and self.mmucr & 0x100 or entry.asid == self.pteh & 255))

    def _fault(self, va, event, vector, update_pteh=True):
        self.tea = self.cpu.tea = va
        if update_pteh:
            self.pteh = (self.pteh & 255) | (va & 0xfffffc00)
        raise MMUFault(va, event, vector)

    def _touch(self, index):
        lru = self.mmucr >> 26
        lru = (lru & ~0x38, (lru | 0x20) & ~6, (lru | 0x14) & ~1, lru | 0xb)[index]
        self.mmucr = (self.mmucr & 0x03ffffff) | (lru << 26)

    def _victim(self):
        lru = self.mmucr >> 26
        return 0 if lru & 0x38 == 0x38 else 1 if lru & 0x26 == 6 else 2 if lru & 0x15 == 1 else 3

    def translate(self, va, kind='read'):
        va &= 0xffffffff
        privileged = bool(self.cpu.regs._sys['sr'] & 0x40000000)
        write = kind == 'write'
        if va >= 0x80000000:
            if not privileged:
                self._fault(va, 0x100 if write else 0xe0, 0x100, False)
            if va < 0xc0000000 or va >= 0xe0000000:
                return va if va >= 0xe0000000 else va & 0x1fffffff
        if not self.mmucr & 1:
            return va & 0x1fffffff
        if self.mmucr & 0x80:
            raise NotImplementedError('SH7305 extended TLB mode is not implemented')
        fetch = kind == 'fetch'
        matches = [i for i, e in enumerate(self.itlb) if self._match(e, va, privileged)] if fetch else []
        if len(matches) > 1:
            self._fault(va, 0x140, 0)
        if matches:
            index = matches[0]
            self._touch(index)
            entry = self.itlb[index]
        else:
            urc = (((self.mmucr >> 10) & 63) + 1) & 63
            if urc == (self.mmucr >> 18) & 63:
                urc = 0
            self.mmucr = (self.mmucr & ~0xfc00) | (urc << 10)
            matches = [e for e in self.utlb if self._match(e, va, privileged)]
            if len(matches) > 1:
                self._fault(va, 0x140, 0)
            if not matches:
                self._fault(va, 0x60 if write else 0x40, 0x400)
            entry = matches[0]
            if fetch:
                index = self._victim()
                self.itlb[index] = replace(entry)
                self._touch(index)
        pr = (entry.data >> 5) & 3
        if (write and not (pr & 1 if privileged else pr == 3)) or (not write and not privileged and not pr & 2):
            self._fault(va, 0xc0 if write else 0xa0, 0x100)
        if write and not entry.data & 4:
            self._fault(va, 0x80, 0x100)
        return (entry.data & 0x1ffffc00 & ~entry.offset) | (va & entry.offset)

    def array_read(self, address):
        bank = address >> 24
        insn = bank in (0xf2, 0xf3)
        entry = (self.itlb if insn else self.utlb)[(address >> 8) & (3 if insn else 63)]
        if bank in (0xf2, 0xf6):
            return entry.vpn | entry.asid | (entry.data & 0x100) | (0 if insn else (entry.data & 4) << 7)
        return entry.data & (0x1ffffdda if insn else 0x1ffffdff)

    def array_write(self, address, value):
        bank = address >> 24
        insn = bank in (0xf2, 0xf3)
        if bank == 0xf6 and address & 0x80:
            for entry in self.utlb:
                if self._match(entry, value, True):
                    entry.data = (entry.data & ~0x104) | (value & 0x100) | ((value >> 7) & 4)
            for entry in self.itlb:
                if self._match(entry, value, True):
                    entry.data = (entry.data & ~0x100) | (value & 0x100)
            return
        entry = (self.itlb if insn else self.utlb)[(address >> 8) & (3 if insn else 63)]
        if bank in (0xf2, 0xf6):
            entry.vpn, entry.asid = value & 0xfffffc00, value & 255
            entry.data = (entry.data & ~(0x100 if insn else 0x104)) | (value & 0x100) | (0 if insn else (value >> 7) & 4)
        else:
            entry.data = value & (0x1ffffdda if insn else 0x1ffffdff)

    def _resolve_bus(self, physical, original):
        if original >= 0xe0000000:
            memory, start = self.bus.resolve(original)
            return original, memory, start
        # Existing machines often map aliases rather than physical addresses.
        candidates = (original, physical, physical | 0x80000000, physical | 0xa0000000) if (original & 0xe0000000 in (0x80000000, 0xa0000000) or not self.mmucr & 1) else (physical | 0x80000000, physical | 0xa0000000, physical)
        for address in candidates:
            try:
                memory, start = self.bus.resolve(address)
                return address, memory, start
            except IndexError:
                pass
        memory, start = self.bus.resolve(physical)
        return physical, memory, start

    def _access(self, address, size, kind, value=None):
        address &= 0xffffffff
        if address & (size // 8 - 1):
            self._fault(address, 0x100 if kind == 'write' else 0xe0, 0x100, False)
        physical = self.translate(address, kind)
        if address in self.REGS and size == 32:
            if kind == 'write': self.write_reg(address, value); return None
            return self.read_reg(address)
        if address in self.CPU_REGS and size == 32:
            if kind == 'write':
                setattr(self.cpu, self.CPU_REGS[address], value & 0xffffffff)
                return None
            return getattr(self.cpu, self.CPU_REGS[address])
        if address >> 24 in (0xf2, 0xf3, 0xf6, 0xf7) and size == 32:
            if kind == 'write': self.array_write(address, value); return None
            return self.array_read(address)
        target, memory, start = self._resolve_bus(physical, address)
        offset = target - start
        if kind != 'write':
            return getattr(memory, 'read' + str(size))(offset)
        if target + size // 8 - 1 > start + len(memory):
            raise IndexError(f'Address overflow : {hex(target)}')
        if not isinstance(value, int):
            value = (value[0] if value else 0) if size == 8 else int.from_bytes(value, 'big')
        return getattr(memory, 'write' + str(size))(offset, value & ((1 << size) - 1))

    def fetch16(self, address): return self._access(address, 16, 'fetch')
    def read8(self, address): return self._access(address, 8, 'read')
    def read16(self, address): return self._access(address, 16, 'read')
    def read32(self, address): return self._access(address, 32, 'read')
    def write8(self, address, value): return self._access(address, 8, 'write', value)
    def write16(self, address, value): return self._access(address, 16, 'write', value)
    def write32(self, address, value): return self._access(address, 32, 'write', value)
    def __getattr__(self, name): return getattr(self.bus, name)
