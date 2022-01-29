import typing
if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.jcore.cpu import CPU

from ctypes import c_long

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
            96: self.DIV0S,
            97: self.DIV0U,
            98: self.DIV1,
            101: self.DMULS,
            102: self.DMULU,
            103: self.DT,
            104: self.EXTSB,
            105: self.EXTSW,
            106: self.EXTUB,
            107: self.EXTUW,
            108: self.MACL,
            109: self.MACW,
            110: self.MULL,
            112: self.MULS,
            113: self.MULU,
            114: self.NEG,
            115: self.NEGC,
            116: self.SUB,
            117: self.SUBC,
            118: self.SUBV,
            119: self.AND,
            120: self.ANDI,
            121: self.ANDM,
            122: self.NOT,
            123: self.OR,
            124: self.ORI,
            125: self.ORM,
            126: self.TAS,
            127: self.TST,
            128: self.TSTI,
            129: self.TSTM,
            130: self.XOR,
            131: self.XORI,
            132: self.XORM,
            133: self.ROTCL,
            134: self.ROTCR,
            135: self.ROTL,
            136: self.ROTR,
            137: self.SHAD,
            138: self.SHAL,
            139: self.SHAR,
            140: self.SHLD,
            141: self.SHLL,
            142: self.SHLL2,
            143: self.SHLL8,
            144: self.SHLL16,
            145: self.SHLR,
            146: self.SHLR2,
            147: self.SHLR8,
            148: self.SHLR16,
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
            164: self.CLRMAC,
            165: self.CLRS,
            166: self.CLRT,
            169: self.LDCSR,
            170: self.LDCMSR,
            172: self.LDCGBR,
            173: self.LDCMGBR,
            174: self.LDCVBR,
            175: self.LDCMVBR,
            184: self.LDCSSR,
            185: self.LDCMSSR,
            186: self.LDCSPC,
            187: self.LDCMSPC,
            188: self.LDCDBR,
            189: self.LDCMDBR,
            190: self.LDCRn_BANK,
            191: self.LDCMRn_BANK,
            194: self.LDSMACH,
            195: self.LDSMMACH,
            196: self.LDSMACL,
            197: self.LDSMMACL,
            198: self.LDSPR,
            199: self.LDSMPR,
            212: self.LDTLB,
            213: self.MOVCAL,
            214: self.NOP,
            215: self.OCBI,
            216: self.OCBP,
            217: self.OCBWB,
            218: self.PREF,
            221: self.RTE,
            224: self.SETS,
            225: self.SETT,
            226: self.SLEEP,
            228: self.STCSR,
            229: self.STCMSR,
            231: self.STCGBR,
            232: self.STCMGBR,
            233: self.STCVBR,
            234: self.STCMVBR,
            241: self.STCSGR,
            242: self.STCMSGR,
            243: self.STCSSR,
            244: self.STCMSSR,
            245: self.STCSPC,
            246: self.STCMSPC,
            247: self.STCDBR,
            248: self.STCMDBR,
            249: self.STCRm_BANK,
            250: self.STCMRm_BANK,
            251: self.STSMACH,
            252: self.STSMMACH,
            253: self.STSMACL,
            254: self.STSMMACL,
            255: self.STSPR,
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
    Emulates OpCodes (Generated)
    """
    

    def MOV(self, m: int, n: int):
        """
        Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def MOVI(self, i: int, n: int):
        """
        imm -> sign extension -> Rn
        :param i: value to add (up to 0xFF)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((i & 0x80) == 0)
        # TODO:  self.cpu.regs[n] = (0x000000FF & i);
        # TODO:  else
        # TODO:  self.cpu.regs[n] = (0xFFFFFF00 | i);
        self.cpu.pc += 2
    
    def MOVA(self, d: int):
        """
        (disp*4) + (PC & 0xFFFFFFFC) + 4 -> R0
        :param d: disp
        """
        # TODO:  unsigned int disp;
        # TODO:  disp = (unsigned int)(0x000000FF & d);
        # TODO:  R[0] = (PC & 0xFFFFFFFC) + 4 + (disp << 2);
        self.cpu.pc += 2
    
    def MOVWI(self, d: int, n: int):
        """
        (disp*2 + PC + 4) -> sign extension -> Rn
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  self.cpu.regs[n] = Read_16 (PC + 4 + (disp << 1));
        # TODO:  if ((self.cpu.regs[n] & 0x8000) == 0)
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def MOVLI(self, d: int, n: int):
        """
        (disp*4 + (PC & 0xFFFFFFFC) + 4) -> sign extension -> Rn
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  self.cpu.regs[n] = Read_32 ((PC & 0xFFFFFFFC) + 4 + (disp << 2));
        self.cpu.pc += 2
    
    def MOVBL(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_8 (self.cpu.regs[m]);
        # TODO:  if ((self.cpu.regs[n] & 0x80) == 0)
        # TODO:  self.cpu.regs[n] &= 0x000000FF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFFFF00;
        self.cpu.pc += 2
    
    def MOVWL(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_16 (self.cpu.regs[m]);
        # TODO:  if ((self.cpu.regs[n] & 0x8000) == 0)
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def MOVLL(self, m: int, n: int):
        """
        (Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_32 (self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVBS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_8 (self.cpu.regs[n], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVWS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_16 (self.cpu.regs[n], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVLS(self, m: int, n: int):
        """
        Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_32 (self.cpu.regs[n], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVBP(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn, Rm+1 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_8 (self.cpu.regs[m]);
        # TODO:  if ((self.cpu.regs[n] & 0x80) == 0)
        # TODO:  self.cpu.regs[n] &= 0x000000FF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFFFF00;
        # TODO:  if (n != m)
        # TODO:  self.cpu.regs[m] += 1;
        self.cpu.pc += 2
    
    def MOVWP(self, m: int, n: int):
        """
        (Rm) -> sign extension -> Rn, Rm+2 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_16 (self.cpu.regs[m]);
        # TODO:  if ((self.cpu.regs[n] & 0x8000) == 0)
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFF0000;
        # TODO:  if (n != m)
        # TODO:  self.cpu.regs[m] += 2;
        self.cpu.pc += 2
    
    def MOVLP(self, m: int, n: int):
        """
        (Rm) -> Rn, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_32 (self.cpu.regs[m]);
        # TODO:  if (n != m)
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def MOVBM(self, m: int, n: int):
        """
        Rn-1 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_8 (self.cpu.regs[n] - 1, self.cpu.regs[m]);
        # TODO:  self.cpu.regs[n] -= 1;
        self.cpu.pc += 2
    
    def MOVWM(self, m: int, n: int):
        """
        Rn-2 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_16 (self.cpu.regs[n] - 2, self.cpu.regs[m]);
        # TODO:  self.cpu.regs[n] -= 2;
        self.cpu.pc += 2
    
    def MOVLM(self, m: int, n: int):
        """
        Rn-4 -> Rn, Rm -> (Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_32 (self.cpu.regs[n] - 4, self.cpu.regs[m]);
        # TODO:  self.cpu.regs[n] -= 4;
        self.cpu.pc += 2
    
    def MOVBL4(self, m: int, d: int):
        """
        (disp + Rm) -> sign extension -> R0
        :param m: register index (between 0 and 15)
        :param d: disp
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  R[0] = Read_8 (self.cpu.regs[m] + disp);
        # TODO:  if ((R[0] & 0x80) == 0)
        # TODO:  R[0] &= 0x000000FF;
        # TODO:  else
        # TODO:  R[0] |= 0xFFFFFF00;
        self.cpu.pc += 2
    
    def MOVWL4(self, m: int, d: int):
        """
        (disp*2 + Rm) -> sign extension -> R0
        :param m: register index (between 0 and 15)
        :param d: disp
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  R[0] = Read_16 (self.cpu.regs[m] + (disp << 1));
        # TODO:  if ((R[0] & 0x8000) == 0)
        # TODO:  R[0] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  R[0] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def MOVLL4(self, m: int, d: int, n: int):
        """
        (disp*4 + Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  self.cpu.regs[n] = Read_32 (self.cpu.regs[m] + (disp << 2));
        self.cpu.pc += 2
    
    def MOVBS4(self, d: int, n: int):
        """
        R0 -> (disp + Rn)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  Write_8 (self.cpu.regs[n] + disp, R[0]);
        self.cpu.pc += 2
    
    def MOVWS4(self, d: int, n: int):
        """
        R0 -> (disp*2 + Rn)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  Write_16 (self.cpu.regs[n] + (disp << 1), R[0]);
        self.cpu.pc += 2
    
    def MOVLS4(self, m: int, d: int, n: int):
        """
        Rm -> (disp*4 + Rn)
        :param m: register index (between 0 and 15)
        :param d: disp
        :param n: register index (between 0 and 15)
        """
        # TODO:  long disp = (0x0000000F & (long)d);
        # TODO:  Write_32 (self.cpu.regs[n] + (disp << 2), self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVBL0(self, m: int, n: int):
        """
        (R0 + Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_8 (self.cpu.regs[m] + R[0]);
        # TODO:  if ((self.cpu.regs[n] & 0x80) == 0)
        # TODO:  self.cpu.regs[n] &= 0x000000FF;
        # TODO:  else self.cpu.regs[n] |= 0xFFFFFF00;
        self.cpu.pc += 2
    
    def MOVWL0(self, m: int, n: int):
        """
        (R0 + Rm) -> sign extension -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_16 (self.cpu.regs[m] + R[0]);
        # TODO:  if ((self.cpu.regs[n] & 0x8000) == 0)
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def MOVLL0(self, m: int, n: int):
        """
        (R0 + Rm) -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Read_32 (self.cpu.regs[m] + R[0]);
        self.cpu.pc += 2
    
    def MOVBS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_8 (self.cpu.regs[n] + R[0], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVWS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_16 (self.cpu.regs[n] + R[0], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVLS0(self, m: int, n: int):
        """
        Rm -> (R0 + Rn)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  Write_32 (self.cpu.regs[n] + R[0], self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MOVBLG(self, d: int):
        """
        (disp + GBR) -> sign extension -> R0
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  R[0] = Read_8 (GBR + disp);
        # TODO:  if ((R[0] & 0x80) == 0)
        # TODO:  R[0] &= 0x000000FF;
        # TODO:  else
        # TODO:  R[0] |= 0xFFFFFF00;
        self.cpu.pc += 2
    
    def MOVWLG(self, d: int):
        """
        (disp*2 + GBR) -> sign extension -> R0
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  R[0] = Read_16 (GBR + (disp << 1));
        # TODO:  if ((R[0] & 0x8000) == 0)
        # TODO:  R[0] &= 0x0000FFFF;
        # TODO:  else
        # TODO:  R[0] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def MOVLLG(self, d: int):
        """
        (disp*4 + GBR) -> R0
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  R[0] = Read_32 (GBR + (disp << 2));
        self.cpu.pc += 2
    
    def MOVBSG(self, d: int):
        """
        R0 -> (disp + GBR)
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  Write_8 (GBR + disp, R[0]);
        self.cpu.pc += 2
    
    def MOVWSG(self, d: int):
        """
        R0 -> (disp*2 + GBR)
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & d);
        # TODO:  Write_16 (GBR + (disp << 1), R[0]);
        self.cpu.pc += 2
    
    def MOVLSG(self, d: int):
        """
        R0 -> (disp*4 + GBR)
        :param d: disp
        """
        # TODO:  unsigned int disp = (0x000000FF & (long)d);
        # TODO:  Write_32 (GBR + (disp << 2), R[0]);
        self.cpu.pc += 2
    
    def MOVT(self, n: int):
        """
        T -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  if (T == 1)
        # TODO:  self.cpu.regs[n] = 0x00000001;
        # TODO:  else
        # TODO:  self.cpu.regs[n] = 0x00000000;
        self.cpu.pc += 2
    
    def SWAPB(self, m: int, n: int):
        """
        Rm -> swap lower 2 bytes -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long temp0, temp1;
        # TODO:  temp0 = self.cpu.regs[m] & 0xFFFF0000;
        # TODO:  temp1 = (self.cpu.regs[m] & 0x000000FF) << 8;
        # TODO:  self.cpu.regs[n] = (self.cpu.regs[m] & 0x0000FF00) >> 8;
        # TODO:  self.cpu.regs[n] = self.cpu.regs[n] | temp1 | temp0;
        self.cpu.pc += 2
    
    def SWAPW(self, m: int, n: int):
        """
        Rm -> swap upper/lower words -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long temp;
        # TODO:  temp = (self.cpu.regs[m] >> 16) & 0x0000FFFF;
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m] << 16;
        # TODO:  self.cpu.regs[n] |= temp;
        self.cpu.pc += 2
    
    def XTRCT(self, m: int, n: int):
        """
        Rm:Rn middle 32 bits -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long high = (self.cpu.regs[m] << 16) & 0xFFFF0000;
        # TODO:  unsigned long low = (self.cpu.regs[n] >> 16) & 0x0000FFFF;
        # TODO:  self.cpu.regs[n] = high | low;
        self.cpu.pc += 2
    
    def ADD(self, m: int, n: int):
        """
        Rn + Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] += self.cpu.regs[m];
        self.cpu.pc += 2
    
    def ADDI(self, i: int, n: int):
        """
        Rn + (sign extension)imm
        :param i: value to add (up to 0xFF)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((i & 0x80) == 0)
        # TODO:  self.cpu.regs[n] += (0x000000FF & (long)i);
        # TODO:  else
        # TODO:  self.cpu.regs[n] += (0xFFFFFF00 | (long)i);
        self.cpu.pc += 2
    
    def ADDC(self, m: int, n: int):
        """
        Rn + Rm + T -> Rn, carry -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long tmp0, tmp1;
        # TODO:  tmp1 = self.cpu.regs[n] + self.cpu.regs[m];
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] = tmp1 + T;
        # TODO:  if (tmp0>tmp1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  if (tmp1 > self.cpu.regs[n])
        # TODO:  T = 1;
        self.cpu.pc += 2
    
    def ADDV(self, m: int, n: int):
        """
        Rn + Rm -> Rn, overflow -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  long dest, src, ans;
        # TODO:  if ((long)self.cpu.regs[n] >= 0)
        # TODO:  dest = 0;
        # TODO:  else
        # TODO:  dest = 1;
        # TODO:  if ((long)self.cpu.regs[m] >= 0)
        # TODO:  src = 0;
        # TODO:  else
        # TODO:  src = 1;
        # TODO:  src += dest;
        # TODO:  self.cpu.regs[n] += self.cpu.regs[m];
        # TODO:  if ((long)self.cpu.regs[n] >= 0)
        # TODO:  ans = 0;
        # TODO:  else
        # TODO:  ans = 1;
        # TODO:  ans += dest;
        # TODO:  if (src == 0 || src == 2)
        # TODO:  if (ans == 1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPIM(self, i: int):
        """
        If R0 = (sign extension)imm: 1 -> T Else: 0 -> T
        :param i: value to add (up to 0xFF)
        """
        # TODO:  long imm;
        # TODO:  if ((i & 0x80) == 0)
        # TODO:  imm = (0x000000FF & (long i));
        # TODO:  else
        # TODO:  imm = (0xFFFFFF00 | (long i));
        # TODO:  if (R[0] == imm)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPEQ(self, m: int, n: int):
        """
        If Rn = Rm: 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if (self.cpu.regs[n] == self.cpu.regs[m])
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPHI(self, m: int, n: int):
        """
        If Rn >= Rm (unsigned): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((unsigned long)self.cpu.regs[n] >= (unsigned long)self.cpu.regs[m])
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPGE(self, m: int, n: int):
        """
        If Rn >= Rm (signed): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((long)self.cpu.regs[n] >= (long)self.cpu.regs[m])
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPHI(self, m: int, n: int):
        """
        If Rn > Rm (unsigned): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((unsigned long)self.cpu.regs[n] > (unsigned long)self.cpu.regs[m])
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPGT(self, m: int, n: int):
        """
        If Rn > Rm (signed): 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((long)self.cpu.regs[n] > (long)self.cpu.regs[m])
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPPL(self, n: int):
        """
        If Rn > 0 (signed): 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((long)self.cpu.regs[n] > 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPPZ(self, n: int):
        """
        If Rn >= 0 (signed): 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((long)self.cpu.regs[n] >= 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def CMPSTR(self, m: int, n: int):
        """
        If Rn and Rm have an equal byte: 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long temp;
        # TODO:  long HH, HL, LH, LL;
        # TODO:  temp = self.cpu.regs[n] ^ self.cpu.regs[m];
        # TODO:  HH = (temp & 0xFF000000) >> 24;
        # TODO:  HL = (temp & 0x00FF0000) >> 16;
        # TODO:  LH = (temp & 0x0000FF00) >> 8;
        # TODO:  LL = temp & 0x000000FF;
        # TODO:  HH = HH && HL && LH && LL;
        # TODO:  if (HH == 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def DIV0S(self, m: int, n: int):
        """
        MSB of Rn -> Q, MSB of Rm -> M, M ^ Q -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  Q = 0;
        # TODO:  else
        # TODO:  Q = 1;
        # TODO:  if ((self.cpu.regs[m] & 0x80000000) == 0)
        # TODO:  M = 0;
        # TODO:  else
        # TODO:  M = 1;
        # TODO:  T = ! (M == Q);
        self.cpu.pc += 2
    
    def DIV0U(self):
        """
        0 -> M, 0 -> Q, 0 -> T
        """
        # TODO:  M = Q = T = 0;
        self.cpu.pc += 2
    
    def DIV1(self, m: int, n: int):
        """
        1-step division (Rn / Rm)
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long tmp0, tmp2;
        # TODO:  unsigned char old_q, tmp1;
        # TODO:  old_q = Q;
        # TODO:  Q = (0x80000000 & self.cpu.regs[n]) != 0;
        # TODO:  tmp2 = self.cpu.regs[m];
        # TODO:  self.cpu.regs[n] <<= 1;
        # TODO:  self.cpu.regs[n] |= (unsigned long)T;
        # TODO:  if (old_q == 0)
        # TODO:  if (M == 0)
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] -= tmp2;
        # TODO:  tmp1 = self.cpu.regs[n] > tmp0;
        # TODO:  if (Q == 0)
        # TODO:  Q = tmp1;
        # TODO:  else if (Q == 1)
        # TODO:  Q = tmp1 == 0;
        # TODO:  else if (M == 1)
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] += tmp2;
        # TODO:  tmp1 = self.cpu.regs[n] < tmp0;
        # TODO:  if (Q == 0)
        # TODO:  Q = tmp1 == 0;
        # TODO:  else if (Q == 1)
        # TODO:  Q = tmp1;
        # TODO:  else if (old_q == 1)
        # TODO:  if (M == 0)
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] += tmp2;
        # TODO:  tmp1 = self.cpu.regs[n] < tmp0;
        # TODO:  if (Q == 0)
        # TODO:  Q = tmp1;
        # TODO:  else if (Q == 1)
        # TODO:  Q = tmp1 == 0;
        # TODO:  else if (M == 1)
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] -= tmp2;
        # TODO:  tmp1 = self.cpu.regs[n] > tmp0;
        # TODO:  if (Q == 0)
        # TODO:  Q = tmp1 == 0;
        # TODO:  else if (Q == 1)
        # TODO:  Q = tmp1;
        # TODO:  T = (Q == M);
        self.cpu.pc += 2
    
    def DMULS(self, m: int, n: int):
        """
        Signed, Rn * Rm -> MACH:MACL 32 * 32 -> 64 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long RnL, RnH, RmL, RmH, Res0, Res1, Res2;
        # TODO:  unsigned long temp0, temp1, temp2, temp3;
        # TODO:  long tempm, tempn, fnLmL;
        # TODO:  tempn = (long)self.cpu.regs[n];
        # TODO:  tempm = (long)self.cpu.regs[m];
        # TODO:  if (tempn < 0)
        # TODO:  tempn = 0 - tempn;
        # TODO:  if (tempm < 0)
        # TODO:  tempm = 0 - tempm;
        # TODO:  if ((long)(self.cpu.regs[n] ^ self.cpu.regs[m]) < 0)
        # TODO:  fnLmL = -1;
        # TODO:  else
        # TODO:  fnLmL = 0;
        # TODO:  temp1 = (unsigned long)tempn;
        # TODO:  temp2 = (unsigned long)tempm;
        # TODO:  RnL = temp1 & 0x0000FFFF;
        # TODO:  RnH = (temp1 >> 16) & 0x0000FFFF;
        # TODO:  RmL = temp2 & 0x0000FFFF;
        # TODO:  RmH = (temp2 >> 16) & 0x0000FFFF;
        # TODO:  temp0 = RmL * RnL;
        # TODO:  temp1 = RmH * RnL;
        # TODO:  temp2 = RmL * RnH;
        # TODO:  temp3 = RmH * RnH;
        # TODO:  Res2 = 0;
        # TODO:  Res1 = temp1 + temp2;
        # TODO:  if (Res1 < temp1)
        # TODO:  Res2 += 0x00010000;
        # TODO:  temp1 = (Res1 << 16) & 0xFFFF0000;
        # TODO:  Res0 = temp0 + temp1;
        # TODO:  if (Res0 < temp0)
        # TODO:  Res2++;
        # TODO:  Res2 = Res2 + ((Res1 >> 16) & 0x0000FFFF) + temp3;
        # TODO:  if (fnLmL < 0)
        # TODO:  Res2 = ~Res2;
        # TODO:  if (Res0 == 0)
        # TODO:  Res2++;
        # TODO:  else
        # TODO:  Res0 = (~Res0) + 1;
        # TODO:  MACH = Res2;
        # TODO:  MACL = Res0;
        self.cpu.pc += 2
    
    def DMULU(self, m: int, n: int):
        """
        Unsigned, Rn * Rm -> MACH:MACL 32 * 32 -> 64 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long RnL, RnH, RmL, RmH, Res0, Res1, Res2;
        # TODO:  unsigned long temp0, temp1, temp2, temp3;
        # TODO:  RnL = self.cpu.regs[n] & 0x0000FFFF;
        # TODO:  RnH = (self.cpu.regs[n] >> 16) & 0x0000FFFF;
        # TODO:  RmL = self.cpu.regs[m] & 0x0000FFFF;
        # TODO:  RmH = (self.cpu.regs[m] >> 16) & 0x0000FFFF;
        # TODO:  temp0 = RmL * RnL;
        # TODO:  temp1 = RmH * RnL;
        # TODO:  temp2 = RmL * RnH;
        # TODO:  temp3 = RmH * RnH;
        # TODO:  Res2 = 0
        # TODO:  Res1 = temp1 + temp2;
        # TODO:  if (Res1 < temp1)
        # TODO:  Res2 += 0x00010000;
        # TODO:  temp1 = (Res1 << 16) & 0xFFFF0000;
        # TODO:  Res0 = temp0 + temp1;
        # TODO:  if (Res0 < temp0)
        # TODO:  Res2++;
        # TODO:  Res2 = Res2 + ((Res1 >> 16) & 0x0000FFFF) + temp3;
        # TODO:  MACH = Res2;
        # TODO:  MACL = Res0;
        self.cpu.pc += 2
    
    def DT(self, n: int):
        """
        Rn-1 -> Rn If Rn = 0: 1 -> T Else: 0 -> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n]--;
        # TODO:  if (self.cpu.regs[n] == 0)
        # TODO:  T = 1;
        # TODO:  else T = 0;
        self.cpu.pc += 2
    
    def EXTSB(self, m: int, n: int):
        """
        Rm sign-extended from byte -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m];
        # TODO:  if ((self.cpu.regs[m] & 0x00000080) == 0)
        # TODO:  self.cpu.regs[n] & = 0x000000FF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFFFF00;
        self.cpu.pc += 2
    
    def EXTSW(self, m: int, n: int):
        """
        Rm sign-extended from word -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m];
        # TODO:  if ((self.cpu.regs[m] & 0x00008000) == 0)
        # TODO:  self.cpu.regs[n] & = 0x0000FFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] |= 0xFFFF0000;
        self.cpu.pc += 2
    
    def EXTUB(self, m: int, n: int):
        """
        Rm zero-extended from byte -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m];
        # TODO:  self.cpu.regs[n] &= 0x000000FF;
        self.cpu.pc += 2
    
    def EXTUW(self, m: int, n: int):
        """
        Rm zero-extended from word -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = self.cpu.regs[m];
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        self.cpu.pc += 2
    
    def MACL(self, m: int, n: int):
        """
        Signed, (Rn) * (Rm) + MAC -> MAC 32 * 32 + 64 -> 64 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long RnL, RnH, RmL, RmH, Res0, Res1, Res2;
        # TODO:  unsigned long temp0, temp1, temp2, temp3;
        # TODO:  long tempm, tempn, fnLmL;
        # TODO:  tempn = Read_32 (self.cpu.regs[n]);
        # TODO:  self.cpu.regs[n] += 4;
        # TODO:  tempm = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        # TODO:  if ((long)(tempn ^ tempm) < 0)
        # TODO:  fnLmL = -1;
        # TODO:  else
        # TODO:  fnLmL = 0;
        # TODO:  if (tempn < 0)
        # TODO:  tempn = 0 - tempn;
        # TODO:  if (tempm < 0)
        # TODO:  tempm = 0 - tempm;
        # TODO:  temp1 = (unsigned long)tempn;
        # TODO:  temp2 = (unsigned long)tempm;
        # TODO:  RnL = temp1 & 0x0000FFFF;
        # TODO:  RnH = (temp1 >> 16) & 0x0000FFFF;
        # TODO:  RmL = temp2 & 0x0000FFFF;
        # TODO:  RmH = (temp2 >> 16) & 0x0000FFFF;
        # TODO:  temp0 = RmL * RnL;
        # TODO:  temp1 = RmH * RnL;
        # TODO:  temp2 = RmL * RnH;
        # TODO:  temp3 = RmH * RnH;
        # TODO:  Res2 = 0;
        # TODO:  Res1 = temp1 + temp2;
        # TODO:  if (Res1 < temp1)
        # TODO:  Res2 += 0x00010000;
        # TODO:  temp1 = (Res1 << 16) & 0xFFFF0000;
        # TODO:  Res0 = temp0 + temp1;
        # TODO:  if (Res0 < temp0)
        # TODO:  Res2++;
        # TODO:  Res2 = Res2 + ((Res1 >> 16) & 0x0000FFFF) + temp3;
        # TODO:  if(fnLmL < 0)
        # TODO:  Res2 = ~Res2;
        # TODO:  if (Res0 == 0)
        # TODO:  Res2++;
        # TODO:  else
        # TODO:  Res0 = (~Res0) + 1;
        # TODO:  if (S == 1)
        # TODO:  Res0 = MACL + Res0;
        # TODO:  if (MACL > Res0)
        # TODO:  Res2++;
        # TODO:  Res2 += MACH & 0x0000FFFF;
        # TODO:  if (((long)Res2 < 0) && (Res2 < 0xFFFF8000))
        # TODO:  Res2 = 0xFFFF8000;
        # TODO:  Res0 = 0x00000000;
        # TODO:  if (((long)Res2 > 0) && (Res2 > 0x00007FFF))
        # TODO:  Res2 = 0x00007FFF;
        # TODO:  Res0 = 0xFFFFFFFF;
        # TODO:  MACH = (Res2 & 0x0000FFFF) | (MACH & 0xFFFF0000);
        # TODO:  MACL = Res0;
        # TODO:  else
        # TODO:  Res0 = MACL + Res0;
        # TODO:  if (MACL > Res0)
        # TODO:  Res2 ++;
        # TODO:  Res2 += MACH;
        # TODO:  MACH = Res2;
        # TODO:  MACL = Res0;
        self.cpu.pc += 2
    
    def MACW(self, m: int, n: int):
        """
        Signed, (Rn) * (Rm) + MAC -> MAC SH1: 16 * 16 + 42 -> 42 bits Other: 16 * 16 + 64 -> 64 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  long tempm, tempn, dest, src, ans;
        # TODO:  unsigned long templ;
        # TODO:  tempn = Read_16 (self.cpu.regs[n]);
        # TODO:  self.cpu.regs[n] += 2;
        # TODO:  tempm = Read_16 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 2;
        # TODO:  templ = MACL;
        # TODO:  tempm = ((long)(short)tempn * (long)(short)tempm);
        # TODO:  if ((long)MACL >= 0)
        # TODO:  dest = 0;
        # TODO:  else
        # TODO:  dest = 1;
        # TODO:  if ((long)tempm >= 0)
        # TODO:  src = 0;
        # TODO:  tempn = 0;
        # TODO:  else
        # TODO:  src = 1;
        # TODO:  tempn = 0xFFFFFFFF;
        # TODO:  src += dest;
        # TODO:  MACL += tempm;
        # TODO:  if ((long)MACL >= 0)
        # TODO:  ans = 0;
        # TODO:  else
        # TODO:  ans = 1;
        # TODO:  ans += dest;
        # TODO:  if (S == 1)
        # TODO:  if (ans == 1)
        # TODO:  if (src == 0)
        # TODO:  MACL = 0x7FFFFFFF;
        # TODO:  if (src == 2)
        # TODO:  MACL = 0x80000000;
        # TODO:  else
        # TODO:  MACH += tempn;
        # TODO:  if (templ > MACL)
        # TODO:  MACH += 1;
        self.cpu.pc += 2
    
    def MULL(self, m: int, n: int):
        """
        Rn * Rm -> MACL 32 * 32 -> 32 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  MACL = self.cpu.regs[n] * self.cpu.regs[m];
        self.cpu.pc += 2
    
    def MULS(self, m: int, n: int):
        """
        Signed, Rn * Rm -> MACL 16 * 16 -> 32 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  MACL = ((long)(short)self.cpu.regs[n] * (long)(short)self.cpu.regs[m]);
        self.cpu.pc += 2
    
    def MULU(self, m: int, n: int):
        """
        Unsigned, Rn * Rm -> MACL 16 * 16 -> 32 bits
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  MACL = ((unsigned long)(unsigned short)self.cpu.regs[n]* (unsigned long)(unsigned short)self.cpu.regs[m];
        self.cpu.pc += 2
    
    def NEG(self, m: int, n: int):
        """
        0 - Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = 0 - self.cpu.regs[m];
        self.cpu.pc += 2
    
    def NEGC(self, m: int, n: int):
        """
        0 - Rm - T -> Rn, borrow -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long temp;
        # TODO:  temp = 0 - self.cpu.regs[m];
        # TODO:  self.cpu.regs[n] = temp - T;
        # TODO:  if (0 < temp)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  if (temp < self.cpu.regs[n])
        # TODO:  T = 1;
        self.cpu.pc += 2
    
    def SUB(self, m: int, n: int):
        """
        Rn - Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= self.cpu.regs[m];
        self.cpu.pc += 2
    
    def SUBC(self, m: int, n: int):
        """
        Rn - Rm - T -> Rn, borrow -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  unsigned long tmp0, tmp1;
        # TODO:  tmp1 = self.cpu.regs[n] - self.cpu.regs[m];
        # TODO:  tmp0 = self.cpu.regs[n];
        # TODO:  self.cpu.regs[n] = tmp1 - T;
        # TODO:  if (tmp0 < tmp1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  if (tmp1 < self.cpu.regs[n])
        # TODO:  T = 1;
        self.cpu.pc += 2
    
    def SUBV(self, m: int, n: int):
        """
        Rn - Rm -> Rn, underflow -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  long dest, src, ans;
        # TODO:  if ((long)self.cpu.regs[n] >= 0)
        # TODO:  dest = 0;
        # TODO:  else
        # TODO:  dest = 1;
        # TODO:  if ((long)self.cpu.regs[m] >= 0)
        # TODO:  src = 0;
        # TODO:  else
        # TODO:  src = 1;
        # TODO:  src += dest;
        # TODO:  self.cpu.regs[n] -= self.cpu.regs[m];
        # TODO:  if ((long)self.cpu.regs[n] >= 0)
        # TODO:  ans = 0;
        # TODO:  else
        # TODO:  ans = 1;
        # TODO:  ans += dest;
        # TODO:  if (src == 1)
        # TODO:  if (ans == 1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def AND(self, m: int, n: int):
        """
        Rn & Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] &= self.cpu.regs[m];
        self.cpu.pc += 2
    
    def ANDI(self, i: int):
        """
        R0 & (zero extend)imm -> R0
        :param i: value to add (up to 0xFF)
        """
        # TODO:  R[0] &= (0x000000FF & (long)i);
        self.cpu.pc += 2
    
    def ANDM(self, i: int):
        """
        (R0 + GBR) & (zero extend)imm -> (R0 + GBR)
        :param i: value to add (up to 0xFF)
        """
        # TODO:  long temp = Read_8 (GBR + R[0]);
        # TODO:  temp &= 0x000000FF & (long)i;
        # TODO:  Write_8 (GBR + R[0], temp);
        self.cpu.pc += 2
    
    def NOT(self, m: int, n: int):
        """
        ~Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = ~self.cpu.regs[m];
        self.cpu.pc += 2
    
    def OR(self, m: int, n: int):
        """
        Rn | Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] |= self.cpu.regs[m];
        self.cpu.pc += 2
    
    def ORI(self, i: int):
        """
        R0 | (zero extend)imm -> R0
        :param i: value to add (up to 0xFF)
        """
        # TODO:  R[0] |= (0x000000FF & (long)i);
        self.cpu.pc += 2
    
    def ORM(self, i: int):
        """
        (R0 + GBR) | (zero extend)imm -> (R0 + GBR)
        :param i: value to add (up to 0xFF)
        """
        # TODO:  long temp = Read_8 (GBR + R[0]);
        # TODO:  temp |= (0x000000FF & (long)i);
        # TODO:  Write_8 (GBR + R[0], temp);
        self.cpu.pc += 2
    
    def TAS(self, n: int):
        """
        If (Rn) = 0: 1 -> T Else: 0 -> T 1 -> MSB of (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  int temp = Read_8 (self.cpu.regs[n]); // Bus Lock
        # TODO:  if (temp == 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        # TODO:  temp |= 0x00000080;
        # TODO:  Write_8 (self.cpu.regs[n], temp);  // Bus unlock
        self.cpu.pc += 2
    
    def TST(self, m: int, n: int):
        """
        If Rn & Rm = 0: 1 -> T Else: 0 -> T
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & self.cpu.regs[m]) == 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def TSTI(self, i: int):
        """
        If R0 & (zero extend)imm = 0: 1 -> T Else: 0 -> T
        :param i: value to add (up to 0xFF)
        """
        # TODO:  long temp = R[0] & (0x000000FF & (long)i);
        # TODO:  if (temp == 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def TSTM(self, i: int):
        """
        If (R0 + GBR) & (zero extend)imm = 0: 1 -> T Else 0: -> T
        :param i: value to add (up to 0xFF)
        """
        # TODO:  long temp = Read_8 (GBR + R[0]);
        # TODO:  temp &= (0x000000FF & (long)i);
        # TODO:  if (temp == 0)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def XOR(self, m: int, n: int):
        """
        Rn ^ Rm -> Rn
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] ^= self.cpu.regs[m];
        self.cpu.pc += 2
    
    def XORI(self, i: int):
        """
        R0 ^ (zero extend)imm -> R0
        :param i: value to add (up to 0xFF)
        """
        # TODO:  R[0] ^= (0x000000FF & (long)i);
        self.cpu.pc += 2
    
    def XORM(self, i: int):
        """
        (R0 + GBR) ^ (zero extend)imm -> (R0 + GBR)
        :param i: value to add (up to 0xFF)
        """
        # TODO:  int temp = Read_8 (GBR + R[0]);
        # TODO:  temp ^= (0x000000FF & (long)i);
        # TODO:  Write_8 (GBR + R[0], temp);
        self.cpu.pc += 2
    
    def ROTCL(self, n: int):
        """
        T << Rn << T
        :param n: register index (between 0 and 15)
        """
        # TODO:  long temp;
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  temp = 0;
        # TODO:  else
        # TODO:  temp = 1;
        # TODO:  self.cpu.regs[n] <<= 1;
        # TODO:  if (T == 1)
        # TODO:  self.cpu.regs[n] |= 0x00000001;
        # TODO:  else
        # TODO:  self.cpu.regs[n] &= 0xFFFFFFFE;
        # TODO:  if (temp == 1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def ROTCR(self, n: int):
        """
        T >> Rn >> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  long temp;
        # TODO:  if ((self.cpu.regs[n] & 0x00000001) == 0)
        # TODO:  temp = 0;
        # TODO:  else
        # TODO:  temp = 1;
        # TODO:  self.cpu.regs[n] >>= 1;
        # TODO:  if (T == 1)
        # TODO:  self.cpu.regs[n] |= 0x80000000;
        # TODO:  else
        # TODO:  self.cpu.regs[n] &= 0x7FFFFFFF;
        # TODO:  if (temp == 1)
        # TODO:  T = 1;
        # TODO:  else
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def ROTL(self, n: int):
        """
        T << Rn << MSB
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  self.cpu.regs[n] <<= 1;
        # TODO:  if (T == 1)
        # TODO:  self.cpu.regs[n] |= 0x00000001;
        # TODO:  else
        # TODO:  self.cpu.regs[n] &= 0xFFFFFFFE;
        self.cpu.pc += 2
    
    def ROTR(self, n: int):
        """
        LSB >> Rn >> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x00000001) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  self.cpu.regs[n] >>= 1;
        # TODO:  if (T == 1)
        # TODO:  self.cpu.regs[n] |= 0x80000000;
        # TODO:  else
        # TODO:  self.cpu.regs[n] &= 0x7FFFFFFF;
        self.cpu.pc += 2
    
    def SHAD(self, m: int, n: int):
        """
        If Rm >= 0: Rn << Rm -> Rn If Rm < 0: Rn >> |Rm| -> [MSB -> Rn]
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  int sgn = self.cpu.regs[m] & 0x80000000;
        # TODO:  if (sgn == 0)
        # TODO:  self.cpu.regs[n] <<= (self.cpu.regs[m] & 0x1F);
        # TODO:  else if ((self.cpu.regs[m] & 0x1F) == 0)
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  self.cpu.regs[n] = 0;
        # TODO:  else
        # TODO:  self.cpu.regs[n] = 0xFFFFFFFF;
        # TODO:  else
        # TODO:  self.cpu.regs[n] = (long)self.cpu.regs[n] >> ((~self.cpu.regs[m] & 0x1F) + 1);
        self.cpu.pc += 2
    
    def SHAL(self, n: int):
        """
        T << Rn << 0
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  self.cpu.regs[n] <<= 1;
        self.cpu.pc += 2
    
    def SHAR(self, n: int):
        """
        MSB >> Rn >> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  long temp;
        # TODO:  if ((self.cpu.regs[n] & 0x00000001) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  temp = 0;
        # TODO:  else
        # TODO:  temp = 1;
        # TODO:  self.cpu.regs[n] >>= 1;
        # TODO:  if (temp == 1)
        # TODO:  self.cpu.regs[n] |= 0x80000000;
        # TODO:  else
        # TODO:  self.cpu.regs[n] &= 0x7FFFFFFF;
        self.cpu.pc += 2
    
    def SHLD(self, m: int, n: int):
        """
        If Rm >= 0: Rn << Rm -> Rn If Rm < 0: Rn >> |Rm| -> [0 -> Rn]
        :param m: register index (between 0 and 15)
        :param n: register index (between 0 and 15)
        """
        # TODO:  int sgn = self.cpu.regs[m] & 0x80000000;
        # TODO:  if (sgn == 0)
        # TODO:  self.cpu.regs[n] <<= (self.cpu.regs[m] & 0x1F);
        # TODO:  else if ((self.cpu.regs[m] & 0x1F) == 0)
        # TODO:  self.cpu.regs[n] = 0;
        # TODO:  else
        # TODO:  self.cpu.regs[n] = (unsigned)self.cpu.regs[n] >> ((~self.cpu.regs[m] & 0x1F) + 1);
        self.cpu.pc += 2
    
    def SHLL(self, n: int):
        """
        T << Rn << 0
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x80000000) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  self.cpu.regs[n] <<= 1;
        self.cpu.pc += 2
    
    def SHLL2(self, n: int):
        """
        Rn << 2 -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] <<= 2;
        self.cpu.pc += 2
    
    def SHLL8(self, n: int):
        """
        Rn << 8 -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] <<= 8;
        self.cpu.pc += 2
    
    def SHLL16(self, n: int):
        """
        Rn << 16 -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] <<= 16;
        self.cpu.pc += 2
    
    def SHLR(self, n: int):
        """
        0 >> Rn >> T
        :param n: register index (between 0 and 15)
        """
        # TODO:  if ((self.cpu.regs[n] & 0x00000001) == 0)
        # TODO:  T = 0;
        # TODO:  else
        # TODO:  T = 1;
        # TODO:  self.cpu.regs[n] >>= 1;
        # TODO:  self.cpu.regs[n] &= 0x7FFFFFFF;
        self.cpu.pc += 2
    
    def SHLR2(self, n: int):
        """
        Rn >> 2 -> [0 -> Rn]
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] >>= 2;
        # TODO:  self.cpu.regs[n] &= 0x3FFFFFFF;
        self.cpu.pc += 2
    
    def SHLR8(self, n: int):
        """
        Rn >> 8 -> [0 -> Rn]
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] >>= 8;
        # TODO:  self.cpu.regs[n] &= 0x00FFFFFF;
        self.cpu.pc += 2
    
    def SHLR16(self, n: int):
        """
        Rn >> 16 -> [0 -> Rn]
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] >>= 16;
        # TODO:  self.cpu.regs[n] &= 0x0000FFFF;
        self.cpu.pc += 2
    
    def BF(self, d: int):
        """
        If T = 0: disp*2 + PC + 4 -> PC Else: nop
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  if ((d & 0x80) == 0)
        # TODO:  disp = (0x000000FF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFFF00 | d);
        # TODO:  if (T == 0)
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  else
        self.cpu.pc += 2
    
    def BFS(self, d: int):
        """
        If T = 0: disp*2 + PC + 4 -> PC Else: nop (Delayed branch)
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  if ((d & 0x80) == 0)
        # TODO:  disp = (0x000000FF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFFF00 | d);
        # TODO:  if (T == 0)
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  else
        # TODO:  PC += 4;
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def BT(self, d: int):
        """
        If T = 1: disp*2 + PC + 4 -> PC Else: nop
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  if ((d & 0x80) == 0)
        # TODO:  disp = (0x000000FF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFFF00 | d);
        # TODO:  if (T == 1)
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  else
        self.cpu.pc += 2
    
    def BTS(self, d: int):
        """
        If T = 1: disp*2 + PC + 4 -> PC Else: nop (Delayed branch)
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  unsigned temp;
        # TODO:  temp = PC;
        # TODO:  if ((d & 0x80) == 0)
        # TODO:  disp = (0x000000FF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFFF00 | d);
        # TODO:  if (T == 1)
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  else
        # TODO:  PC += 4;
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def BRA(self, d: int):
        """
        disp*2 + PC + 4 -> PC (Delayed branch)
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  if ((d & 0x800) == 0)
        # TODO:  disp = (0x00000FFF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFF000 | d);
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  Delay_Slot(temp + 2);
        pass  # TODO: Implement me !
    
    def BRAF(self, m: int):
        """
        Rm + PC + 4 -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  PC = PC + 4 + self.cpu.regs[m];
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def BSR(self, d: int):
        """
        PC + 4 -> PR, disp*2 + PC + 4 -> PC (Delayed branch)
        :param d: disp
        """
        # TODO:  int disp;
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  if ((d & 0x800) == 0)
        # TODO:  disp = (0x00000FFF & d);
        # TODO:  else
        # TODO:  disp = (0xFFFFF000 | d);
        # TODO:  PR = PC + 4;
        # TODO:  PC = PC + 4 + (disp << 1);
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def BSRF(self, m: int):
        """
        PC + 4 -> PR, Rm + PC + 4 -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  PR = PC + 4;
        # TODO:  PC = PC + 4 + self.cpu.regs[m];
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def JMP(self, m: int):
        """
        Rm -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  PC = self.cpu.regs[m];
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def JSR(self, m: int):
        """
        PC + 4 -> PR, Rm -> PC (Delayed branch)
        :param m: register index (between 0 and 15)
        """
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  PR = PC + 4;
        # TODO:  PC = self.cpu.regs[m];
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def RTS(self):
        """
        PR -> PC Delayed branch
        """
        # TODO:  unsigned int temp;
        # TODO:  temp = PC;
        # TODO:  PC = PR;
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def CLRMAC(self):
        """
        0 -> MACH, 0 -> MACL
        """
        # TODO:  MACH = 0;
        # TODO:  MACL = 0;
        self.cpu.pc += 2
    
    def CLRS(self):
        """
        0 -> S
        """
        # TODO:  S = 0;
        self.cpu.pc += 2
    
    def CLRT(self):
        """
        0 -> T
        """
        # TODO:  T = 0;
        self.cpu.pc += 2
    
    def LDCSR(self, m: int):
        """
        Rm -> SR
        :param m: register index (between 0 and 15)
        """
        # TODO:  SR = self.cpu.regs[m] & 0x700083F3;
        self.cpu.pc += 2
    
    def LDCMSR(self, m: int):
        """
        (Rm) -> SR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  SR = Read_32 (self.cpu.regs[m]) & 0x700083F3;
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCGBR(self, m: int):
        """
        Rm -> GBR
        :param m: register index (between 0 and 15)
        """
        # TODO:  GBR = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDCMGBR(self, m: int):
        """
        (Rm) -> GBR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  GBR = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCVBR(self, m: int):
        """
        Rm -> VBR
        :param m: register index (between 0 and 15)
        """
        # TODO:  VBR = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDCMVBR(self, m: int):
        """
        (Rm) -> VBR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  VBR = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCSSR(self, m: int):
        """
        Rm -> SSR
        :param m: register index (between 0 and 15)
        """
        # TODO:  SSR = self.cpu.regs[m],
        self.cpu.pc += 2
    
    def LDCMSSR(self, m: int):
        """
        (Rm) -> SSR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  SSR = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCSPC(self, m: int):
        """
        Rm -> SPC
        :param m: register index (between 0 and 15)
        """
        # TODO:  SPC = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDCMSPC(self, m: int):
        """
        (Rm) -> SPC, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  SPC = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCDBR(self, m: int):
        """
        Rm -> DBR
        :param m: register index (between 0 and 15)
        """
        # TODO:  DBR = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDCMDBR(self, m: int):
        """
        (Rm) -> DBR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  DBR = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDCRn_BANK(self, m: int):
        """
        Rm -> Rn_BANK (n = 0-7)
        :param m: register index (between 0 and 15)
        """
        # TODO:  Rn_BANK = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDCMRn_BANK(self, m: int):
        """
        (Rm) -> Rn_BANK, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  Rn_BANK = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDSMACH(self, m: int):
        """
        Rm -> MACH
        :param m: register index (between 0 and 15)
        """
        # TODO:  MACH = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDSMMACH(self, m: int):
        """
        (Rm) -> MACH, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  MACH = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDSMACL(self, m: int):
        """
        Rm -> MACL
        :param m: register index (between 0 and 15)
        """
        # TODO:  MACL = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDSMMACL(self, m: int):
        """
        (Rm) -> MACL, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  MACL = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDSPR(self, m: int):
        """
        Rm -> PR
        :param m: register index (between 0 and 15)
        """
        # TODO:  PR = self.cpu.regs[m];
        self.cpu.pc += 2
    
    def LDSMPR(self, m: int):
        """
        (Rm) -> PR, Rm+4 -> Rm
        :param m: register index (between 0 and 15)
        """
        # TODO:  PR = Read_32 (self.cpu.regs[m]);
        # TODO:  self.cpu.regs[m] += 4;
        self.cpu.pc += 2
    
    def LDTLB(self):
        """
        PTEH/PTEL -> TLB
        """
        self.cpu.pc += 2
    
    def MOVCAL(self, n: int):
        """
        R0 -> (Rn) (without fetching cache block)
        :param n: register index (between 0 and 15)
        """
        # TODO:  if (is_write_back_memory (self.cpu.regs[n]) && look_up_in_operand_cache (self.cpu.regs[n]) == MISS)
        # TODO:  allocate_operand_cache_block (self.cpu.regs[n]);
        # TODO:  Write_32 (self.cpu.regs[n], R[0]);
        self.cpu.pc += 2
    
    def NOP(self):
        """
        No operation
        """
        self.cpu.pc += 2
    
    def OCBI(self, n: int):
        """
        Invalidate operand cache block
        :param n: register index (between 0 and 15)
        """
        # TODO:  invalidate_operand_cache_block (self.cpu.regs[n]);
        self.cpu.pc += 2
    
    def OCBP(self, n: int):
        """
        Write back and invalidate operand cache block
        :param n: register index (between 0 and 15)
        """
        # TODO:  if (is_dirty_block (self.cpu.regs[n]))
        # TODO:  write_back (self.cpu.regs[n])
        # TODO:  invalidate_operand_cache_block (self.cpu.regs[n]);
        self.cpu.pc += 2
    
    def OCBWB(self, n: int):
        """
        Write back operand cache block
        :param n: register index (between 0 and 15)
        """
        # TODO:  if (is_dirty_block (self.cpu.regs[n]))
        # TODO:  write_back (self.cpu.regs[n]);
        self.cpu.pc += 2
    
    def PREF(self, n: int):
        """
        (Rn) -> operand cache
        :param n: register index (between 0 and 15)
        """
        # TODO:  prefetch_operand_cache_block (self.cpu.regs[n]);
        self.cpu.pc += 2
    
    def RTE(self):
        """
        Delayed branch SH1*,SH2*: stack area -> PC/SR SH3*,SH4*: SSR/SPC -> SR/PC
        """
        # TODO:  unsigned long temp = PC;
        # TODO:  SR = SSR;
        # TODO:  PC = SPC;
        # TODO:  Delay_Slot (temp + 2);
        pass  # TODO: Implement me !
    
    def SETS(self):
        """
        1 -> S
        """
        # TODO:  S = 1;
        self.cpu.pc += 2
    
    def SETT(self):
        """
        1 -> T
        """
        # TODO:  T = 1;
        self.cpu.pc += 2
    
    def SLEEP(self):
        """
        Sleep or standby
        """
        # TODO:  Sleep_standby();
        pass  # TODO: Implement me !
    
    def STCSR(self, n: int):
        """
        SR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = SR;
        self.cpu.pc += 2
    
    def STCMSR(self, n: int):
        """
        Rn-4 -> Rn, SR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], SR);
        self.cpu.pc += 2
    
    def STCGBR(self, n: int):
        """
        GBR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = GBR;
        self.cpu.pc += 2
    
    def STCMGBR(self, n: int):
        """
        Rn-4 -> Rn, GBR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], GBR);
        self.cpu.pc += 2
    
    def STCVBR(self, n: int):
        """
        VBR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = VBR;
        self.cpu.pc += 2
    
    def STCMVBR(self, n: int):
        """
        Rn-4 -> Rn, VBR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], VBR);
        self.cpu.pc += 2
    
    def STCSGR(self, n: int):
        """
        SGR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = SGR;
        self.cpu.pc += 2
    
    def STCMSGR(self, n: int):
        """
        Rn-4 -> Rn, SGR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], SGR);
        self.cpu.pc += 2
    
    def STCSSR(self, n: int):
        """
        SSR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = SSR;
        self.cpu.pc += 2
    
    def STCMSSR(self, n: int):
        """
        Rn-4 -> Rn, SSR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], SSR);
        self.cpu.pc += 2
    
    def STCSPC(self, n: int):
        """
        SPC -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = SPC;
        self.cpu.pc += 2
    
    def STCMSPC(self, n: int):
        """
        Rn-4 -> Rn, SPC -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], SPC);
        self.cpu.pc += 2
    
    def STCDBR(self, n: int):
        """
        DBR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = DBR;
        self.cpu.pc += 2
    
    def STCMDBR(self, n: int):
        """
        Rn-4 -> Rn, DBR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], DBR);
        self.cpu.pc += 2
    
    def STCRm_BANK(self, n: int):
        """
        Rm_BANK -> Rn (m = 0-7)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = Rm_BANK;
        self.cpu.pc += 2
    
    def STCMRm_BANK(self, n: int):
        """
        Rn-4 -> Rn, Rm_BANK -> (Rn) (m = 0-7)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], Rm_BANK);
        self.cpu.pc += 2
    
    def STSMACH(self, n: int):
        """
        MACH -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = MACH;
        self.cpu.pc += 2
    
    def STSMMACH(self, n: int):
        """
        Rn-4 -> Rn, MACH -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        self.cpu.pc += 2
    
    def STSMACL(self, n: int):
        """
        MACL -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = MACL;
        self.cpu.pc += 2
    
    def STSMMACL(self, n: int):
        """
        Rn-4 -> Rn, MACL -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], MACL);
        self.cpu.pc += 2
    
    def STSPR(self, n: int):
        """
        PR -> Rn
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] = PR;
        self.cpu.pc += 2
    
    def STSMPR(self, n: int):
        """
        Rn-4 -> Rn, PR -> (Rn)
        :param n: register index (between 0 and 15)
        """
        # TODO:  self.cpu.regs[n] -= 4;
        # TODO:  Write_32 (self.cpu.regs[n], PR);
        self.cpu.pc += 2
    
    def TRAPA(self, i: int):
        """
        SH1*,SH2*: PC/SR -> stack area, (imm*4 + VBR) -> PC SH3*,SH4*: PC/SR -> SPC/SSR, imm*4 -> TRA, 0x160 -> EXPEVT, VBR + 0x0100 -> PC
        :param i: value to add (up to 0xFF)
        """
        # TODO:  int imm = (0x000000FF & i);
        # TODO:  TRA = imm << 2;
        # TODO:  SSR = SR;
        # TODO:  SPC = PC + 2;
        # TODO:  SGR = R15;
        # TODO:  SR.MD = 1;
        # TODO:  SR.BL = 1;
        # TODO:  SR.RB = 1;
        # TODO:  EXPEVT = 0x00000160;
        # TODO:  PC = VBR + 0x00000100;
        pass  # TODO: Implement me !
    
