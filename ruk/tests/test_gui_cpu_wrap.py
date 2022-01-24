from unittest import TestCase
from unittest.mock import MagicMock

import tkinter as tk

from ruk.gui.cpu_wrap import RegisterWrapper
from ruk.jcore.cpu import Register


class TestRegisterWrapper(TestCase):
    def setUp(self) -> None:
        self.regs = Register()

        self.regs['r1'] = 0xff
        self.regs['sr'] = 1

        self.root = tk.Tk()
        self.frame = tk.Frame(self.root, bd=12)
        self.frame.pack(fill='both', expand=1, anchor=tk.SE)

        self.wrap_r1 = RegisterWrapper('r1', self.regs)
        self.wrap_sr = RegisterWrapper('sr', self.regs)

        self.wrap_r1.set_widget(self.frame)
        self.wrap_sr.set_widget(self.frame)

    def tearDown(self) -> None:
        pass

    def test_wrap(self):
        self.assertEqual(self.wrap_r1.name, "r1")
        self.assertEqual(self.wrap_sr.name, "sr")

    def test_update(self):
        self.wrap_r1.update_values()
        self.assertEqual(self.wrap_r1.regEdit.get(), '0xff')

        self.regs['r1'] = 0x7f
        self.assertEqual(self.wrap_r1.regEdit.get(), '0xff')
        self.wrap_r1.update_values()
        self.assertEqual(self.wrap_r1.regEdit.get(), '0x7f')

    def test_update_step(self):
        self.wrap_r1.update_values()
        self.assertEqual(self.wrap_r1._value_changed, False)
        self.regs['r1'] = 0x7f
        self.wrap_r1.update_values(step=True)
        self.assertEqual(self.wrap_r1.regEdit.get(), '0x7f')
        self.assertEqual(self.wrap_r1._value_changed, True)

        self.wrap_r1.update_values(step=True)
        self.assertEqual(self.wrap_r1.regEdit.get(), '0x7f')
        self.assertEqual(self.wrap_r1._value_changed, False)

    def _set_value(self, wrap, val):
        wrap.delete(0, tk.END)
        wrap.insert(0, val)

    def test_validate(self):
        self.wrap_r1.update_values()

        self._set_value(self.wrap_r1.regEdit, "0xERR")

        self.wrap_r1.do_validate()
        self.assertIn("invalid", self.wrap_r1.regEdit.state())

        self._set_value(self.wrap_r1.regEdit, "0xDeAdBeEf")
        self.wrap_r1.update_values()
        self.wrap_r1.do_validate()
        self.assertNotIn("invalid", self.wrap_r1.regEdit.state())
