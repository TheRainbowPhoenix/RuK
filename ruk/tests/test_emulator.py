from unittest import TestCase
from unittest.mock import MagicMock, patch

from ruk.jcore.cpu import CPU
from ruk.jcore.emulator import Emulator


class TestEmulator(TestCase):
    def setUp(self) -> None:
        self.emu = Emulator(MagicMock(
            debug=False, pc=0, regs={
                1: 0xFF, 2: 0, 'sr': 0, 'pr': 0
            }))

    def test_resolve(self):
        with self.assertRaises(IndexError):
            self.emu.resolve(-1)

    def test_mov(self):
        self.emu.mov(1, 2)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[2], 0xFF)

    def test_movi(self):
        self.emu.movi(0x01, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[1], 0x01)

        self.emu.movi(0x0F, 1)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[1], 0x0F)

        self.emu.movi(-1, 2)
        self.assertEqual(self.emu.cpu.regs[2], -1)

    def test_add(self):
        self.emu.add(1, 2)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[2], 0xFF)

        self.emu.add(1, 2)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[2], 0x1FE)

    def test_addi(self):
        self.emu.addi(0x01, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[1], 0x100)

        self.emu.addi(0x0F, 1)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[1], 0x10F)

        self.emu.addi(-1, 2)
        self.assertEqual(self.emu.cpu.regs[2], 1)

    def test_cmpgt(self):
        self.emu.cmpgt(2, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs['sr'], 1)

    def test_bf(self):
        self.emu.cpu.regs['sr'] = 1
        self.emu.bf(1)

        self.assertEqual(self.emu.cpu.pc, 2)

        self.emu.cpu.regs['sr'] = 0
        self.emu.bf(1)

        # pc = 2, disp = 1, expect 2 + 4 + (disp << 1) = 2 + 6 = 8
        self.assertEqual(self.emu.cpu.pc, 8)

    def test_rts(self):
        self.emu.cpu.pc = 40
        self.emu.cpu.regs['pr'] = 20
        self.emu.rts()
        self.emu.cpu.delay_slot.assert_called_once()

        self.assertEqual(self.emu.cpu.pc, 20)



