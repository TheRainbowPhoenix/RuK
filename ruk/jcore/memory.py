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
        raise IndexError(f'Out of bound read16 : \"{addr:04X}\"')

    def read32(self, addr) -> bytes:
        if 0 <= addr+4 <= len(self._mem):
            # TODO: endianness ?
            return self._mem[addr:addr+4]
        raise IndexError(f'Out of bound read32 : \"{addr:04X}\"')

    def write8(self, addr, val: int) -> int:
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

    def get_range(self, start: int, end: int):
        return self._mem[start:end]


class MemoryMap:
    def __init__(self):
        self._mem = {}

    def add(self, addr_start: int, memory: Memory):
        self._mem[addr_start] = memory

    def resolve(self, address: int) -> Tuple[Memory, int]:
        """
        Browse the memory map for the address.
        :param address:
        :return: Memory
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
        raise IndexError(f'Address overflow : {hex(address)}')   # pragma: no cover

    def read16(self, address: int):
        # try:
        mem, start = self.resolve(address)
        # except IndexError:
        #     raise IndexError
        # Can read 4bytes ?
        if address+1 <= start + len(mem):
            return mem.read16(address - start)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def get_arround(self, address: int, size: int):
        """
        Get memory around address
        :param address: Memory address to seek at
        :param size: relative size to get bytes, eg 5 will get 5 bytes before address and 5 bytes after.
        """
        mem, start = self.resolve(address)

        start_p = address - size
        end_p = address + size

        if end_p <= start or start_p >= start + len(mem):
            raise IndexError(f'Reading out of memory bounds : {hex(address)} +- {size}')

        # Case where we start at the end :
        if end_p >= start + len(mem):
            diff = end_p - (start + len(mem))
            start_p -= diff
            end_p -= diff

        if start <= start_p and end_p <= start + len(mem):
            return start_p, end_p, mem.get_range(start_p-start, end_p-start)

        if start_p < start:
            start_p = start
            end_p = start+size*2
            return start_p, end_p, mem.get_range(0, size*2)

        # TODO: if at end, etc
        raise IndexError(f"Edge case not handled : {start_p} {end_p}")
        # return start_p, end_p, b'\x0f'*(size*2)

    def _write16(self, address: int, bytes_data: bytes):
        """
        Potentially dangerous function that write anywhere in memory.
        Used for the "Edit" functions of the GUI
        """
        mem, start = self.resolve(address)
        # Can write 4bytes ?
        if address + 1 <= start + len(mem):
            return mem.write_bin(address - start, bytes_data)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover

    def _write8(self, address: int, bytes_data: bytes):
        """
        Potentially dangerous function that write anywhere in memory.
        Used for the "Edit" functions of the GUI
        """
        mem, start = self.resolve(address)
        # Can write 4bytes ?
        if address <= start + len(mem):
            return mem.write_bin(address - start, bytes_data)
        raise IndexError(f'Address overflow : {hex(address)}')  # pragma: no cover
