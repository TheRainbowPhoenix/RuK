from unittest import TestCase
from unittest.mock import MagicMock, patch

from ruk.jcore.cpu import CPU
from ruk.jcore.emulator import Emulator


class TestEmulator(TestCase):
    def setUp(self) -> None:
        self.emu = Emulator(MagicMock(debug=False, pc=0, regs={1: 0xFF, 2: 0}))

    def test_mov(self):
        self.emu.mov(1, 2)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[2], 0xFF)

    def test_addi(self):
        self.emu.addi(0x01, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[1], 0x100)

        self.emu.addi(0x0F, 1)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[1], 0x10F)

        self.emu.addi(-1, 2)
        self.assertEqual(self.emu.cpu.regs[2], -1)
