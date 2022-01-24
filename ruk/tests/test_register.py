from unittest import TestCase
from unittest.mock import patch

from ruk.jcore.cpu import Register

class TestRegister(TestCase):
    def setUp(self) -> None:
        self.regs = Register()
        self.regs._regs["r15"] = 0xFF

    def test_get(self):
        self.assertEqual(self.regs[0], 0)
        self.assertEqual(self.regs['r0'], 0)
        self.assertEqual(self.regs[15], 0xFF)
        self.assertEqual(self.regs['r15'], 0xFF)

        with self.assertRaises(IndexError):
            _ = self.regs['invalid']

    def test_set(self):
        self.regs[0] = 15
        self.assertEqual(self.regs[0], 15)
        self.regs['r0'] = 14
        self.assertEqual(self.regs['r0'], 14)

        with self.assertRaises(IndexError):
            self.regs['invalid'] = 255

    def test_str(self):
        self.assertIn("r15: FF", str(self.regs))

    def test_len(self):
        self.assertEqual(22, len(self.regs))

    def test_reset(self):
        self.regs[0] = 15
        self.regs[5] = 5
        self.regs.reset()
        self.assertEqual(self.regs[0], 0)
        self.assertEqual(self.regs[5], 0)

    def test_iter(self):
        self.assertIn('r5', list(self.regs))

    @patch('builtins.print')
    def test_dump(self, mock_print):
        self.regs.dump()
        mock_print.assert_called_with('r0   = 00\t\tr1   = 00\t\tr2   = 00\t\tr3   = 00\t\nr4   = 00\t\tr5   = 00\t\tr6   = 00\t\tr7   = 00\t\nr8   = 00\t\tr9   = 00\t\tr10  = 00\t\tr11  = 00\t\nr12  = 00\t\tr13  = 00\t\tr14  = 00\t\tr15  = FF\t\npr   = 00\t\tsr   = 00\t\tgbr  = 00\t\tvbr  = 00\t', end='\nmach = 00\t\tmacl = 00\t\n')

