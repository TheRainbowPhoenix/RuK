import typing

from typing import Union

if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.jcore.cpu import CPU

from ctypes import c_long, c_uint32, c_ulong


def _i(val: Union[int, bytearray, bytes]) -> int:
    """
    Safe type conversion
    """
    if type(val) in [bytearray, bytes]:
        return int.from_bytes(val, "big")  # , signed=True
    return c_long(val).value


def _b(val: int, size: int = 4) -> bytes:
    return val.to_bytes(size, 'big')


def _u(val: Union[int, bytearray, bytes]) -> int:
    """
    Safe type conversion, unsigned
    """
    if type(val) in [bytearray, bytes]:
        return int.from_bytes(val, "big", signed=False)  # , signed=True
    return c_ulong(val).value


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
            81: self.ADDC,
            82: self.ADDV,
            83: self.CMPIM,
            84: self.CMPEQ,
            85: self.CMPHI,
            86: self.CMPGE,
            87: self.CMPHI,
            88: self.CMPGT,
            89: self.CMPPL,
            90: self.CMPPZ,
            91: self.CMPSTR,
            103: self.DT,
            104: self.EXTSB,
            105: self.EXTSW,
            106: self.EXTUB,
            107: self.EXTUW,
            116: self.SUB,
            141: self.SHLL,
            142: self.SHLL2,
            143: self.SHLL8,
            144: self.SHLL16,
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
            256: self.STSMPR,
            270: self.TRAPA,
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
        self.cpu.mem.write32(self.cpu.regs[n], _b(self.cpu.regs[m]))  # TODO: generated
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
        self.cpu.mem.write32(self.cpu.regs[n] - 4, _b(self.cpu.regs[m]))  # TODO: generated
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
        if ((self.cpu.regs[0] & 0x80) == 0):  # TODO
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
        if (self.cpu.regs[0] & 0x8000) == 0:  # TODO
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

    def ADDC(self, m: int, n: int):
        """
        Rn + Rm + T -> Rn, carry -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        tmp1 = _u(self.cpu.regs[n] + self.cpu.regs[m])  # TODO: generated
        tmp0 = _u(self.cpu.regs[n])  # TODO: generated
        self.cpu.regs[n] = _u(tmp1 + self.cpu.regs['sr'])  # TODO: generated
        if tmp0 > tmp1:  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        if tmp1 > _u(self.cpu.regs[n]):  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        self.cpu.pc += 2

    def ADDV(self, m: int, n: int):
        """
        Rn + Rm -> Rn, overflow -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # long dest, src, ans  # TODO: generated
        dest = 0 if _i(self.cpu.regs[n]) >= 0 else 1
        src = 0 if _i(self.cpu.regs[m]) >= 0 else 1

        src += dest  # TODO: generated
        self.cpu.regs[n] += self.cpu.regs[m]  # TODO: generated
        ans = 0 if _i(self.cpu.regs[n]) >= 0 else 1  # TODO
        ans += dest  # TODO: generated
        if src == 0 or src == 2:  # TODO
            if ans == 1:  # TODO
                self.cpu.regs['sr'] = 1  # TODO: generated
            else:  # TODO
                self.cpu.regs['sr'] = 0  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def CMPIM(self, i: int):
        """
        If R0 = (sign extension)imm: 1 -> T Else: 0 -> T
        :param i: value to add (up to 0xFF)
        """
        if (i & 0x80) == 0:  # TODO
            imm = _i(0x000000FF & i)  # TODO: generated
        else:  # TODO
            imm = _i(0xFFFFFF00 | i)  # TODO: generated
        if self.cpu.regs[0] == imm:  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def CMPEQ(self, m: int, n: int):
        """
        If Rn = Rm: 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        if self.cpu.regs[n] == self.cpu.regs[m]:  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def CMPHI(self, m: int, n: int):
        """
        If Rn > Rm (unsigned): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        if _u(self.cpu.regs[n]) > _u(self.cpu.regs[m]):  # TODO
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def CMPGE(self, m: int, n: int):
        """
        If Rn >= Rm (signed): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        if _i(self.cpu.regs[n]) >= _i(self.cpu.regs[m]):
            self.cpu.regs['sr'] = 1  # TODO: generated
        else:  # TODO
            self.cpu.regs['sr'] = 0  # TODO: generated
        self.cpu.pc += 2

    def CMPGT(self, m: int, n: int):
        """
        1 -> T If Rn > Rm (signed) Else 0 -> 1
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs['sr'] = 1 if _i(self.cpu.regs[n]) > _i(self.cpu.regs[m]) else 0
        self.cpu.pc += 2

    def CMPPL(self, n: int):
        """
        If Rn > 0 (signed): 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        if _i(self.cpu.regs[n]) > 0:
            self.cpu.regs['sr'] = 1
        else:
            self.cpu.regs['sr'] = 0
        self.cpu.pc += 2

    def CMPPZ(self, n: int):
        """
        If Rn >= 0 (signed): 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        if _i(self.cpu.regs[n]) >= 0:
            self.cpu.regs['sr'] = 1
        else:
            self.cpu.regs['sr'] = 0
        self.cpu.pc += 2

    def CMPSTR(self, m: int, n: int):
        """
        If Rn and Rm have an equal byte: 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # unsigned long temp  # TODO: generated
        # long HH, HL, LH, LL  # TODO: generated
        # temp = self.cpu.regs[n] ^ self.cpu.regs[m]  # TODO: generated
        # HH = (temp & 0xFF000000) >> 24  # TODO: generated
        # HL = (temp & 0x00FF0000) >> 16  # TODO: generated
        # LH = (temp & 0x0000FF00) >> 8  # TODO: generated
        # LL = temp & 0x000000FF  # TODO: generated
        # HH = HH && HL && LH && LL  # TODO: generated
        # if (HH == 0):  # TODO
        #     T = 1  # TODO: generated
        # else:  # TODO
        #     T = 0  # TODO: generated
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

    def SUB(self, m: int, n: int):
        """
        Rn - Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] -= self.cpu.regs[m]  # TODO: generated
        self.cpu.pc += 2

    def SHLL(self, n: int):
        """
        T << Rn << 0
        :param n: register index (between 0 and 15)
        """
        if (self.cpu.regs[n] & 0x80000000) == 0:
            T = 0  # TODO: generated
        else:  # TODO
            T = 1  # TODO: generated
        self.cpu.regs[n] <<= 1  # TODO: generated
        self.cpu.pc += 2

    def SHLL2(self, n: int):
        """
        Rn << 2 -> Rn
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] <<= 2
        self.cpu.pc += 2

    def SHLL8(self, n: int):
        """
        Rn << 8 -> Rn
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] <<= 8
        self.cpu.pc += 2

    def SHLL16(self, n: int):
        """
        Rn << 16 -> Rn
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] <<= 16
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
        if (d & 0x80) == 0:  # TODO
            disp = 0x000000FF & d
        else:  # TODO
            disp = _i(0xFFFFFF00 | d)  # (long)i
        if self.cpu.regs['sr'] == 1:  # TODO
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

    def STSMPR(self, n: int):
        """
        Rn-4 -> Rn, PR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        self.cpu.regs[n] -= 4
        self.cpu.mem.write32(self.cpu.regs[n], _b(self.cpu.regs['pr']))  # TODO: generated
        self.cpu.pc += 2

    def TRAPA(self, i: int):
        """
        SH1*,SH2*: PC/SR -> stack area, (imm*4 + VBR) -> PC SH3*,SH4*: PC/SR -> SPC/SSR, imm*4 -> TRA, 0x160 -> EXPEVT, VBR + 0x0100 -> PC
        :param i: value to add (up to 0xFF)
        """
        # int imm = (0x000000FF & i)  # TODO: generated
        # TRA = imm << 2  # TODO: generated
        # SSR = SR  # TODO: generated
        # Sself.cpu.pc = self.cpu.pc + 2  # TODO: generated
        # SGR = R15  # TODO: generated
        # SR.MD = 1  # TODO: generated
        # SR.BL = 1  # TODO: generated
        # SR.RB = 1  # TODO: generated
        # EXPEVT = 0x00000160  # TODO: generated
        # self.cpu.pc = VBR + 0x00000100  # TODO: generated
        raise NotImplementedError()
        pass  # TODO: Implement me !
