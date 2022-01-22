from typing import Tuple


class Memory:
    """
    Simple bytearray wrapper
    """

    def __init__(self, size):
        self._mem = bytearray(size)
        self._ptr = 0

    def read8(self, addr: int) -> bytes:
        """
        Read 8 bits in memory
        :param addr: memory addr
        :return:
        """
        return self._mem[addr]

    def read16(self, addr: int) -> bytes:
        """
        read 16 bits in memory
        :param addr: memory addr
        :return:
        """
        if 0 <= addr+2 <= len(self._mem):
            # TODO: endianness ?
            return self._mem[addr:addr+2]

    def read32(self, addr) -> bytes:
        if 0 <= addr+4 <= len(self._mem):
            # TODO: endianness ?
            return self._mem[addr:addr+4]

    def write8(self, addr, val: bytes) -> bytes:
        self._mem[addr] = val
        return val

    def write_bin(self, addr: int, data: bytes) -> None:
        self._mem[addr: addr + len(data)] = data
        self._ptr = addr + len(data)

    def __setitem__(self, key, value):
        return self.write8(key, value)

    def __getitem__(self, item):
        return self.read8(item)

    def __len__(self):
        return len(self._mem)


class MemoryMap:
    def __init__(self):
        self._mem = {}

    def add(self, addr_start: int, memory: Memory):
        self._mem[addr_start] = memory

    def resolve(self, address: int) -> Tuple[Memory, int]:
        """
        Browse the memory map for the address.
        :param address:
        :return: Memori
        """
        for start in self._mem:
            mem = self._mem[start]
            if start <= address <= start + len(mem):
                return mem, start
        # no memory mapped
        raise IndexError(f'Address is unmapped : {hex(address)}')

    def read32(self, address: int):
        # try:
        mem, start = self.resolve(address)
        # except IndexError:
        #     raise IndexError
        # Can read 4bytes ?
        if address+3 <= start + len(mem):
            return mem.read32(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')

    def read16(self, address: int):
        # try:
        mem, start = self.resolve(address)
        # except IndexError:
        #     raise IndexError
        # Can read 4bytes ?
        if address+1 <= start + len(mem):
            return mem.read16(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')
