import typing
if typing.TYPE_CHECKING:
    from ruk.jcore.cpu import CPU

from ctypes import c_long

class Emulator:
    """
    Simple python OPCodes emulator
    """
    def __init__(self, cpu: 'CPU'):
        self.cpu = cpu
        self.debug = self.cpu.debug

        # TODO: Lookup table, please keep me updated when adding OP !
        self._resolve_table = {
            0: self.mov,
            80: self.addi,
        }

    def resolve(self, opcode_id: int) -> typing.Callable:
        """
        Resolve opcode index in lookup table, getting the asm method from it.
        :param opcode_id: integer
        :return: self method
        """
        if opcode_id in self._resolve_table:
            return self._resolve_table[opcode_id]
        raise IndexError(f"OPCode index \"{opcode_id}\" not resolved (did you added it to _resolve_table ?)")

    """
    Emulates OpCodes
    """

    def mov(self, m: int, n: int):
        """
        MOV Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = self.cpu.regs[m]
        self.cpu.pc += 2

    def addi(self, i: int, n: int):
        """
        Rn + i
        :param i: value to add (up to 0xFF)
        :param n: register index (between 0 and 15)
        """
        if (i & 0x80) == 0:
            self.cpu.regs[n] += (0x000000FF & i)  # in C: (long)i
        else:
            self.cpu.regs[n] += c_long(0xFFFFFF00 | c_long(-1).value).value

        self.cpu.pc += 2
