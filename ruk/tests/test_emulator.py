from unittest import TestCase
from unittest.mock import MagicMock, patch

from ruk.jcore.cpu import CPU
from ruk.jcore.emulator import Emulator  # generated_


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
        self.emu.MOV(1, 2)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[2], 0xFF)

    def test_movi(self):
        self.emu.MOVI(0x01, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[1], 0x01)

        self.emu.MOVI(0x0F, 1)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[1], 0x0F)

        self.emu.MOVI(-1, 2)
        self.assertEqual(self.emu.cpu.regs[2], -1)

    def test_add(self):
        self.emu.ADD(1, 2)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[2], 0xFF)

        self.emu.ADD(1, 2)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[2], 0x1FE)

    def test_addi(self):
        self.emu.ADDI(0x01, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs[1], 0x100)

        self.emu.ADDI(0x0F, 1)
        self.assertEqual(self.emu.cpu.pc, 4)
        self.assertEqual(self.emu.cpu.regs[1], 0x10F)

        self.emu.ADDI(0xFF, 2)
        self.assertEqual(self.emu.cpu.regs[2], -1)

    def test_cmpgt(self):
        self.emu.CMPGT(2, 1)
        self.assertEqual(self.emu.cpu.pc, 2)
        self.assertEqual(self.emu.cpu.regs['sr'], 1)

    def test_bf(self):
        self.emu.cpu.regs['sr'] = 1
        self.emu.BF(1)

        self.assertEqual(self.emu.cpu.pc, 2)

        self.emu.cpu.regs['sr'] = 0
        self.emu.BF(1)

        # pc = 2, disp = 1, expect 2 + 4 + (disp << 1) = 2 + 6 = 8
        self.assertEqual(self.emu.cpu.pc, 8)

    def test_bra(self):
        self.emu.cpu.regs['sr'] = 1
        self.emu.cpu.regs['pc'] = 0x80
        self.emu.cpu.pc = self.emu.cpu.regs['pc']
        disp = 1
        self.emu.BRA(disp)

        self.emu.cpu.delay_slot.assert_called_once()
        self.emu.cpu.delay_slot.assert_called_with(0x80 + 2)
        self.assertEqual(self.emu.cpu.pc, 0x80 + 4 + disp*2)

    def test_rts(self):
        self.emu.cpu.pc = 40
        self.emu.cpu.regs['pr'] = 20
        self.emu.RTS()
        self.emu.cpu.delay_slot.assert_called_once()

        self.assertEqual(self.emu.cpu.pc, 20)

    def test_movbs(self):
        self.emu.cpu.regs[2] = 0x8001
        self.emu.cpu.regs[1] = 0x42
        self.emu.MOVBS(2, 1)
        self.emu.cpu.mem.write8.assert_called_once()
        self.emu.cpu.mem.write8.assert_called_with(0x42, 0x8001)



