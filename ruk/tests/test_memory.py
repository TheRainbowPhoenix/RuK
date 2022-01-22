from unittest import TestCase

from ruk.jcore.memory import Memory


class TestMemory(TestCase):
    def setUp(self) -> None:
        self.mem = Memory(0x800)

    def test_read8(self):
        self.assertEqual(self.mem.read8(0x0), 0)
        self.assertEqual(self.mem.read8(0x7FF), 0)
        self.assertEqual(self.mem.read8(-1), 0)
        self.assertEqual(self.mem[0x0], 0)

        with self.assertRaises(IndexError):
            self.mem.read8(0x800)

    def test_write8(self):
        self.assertEqual(self.mem.write8(0x0, 0xFF), 0xFF)
        self.assertEqual(self.mem.read8(0x0), 0xFF)
        self.assertEqual(self.mem[0x0], 0xFF)

        self.mem[0xFF] = 0x7F
        self.assertEqual(self.mem[0xFF], 0x7F)

        with self.assertRaises(IndexError):
            self.mem.write8(0x800, 0xFF)

        with self.assertRaises(IndexError):
            self.mem[0x800] = 0xFF

    def test_write_bin(self):
        self.fail()
