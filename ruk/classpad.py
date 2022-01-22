from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class Classpad:
    def __init__(self, rom: bytes, debug: bool = False):
        """
        Create a virtual Classpad II
        :param rom: rom bytes, raw assembly !
        :param debug: Flag to enable exception and stacktrace printing
        """
        # TODO: get real values !!
        self._ram = Memory(0x100_0000)
        self._rom = Memory(0x150_0000)
        # Debug turn on stacktrace
        self.debug = debug

        self._memory = MemoryMap()

        self.load_rom(rom)
        self.setup_memory()

        self._cpu = CPU(self._memory, start_pc=0x8000_0000, debug=debug)

    def load_rom(self, rom: bytes):
        self._rom.write_bin(0, rom)

    def setup_memory(self):
        self._memory.add(0x8C00_0000, self._ram)
        self._memory.add(0x8000_0000, self._rom)

    def run(self):
        while not self._cpu.ebreak:
            try:
                self._cpu.step()
            except Exception as e:
                print(f"!!! CPU Error : {e} !!!")
                self._cpu.stacktrace()
                if self.debug:
                    raise

