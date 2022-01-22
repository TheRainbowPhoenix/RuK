from unittest import TestCase

from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class TestCPU(TestCase):
    def setUp(self) -> None:
        raw_asm = b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13\x60\x13\x60\x03'

        # RAM
        ram = Memory(0x100)

        # ROM
        rom = Memory(0x150)

        rom.write_bin(0, raw_asm)

        memory = MemoryMap()
        memory.add(0x8C00, ram)
        memory.add(0x8000, rom)

        # memory.add(0x8?00_0000, ScreenIO)
        cpu = CPU(memory, start_pc=0x8000, debug=False)

        self.cpu = CPU(memory, start_pc=0x8000, debug=False)

    def test_pc(self):
        self.assertEqual(self.cpu.pc, 0x8000)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8002)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8004)

