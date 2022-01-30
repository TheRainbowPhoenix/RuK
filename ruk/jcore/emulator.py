import typing

from typing import Union

if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.jcore.cpu import CPU

from ctypes import c_long, c_uint32


def _i(val: Union[int, bytearray, bytes]) -> int:
    """
    Safe type conversion
    """
    if type(val) in [bytearray, bytes]:
        return int.from_bytes(val, "big")  # , signed=True
    return c_long(val).value


class Emulator:
    """
    Simple python OPCodes emulator
    """

    def __init__(self, cpu: 'CPU'):
        self.cpu = cpu
        self.debug = self.cpu.debug

        self._resolve_table = {
            0: self.MOV,
            1: self.MOVI,
            4: self.MOVA,
            5: self.MOVWI,
            6: self.MOVLI,
            7: self.MOVBL,
            8: self.MOVWL,
            9: self.MOVLL,
            10: self.MOVBS,
            11: self.MOVWS,
            12: self.MOVLS,
            13: self.MOVBP,
            14: self.MOVWP,
            15: self.MOVLP,
            16: self.MOVBM,
            17: self.MOVWM,
            18: self.MOVLM,
            25: self.MOVBL4,
            28: self.MOVWL4,
            31: self.MOVLL4,
            33: self.MOVBS4,
            35: self.MOVWS4,
            37: self.MOVLS4,
            39: self.MOVBL0,
            40: self.MOVWL0,
            41: self.MOVLL0,
            42: self.MOVBS0,
            43: self.MOVWS0,
            44: self.MOVLS0,
            45: self.MOVBLG,
            46: self.MOVWLG,
            47: self.MOVLLG,
            48: self.MOVBSG,
            49: self.MOVWSG,
            50: self.MOVLSG,
            60: self.MOVT,
            62: self.SWAPB,
            63: self.SWAPW,
            64: self.XTRCT,
            79: self.ADD,
            80: self.ADDI,
            88: self.CMPGT,
            103: self.DT,
            104: self.EXTSB,
            105: self.EXTSW,
            106: self.EXTUB,
            107: self.EXTUW,
            149: self.BF,
            150: self.BFS,
            151: self.BT,
            152: self.BTS,
            153: self.BRA,
            154: self.BRAF,
            155: self.BSR,
            156: self.BSRF,
            157: self.JMP,
            158: self.JSR,
            161: self.RTS,
            214: self.NOP,
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
    Emulates OpCodes (Manually Reviewed)
    """

    def MOV(self, m: int, n: int):
        """
        MOV Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.regs[m])
        self.cpu.pc += 2

    def MOVI(self, i: int, n: int):
        """
        Rn + i
        :param i: value to add (up to 0xFF)
        :param n: register index (between 0 and 15)
        """
        if (i & 0x80) == 0:
            self.cpu.regs[n] = _i(0x000000FF & i)  # in C: (long)i
        else:
            self.cpu.regs[n] = _i(0xFFFFFF00 | i)

        self.cpu.pc += 2

    def MOVA(self, d: int):
        """
        (disp*4) + (PC & 0xFFFFFFFC) + 4 -> R0
        :param d: disp
        """
        disp = (0x000000FF & d)
        self.cpu.regs[0] = _i((self.cpu.pc & 0xFFFFFFFC) + 4 + (disp << 2))
        self.cpu.pc += 2

    def MOVWI(self, d: int, n: int):
        """
        (disp*2 + PC + 4) -> sign extension -> Rn
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x000000FF & d)
        self.cpu.regs[n] = _i(self.cpu.mem.read16(self.cpu.pc + 4 + (disp << 1)))
        if (self.cpu.regs[n] & 0x8000) == 0:  # TODO
            self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFF0000 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def MOVLI(self, d: int, n: int):
        """
        (disp*4 + (PC & 0xFFFFFFFC) + 4) -> sign extension -> Rn
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x000000FF & d)  # TODO: generated
        self.cpu.regs[n] = _i(self.cpu.mem.read32((self.cpu.pc & 0xFFFFFFFC) + 4 + (disp << 2)))  # TODO: generated
        self.cpu.pc += 2

    def MOVBL(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read8(self.cpu.regs[m]))  # TODO: generated
        if (self.cpu.regs[n] & 0x80) == 0:  # TODO
            self.cpu.regs[n] &= 0x000000FF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFFFF00 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def MOVWL(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read16(self.cpu.regs[m]))  # TODO: generated
        if (self.cpu.regs[n] & 0x8000) == 0:  # TODO
            self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFF0000 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def MOVLL(self, m: int, n: int):
        """
        (Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read32(self.cpu.regs[m]))  # TODO: generated
        self.cpu.pc += 2

    def MOVBS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write8(self.cpu.regs[n], self.cpu.regs[m])
        self.cpu.pc += 2

    def MOVWS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write16(self.cpu.regs[n], self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVLS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write32(self.cpu.regs[n], self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVBP(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn, Rm+1 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read8(self.cpu.regs[m]))  # TODO: generated
        if (self.cpu.regs[n] & 0x80) == 0:  # TODO
            self.cpu.regs[n] &= 0x000000FF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFFFF00 | self.cpu.regs[n])  # TODO: generated
        if n != m:  # TODO
            self.cpu.regs[m] += 1  # TODO: generated
        self.cpu.pc += 2

    def MOVWP(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn, Rm+2 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read16(self.cpu.regs[m]))  # TODO: generated
        if (self.cpu.regs[n] & 0x8000) == 0:  # TODO
            self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFF0000 | self.cpu.regs[n])  # TODO: generated
        if n != m:  # TODO
            self.cpu.regs[m] += 2  # TODO: generated
        self.cpu.pc += 2

    def MOVLP(self, m: int, n: int):
        """
        (Rm) -> Rn, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read32(self.cpu.regs[m]))  # TODO: generated
        if (n != m):  # TODO
            self.cpu.regs[m] += 4  # TODO: generated
        self.cpu.pc += 2

    def MOVBM(self, m: int, n: int):
        """
        Rn-1 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write8(self.cpu.regs[n] - 1, self.cpu.regs[m])
        self.cpu.regs[n] -= 1
        self.cpu.pc += 2

    def MOVWM(self, m: int, n: int):
        """
        Rn-2 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write16(self.cpu.regs[n] - 2, self.cpu.regs[m])  # TODO: generated
        self.cpu.regs[n] -= 2  # TODO: generated
        self.cpu.pc += 2

    def MOVLM(self, m: int, n: int):
        """
        Rn-4 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write32(self.cpu.regs[n] - 4, self.cpu.regs[m])  # TODO: generated
        self.cpu.regs[n] -= 4  # TODO: generated
        self.cpu.pc += 2

    def MOVBL4(self, m: int, d: int):
        """
        (disp + Rm) -> sign extension -> R0
        :param m: register index (between 0 and 15)
        :param d: disp
        """
        disp = (0x0000000F & d)  # (long)d  # TODO: generated
        self.cpu.regs[0] = _i(self.cpu.mem.read8(self.cpu.regs[m] + disp))  # TODO: generated
        if ((R[0] & 0x80) == 0):  # TODO
            self.cpu.regs[0] &= 0x000000FF  # TODO: generated
        else:  # TODO
            self.cpu.regs[0] = _i(0xFFFFFF00 | self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVWL4(self, m: int, d: int):
        """
        (disp*2 + Rm) -> sign extension -> R0
        :param m: register index (between 0 and 15)
        :param d: disp
        """
        disp = (0x0000000F & d)  # (long)d  # TODO: generated
        self.cpu.regs[0] = _i(self.cpu.mem.read16(self.cpu.regs[m] + (disp << 1)))  # TODO: generated
        if ((R[0] & 0x8000) == 0):  # TODO
            self.cpu.regs[0] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[0] = _i(0xFFFF0000 | self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVLL4(self, m: int, d: int, n: int):
        """
        (disp*4 + Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x0000000F & d)  # (long)d  # TODO: generated
        self.cpu.regs[n] = _i(self.cpu.mem.read32(self.cpu.regs[m] + (disp << 2)))  # TODO: generated
        self.cpu.pc += 2

    def MOVBS4(self, d: int, n: int):
        """
        R0 -> (disp + Rn)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x0000000F & d)  # (long)  # TODO: generated
        self.cpu.mem.write8(self.cpu.regs[n] + disp, self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVWS4(self, d: int, n: int):
        """
        R0 -> (disp*2 + Rn)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x0000000F & d)  # (long)d  # TODO: generated
        self.cpu.mem.write16(self.cpu.regs[n] + (disp << 1), self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVLS4(self, m: int, d: int, n: int):
        """
        Rm -> (disp*4 + Rn)
        :param m: register index (between 0 and 15)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        disp = (0x0000000F & d)  # (long)d  # TODO: generated
        self.cpu.mem.write32(self.cpu.regs[n] + (disp << 2), self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVBL0(self, m: int, n: int):
        """
        (R0 + Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read8(self.cpu.regs[m] + self.cpu.regs[0]))  # TODO: generated
        if (self.cpu.regs[n] & 0x80) == 0:  # TODO
            self.cpu.regs[n] &= 0x000000FF  # TODO: generated
        else:
            self.cpu.regs[n] = _i(0xFFFFFF00 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def MOVWL0(self, m: int, n: int):
        """
        (R0 + Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read16(self.cpu.regs[m] + self.cpu.regs[0]))  # TODO: generated
        if (self.cpu.regs[n] & 0x8000) == 0:  # TODO
            self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFF0000 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def MOVLL0(self, m: int, n: int):
        """
        (R0 + Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.mem.read32(self.cpu.regs[m] + self.cpu.regs[0]))  # TODO: generated
        self.cpu.pc += 2

    def MOVBS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write8(self.cpu.regs[n] + self.cpu.regs[0], self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVWS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write16(self.cpu.regs[n] + self.cpu.regs[0], self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVLS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.mem.write32(self.cpu.regs[n] + self.cpu.regs[0], self.cpu.regs[m])  # TODO: generated
        self.cpu.pc += 2

    def MOVBLG(self, d: int):
        """
        (disp + GBR) -> sign extension -> R0
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int  # TODO: generated
        self.cpu.regs[0] = _i(self.cpu.mem.read8(self.cpu.regs['gbr'] + disp))  # TODO: generated
        if ((self.cpu.regs[0] & 0x80) == 0):  # TODO
            self.cpu.regs[0] &= 0x000000FF  # TODO: generated
        else:  # TODO
            self.cpu.regs[0] = _i(0xFFFFFF00 | self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVWLG(self, d: int):
        """
        (disp*2 + GBR) -> sign extension -> R0
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int  # TODO: generated
        self.cpu.regs[0] = _i(self.cpu.mem.read16(self.cpu.regs['gbr'] + (disp << 1)))  # TODO: generated
        if ((self.cpu.regs[0] & 0x8000) == 0):  # TODO
            self.cpu.regs[0] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[0] = _i(0xFFFF0000 | self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVLLG(self, d: int):
        """
        (disp*4 + GBR) -> R0
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int   # TODO: generated
        self.cpu.regs[0] = _i(self.cpu.mem.read32(self.cpu.regs['gbr'] + (disp << 2)))  # TODO: generated
        self.cpu.pc += 2

    def MOVBSG(self, d: int):
        """
        R0 -> (disp + GBR)
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int  # TODO: generated
        self.cpu.mem.write8(self.cpu.regs['gbr'] + disp, self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVWSG(self, d: int):
        """
        R0 -> (disp*2 + GBR)
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int  # TODO: generated
        self.cpu.mem.write16(self.cpu.regs['gbr'] + (disp << 1), self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVLSG(self, d: int):
        """
        R0 -> (disp*4 + GBR)
        :param d: disp
        """
        disp = (0x000000FF & d)  # unsigned int, (long)d  # TODO: generated
        self.cpu.mem.write32(self.cpu.regs['gbr'] + (disp << 2), self.cpu.regs[0])  # TODO: generated
        self.cpu.pc += 2

    def MOVT(self, n: int):
        """
        T -> Rn
        :param n: register index (between 0 and 15)
        """
        if self.cpu.regs['sr'] == 1:  # TODO
            self.cpu.regs[n] = 0x00000001  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = 0x00000000  # TODO: generated
        self.cpu.pc += 2

    def SWAPB(self, m: int, n: int):
        """
        Rm -> swap lower 2 bytes -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # unsigned long temp0, temp1  # TODO: generated
        temp0 = self.cpu.regs[m] & 0xFFFF0000  # TODO: generated
        temp1 = (self.cpu.regs[m] & 0x000000FF) << 8  # TODO: generated
        self.cpu.regs[n] = _i((self.cpu.regs[m] & 0x0000FF00) >> 8)  # TODO: generated
        self.cpu.regs[n] = _i(self.cpu.regs[n] | temp1 | temp0)  # TODO: generated
        self.cpu.pc += 2

    def SWAPW(self, m: int, n: int):
        """
        Rm -> swap upper/lower words -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # unsigned long temp  # TODO: generated
        temp = (self.cpu.regs[m] >> 16) & 0x0000FFFF  # TODO: generated
        self.cpu.regs[n] = _i(self.cpu.regs[m] << 16)  # TODO: generated
        self.cpu.regs[n] = _i(self.cpu.regs[n] | temp)  # TODO: generated
        self.cpu.pc += 2

    def XTRCT(self, m: int, n: int):
        """
        Rm:Rn middle 32 bits -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        high = (self.cpu.regs[m] << 16) & 0xFFFF0000  # unsigned long # TODO: generated
        low = (self.cpu.regs[n] >> 16) & 0x0000FFFF  # unsigned long # TODO: generated
        self.cpu.regs[n] = _i(high | low)  # TODO: generated
        self.cpu.pc += 2

    def ADD(self, m: int, n: int):
        """
        Rn += Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] += _i(self.cpu.regs[m])
        self.cpu.pc += 2

    def ADDI(self, i: int, n: int):
        """
        Rn + i
        :param i: value to add (up to 0xFF)
        :param n: register index (between 0 and 15)
        """
        if (i & 0x80) == 0:  # TODO
            self.cpu.regs[n] += _i(0x000000FF & i)  # (long)i # TODO: generated
        else:  # TODO
            self.cpu.regs[n] += _i(0xFFFFFF00 | i)  # (long)i # TODO: generated

        self.cpu.pc += 2

    def CMPGT(self, m: int, n: int):
        """
        1 -> T If Rn > Rm (signed) Else 0 -> 1
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs['sr'] = 1 if _i(self.cpu.regs[n]) > _i(self.cpu.regs[m]) else 0
        self.cpu.pc += 2

    def DT(self, n: int):
        """
        Rn-1 -> Rn If Rn = 0: 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] -= 1  # TODO: generated
        if self.cpu.regs[n] == 0:  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def EXTSB(self, m: int, n: int):
        """
        Rm sign-extended from byte -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.regs[m])
        if (self.cpu.regs[m] & 0x00000080) == 0:  # TODO
            self.cpu.regs[n] &= 0x000000FF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFFFF00 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def EXTSW(self, m: int, n: int):
        """
        Rm sign-extended from word -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.regs[m])
        if (self.cpu.regs[m] & 0x00008000) == 0:  # TODO
            self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        else:  # TODO
            self.cpu.regs[n] = _i(0xFFFF0000 | self.cpu.regs[n])  # TODO: generated
        self.cpu.pc += 2

    def EXTUB(self, m: int, n: int):
        """
        Rm zero-extended from byte -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.regs[m])
        self.cpu.regs[n] &= 0x000000FF  # TODO: generated
        self.cpu.pc += 2

    def EXTUW(self, m: int, n: int):
        """
        Rm zero-extended from word -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] = _i(self.cpu.regs[m])
        self.cpu.regs[n] &= 0x0000FFFF  # TODO: generated
        self.cpu.pc += 2

    def BF(self, d: int):
        """
        disp*2 + PC + 4 -> PC If T = 0 Else nop
        :param d: label
        T: cpu.regs['sr']
        """
        if (d & 0x80) == 0:  # TODO
            disp = (0x000000FF & d)
        else:  # TODO
            disp = _i(0xFFFFFF00 | d)  # (long)i # TODO: generated

        if self.cpu.regs['sr'] == 0:
            self.cpu.pc += 4 + (disp << 1)
        else:
            self.cpu.pc += 2

    def BFS(self, d: int):
        """
        If T = 0: disp*2 + PC + 4 -> PC Else: nop (Delayed branch)
        :param d: disp
        """
        # int disp  # TODO: generated
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc
        if (d & 0x80) == 0:  # TODO
            disp = (0x000000FF & d)
        else:  # TODO
            disp = c_long(0xFFFFFF00 | d).value  # (long)i
        if self.cpu.regs['sr'] == 0:  # TODO
            self.cpu.pc = self.cpu.pc + 4 + (disp << 1)
        else:  # TODO
            self.cpu.pc += 4
        self.cpu.delay_slot(temp + 2)

    def BT(self, d: int):
        """
        If T = 1: disp*2 + PC + 4 -> PC Else: nop
        :param d: disp
        """
        # int disp  # TODO: generated
        if ((d & 0x80) == 0):  # TODO
            disp = (0x000000FF & d)  # TODO: generated
        else:  # TODO
            disp = c_long(0xFFFFFF00 | d).value  # (long)i
        if self.cpu.regs['sr'] == 0:  # TODO
            self.cpu.pc = self.cpu.pc + 4 + (disp << 1)  # TODO: generated
        else:  # TODO
            self.cpu.pc += 2

    def BTS(self, d: int):
        """
        If T = 1: disp*2 + PC + 4 -> PC Else: nop (Delayed branch)
        :param d: disp
        """
        # int disp  # TODO: generated
        # unsigned temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        if (d & 0x80) == 0:  # TODO
            disp = (0x000000FF & d)  # TODO: generated
        else:  # TODO
            disp = (0xFFFFFF00 | d)  # TODO: generated
        if self.cpu.regs['sr'] == 0:
            self.cpu.pc += 4 + (disp << 1)  # TODO: generated
        else:  # TODO
            self.cpu.pc += 4  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated

    def BRA(self, d: int):
        """
        disp*2 + PC + 4 -> PC
        :param d: label
        """
        if (d & 0x800) == 0:  # TODO
            disp = (0x00000FFF & d)  # TODO: generated
        else:  # TODO
            disp = c_long(0xFFFFF000 | d).value
        pc = self.cpu.pc
        self.cpu.delay_slot(pc + 2)
        self.cpu.pc += 4 + (disp << 1)

    def BRAF(self, m: int):
        """
        Rm + PC + 4 -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated
        self.cpu.pc += 4 + self.cpu.regs[m]  # TODO: generated

    def BSR(self, d: int):
        """
        PC + 4 -> PR, disp*2 + PC + 4 -> PC (Delayed branch)
        :param d: disp
        """
        # int disp  # TODO: generated
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        if (d & 0x800) == 0:  # TODO
            disp = (0x00000FFF & d)  # TODO: generated
        else:  # TODO
            disp = c_long(0xFFFFF000 | d).value  # TODO: generated
        PR = self.cpu.pc + 4  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated
        self.cpu.pc = self.cpu.pc + 4 + (disp << 1)  # TODO: generated

    def BSRF(self, m: int):
        """
        PC + 4 -> PR, Rm + PC + 4 -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        self.cpu.regs['pr'] = self.cpu.pc + 4  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated
        self.cpu.pc = self.cpu.pc + 4 + self.cpu.regs[m]  # TODO: generated

    def JMP(self, m: int):
        """
        Rm -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated
        self.cpu.pc = self.cpu.regs[m]  # TODO: generated

    def JSR(self, m: int):
        """
        PC + 4 -> PR, Rm -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # unsigned int temp  # TODO: generated
        temp = self.cpu.pc  # TODO: generated
        PR = self.cpu.pc + 4  # TODO: generated
        self.cpu.delay_slot(temp + 2)  # TODO: generated
        self.cpu.pc = self.cpu.regs[m]  # TODO: generated

    def RTS(self):
        """
        PR -> PC
        """
        temp = self.cpu.pc
        self.cpu.delay_slot(temp + 2)
        self.cpu.pc = self.cpu.regs['pr']

    def NOP(self):
        """
        No operation
        """
        self.cpu.pc += 2
