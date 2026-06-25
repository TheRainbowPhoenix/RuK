import typing
from typing import Union, Dict, Callable

if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.jcore.cpu import CPU

from ctypes import c_long, c_uint32, c_ulong

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _u32(val: int) -> int:
    """Mask to 32 bits unsigned."""
    return val & 0xFFFFFFFF


def _i32(val: int) -> int:
    """Interpret a 32-bit pattern as signed."""
    val &= 0xFFFFFFFF
    if val & 0x80000000:
        return val - 0x100000000
    return val


def _sext(val: int, bits: int) -> int:
    """
    Sign-extend `val` (treated as a `bits`-bit number) to a Python int.
    Mirrors cp-emu's s_ext(arg, n).
    """
    mask = 1 << (bits - 1)
    return (val ^ mask) - mask


def _b(val: int, size: int = 4) -> bytes:
    """Convert int to big-endian bytes."""
    return (val & ((1 << (size * 8)) - 1)).to_bytes(size, 'big')


# ---------------------------------------------------------------------------
# Branch-delay-slot helper
# ---------------------------------------------------------------------------

def _exec_delay_slot(cpu, delay_slot_pc: int, branch_target: int):
    """
    Execute one instruction at `delay_slot_pc`, then set PC to
    `branch_target`.  This models the SH-4's branch-delay slot:
    the instruction immediately after a branch is executed before
    the branch takes effect.

    Mirrors cp-emu's `delayedBranch()` + `isBranchDelaySlot` logic.
    """
    cpu.pc = _u32(delay_slot_pc)
    # Run one instruction.  We can't call cpu.step() because that would
    # check the UBC and might trigger another break; instead, we inline
    # the minimal step logic.
    try:
        ins = cpu.mem.read16(cpu.pc)
        if isinstance(ins, int):
            op_val = ins
        else:
            op_val = int.from_bytes(ins, "big")
        op, args = cpu.disassembler.disasm(op_val)
        callback = cpu.emulator.resolve(op)
        callback(**args)
    except Exception:
        # If the delay slot fails (e.g. invalid opcode), just advance PC.
        cpu.pc = _u32(cpu.pc + 2)
    # Overwrite PC with the branch target (the delay slot's PC change
    # is discarded -- that's the point of a delay slot).
    cpu.pc = _u32(branch_target)


# ---------------------------------------------------------------------------
# Emulator
# ---------------------------------------------------------------------------

class Emulator:
    """
    SH-4 instruction emulator.

    Each method corresponds to one SH-4 opcode (or a small group of related
    opcodes).  Methods are registered in `self._resolve_table` keyed by the
    opcode ID from `ruk.jcore.generated_opcodes.opcodes_table`.
    """

    def __init__(self, cpu: 'CPU'):
        self.cpu = cpu
        self.debug = self.cpu.debug

        # Build the resolve table.  We populate it with all the opcodes
        # we implement, then fall back to "not resolved" for the rest.
        self._resolve_table: Dict[int, Callable] = {}

        # --- data movement ---
        self._reg(0,   self.MOV)         # MOV Rm, Rn
        self._reg(1,   self.MOVI)        # MOV #imm, Rn
        self._reg(4,   self.MOVA)        # MOVA @(disp,PC), R0
        self._reg(5,   self.MOVWI)       # MOV.W @(disp,PC), Rn
        self._reg(6,   self.MOVLI)       # MOV.L @(disp,PC), Rn
        self._reg(7,   self.MOVBL)       # MOV.B @Rm, Rn
        self._reg(8,   self.MOVWL)       # MOV.W @Rm, Rn
        self._reg(9,   self.MOVLL)       # MOV.L @Rm, Rn
        self._reg(10,  self.MOVBS)       # MOV.B Rm, @Rn
        self._reg(11,  self.MOVWS)       # MOV.W Rm, @Rn
        self._reg(12,  self.MOVLS)       # MOV.L Rm, @Rn
        self._reg(13,  self.MOVBP)       # MOV.B @Rm+, Rn
        self._reg(14,  self.MOVWP)       # MOV.W @Rm+, Rn
        self._reg(15,  self.MOVLP)       # MOV.L @Rm+, Rn
        self._reg(16,  self.MOVBM)       # MOV.B Rm, @-Rn
        self._reg(17,  self.MOVWM)       # MOV.W Rm, @-Rn
        self._reg(18,  self.MOVLM)       # MOV.L Rm, @-Rn
        self._reg(25,  self.MOVBL4)      # MOV.B @(disp,Rm), R0
        self._reg(28,  self.MOVWL4)      # MOV.W @(disp,Rm), R0
        self._reg(31,  self.MOVLL4)      # MOV.L @(disp,Rm), Rn
        self._reg(33,  self.MOVBS4)      # MOV.B R0, @(disp,Rn)
        self._reg(35,  self.MOVWS4)      # MOV.W R0, @(disp,Rn)
        self._reg(37,  self.MOVLS4)      # MOV.L Rm, @(disp,Rn)
        self._reg(39,  self.MOVBL0)      # MOV.B @(R0,Rm), Rn
        self._reg(40,  self.MOVWL0)      # MOV.W @(R0,Rm), Rn
        self._reg(41,  self.MOVLL0)      # MOV.L @(R0,Rm), Rn
        self._reg(42,  self.MOVBS0)      # MOV.B Rm, @(R0,Rn)
        self._reg(43,  self.MOVWS0)      # MOV.W Rm, @(R0,Rn)
        self._reg(44,  self.MOVLS0)      # MOV.L Rm, @(R0,Rn)
        self._reg(45,  self.MOVBLG)      # MOV.B @(disp,GBR), R0
        self._reg(46,  self.MOVWLG)      # MOV.W @(disp,GBR), R0
        self._reg(47,  self.MOVLLG)      # MOV.L @(disp,GBR), R0
        self._reg(48,  self.MOVBSG)      # MOV.B R0, @(disp,GBR)
        self._reg(49,  self.MOVWSG)      # MOV.W R0, @(disp,GBR)
        self._reg(50,  self.MOVLSG)      # MOV.L R0, @(disp,GBR)

        # --- arithmetic / logic ---
        self._reg(60,  self.MOVT)        # MOVT Rn
        self._reg(62,  self.SWAPB)       # SWAP.B Rm, Rn
        self._reg(63,  self.SWAPW)       # SWAP.W Rm, Rn
        self._reg(64,  self.XTRCT)       # XTRCT Rm, Rn
        self._reg(79,  self.ADD)         # ADD Rm, Rn
        self._reg(80,  self.ADDI)        # ADD #imm, Rn
        self._reg(81,  self.ADDC)        # ADDC Rm, Rn
        self._reg(82,  self.ADDV)        # ADDV Rm, Rn
        self._reg(83,  self.CMPIM)       # CMP/EQ #imm, R0
        self._reg(84,  self.CMPEQ)       # CMP/EQ Rm, Rn
        self._reg(85,  self.CMPHS)       # CMP/HS Rm, Rn (unsigned >=)
        self._reg(86,  self.CMPGE)       # CMP/GE Rm, Rn (signed >=)
        self._reg(87,  self.CMPHI)       # CMP/HI Rm, Rn (unsigned >)
        self._reg(88,  self.CMPGT)       # CMP/GT Rm, Rn (signed >)
        self._reg(89,  self.CMPPL)       # CMP/PL Rn  (signed > 0)
        self._reg(90,  self.CMPPZ)       # CMP/PZ Rn  (signed >= 0)
        self._reg(91,  self.CMPSTR)      # CMP/STR Rm, Rn
        self._reg(96,  self.DIV0S)       # DIV0S Rm, Rn
        self._reg(97,  self.DIV0U)       # DIV0U
        self._reg(98,  self.DIV1)        # DIV1 Rm, Rn
        self._reg(103, self.DT)          # DT Rn
        self._reg(104, self.EXTSB)       # EXTS.B Rm, Rn
        self._reg(105, self.EXTSW)       # EXTS.W Rm, Rn
        self._reg(106, self.EXTUB)       # EXTU.B Rm, Rn
        self._reg(107, self.EXTUW)       # EXTU.W Rm, Rn
        self._reg(110, self.MULL)        # MUL.L Rm, Rn
        self._reg(112, self.MULSW)       # MULS.W Rm, Rn
        self._reg(113, self.MULUW)       # MULU.W Rm, Rn
        self._reg(101, self.DMULS)       # DMULS.L Rm, Rn
        self._reg(102, self.DMULU)       # DMULU.L Rm, Rn
        self._reg(108, self.MACL)        # MAC.L @Rm+, @Rn+
        self._reg(109, self.MACW)        # MAC.W @Rm+, @Rn+
        self._reg(114, self.NEG)         # NEG Rm, Rn
        self._reg(115, self.NEGC)        # NEGC Rm, Rn
        self._reg(116, self.SUB)         # SUB Rm, Rn
        self._reg(117, self.SUBC)        # SUBC Rm, Rn
        self._reg(118, self.SUBV)        # SUBV Rm, Rn
        self._reg(119, self.AND_RM_RN)   # AND Rm, Rn
        self._reg(120, self.AND_IMM)     # AND #imm, R0
        self._reg(121, self.ANDB)        # AND.B #imm, @(R0,GBR)
        self._reg(122, self.NOT)         # NOT Rm, Rn
        self._reg(123, self.OR_RM_RN)    # OR Rm, Rn
        self._reg(124, self.OR_IMM)      # OR #imm, R0
        self._reg(125, self.ORB)         # OR.B #imm, @(R0,GBR)
        self._reg(126, self.TASB)        # TAS.B @Rn
        self._reg(127, self.TST_RM_RN)   # TST Rm, Rn
        self._reg(128, self.TST_IMM)     # TST #imm, R0
        self._reg(129, self.TST_B)       # TST.B #imm, @(R0,GBR)
        self._reg(130, self.XOR_RM_RN)   # XOR Rm, Rn
        self._reg(131, self.XOR_IMM)     # XOR #imm, R0
        self._reg(132, self.XORB)        # XOR.B #imm, @(R0,GBR)

        # --- shifts / rotates ---
        self._reg(133, self.ROTCL)       # ROTCL Rn
        self._reg(134, self.ROTCR)       # ROTCR Rn
        self._reg(135, self.ROTL)        # ROTL Rn
        self._reg(136, self.ROTR)        # ROTR Rn
        self._reg(137, self.SHAD)        # SHAD Rm, Rn (dynamic arithmetic)
        self._reg(138, self.SHAL)        # SHAL Rn
        self._reg(139, self.SHAR)        # SHAR Rn
        self._reg(140, self.SHLD)        # SHLD Rm, Rn (dynamic logical)
        self._reg(141, self.SHLL)        # SHLL Rn
        self._reg(142, self.SHLL2)       # SHLL2 Rn
        self._reg(143, self.SHLL8)       # SHLL8 Rn
        self._reg(144, self.SHLL16)      # SHLL16 Rn
        self._reg(145, self.SHLR)        # SHLR Rn
        self._reg(146, self.SHLR2)       # SHLR2 Rn
        self._reg(147, self.SHLR8)       # SHLR8 Rn
        self._reg(148, self.SHLR16)      # SHLR16 Rn

        # --- branches ---
        self._reg(149, self.BF)          # BF disp
        self._reg(150, self.BFS)         # BF/S disp
        self._reg(151, self.BT)          # BT disp
        self._reg(152, self.BTS)         # BT/S disp
        self._reg(153, self.BRA)         # BRA disp
        self._reg(154, self.BRAF)        # BRAF Rm
        self._reg(155, self.BSR)         # BSR disp
        self._reg(156, self.BSRF)        # BSRF Rm
        self._reg(157, self.JMP)         # JMP @Rm
        self._reg(158, self.JSR)         # JSR @Rm
        self._reg(161, self.RTS)         # RTS

        # --- system / control ---
        self._reg(164, self.CLRMAC)      # CLRMAC
        self._reg(165, self.CLRS)        # CLRS
        self._reg(166, self.CLRT)        # CLRT
        self._reg(212, self.LDTLB)       # LDTLB
        self._reg(213, self.MOVCA)       # MOVCA.L R0, @Rn
        self._reg(214, self.NOP)         # NOP
        self._reg(215, self.OCBI)        # OCBI @Rn
        self._reg(216, self.OCBP)        # OCBP @Rn
        self._reg(217, self.OCBWB)       # OCBWB @Rn
        self._reg(218, self.PREF)        # PREF @Rn

        self._reg(300, self.ICBI)        # ICBI @Rn (custom ID)
        self._reg(301, self.PREFI)       # PREFI @Rn (custom ID)
        self._reg(302, self.SYNCO)       # SYNCO (custom ID)
        self._reg(221, self.RTE)         # RTE
        self._reg(224, self.SETS)        # SETS
        self._reg(225, self.SETT)        # SETT
        self._reg(226, self.SLEEP)       # SLEEP

        # --- LDC / LDS / STC / STS ---
        # LDC Rm, SR/GBR/VBR/SSR/SPC/DBR
        self._reg(169, self.LDC_SR)      # LDC Rm, SR
        self._reg(170, self.LDCL_SR)     # LDC.L @Rm+, SR
        self._reg(172, self.LDC_GBR)     # LDC Rm, GBR
        self._reg(173, self.LDCL_GBR)    # LDC.L @Rm+, GBR
        self._reg(174, self.LDC_VBR)     # LDC Rm, VBR
        self._reg(175, self.LDCL_VBR)    # LDC.L @Rm+, VBR
        self._reg(184, self.LDC_SSR)     # LDC Rm, SSR
        self._reg(185, self.LDCL_SSR)    # LDC.L @Rm+, SSR
        self._reg(186, self.LDC_SPC)     # LDC Rm, SPC
        self._reg(187, self.LDCL_SPC)    # LDC.L @Rm+, SPC
        self._reg(188, self.LDC_DBR)     # LDC Rm, DBR
        self._reg(189, self.LDCL_DBR)    # LDC.L @Rm+, DBR
        self._reg(190, self.LDC_BANK)    # LDC Rm, Rn_BANK
        self._reg(191, self.LDCL_BANK)   # LDC.L @Rm+, Rn_BANK

        # LDS Rm, PR/MACH/MACL
        self._reg(194, self.LDS_MACH)    # LDS Rm, MACH
        self._reg(195, self.LDSL_MACH)   # LDS.L @Rm+, MACH
        self._reg(196, self.LDS_MACL)    # LDS Rm, MACL
        self._reg(197, self.LDSL_MACL)   # LDS.L @Rm+, MACL
        self._reg(198, self.LDS_PR)      # LDS Rm, PR
        self._reg(199, self.LDSL_PR)     # LDS.L @Rm+, PR
        # DSP repeat-loop registers (SH4AL-DSP extension)
        self._reg(200, self.LDS_RS)      # LDS Rm, RS
        self._reg(201, self.LDSL_RS)     # LDS.L @Rm+, RS
        self._reg(202, self.LDS_RE)      # LDS Rm, RE
        self._reg(203, self.LDSL_RE)     # LDS.L @Rm+, RE
        self._reg(204, self.LDS_RC)      # LDS Rm, RC
        self._reg(205, self.LDSL_RC)     # LDS.L @Rm+, RC
        self._reg(206, self.LDS_MOD)     # LDS Rm, MOD
        self._reg(207, self.LDS_DSR)     # LDS Rm, DSR
        # STS for DSP repeat-loop registers
        self._reg(208, self.STS_RS)      # STS RS, Rn
        self._reg(209, self.STSL_RS)     # STS.L RS, @-Rn
        self._reg(210, self.STS_RE)      # STS RE, Rn
        self._reg(211, self.STSL_RE)     # STS.L RE, @-Rn
        self._reg(271, self.STS_RC)      # STS RC, Rn
        self._reg(272, self.STSL_RC)     # STS.L RC, @-Rn
        # DSP repeat-loop setup instructions (SH4AL-DSP)
        self._reg(273, self.LDRS_DISP)   # LDRS @(disp,PC) -- load RS
        self._reg(274, self.LDRE_DISP)   # LDRE @(disp,PC) -- load RE
        self._reg(275, self.LDRC_IMM)    # LDRC #imm -- load RC immediate
        self._reg(276, self.LDRC_REG)    # LDRC Rn -- load RC from register

        # STC SR/GBR/VBR/SSR/SPC/SGR/DBR, Rn
        self._reg(228, self.STC_SR)      # STC SR, Rn
        self._reg(229, self.STCL_SR)     # STC.L SR, @-Rn
        self._reg(231, self.STC_GBR)     # STC GBR, Rn
        self._reg(232, self.STCL_GBR)    # STC.L GBR, @-Rn
        self._reg(233, self.STC_VBR)     # STC VBR, Rn
        self._reg(234, self.STCL_VBR)    # STC.L VBR, @-Rn
        self._reg(241, self.STC_SGR)     # STC SGR, Rn
        self._reg(242, self.STCL_SGR)    # STC.L SGR, @-Rn
        self._reg(243, self.STC_SSR)     # STC SSR, Rn
        self._reg(244, self.STCL_SSR)    # STC.L SSR, @-Rn
        self._reg(245, self.STC_SPC)     # STC SPC, Rn
        self._reg(246, self.STCL_SPC)    # STC.L SPC, @-Rn
        self._reg(247, self.STC_DBR)     # STC DBR, Rn
        self._reg(248, self.STCL_DBR)    # STC.L DBR, @-Rn
        self._reg(249, self.STC_BANK)    # STC Rm_BANK, Rn
        self._reg(250, self.STCL_BANK)   # STC.L Rm_BANK, @-Rn

        # STS PR/MACH/MACL, Rn
        self._reg(251, self.STS_MACH)    # STS MACH, Rn
        self._reg(252, self.STSL_MACH)   # STS.L MACH, @-Rn
        self._reg(253, self.STS_MACL)    # STS MACL, Rn
        self._reg(254, self.STSL_MACL)   # STS.L MACL, @-Rn
        self._reg(255, self.STS_PR)      # STS PR, Rn
        self._reg(256, self.STSL_PR)     # STS.L PR, @-Rn

        # --- misc ---
        self._reg(270, self.TRAPA)       # TRAPA #imm

    def _reg(self, op_id: int, handler: Callable):
        """Register a handler in the resolve table."""
        self._resolve_table[op_id] = handler

    def resolve(self, opcode_id: int) -> Callable:
        """
        Resolve opcode index in lookup table.
        """
        if opcode_id in self._resolve_table:
            return self._resolve_table[opcode_id]
        raise IndexError(f'OPCode index "{opcode_id}" not resolved '
                         f'(did you add it to _resolve_table?)')

    # ===================================================================
    # SR.T helpers
    # ===================================================================

    def _get_t(self) -> int:
        return self.cpu.regs['sr'] & 1

    def _set_t(self, value: int):
        if value:
            self.cpu.regs['sr'] |= 1
        else:
            self.cpu.regs['sr'] &= ~1 & 0xFFFFFFFF

    # ===================================================================
    # Data movement
    # ===================================================================

    def MOV(self, m: int, n: int):
        """MOV Rm, Rn: Rm -> Rn."""
        self.cpu.regs[n] = self.cpu.regs[m]
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVI(self, i: int, n: int):
        """MOV #imm, Rn: sign-extended imm -> Rn."""
        self.cpu.regs[n] = _u32(_sext(i & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVA(self, d: int):
        """MOVA @(disp,PC), R0: (disp*4) + (PC & ~3) + 4 -> R0."""
        disp = d & 0xFF
        self.cpu.regs[0] = _u32((self.cpu.pc & 0xFFFFFFFC) + 4 + (disp << 2))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWI(self, d: int, n: int):
        """MOV.W @(disp,PC), Rn: sign-extended 16-bit load."""
        disp = d & 0xFF
        val = self.cpu.mem.read16(_u32(self.cpu.pc + 4 + (disp << 1)))
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLI(self, d: int, n: int):
        """MOV.L @(disp,PC), Rn: 32-bit load."""
        disp = d & 0xFF
        val = self.cpu.mem.read32(_u32((self.cpu.pc & 0xFFFFFFFC) + 4 + (disp << 2)))
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBL(self, m: int, n: int):
        """MOV.B @Rm, Rn: sign-extended 8-bit load."""
        val = self.cpu.mem.read8(self.cpu.regs[m])
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.regs[n] = _u32(_sext(val & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWL(self, m: int, n: int):
        """MOV.W @Rm, Rn: sign-extended 16-bit load."""
        val = self.cpu.mem.read16(self.cpu.regs[m])
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLL(self, m: int, n: int):
        """MOV.L @Rm, Rn: 32-bit load."""
        val = self.cpu.mem.read32(self.cpu.regs[m])
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBS(self, m: int, n: int):
        """MOV.B Rm, @Rn: 8-bit store."""
        self.cpu.mem.write8(self.cpu.regs[n], self.cpu.regs[m] & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWS(self, m: int, n: int):
        """MOV.W Rm, @Rn: 16-bit store."""
        self.cpu.mem.write16(self.cpu.regs[n], self.cpu.regs[m] & 0xFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLS(self, m: int, n: int):
        """MOV.L Rm, @Rn: 32-bit store."""
        self.cpu.mem.write32(self.cpu.regs[n], self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBP(self, m: int, n: int):
        """MOV.B @Rm+, Rn: sign-extended 8-bit load with post-increment."""
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.regs[n] = _u32(_sext(val & 0xFF, 8))
        self.cpu.regs[m] = _u32(addr + 1)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWP(self, m: int, n: int):
        """MOV.W @Rm+, Rn: sign-extended 16-bit load with post-increment."""
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read16(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.regs[m] = _u32(addr + 2)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLP(self, m: int, n: int):
        """MOV.L @Rm+, Rn: 32-bit load with post-increment."""
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(val)
        self.cpu.regs[m] = _u32(addr + 4)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBM(self, m: int, n: int):
        """MOV.B Rm, @-Rn: 8-bit store with pre-decrement."""
        addr = _u32(self.cpu.regs[n] - 1)
        self.cpu.regs[n] = addr
        self.cpu.mem.write8(addr, self.cpu.regs[m] & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWM(self, m: int, n: int):
        """MOV.W Rm, @-Rn: 16-bit store with pre-decrement."""
        addr = _u32(self.cpu.regs[n] - 2)
        self.cpu.regs[n] = addr
        self.cpu.mem.write16(addr, self.cpu.regs[m] & 0xFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLM(self, m: int, n: int):
        """MOV.L Rm, @-Rn: 32-bit store with pre-decrement."""
        addr = _u32(self.cpu.regs[n] - 4)
        self.cpu.regs[n] = addr
        self.cpu.mem.write32(addr, self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBL4(self, m: int, d: int):
        """MOV.B @(disp,Rm), R0: sign-extended 8-bit load."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[m] + disp)
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.regs[0] = _u32(_sext(val & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWL4(self, m: int, d: int):
        """MOV.W @(disp,Rm), R0: sign-extended 16-bit load."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[m] + (disp << 1))
        val = self.cpu.mem.read16(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[0] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLL4(self, m: int, d: int, n: int):
        """MOV.L @(disp,Rm), Rn: 32-bit load."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[m] + (disp << 2))
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBS4(self, d: int, n: int):
        """MOV.B R0, @(disp,Rn): 8-bit store."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[n] + disp)
        self.cpu.mem.write8(addr, self.cpu.regs[0] & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWS4(self, d: int, n: int):
        """MOV.W R0, @(disp,Rn): 16-bit store."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[n] + (disp << 1))
        self.cpu.mem.write16(addr, self.cpu.regs[0] & 0xFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLS4(self, m: int, d: int, n: int):
        """MOV.L Rm, @(disp,Rn): 32-bit store."""
        disp = d & 0x0F
        addr = _u32(self.cpu.regs[n] + (disp << 2))
        self.cpu.mem.write32(addr, self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBL0(self, m: int, n: int):
        """MOV.B @(R0,Rm), Rn: sign-extended 8-bit load."""
        addr = _u32(self.cpu.regs[m] + self.cpu.regs[0])
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.regs[n] = _u32(_sext(val & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWL0(self, m: int, n: int):
        """MOV.W @(R0,Rm), Rn: sign-extended 16-bit load."""
        addr = _u32(self.cpu.regs[m] + self.cpu.regs[0])
        val = self.cpu.mem.read16(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLL0(self, m: int, n: int):
        """MOV.L @(R0,Rm), Rn: 32-bit load."""
        addr = _u32(self.cpu.regs[m] + self.cpu.regs[0])
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[n] = _u32(val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBS0(self, m: int, n: int):
        """MOV.B Rm, @(R0,Rn): 8-bit store."""
        addr = _u32(self.cpu.regs[n] + self.cpu.regs[0])
        self.cpu.mem.write8(addr, self.cpu.regs[m] & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWS0(self, m: int, n: int):
        """MOV.W Rm, @(R0,Rn): 16-bit store."""
        addr = _u32(self.cpu.regs[n] + self.cpu.regs[0])
        self.cpu.mem.write16(addr, self.cpu.regs[m] & 0xFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLS0(self, m: int, n: int):
        """MOV.L Rm, @(R0,Rn): 32-bit store."""
        addr = _u32(self.cpu.regs[n] + self.cpu.regs[0])
        self.cpu.mem.write32(addr, self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBLG(self, d: int):
        """MOV.B @(disp,GBR), R0: sign-extended 8-bit load."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + disp)
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.regs[0] = _u32(_sext(val & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWLG(self, d: int):
        """MOV.W @(disp,GBR), R0: sign-extended 16-bit load."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + (disp << 1))
        val = self.cpu.mem.read16(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[0] = _u32(_sext(val & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLLG(self, d: int):
        """MOV.L @(disp,GBR), R0: 32-bit load."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + (disp << 2))
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[0] = _u32(val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVBSG(self, d: int):
        """MOV.B R0, @(disp,GBR): 8-bit store."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + disp)
        self.cpu.mem.write8(addr, self.cpu.regs[0] & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVWSG(self, d: int):
        """MOV.W R0, @(disp,GBR): 16-bit store."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + (disp << 1))
        self.cpu.mem.write16(addr, self.cpu.regs[0] & 0xFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVLSG(self, d: int):
        """MOV.L R0, @(disp,GBR): 32-bit store."""
        disp = d & 0xFF
        addr = _u32(self.cpu.regs['gbr'] + (disp << 2))
        self.cpu.mem.write32(addr, self.cpu.regs[0])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ===================================================================
    # Arithmetic / logic
    # ===================================================================

    def MOVT(self, n: int):
        """MOVT Rn: T -> Rn."""
        self.cpu.regs[n] = self._get_t()
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SWAPB(self, m: int, n: int):
        """SWAP.B Rm, Rn: swap low bytes of Rm -> Rn."""
        val = self.cpu.regs[m]
        result = (val & 0xFFFF0000) | ((val & 0x00FF) << 8) | ((val & 0xFF00) >> 8)
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SWAPW(self, m: int, n: int):
        """SWAP.W Rm, Rn: swap halfwords of Rm -> Rn."""
        val = self.cpu.regs[m]
        result = ((val & 0xFFFF) << 16) | ((val & 0xFFFF0000) >> 16)
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def XTRCT(self, m: int, n: int):
        """XTRCT Rm, Rn: extract middle 32 bits (Rm<<16 | Rn>>16)."""
        result = ((self.cpu.regs[m] << 16) & 0xFFFF0000) | ((self.cpu.regs[n] >> 16) & 0x0000FFFF)
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ADD(self, m: int, n: int):
        """ADD Rm, Rn: Rn + Rm -> Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] + self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ADDI(self, i: int, n: int):
        """ADD #imm, Rn: Rn + sign-ext(imm) -> Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] + _sext(i & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ADDC(self, m: int, n: int):
        """ADDC Rm, Rn: Rn + Rm + T -> Rn, carry -> T."""
        T = self._get_t()
        tmp1 = _u32(self.cpu.regs[n] + self.cpu.regs[m])
        result = _u32(tmp1 + T)
        # Carry if tmp1 < Rn (unsigned) or result < tmp1
        if tmp1 < self.cpu.regs[n] or result < tmp1:
            self._set_t(1)
        else:
            self._set_t(0)
        self.cpu.regs[n] = result
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ADDV(self, m: int, n: int):
        """ADDV Rm, Rn: signed overflow -> T."""
        src1 = _i32(self.cpu.regs[n])
        src2 = _i32(self.cpu.regs[m])
        result = src1 + src2
        self.cpu.regs[n] = _u32(result)
        if result < -0x80000000 or result > 0x7FFFFFFF:
            self._set_t(1)
        else:
            self._set_t(0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPIM(self, i: int, n: int=None):
        """CMP/EQ #imm, R0: T = (R0 == sign-ext(imm))."""
        # Some variants pass only `i` (R0 implicit); others pass `i, n`.
        # Be tolerant: if n is None, compare against R0.
        reg = 0 if n is None else n
        self._set_t(1 if _i32(self.cpu.regs[reg]) == _sext(i & 0xFF, 8) else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPEQ(self, m: int, n: int):
        """CMP/EQ Rm, Rn: T = (Rn == Rm)."""
        self._set_t(1 if self.cpu.regs[n] == self.cpu.regs[m] else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPHS(self, m: int, n: int):
        """CMP/HS Rm, Rn: T = (Rn >= Rm) unsigned."""
        self._set_t(1 if self.cpu.regs[n] >= self.cpu.regs[m] else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPGE(self, m: int, n: int):
        """CMP/GE Rm, Rn: T = (Rn >= Rm) signed."""
        self._set_t(1 if _i32(self.cpu.regs[n]) >= _i32(self.cpu.regs[m]) else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPHI(self, m: int, n: int):
        """CMP/HI Rm, Rn: T = (Rn > Rm) unsigned."""
        self._set_t(1 if self.cpu.regs[n] > self.cpu.regs[m] else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPGT(self, m: int, n: int):
        """CMP/GT Rm, Rn: T = (Rn > Rm) signed."""
        self._set_t(1 if _i32(self.cpu.regs[n]) > _i32(self.cpu.regs[m]) else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPPL(self, n: int):
        """CMP/PL Rn: T = (Rn > 0) signed."""
        self._set_t(1 if _i32(self.cpu.regs[n]) > 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPPZ(self, n: int):
        """CMP/PZ Rn: T = (Rn >= 0) signed."""
        self._set_t(1 if _i32(self.cpu.regs[n]) >= 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CMPSTR(self, m: int, n: int):
        """CMP/STR Rm, Rn: T = 1 if any byte of (Rn^Rm) is 0."""
        xor = self.cpu.regs[n] ^ self.cpu.regs[m]
        if (xor & 0xFF000000) == 0 or (xor & 0x00FF0000) == 0 or (xor & 0x0000FF00) == 0 or (xor & 0x000000FF) == 0:
            self._set_t(1)
        else:
            self._set_t(0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DT(self, n: int):
        """DT Rn: Rn - 1 -> Rn; T = (Rn == 0)."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] - 1)
        self._set_t(1 if self.cpu.regs[n] == 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def EXTSB(self, m: int, n: int):
        """EXTS.B Rm, Rn: sign-extend low byte of Rm -> Rn."""
        self.cpu.regs[n] = _u32(_sext(self.cpu.regs[m] & 0xFF, 8))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def EXTSW(self, m: int, n: int):
        """EXTS.W Rm, Rn: sign-extend low halfword of Rm -> Rn."""
        self.cpu.regs[n] = _u32(_sext(self.cpu.regs[m] & 0xFFFF, 16))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def EXTUB(self, m: int, n: int):
        """EXTU.B Rm, Rn: zero-extend low byte of Rm -> Rn."""
        self.cpu.regs[n] = self.cpu.regs[m] & 0xFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def EXTUW(self, m: int, n: int):
        """EXTU.W Rm, Rn: zero-extend low halfword of Rm -> Rn."""
        self.cpu.regs[n] = self.cpu.regs[m] & 0xFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def NOT(self, m: int, n: int):
        """NOT Rm, Rn: ~Rm -> Rn."""
        self.cpu.regs[n] = _u32(~self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def NOT_RM_RN(self, m: int, n: int):
        """(alias of NOT)"""
        self.NOT(m, n)

    def NEG(self, m: int, n: int):
        """NEG Rm, Rn: 0 - Rm -> Rn."""
        self.cpu.regs[n] = _u32(-self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def NEGC(self, m: int, n: int):
        """NEGC Rm, Rn: 0 - Rm - T -> Rn, borrow -> T."""
        val = self.cpu.regs[m]
        T = self._get_t()
        result = _u32(0 - val - T)
        # Borrow if val + T != 0 (i.e. we subtracted something nonzero)
        self._set_t(1 if (val | T) != 0 else 0)
        self.cpu.regs[n] = result
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SUB(self, m: int, n: int):
        """SUB Rm, Rn: Rn - Rm -> Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] - self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SUBC(self, m: int, n: int):
        """SUBC Rm, Rn: Rn - Rm - T -> Rn, borrow -> T."""
        T = self._get_t()
        tmp = _u32(self.cpu.regs[n] - self.cpu.regs[m])
        result = _u32(tmp - T)
        # Borrow if Rn < Rm (unsigned) or tmp < T
        if self.cpu.regs[n] < self.cpu.regs[m] or tmp < T:
            self._set_t(1)
        else:
            self._set_t(0)
        self.cpu.regs[n] = result
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SUBV(self, m: int, n: int):
        """SUBV Rm, Rn: signed overflow -> T."""
        src1 = _i32(self.cpu.regs[n])
        src2 = _i32(self.cpu.regs[m])
        result = src1 - src2
        self.cpu.regs[n] = _u32(result)
        if result < -0x80000000 or result > 0x7FFFFFFF:
            self._set_t(1)
        else:
            self._set_t(0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def AND_RM_RN(self, m: int, n: int):
        """AND Rm, Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] & self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def AND_IMM(self, i: int):
        """AND #imm, R0."""
        self.cpu.regs[0] = _u32(self.cpu.regs[0] & (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def OR_RM_RN(self, m: int, n: int):
        """OR Rm, Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] | self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def OR_IMM(self, i: int):
        """OR #imm, R0."""
        self.cpu.regs[0] = _u32(self.cpu.regs[0] | (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def XOR_RM_RN(self, m: int, n: int):
        """XOR Rm, Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] ^ self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def XOR_IMM(self, i: int):
        """XOR #imm, R0."""
        self.cpu.regs[0] = _u32(self.cpu.regs[0] ^ (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def TST_RM_RN(self, m: int, n: int):
        """TST Rm, Rn: T = ((Rn & Rm) == 0)."""
        self._set_t(1 if (self.cpu.regs[n] & self.cpu.regs[m]) == 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def TST_RM_RN2(self, m: int, n: int):
        """(alias of TST_RM_RN)"""
        self.TST_RM_RN(m, n)

    def TST_IMM(self, i: int):
        """TST #imm, R0: T = ((R0 & imm) == 0)."""
        self._set_t(1 if (self.cpu.regs[0] & (i & 0xFF)) == 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def TST_B(self, i: int):
        """TST.B #imm, @(R0,GBR): T = ((mem[R0+GBR] & imm) == 0)."""
        addr = _u32(self.cpu.regs[0] + self.cpu.regs['gbr'])
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self._set_t(1 if (val & (i & 0xFF)) == 0 else 0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ANDB(self, i: int):
        """AND.B #imm, @(R0,GBR): mem[R0+GBR] & imm -> mem[R0+GBR]."""
        addr = _u32(self.cpu.regs[0] + self.cpu.regs['gbr'])
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.mem.write8(addr, val & (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ORB(self, i: int):
        """OR.B #imm, @(R0,GBR): mem[R0+GBR] | imm -> mem[R0+GBR]."""
        addr = _u32(self.cpu.regs[0] + self.cpu.regs['gbr'])
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.mem.write8(addr, val | (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def XORB(self, i: int):
        """XOR.B #imm, @(R0,GBR): mem[R0+GBR] ^ imm -> mem[R0+GBR]."""
        addr = _u32(self.cpu.regs[0] + self.cpu.regs['gbr'])
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self.cpu.mem.write8(addr, val ^ (i & 0xFF))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def TASB(self, n: int):
        """TAS.B @Rn: T = (mem[Rn] == 0); mem[Rn] |= 0x80."""
        addr = self.cpu.regs[n]
        val = self.cpu.mem.read8(addr)
        if isinstance(val, bytes):
            val = val[0]
        self._set_t(1 if val == 0 else 0)
        self.cpu.mem.write8(addr, val | 0x80)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MULL(self, m: int, n: int):
        """MUL.L Rm, Rn: Rn * Rm -> MACL (32-bit result)."""
        self.cpu.regs['macl'] = _u32(self.cpu.regs[n] * self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DMULS(self, m: int, n: int):
        """DMULS.L Rm, Rn: signed 32x32 -> 64-bit -> MACH:MACL."""
        result = _i32(self.cpu.regs[n]) * _i32(self.cpu.regs[m])
        result &= 0xFFFFFFFFFFFFFFFF
        self.cpu.regs['mach'] = _u32((result >> 32) & 0xFFFFFFFF)
        self.cpu.regs['macl'] = _u32(result & 0xFFFFFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DMULU(self, m: int, n: int):
        """DMULU.L Rm, Rn: unsigned 32x32 -> 64-bit -> MACH:MACL."""
        result = self.cpu.regs[n] * self.cpu.regs[m]
        self.cpu.regs['mach'] = _u32((result >> 32) & 0xFFFFFFFF)
        self.cpu.regs['macl'] = _u32(result & 0xFFFFFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MACL(self, m: int, n: int):
        """MAC.L @Rm+, @Rn+: 32x32 signed multiply-accumulate -> MACH:MACL."""
        src1 = self.cpu.mem.read32(self.cpu.regs[m])
        if isinstance(src1, bytes):
            src1 = int.from_bytes(src1, 'big')
        src2 = self.cpu.mem.read32(self.cpu.regs[n])
        if isinstance(src2, bytes):
            src2 = int.from_bytes(src2, 'big')
        self.cpu.regs[m] = _u32(self.cpu.regs[m] + 4)
        self.cpu.regs[n] = _u32(self.cpu.regs[n] + 4)
        # Signed multiply, accumulate into MACH:MACL
        prod = _i32(src1) * _i32(src2)
        # Accumulate (simplified -- no saturation)
        old = (self.cpu.regs['mach'] << 32) | self.cpu.regs['macl']
        result = old + prod
        result &= 0xFFFFFFFFFFFFFFFF
        self.cpu.regs['mach'] = _u32((result >> 32) & 0xFFFFFFFF)
        self.cpu.regs['macl'] = _u32(result & 0xFFFFFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MACW(self, m: int, n: int):
        """MAC.W @Rm+, @Rn+: 16x16 signed multiply-accumulate -> MACH:MACL."""
        src1 = self.cpu.mem.read16(self.cpu.regs[m])
        if isinstance(src1, bytes):
            src1 = int.from_bytes(src1, 'big')
        src2 = self.cpu.mem.read16(self.cpu.regs[n])
        if isinstance(src2, bytes):
            src2 = int.from_bytes(src2, 'big')
        self.cpu.regs[m] = _u32(self.cpu.regs[m] + 2)
        self.cpu.regs[n] = _u32(self.cpu.regs[n] + 2)
        # Sign-extend 16-bit
        s1 = _i32(src1 & 0xFFFF)
        if s1 & 0x8000:
            s1 -= 0x10000
        s2 = _i32(src2 & 0xFFFF)
        if s2 & 0x8000:
            s2 -= 0x10000
        prod = s1 * s2
        old = (self.cpu.regs['mach'] << 32) | self.cpu.regs['macl']
        result = old + prod
        result &= 0xFFFFFFFFFFFFFFFF
        self.cpu.regs['mach'] = _u32((result >> 32) & 0xFFFFFFFF)
        self.cpu.regs['macl'] = _u32(result & 0xFFFFFFFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MULSW(self, m: int, n: int):
        """MULS.W Rm, Rn: (signed)Rn * (signed)Rm -> MACL (low 16 bits)."""
        a = _i32(self.cpu.regs[n]) & 0xFFFF
        if a & 0x8000:
            a -= 0x10000
        b = _i32(self.cpu.regs[m]) & 0xFFFF
        if b & 0x8000:
            b -= 0x10000
        self.cpu.regs['macl'] = _u32(a * b)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MULUW(self, m: int, n: int):
        """MULU.W Rm, Rn: (unsigned)Rn * (unsigned)Rm -> MACL (low 16 bits)."""
        a = self.cpu.regs[n] & 0xFFFF
        b = self.cpu.regs[m] & 0xFFFF
        self.cpu.regs['macl'] = _u32(a * b)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DIV0S(self, m: int, n: int):
        """DIV0S Rm, Rn: initialize for signed division."""
        sr = self.cpu.regs['sr']
        # Q = MSB of Rn, M = MSB of Rm, T = (Q != M)
        if self.cpu.regs[n] & 0x80000000:
            sr |= 0x100   # Q
        else:
            sr &= ~0x100 & 0xFFFFFFFF
        if self.cpu.regs[m] & 0x80000000:
            sr |= 0x200   # M
        else:
            sr &= ~0x200 & 0xFFFFFFFF
        # T = (Q XOR M)
        q = 1 if self.cpu.regs[n] & 0x80000000 else 0
        mm = 1 if self.cpu.regs[m] & 0x80000000 else 0
        if q != mm:
            sr |= 1
        else:
            sr &= ~1 & 0xFFFFFFFF
        self.cpu.regs['sr'] = sr
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DIV0U(self):
        """DIV0U: initialize for unsigned division. Q=M=T=0."""
        self.cpu.regs['sr'] &= ~0x301 & 0xFFFFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def DIV1(self, m: int, n: int):
        """DIV1 Rm, Rn: one step of division. (Complex -- see SH-4 manual.)"""
        # This is a faithful port of the Renesas reference implementation.
        sr = self.cpu.regs['sr']
        old_q = (sr >> 8) & 1
        new_q = 1 if self.cpu.regs[n] & 0x80000000 else 0
        # Clear Q, set new Q
        sr &= ~0x100 & 0xFFFFFFFF
        if new_q:
            sr |= 0x100
        tmp2 = self.cpu.regs[m]
        # Rn <<= 1 | T
        rn = _u32((self.cpu.regs[n] << 1) | (sr & 1))
        if old_q == 0:
            if (sr & 0x200) == 0:  # M == 0
                tmp0 = rn
                rn = _u32(rn - tmp2)
                tmp1 = 1 if rn > tmp0 else 0
                if new_q == 0:
                    new_q = tmp1
                else:
                    new_q = 1 if tmp1 == 0 else 0
            else:  # M == 1
                tmp0 = rn
                rn = _u32(rn + tmp2)
                tmp1 = 1 if rn < tmp0 else 0
                if new_q == 0:
                    new_q = 1 if tmp1 == 0 else 0
                else:
                    new_q = tmp1
        else:  # old_q == 1
            if (sr & 0x200) == 0:  # M == 0
                tmp0 = rn
                rn = _u32(rn + tmp2)
                tmp1 = 1 if rn < tmp0 else 0
                if new_q == 0:
                    new_q = tmp1
                else:
                    new_q = 1 if tmp1 == 0 else 0
            else:  # M == 1
                tmp0 = rn
                rn = _u32(rn - tmp2)
                tmp1 = 1 if rn > tmp0 else 0
                if new_q == 0:
                    new_q = 1 if tmp1 == 0 else 0
                else:
                    new_q = tmp1
        # Update Q
        sr &= ~0x100 & 0xFFFFFFFF
        if new_q:
            sr |= 0x100
        # T = (Q == M)
        q_bit = (sr >> 8) & 1
        m_bit = (sr >> 9) & 1
        if q_bit == m_bit:
            sr |= 1
        else:
            sr &= ~1 & 0xFFFFFFFF
        self.cpu.regs['sr'] = sr
        self.cpu.regs[n] = rn
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ===================================================================
    # Shifts / rotates
    # ===================================================================

    def SHLL(self, n: int):
        """SHLL Rn: Rn << 1; T = MSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 0x80000000 else 0)
        self.cpu.regs[n] = _u32(val << 1)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLR(self, n: int):
        """SHLR Rn: Rn >> 1 (logical); T = LSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 1 else 0)
        self.cpu.regs[n] = (val >> 1) & 0x7FFFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHAL(self, n: int):
        """SHAL Rn: Rn << 1 (arithmetic); T = MSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 0x80000000 else 0)
        self.cpu.regs[n] = _u32(val << 1)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHAR(self, n: int):
        """SHAR Rn: Rn >> 1 (arithmetic, sign-preserving); T = LSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 1 else 0)
        result = (val >> 1) | (val & 0x80000000)
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLL2(self, n: int):
        """SHLL2 Rn: Rn << 2."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] << 2)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLR2(self, n: int):
        """SHLR2 Rn: Rn >> 2 (logical)."""
        self.cpu.regs[n] = (self.cpu.regs[n] >> 2) & 0x3FFFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLL8(self, n: int):
        """SHLL8 Rn: Rn << 8."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] << 8)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLR8(self, n: int):
        """SHLR8 Rn: Rn >> 8 (logical)."""
        self.cpu.regs[n] = (self.cpu.regs[n] >> 8) & 0x00FFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLL16(self, n: int):
        """SHLL16 Rn: Rn << 16."""
        self.cpu.regs[n] = _u32(self.cpu.regs[n] << 16)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLR16(self, n: int):
        """SHLR16 Rn: Rn >> 16 (logical)."""
        self.cpu.regs[n] = (self.cpu.regs[n] >> 16) & 0x0000FFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHAD(self, m: int, n: int):
        """SHAD Rm, Rn: dynamic arithmetic shift.  Shift amount = signed low 5 bits of Rm."""
        shift = _i32(self.cpu.regs[m]) & 0x1F
        # sign-extend from 5 bits
        if shift & 0x10:
            shift -= 0x20
        val = _i32(self.cpu.regs[n])
        if shift >= 0:
            result = val << shift
        else:
            result = val >> (-shift)
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SHLD(self, m: int, n: int):
        """SHLD Rm, Rn: dynamic logical shift.  Shift amount = signed low 5 bits of Rm."""
        shift = _i32(self.cpu.regs[m]) & 0x1F
        if shift & 0x10:
            shift -= 0x20
        val = self.cpu.regs[n]
        if shift >= 0:
            result = val << shift
        else:
            result = (val >> (-shift)) & (0xFFFFFFFF >> (-shift))
        self.cpu.regs[n] = _u32(result)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ROTL(self, n: int):
        """ROTL Rn: rotate left 1; T = MSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 0x80000000 else 0)
        self.cpu.regs[n] = _u32((val << 1) | (val >> 31))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ROTR(self, n: int):
        """ROTR Rn: rotate right 1; T = LSB before shift."""
        val = self.cpu.regs[n]
        self._set_t(1 if val & 1 else 0)
        self.cpu.regs[n] = _u32((val >> 1) | (val << 31))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ROTCL(self, n: int):
        """ROTCL Rn: rotate left 1 through T."""
        val = self.cpu.regs[n]
        T = self._get_t()
        self._set_t(1 if val & 0x80000000 else 0)
        self.cpu.regs[n] = _u32((val << 1) | T)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ROTCR(self, n: int):
        """ROTCR Rn: rotate right 1 through T."""
        val = self.cpu.regs[n]
        T = self._get_t()
        self._set_t(1 if val & 1 else 0)
        self.cpu.regs[n] = _u32((val >> 1) | (T << 31))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ===================================================================
    # Branches
    # ===================================================================

    def BF(self, d: int):
        """BF disp: if T=0, branch to PC+4+disp*2; else PC+=2."""
        disp = _sext(d & 0xFF, 8)
        if not self._get_t():
            self.cpu.pc = _u32(self.cpu.pc + 4 + (disp << 1))
        else:
            self.cpu.pc = _u32(self.cpu.pc + 2)

    def BFS(self, d: int):
        """BF/S disp: if T=0, branch with delay slot."""
        disp = _sext(d & 0xFF, 8)
        target = _u32(self.cpu.pc + 4 + (disp << 1))
        slot_pc = _u32(self.cpu.pc + 2)
        if not self._get_t():
            _exec_delay_slot(self.cpu, slot_pc, target)
        else:
            # Not taken: just execute the delay slot and continue
            _exec_delay_slot(self.cpu, slot_pc, _u32(slot_pc + 2))

    def BT(self, d: int):
        """BT disp: if T=1, branch to PC+4+disp*2; else PC+=2."""
        disp = _sext(d & 0xFF, 8)
        if self._get_t():
            self.cpu.pc = _u32(self.cpu.pc + 4 + (disp << 1))
        else:
            self.cpu.pc = _u32(self.cpu.pc + 2)

    def BTS(self, d: int):
        """BT/S disp: if T=1, branch with delay slot."""
        disp = _sext(d & 0xFF, 8)
        target = _u32(self.cpu.pc + 4 + (disp << 1))
        slot_pc = _u32(self.cpu.pc + 2)
        if self._get_t():
            _exec_delay_slot(self.cpu, slot_pc, target)
        else:
            _exec_delay_slot(self.cpu, slot_pc, _u32(slot_pc + 2))

    def BRA(self, d: int):
        """BRA disp: branch always with delay slot."""
        disp = _sext(d & 0xFFF, 12)
        target = _u32(self.cpu.pc + 4 + (disp << 1))
        slot_pc = _u32(self.cpu.pc + 2)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def BRAF(self, m: int):
        """BRAF Rm: branch always to PC+4+Rm, with delay slot."""
        target = _u32(self.cpu.pc + 4 + self.cpu.regs[m])
        slot_pc = _u32(self.cpu.pc + 2)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def BSR(self, d: int):
        """BSR disp: call with delay slot. PR = PC+4, branch to PC+4+disp*2."""
        disp = _sext(d & 0xFFF, 12)
        target = _u32(self.cpu.pc + 4 + (disp << 1))
        slot_pc = _u32(self.cpu.pc + 2)
        self.cpu.regs['pr'] = _u32(self.cpu.pc + 4)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def BSRF(self, m: int):
        """BSRF Rm: call with delay slot. PR = PC+4, branch to PC+4+Rm."""
        target = _u32(self.cpu.pc + 4 + self.cpu.regs[m])
        slot_pc = _u32(self.cpu.pc + 2)
        self.cpu.regs['pr'] = _u32(self.cpu.pc + 4)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def JMP(self, m: int):
        """JMP @Rm: jump to Rm with delay slot."""
        target = _u32(self.cpu.regs[m])
        slot_pc = _u32(self.cpu.pc + 2)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def JSR(self, m: int):
        """JSR @Rm: call Rm with delay slot. PR = PC+4."""
        target = _u32(self.cpu.regs[m])
        slot_pc = _u32(self.cpu.pc + 2)
        self.cpu.regs['pr'] = _u32(self.cpu.pc + 4)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def RTS(self):
        """RTS: return to PR with delay slot."""
        target = _u32(self.cpu.regs['pr'])
        slot_pc = _u32(self.cpu.pc + 2)
        _exec_delay_slot(self.cpu, slot_pc, target)

    def RTE(self):
        """RTE: return from exception. SR=SSR, PC=SPC, with delay slot."""
        target = _u32(self.cpu.spc)
        slot_pc = _u32(self.cpu.pc + 2)
        # Restore SR from SSR before executing the delay slot
        self.cpu.regs['sr'] = _u32(self.cpu.ssr)
        _exec_delay_slot(self.cpu, slot_pc, target)

    # ===================================================================
    # System / control
    # ===================================================================

    def SETT(self):
        """SETT: T = 1."""
        self._set_t(1)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CLRT(self):
        """CLRT: T = 0."""
        self._set_t(0)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SETS(self):
        """SETS: S = 1."""
        self.cpu.regs['sr'] |= 2
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def CLRS(self):
        """CLRS: S = 0."""
        self.cpu.regs['sr'] &= ~2 & 0xFFFFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def NOP(self):
        """NOP."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def NOP2(self):
        """NOP (alternate opcode ID)."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SLEEP(self):
        """SLEEP: CPU halts until next interrupt.  We advance PC and set is_sleeping."""
        self.cpu.pc = _u32(self.cpu.pc + 2)
        self.cpu.is_sleeping = True

    def CLRMAC(self):
        """CLRMAC: MACH = MACL = 0."""
        self.cpu.regs['mach'] = 0
        self.cpu.regs['macl'] = 0
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDTLB(self):
        """LDTLB: load TLB entry.  We don't model the MMU/TLB, so this is a NOP."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def MOVCA(self, n: int):
        """MOVCA.L R0, @Rn: move with cache allocation.  Treated as MOV.L R0, @Rn."""
        self.cpu.mem.write32(self.cpu.regs[n], self.cpu.regs[0])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def OCBI(self, n: int):
        """OCBI @Rn: instruction cache block invalidate.  NOP (no cache)."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def OCBP(self, n: int):
        """OCBP @Rn: operand cache block purge.  NOP (no cache)."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def OCBWB(self, n: int):
        """OCBWB @Rn: operand cache block write-back.  NOP (no cache)."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def PREF(self, n: int):
        """PREF @Rn: prefetch.  NOP."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def ICBI(self, n: int):
        """ICBI @Rn: instruction cache block invalidate.  NOP (no cache)."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def PREFI(self, n: int):
        """PREFI @Rn: instruction prefetch.  NOP."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def SYNCO(self):
        """SYNCO: pipeline synchronization barrier.  NOP."""
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def TRAPA(self, i: int):
        """TRAPA #imm: trap exception.  PC -> SPC, SR -> SSR, EXPEVT=0x160, PC = VBR+0x100."""
        imm = i & 0xFF
        self.cpu.spc = _u32(self.cpu.pc + 2)
        self.cpu.ssr = self.cpu.regs['sr']
        self.cpu.sgr = self.cpu.regs[15]
        self.cpu.tra = imm << 2
        self.cpu.expevt = 0x00000160
        # Set SR.BL=1, SR.MD=1, SR.RB=1
        self.cpu.regs['sr'] |= 0xB0000000
        vbr = self.cpu.regs['vbr']
        self.cpu.pc = _u32(vbr + 0x100)

    # ===================================================================
    # LDC / LDS / STC / STS
    # ===================================================================

    # ---- LDC Rm, REG ----
    def LDC_SR(self, m: int):
        self.cpu.regs['sr'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDC_GBR(self, m: int):
        self.cpu.regs['gbr'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDC_VBR(self, m: int):
        self.cpu.regs['vbr'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDC_SSR(self, m: int):
        self.cpu.ssr = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDC_SPC(self, m: int):
        self.cpu.spc = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDC_DBR(self, m: int):
        self.cpu.dbr = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- LDC.L @Rm+, REG ----
    def _ldcl(self, m: int, attr: str):
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        if attr == 'sr':
            self.cpu.regs['sr'] = _u32(val)
        elif attr == 'gbr':
            self.cpu.regs['gbr'] = _u32(val)
        elif attr == 'vbr':
            self.cpu.regs['vbr'] = _u32(val)
        elif attr == 'ssr':
            self.cpu.ssr = _u32(val)
        elif attr == 'spc':
            self.cpu.spc = _u32(val)
        elif attr == 'dbr':
            self.cpu.dbr = _u32(val)
        self.cpu.regs[m] = _u32(addr + 4)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDCL_SR(self, m: int):     self._ldcl(m, 'sr')
    def LDCL_GBR(self, m: int):    self._ldcl(m, 'gbr')
    def LDCL_VBR(self, m: int):    self._ldcl(m, 'vbr')
    def LDCL_SSR(self, m: int):    self._ldcl(m, 'ssr')
    def LDCL_SPC(self, m: int):    self._ldcl(m, 'spc')
    def LDCL_DBR(self, m: int):    self._ldcl(m, 'dbr')

    # ---- LDC/STC banked registers (R0_BANK..R7_BANK) ----
    def LDC_BANK(self, m: int, n: int):
        """LDC Rm, Rn_BANK: load Rm into the nth banked register."""
        self.cpu.regs[f'r{n}_bank'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDCL_BANK(self, m: int, n: int):
        """LDC.L @Rm+, Rn_BANK: load from memory into nth banked register."""
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, 'big')
        self.cpu.regs[f'r{n}_bank'] = _u32(val)
        self.cpu.regs[m] = _u32(addr + 4)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_BANK(self, m: int, n: int):
        """STC Rm_BANK, Rn: read mth banked register into Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs[f'r{m}_bank'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STCL_BANK(self, m: int, n: int):
        """STC.L Rm_BANK, @-Rn: push mth banked register to stack."""
        addr = _u32(self.cpu.regs[n] - 4)
        self.cpu.regs[n] = addr
        self.cpu.mem.write32(addr, self.cpu.regs[f'r{m}_bank'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- LDS Rm, REG ----
    def LDS_MACH(self, m: int):
        self.cpu.regs['mach'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_MACL(self, m: int):
        self.cpu.regs['macl'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_PR(self, m: int):
        self.cpu.regs['pr'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- LDS.L @Rm+, REG ----
    def _ldsl(self, m: int, attr: str):
        addr = self.cpu.regs[m]
        val = self.cpu.mem.read32(addr)
        if isinstance(val, bytes):
            val = int.from_bytes(val, "big")
        self.cpu.regs[attr] = _u32(val)
        self.cpu.regs[m] = _u32(addr + 4)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDSL_MACH(self, m: int):   self._ldsl(m, 'mach')
    def LDSL_MACL(self, m: int):   self._ldsl(m, 'macl')
    def LDSL_PR(self, m: int):     self._ldsl(m, 'pr')

    # ---- LDS Rm, DSP repeat-loop registers (SH4AL-DSP) ----
    def LDS_RS(self, m: int):
        """LDS Rm, RS: load repeat-start address."""
        self.cpu.regs['rs'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_RE(self, m: int):
        """LDS Rm, RE: load repeat-end address."""
        self.cpu.regs['re'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_RC(self, m: int):
        """LDS Rm, RC: load repeat-count.

        If RC is loaded with a non-zero value, the next instruction
        at RE will start a zero-overhead loop that branches back to RS
        RC-1 times.  RC=0 disables the repeat loop.
        """
        self.cpu.regs['rc'] = _u32(self.cpu.regs[m]) & 0xFFFFFFFF
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_MOD(self, m: int):
        """LDS Rm, MOD: load DSP mode register."""
        self.cpu.regs['mod'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDS_DSR(self, m: int):
        """LDS Rm, DSR: load DSP status register."""
        self.cpu.regs['dsr'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDSL_RS(self, m: int):   self._ldsl(m, 'rs')
    def LDSL_RE(self, m: int):   self._ldsl(m, 're')
    def LDSL_RC(self, m: int):   self._ldsl(m, 'rc')

    # ---- STS DSP repeat-loop registers, Rn (SH4AL-DSP) ----
    def STS_RS(self, n: int):
        """STS RS, Rn: read repeat-start address into Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs['rs'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STS_RE(self, n: int):
        """STS RE, Rn: read repeat-end address into Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs['re'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STS_RC(self, n: int):
        """STS RC, Rn: read repeat-count into Rn."""
        self.cpu.regs[n] = _u32(self.cpu.regs['rc'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def _stsl(self, n: int, attr: str):
        """STS.L REG, @-Rn: push system register to stack."""
        addr = _u32(self.cpu.regs[n] - 4)
        self.cpu.regs[n] = addr
        val = self.cpu.regs[attr]
        self.cpu.mem.write32(addr, val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STSL_RS(self, n: int):   self._stsl(n, 'rs')
    def STSL_RE(self, n: int):   self._stsl(n, 're')
    def STSL_RC(self, n: int):   self._stsl(n, 'rc')

    # ---- DSP repeat-loop setup (SH4AL-DSP) ----
    def LDRS_DISP(self, d: int):
        """LDRS @(disp,PC): load repeat-start address from PC-relative.

        Encoding: 1000_1100_dddd_dddd
        RS = PC + 4 + (disp * 2)  (PC is the address of the LDRS instruction)
        """
        pc = self.cpu.pc & 0xFFFFFFFF
        self.cpu.regs['rs'] = _u32(pc + 4 + (d * 2))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDRE_DISP(self, d: int):
        """LDRE @(disp,PC): load repeat-end address from PC-relative.

        Encoding: 1000_1110_dddd_dddd
        RE = PC + 4 + (disp * 2)
        """
        pc = self.cpu.pc & 0xFFFFFFFF
        self.cpu.regs['re'] = _u32(pc + 4 + (d * 2))
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDRC_IMM(self, d: int):
        """LDRC #imm: load repeat-count from 8-bit immediate.

        Encoding: 1000_1010_iiii_iiii
        RC = imm (8-bit, zero-extended to 32 bits)
        """
        self.cpu.regs['rc'] = _u32(d & 0xFF)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def LDRC_REG(self, m: int):
        """LDRC Rm: load repeat-count from register.

        Encoding: 0100_mmmm_0011_0100
        RC = Rm
        """
        self.cpu.regs['rc'] = _u32(self.cpu.regs[m])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- STC REG, Rn ----
    def STC_SR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['sr'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_GBR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['gbr'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_VBR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['vbr'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_SSR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.ssr)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_SPC(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.spc)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_SGR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.sgr)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STC_SGR2(self, n: int):
        self.STC_SGR(n)

    def STC_DBR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.dbr)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- STC.L REG, @-Rn ----
    def _stcl(self, n: int, attr: str):
        addr = _u32(self.cpu.regs[n] - 4)
        self.cpu.regs[n] = addr
        if attr == 'sr':
            val = self.cpu.regs['sr']
        elif attr == 'gbr':
            val = self.cpu.regs['gbr']
        elif attr == 'vbr':
            val = self.cpu.regs['vbr']
        elif attr == 'ssr':
            val = self.cpu.ssr
        elif attr == 'spc':
            val = self.cpu.spc
        elif attr == 'sgr':
            val = self.cpu.sgr
        elif attr == 'dbr':
            val = self.cpu.dbr
        else:
            val = 0
        self.cpu.mem.write32(addr, val)
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STCL_SR(self, n: int):     self._stcl(n, 'sr')
    def STCL_GBR(self, n: int):    self._stcl(n, 'gbr')
    def STCL_VBR(self, n: int):    self._stcl(n, 'vbr')
    def STCL_SSR(self, n: int):    self._stcl(n, 'ssr')
    def STCL_SPC(self, n: int):    self._stcl(n, 'spc')
    def STCL_SGR(self, n: int):    self._stcl(n, 'sgr')
    def STCL_DBR(self, n: int):    self._stcl(n, 'dbr')

    # ---- STS REG, Rn ----
    def STS_MACH(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['mach'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STS_MACL(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['macl'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STS_PR(self, n: int):
        self.cpu.regs[n] = _u32(self.cpu.regs['pr'])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    # ---- STS.L REG, @-Rn ----
    def _stsl(self, n: int, attr: str):
        addr = _u32(self.cpu.regs[n] - 4)
        self.cpu.regs[n] = addr
        self.cpu.mem.write32(addr, self.cpu.regs[attr])
        self.cpu.pc = _u32(self.cpu.pc + 2)

    def STSL_MACH(self, n: int):   self._stsl(n, 'mach')
    def STSL_MACL(self, n: int):   self._stsl(n, 'macl')
    def STSL_PR(self, n: int):     self._stsl(n, 'pr')

    def STSMPR(self, n: int):
        """STS.L PR, @-Rn (the original RuK opcode 257 alias)."""
        self._stsl(n, 'pr')
