from typing import Tuple, Union


class Memory:
    """
    Simple bytearray wrapper.

    All read methods return int (unsigned).  All write methods accept int.
    This is a change from the original RuK API which returned bytes for
    read16/read32 and accepted bytes for write_bin -- the int-everywhere
    convention is needed because the emulator's MOV.B/W/L handlers pass
    ints to write8/16/32, and the CPU's step() does arithmetic on the
    values returned by read16.
    """

    def __init__(self, size):
        self._mem = bytearray(size)
        self._ptr = 0

    def read8(self, addr: int) -> int:
        """
        Read 8 bits in memory.
        :param addr: memory addr
        :return: int in [0, 0xFF]
        """
        return self._mem[addr] & 0xFF

    def read16(self, addr: int) -> int:
        """
        Read 16 bits in memory (big-endian, matching the SH-4's
        big-endian bus when the host is also big-endian-aware).
        :param addr: memory addr
        :return: int in [0, 0xFFFF]
        """
        if 0 <= addr + 2 <= len(self._mem):
            return int.from_bytes(self._mem[addr:addr + 2], "big")
        raise IndexError(f'Out of bound read16 : "{addr:04X}"')

    def read32(self, addr: int) -> int:
        """
        Read 32 bits in memory (big-endian).
        :param addr: memory addr
        :return: int in [0, 0xFFFFFFFF]
        """
        if 0 <= addr + 4 <= len(self._mem):
            return int.from_bytes(self._mem[addr:addr + 4], "big")
        raise IndexError(f'Out of bound read32 : "{addr:04X}"')

    def write8(self, addr, val: int) -> int:
        self._mem[addr] = val & 0xFF
        return val

    def write16(self, addr: int, val: int):
        """Write 16 bits (big-endian)."""
        if 0 <= addr + 2 <= len(self._mem):
            self._mem[addr:addr + 2] = (val & 0xFFFF).to_bytes(2, "big")
            return
        raise IndexError(f'Out of bound write16 : "{addr:04X}"')

    def write32(self, addr: int, val: int):
        """Write 32 bits (big-endian)."""
        if 0 <= addr + 4 <= len(self._mem):
            self._mem[addr:addr + 4] = (val & 0xFFFFFFFF).to_bytes(4, "big")
            return
        raise IndexError(f'Out of bound write32 : "{addr:04X}"')

    def write_bin(self, addr: int, data) -> None:
        """
        Write raw bytes to memory.  Accepts both `bytes` and `int`:
        - bytes: written as-is (used by the loader)
        - int: treated as a single byte (used by the old API and by
          MemoryMap.write8/16/32 when they fall back to write_bin)
        """
        if isinstance(data, int):
            self._mem[addr] = data & 0xFF
            self._ptr = addr + 1
            return
        self._mem[addr: addr + len(data)] = data
        self._ptr = addr + len(data)

    def __setitem__(self, key, value):
        return self.write8(key, value)

    def __getitem__(self, item):
        return self.read8(item)

    def __len__(self):
        return len(self._mem)

    def get_range(self, start: int, end: int):
        return self._mem[start:end]


class MemoryPermission:
    READ_PERMISSION = 1
    WRITE_PERMISSION = 2
    EXECUTE_PERMISSION = 4

    @staticmethod
    def from_string(permissions_str: str) -> int:
        permissions = 0
        if 'R' in permissions_str:
            permissions |= MemoryPermission.READ_PERMISSION
        if 'W' in permissions_str:
            permissions |= MemoryPermission.WRITE_PERMISSION
        if 'X' in permissions_str:
            permissions |= MemoryPermission.EXECUTE_PERMISSION
        return permissions

    @staticmethod
    def to_string(permissions: int) -> str:
        permission_str = ""
        if permissions & MemoryPermission.READ_PERMISSION:
            permission_str += 'R'
        if permissions & MemoryPermission.WRITE_PERMISSION:
            permission_str += 'W'
        if permissions & MemoryPermission.EXECUTE_PERMISSION:
            permission_str += 'X'
        return permission_str


class MemoryMap:
    def __init__(self):
        self._mem = {}
        self._metas = {}

    def add(self, addr_start: int, memory: Memory, name: str = "-", perms: str = None):
        self._mem[addr_start] = memory
        self._metas[addr_start] = {
            "perms": MemoryPermission.from_string(perms or "RWX"),
            "name": name
        }

    def resolve(self, address: Union[int, bytearray]) -> Tuple[Memory, int]:
        """
        Browse the memory map for the address.
        :param address:
        :return: Memory
        """
        if type(address) == bytearray:
            address = int.from_bytes(address, "big")

        for start in self._mem:
            mem = self._mem[start]
            if start <= address <= start + len(mem):
                return mem, start
        # no memory mapped
        raise IndexError(f'Address is unmapped : {hex(address)}')

    def read32(self, address: int) -> int:
        mem, start = self.resolve(address)
        if address + 3 <= start + len(mem):
            return mem.read32(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def read16(self, address: int) -> int:
        mem, start = self.resolve(address)
        if address + 1 <= start + len(mem):
            return mem.read16(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def read8(self, address: int) -> int:
        mem, start = self.resolve(address)
        if address <= start + len(mem):
            return mem.read8(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def get_arround(self, address: Union[int, bytearray], size: int):
        """
        Get memory around address
        :param address: Memory address to seek at
        :param size: relative size to get bytes, eg 5 will get 5 bytes before address and 5 bytes after.
        """
        if type(address) == bytearray:
            address = int.from_bytes(address, "big")

        mem, start = self.resolve(address)

        # start_p = address - size
        # end_p = address + size
        start_p = address
        end_p = address + size * 2

        if end_p <= start or start_p >= start + len(mem):
            raise IndexError(f'Reading out of memory bounds : {hex(address)} +- {size}')

        # Case where we start at the end :
        if end_p >= start + len(mem):
            diff = end_p - (start + len(mem))
            start_p -= diff
            end_p -= diff

        if start <= start_p and end_p <= start + len(mem):
            return start_p, end_p, mem.get_range(start_p - start, end_p - start)

        if start_p < start:
            start_p = start
            end_p = start + size * 2
            return start_p, end_p, mem.get_range(0, size * 2)

        # TODO: if at end, etc
        raise IndexError(f"Edge case not handled : {start_p} {end_p}")
        # return start_p, end_p, b'\x0f'*(size*2)

    def write32(self, address: int, val):
        """
        Write 32 bits.  Accepts both int and bytes (4-byte big-endian).
        """
        if isinstance(val, int):
            v = val & 0xFFFFFFFF
        else:
            v = int.from_bytes(val, "big")
        mem, start = self.resolve(address)
        # Can write 4bytes ?
        if address + 3 <= start + len(mem):
            return mem.write32(address - start, v)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def write16(self, address: int, val):
        """
        Write 16 bits.  Accepts both int and bytes (2-byte big-endian).
        """
        if isinstance(val, int):
            v = val & 0xFFFF
        else:
            v = int.from_bytes(val, "big")
        mem, start = self.resolve(address)
        # Can write 2bytes ?
        if address + 1 <= start + len(mem):
            return mem.write16(address - start, v)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def write8(self, address: int, val):
        """
        Write 8 bits.  Accepts both int and bytes (1-byte).
        """
        if isinstance(val, int):
            v = val & 0xFF
        else:
            v = val[0] if len(val) > 0 else 0
        mem, start = self.resolve(address)
        # Can write 1bytes ?
        if address <= start + len(mem):
            return mem.write8(address - start, v)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def get_mapped_areas(self):
        mapped_areas = []
        for start, memory in self._mem.items():
            if start in self._metas:
                perms, name = self._metas[start].values()
                perms = MemoryPermission.to_string(perms)
            else:
                perms, name = ("RWX", "???")
            end = start + len(memory)
            mapped_areas.append((start, end, name, perms))  # TODO: name + perms !
        return mapped_areas
