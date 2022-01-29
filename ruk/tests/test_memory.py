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

    def test_get_range(self):
        self.assertEqual(self.mem.get_range(2, 6), b'\x00\x00\x00\x00')
        self.mem.write_bin(4, b'\xde\xad\xbe\xef')
        self.assertEqual(self.mem.get_range(2, 6), b'\x00\x00\xde\xad')
        self.assertEqual(self.mem.get_range(6, 10), b'\xbe\xef\x00\x00')

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

    def test_get_arround(self):
        with self.assertRaises(IndexError):
            self.memmap.get_arround(0x100, 2)

        with self.assertRaises(IndexError):
            self.memmap.get_arround(0x1001, 2)

        self.assertEqual(self.memmap.get_arround(0x870, 2), (0x86e, 0x86e + 2 * 2, b'\x00\x00\xFF\xFF'))
        self.assertEqual(self.memmap.get_arround(0x800, 2), (0x800, 0x800 + 2 * 2, b'\x00\x00\x00\x00'))
        self.assertEqual(self.memmap.get_arround(0x1000, 2), (0x1000 - 2 * 2, 0x1000, b'\x00\x00\x00\x00'))

    def test__write16(self):
        self.assertEqual(self.memmap.read16(0x870), b'\xFF\xFF')
        self.memmap._write16(0x870, b'\x13\x3F')
        self.assertEqual(self.memmap.read16(0x870), b'\x13\x3F')
