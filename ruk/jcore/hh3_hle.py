"""Opt-in Hollyhock services for HH3 programs, with read-only host files."""
import re
from collections import deque
from pathlib import Path
from ruk.jcore.memory import Memory

TABLE = 0x8c070000
STUB = 0xe5200200
VRAM = 0xfe280000
DEBUG_FONT = 0x8c090000
DEBUG_FONT_SIZE = 0xc000  # 256 glyphs, 8 by 12 RGB565 pixels
MASK = 0xffffffff


class HH3Services:
    def __init__(self, machine, root, executable, font_path=None):
        self.cpu, self.mem = machine.cpu, machine.mem
        self.root = Path(root).resolve()
        self.executable = Path(executable)
        self.font_path = Path(font_path) if font_path else None
        self.symbols = {}
        self.calls = {}
        self.events = deque(maxlen=128)
        self.files = {}
        self.next_fd = 3
        self.brk = 0x8c100000
        self.brk_min, self.brk_max = self.brk, 0x8ce80000
        self.free = []
        self.alloc = {}
        self.sbrk_mode = 0
        self.output = []

    def install(self):
        # SH7305 performance counter window: stored values, no cycle model yet.
        self.mem.add(0xfc100000, Memory(0x100), name='HH3 performance counters', perms='RW')
        data = self.executable.read_bytes()
        names = set(x.decode('ascii') for x in re.findall(
            rb'Symbol ([A-Za-z_][A-Za-z_0-9]*) not linked', data))
        if not names:
            raise ValueError('HH3 has no recognizable Hollyhock symbol names')
        # Data symbols have no "not linked" function, so they do not appear
        # in the panic-message scan.  The guest uses this as a pixel array.
        if b'DEBUG_FONTBASE\0' in data:
            names.add('DEBUG_FONTBASE')
        names = sorted(names)
        guard = bytearray()
        for i in range(16):
            b = self.mem.read8(0x814fffe0 + i)
            guard.append(b)
            if b == 0:
                break
        if guard[-1] != 0:
            guard.append(0)
        table = bytearray(guard)
        for index, name in enumerate(names):
            if name == 'DEBUG_FONTBASE':
                # Blank fallback glyphs until an OS-matched font is available.
                addr = DEBUG_FONT
                for offset in range(0, DEBUG_FONT_SIZE, 4):
                    self.mem.write32(addr + offset, 0)
                if self.font_path:
                    font = self.font_path.read_bytes()
                    if len(font) != 95 * 0xc0:
                        raise ValueError('font must contain 95 glyphs of 192 bytes')
                    for offset, value in enumerate(font):
                        self.mem.write8(addr + offset, value)
            else:
                addr = STUB + index * 4
                self.symbols[addr] = name
                self.mem.write16(addr, 0xc3fd)  # TRAPA #FD, intercepted at this address only
            table.extend(name.encode('ascii') + b'\0' + addr.to_bytes(4, 'big'))
        if len(table) > 0x8000:
            raise ValueError('HH3 symbol table exceeds reserved memory')
        for i, b in enumerate(table):
            self.mem.write8(TABLE + i, b)
        return TABLE, len(table)

    def cstring(self, addr, limit=4096):
        b = bytearray()
        for i in range(limit):
            c = self.mem.read8((addr + i) & MASK)
            if not c:
                return b.decode('shift_jis', errors='replace')
            b.append(c)
        raise ValueError('unterminated HH3 string')

    def file_path(self, addr):
        path = self.cstring(addr).replace('\\', '/')
        parts = [p for p in path.split('/') if p]
        if not parts or parts[0].lower() != 'fls0' or any(p in ('.', '..') for p in parts):
            raise ValueError('path outside fls0')
        target = self.root.joinpath(*parts[1:]).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError('path outside mounted directory')
        return target

    def _add_free(self, start, size):
        if size <= 0:
            return
        regions = sorted(self.free + [(start, size)])
        self.free = []
        for start, size in regions:
            if self.free and self.free[-1][0] + self.free[-1][1] == start:
                p, n = self.free[-1]; self.free[-1] = (p, n + size)
            else:
                self.free.append((start, size))

    def dispatch(self, pc):
        name = self.symbols.get(pc)
        if name is None:
            return False
        self.calls[name] = self.calls.get(name, 0) + 1
        r, m = self.cpu.regs, self.mem
        a, b, c = r[4], r[5], r[6]
        self.events.append((name, a, b, c))
        result = 0
        if name == 'Mem_Sbrk':
            delta = a if a < 0x80000000 else a - 0x100000000
            old = self.brk
            if self.brk_min <= old + delta <= self.brk_max:
                self.brk += delta; result = old
            else:
                result = MASK
        elif name == 'Mem_SbrkMode':
            result, self.sbrk_mode = self.sbrk_mode, a & 255
        elif name == 'Mem_Free':
            if a:
                size = self.alloc.pop(a, None)
                if size is None:
                    # big_app donates a preformatted free block.
                    size = m.read32(a - 4)
                self._add_free(a, size)
        elif name == 'Mem_Malloc':
            size = (a + 7) & ~7
            for i, (start, available) in enumerate(self.free):
                if available >= size:
                    result = start; self.alloc[start] = size
                    self.free.pop(i); self._add_free(start + size, available - size)
                    break
        elif name in ('Mem_Memset', 'Mem_Memcpy'):
            values = bytes([b & 255]) * c if name == 'Mem_Memset' else bytes(m.read8(b+i) for i in range(c))
            for i, value in enumerate(values): m.write8(a+i, value)
            result = a
        elif name == 'String_Strlen':
            result = len(self.cstring(a).encode('shift_jis', errors='replace'))
        elif name == 'LCD_ClearScreen':
            for i in range(0, 0x52800, 4): m.write32(VRAM+i, MASK)
        elif name == 'LCD_GetVRAMAddress':
            result = VRAM
        elif name == 'LCD_GetSize':
            m.write32(a, 320); m.write32(b, 528)
        elif name == 'Debug_PrintString':
            s = self.cstring(a); self.output.append(s); print(s, end='', flush=True); result = 1
        elif name in ('Debug_SetCursorPosition', 'LCD_Refresh', 'Input_IsAnyKeyDown', 'Input_GetKeyState'):
            pass
        elif name == 'File_Open':
            try:
                if b & ~1 or not b & 1: raise ValueError('read-only mount')
                f = self.file_path(a).open('rb')
                result = self.next_fd; self.next_fd += 1; self.files[result] = f
            except (OSError, ValueError): result = -14
        elif name == 'File_Read':
            f = self.files.get(a)
            if f is None: result = -18
            else:
                data = f.read(c)
                for i, value in enumerate(data): m.write8(b+i, value)
                result = len(data) if data else -19
        elif name == 'File_Close':
            f = self.files.pop(a, None)
            if f is None: result = -18
            else: f.close()
        elif name == 'File_Lseek':
            f = self.files.get(a)
            if f is None: result = -18
            else:
                try: result = f.seek(b if b < 0x80000000 else b - 0x100000000, c)
                except (OSError, ValueError): result = -11
        else:
            raise NotImplementedError(f'HH3 service {name} at {pc:#x}')
        r[0] = result & MASK
        self.cpu.pc = r['pr'] & MASK
        return True
