from unittest import TestCase

from ruk.jcore.memory import Memory, MemoryMap


class TestMemory(TestCase):
    def setUp(self) -> None:
        self.mem = Memory(0x800)
        self.mem._mem[0x70:0x7F] = b'\xFF' * 0xF

        self.memmap = MemoryMap()
        self.memmap.add(0x800, self.mem)

    def test_read8(self):
        self.assertEqual(self.mem.read8(0x0), 0)
        self.assertEqual(self.mem.read8(0x7FF), 0)
        self.assertEqual(self.mem.read8(-1), 0)
        self.assertEqual(self.mem[0x0], 0)

        self.assertEqual(self.mem[0x70], 0xFF)

        with self.assertRaises(IndexError):
            self.mem.read8(0x800)

    def test_read16(self):
        self.assertEqual(self.mem.read16(0x0), b'\x00\x00')
        self.assertEqual(self.mem.read16(0x7FE), b'\x00\x00')
        self.assertEqual(self.mem.read16(-1), b'')

        self.assertEqual(self.mem.read16(0x70), b'\xFF\xFF')


        with self.assertRaises(IndexError):
            self.mem.read16(0x800)

        with self.assertRaises(IndexError):
            self.mem.read16(0x7FF)

    def test_read32(self):
        self.assertEqual(self.mem.read32(0x0), b'\x00\x00\x00\x00')
        self.assertEqual(self.mem.read32(0x7FC), b'\x00\x00\x00\x00')
        self.assertEqual(self.mem.read32(-1), b'')

        self.assertEqual(self.mem.read32(0x70), b'\xFF\xFF\xFF\xFF')


        with self.assertRaises(IndexError):
            self.mem.read32(0x800)

        with self.assertRaises(IndexError):
            self.mem.read32(0x7FD)

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
        self.assertEqual(len(self.mem), 0x800)
        self.mem.write_bin(0, b'\xde\xad\xbe\xef')
        self.assertEqual(len(self.mem), 0x800)
        self.assertEqual(self.mem[0:2], b'\xde\xad')
        self.assertEqual(self.mem[2:4], b'\xbe\xef')

    def test_resolve(self):
        with self.assertRaises(IndexError):
            self.memmap.resolve(0x100)

        self.assertEqual((self.mem, 0x800), self.memmap.resolve(0x900))

    def test_mmap_read(self):
        with self.assertRaises(IndexError):
            self.memmap.read16(0x100)

        with self.assertRaises(IndexError):
            self.memmap.read32(0x100)

        self.assertEqual(self.memmap.read32(0x870), b'\xFF\xFF\xFF\xFF')
        self.assertEqual(self.memmap.read16(0x870), b'\xFF\xFF')

        with self.assertRaises(IndexError):
            self.memmap.read16(0x1FFF)

        with self.assertRaises(IndexError):
            self.memmap.read32(0x1FFD)
