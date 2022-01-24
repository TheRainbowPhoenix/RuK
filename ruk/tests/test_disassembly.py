from unittest import TestCase
from unittest.mock import patch

from ruk.jcore.disassembly import Disassembler


class TestDisassembler(TestCase):
    def setUp(self) -> None:
        self.disasm = Disassembler(debug=False)

    @patch('builtins.print')
    def test_disasm_debug(self, mock_print):
        self.disasm = Disassembler(debug=True)
        self.disasm.disasm(0x717f)
        mock_print.assert_called_with('R1 += 7F')

    def test_disasm_trace_only(self):
        self.disasm = Disassembler(debug=False)
        self.assertEqual(("add #h'%04x, r%d", (0x7f, 1)), self.disasm.disasm(0x717f, trace_only=True))
