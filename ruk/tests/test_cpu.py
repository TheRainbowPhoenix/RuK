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

        self.start_pc = 0x8000

        # memory.add(0x8?00_0000, ScreenIO)
        cpu = CPU(memory, start_pc=self.start_pc, debug=False)

        self.cpu = CPU(memory, start_pc=self.start_pc, debug=False)

    def test_pc(self):
        self.assertEqual(self.cpu.pc, 0x8000)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8002)

        self.cpu.pc += 2
        self.assertEqual(self.cpu.pc, 0x8004)

    def test_mov(self):
        self.cpu.regs[15] = 0xFF

        raw_asm = b'\x6E\xF3'
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[14], 0xFF)

        raw_asm = b'\x61\xE3'
        self.rom.write_bin(2, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[1], 0xFF)

    def test_movi(self):
        self.cpu.regs[15] = 0x01

        raw_asm = b'\xEF\x7F'
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[15], 0x7F)

        raw_asm = b'\xE1\x0F'
        self.rom.write_bin(2, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[1], 0x0F)

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

    def test_addi(self):
        self.cpu.regs[3] = 0xFF

        raw_asm = b'\x34\x3C'
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[4], 0xFF)

        raw_asm = b'\x34\x3C'
        self.rom.write_bin(2, raw_asm)
        self.cpu.step()

        self.assertEqual(self.cpu.regs[4], 0x1FE)

    def test_cmpgt(self):
        raw_asm = b'\x34\x17'  # CMP/GT R1, R4
        raw_asm += b'\x34\x27'  # CMP/GT R2, R4

        self.cpu.regs[1] = 0x1
        self.cpu.regs[4] = 0x2
        self.rom.write_bin(0, raw_asm)
        self.cpu.step()
        self.assertEqual(self.cpu.regs['sr'], 1)

        self.cpu.regs[2] = 0x3
        self.cpu.step()
        self.assertEqual(self.cpu.regs['sr'], 0)

    @patch('builtins.print')
    def test_rts(self, mock_print):
        self.cpu.debug = True

        raw_asm = b'\x00\x0B\x60\x43'
        self.rom.write_bin(0, raw_asm)
        self.cpu.regs[0] = 0x0
        self.cpu.regs[4] = 0x3
        self.cpu.step()

        # Checking the delay slot
        self.assertEqual(self.cpu.regs[0], 0x3)
        mock_print.assert_called_with('mov R4,R0')

    def test_reset(self):
        self.cpu.pc = 0xdeadbeef
        self.cpu.regs[15] = 0xff
        self.cpu.ebreak = True

        self.cpu.reset()

        self.assertEqual(self.cpu.pc, self.start_pc)
        self.assertEqual(self.cpu.regs[15], 0)
        self.assertEqual(self.cpu.ebreak, False)

    def test_surrounding_memory(self):
        self.assertEqual(self.cpu.get_surrounding_memory(size=4), (self.cpu.pc, self.cpu.pc+8, b'\x6E\xF3\x6E\x13\x6A\x13\x6F\x13'))

    def test_reg_pc(self):
        self.assertEqual(self.cpu.reg_pc['pc'], self.cpu.pc)
        self.cpu.reg_pc['pc'] = 0xdeadbeef
        self.assertEqual(self.cpu.pc, 0xdeadbeef)

    def test_errors(self):
        raw_asm = b'\xFF\xFF'  # That should be illegal according to Renesas
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
