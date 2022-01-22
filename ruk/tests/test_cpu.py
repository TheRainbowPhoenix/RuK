from unittest import TestCase
from unittest.mock import patch

from ruk.jcore.cpu import CPU
from ruk.jcore.memory import Memory, MemoryMap


class TestCPU(TestCase):
    def setUp(self) -> None:
        raw_asm = b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13\x60\x13\x60\x03'

        # RAM
        self.ram = Memory(0x100)

        # ROM
        self.rom = Memory(0x150)

        self.rom.write_bin(0, raw_asm)

        memory = MemoryMap()
        memory.add(0x8C00, self.ram)
        memory.add(0x8000, self.rom)

        # memory.add(0x8?00_0000, ScreenIO)
        cpu = CPU(memory, start_pc=0x8000, debug=False)

        self.cpu = CPU(memory, start_pc=0x8000, debug=False)

    def test_pc(self):
        self.assertEqual(self.cpu.pc, 0x8000)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8002)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8004)

    def test_add(self):
        raw_asm = b'\x71\x7F\x74\x01'
        self.rom.write_bin(0, raw_asm)

        for i in range(2):
            self.cpu.step()

        self.assertEqual(self.cpu.regs[1], 0x7F)
        self.assertEqual(self.cpu.regs[4], 0x01)

        raw_asm = b'\x73\x03\x73\x03'
        self.rom.write_bin(4, raw_asm)

        for i in range(2):
            self.cpu.step()

        self.assertEqual(self.cpu.regs[3], 0x06)

    def test_mov(self):
        self.cpu.regs[15] = 0xff

        raw_asm = b'\x6E\xF3'
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[14], 0xff)

        raw_asm = b'\x61\xE3'
        self.rom.write_bin(2, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[1], 0xff)

    def test_errors(self):
        raw_asm = b'\xff\xff'  # That should be illegal according to Renesas
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()
        self.assertTrue(self.cpu.ebreak)

        self.cpu.debug = True
        self.rom.write_bin(2, raw_asm)

        with self.assertRaises(IndexError):
            self.cpu.step()

    @patch('builtins.print')
    def test_stacktrace(self, mock_print):
        self.cpu.stacktrace()
        mock_print.assert_called_with('pc   = 8000')
