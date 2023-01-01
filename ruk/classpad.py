from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class Classpad:
    def __init__(self, rom: bytes, debug: bool = False, start_pc=None, ram_size: int = 0x100_0000):
        """
        Create a virtual Classpad II
        :param rom: rom bytes, raw assembly !
        :param debug: Flag to enable exception and stacktrace printing
        """
        # TODO: get real values !!
        self._ram = Memory(ram_size)
        self._rom = Memory(len(rom))  # 0x1FF_FFFF)
        self._cached_rom = Memory(len(rom))  # 0x1FF_FFFF)
        # Debug turn on stacktrace
        self.debug = debug

        self._memory = MemoryMap()

        self.load_rom(rom)
        self.setup_memory()

        if start_pc is None:
            start_pc = 0x8000_0000

        self._cpu = CPU(self._memory, start_pc=start_pc, debug=debug)

    def load_rom(self, rom: bytes):
        self._rom.write_bin(0, rom)
        self._cached_rom.write_bin(0, rom)

    def setup_memory(self):
        self._memory.add(0x8C00_0000, self._ram)
        self._memory.add(0x8000_0000, self._rom)
        self._memory.add(0xA000_0000, self._cached_rom)

        self.setup_direct_io()

    def setup_direct_io(self):
        pass
        # 0xFEC0_0000 -> 0xFEFF_FFFF

    @property
    def cpu(self):
        return self._cpu

    @property
    def ram(self):
        return self._ram

    def run(self):
        while not self._cpu.ebreak:
            try:
                self._cpu.step()
            except Exception as e:
                print(f"!!! CPU Error : {e} !!!")
                self._cpu.stacktrace()
                if self.debug:
                    raise

    def add_rom(self, rom: bytes, index: int):
        rom_memory = Memory(len(rom))
        rom_memory.write_bin(0, rom)
        self._memory.add(index, rom_memory)


