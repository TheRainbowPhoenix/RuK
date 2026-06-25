"""
CPG (Clock Pulse Generator) and Power (MSTPCR) for the Casio SH7305.

CPG at 0xA4150000 controls the PLL and clock dividers that generate
Pphi (peripheral clock), Iphi (CPU clock), and other system clocks.

Power at 0xA4150030 (MSTPCR0) and 0xA4150038 (MSTPCR2) gates clock
to individual peripherals.

Register layout (from cp-emu/src/hardware/power/power.c and gint/mpu/cpg.h):
  CPG:
    +0x000 FRQCR   (16-bit)  Frequency Control Register
    +0x010 FRQCRA  (32-bit)  Frequency Control Register A
    +0x014 FRQCRB  (32-bit)  Frequency Control Register B
    +0x020 VCLKCR  (16-bit)  VCLK divider
    +0x024 SCLKCR  (16-bit)  SCLK divider
    +0x028 PLLCR   (16-bit)  PLL Control
    +0x030 FLLFRQ  (32-bit)  FLL Frequency
    +0x050 LSTATS  (32-bit)  PLL lock status

  Power (MSTPCR):
    +0x030 MSTPCR0 (32-bit at 0xA4150030)  Module Stop Control 0
    +0x034 MSTPCR1 (32-bit at 0xA4150034)  Module Stop Control 1
    +0x038 MSTPCR2 (32-bit at 0xA4150038)  Module Stop Control 2

  Also:
    0xA4150020 = PLL0 (16-bit) -- older PLL control
    0xA4150024 = PLL1 (16-bit)
    0xA4150028 = PLL2 (16-bit)

MSTPCR0 bits (from cp-emu/gint):
  bit 0: TMU0 (0=running, 1=stopped)
  bit 1: TMU1
  bit 2: TMU2
  bit 19: UDB (UBC) -- must be 0 for UBC to work
  bit 22: SPU

MSTPCR2 bits:
  bit 0: SCIF (serial)
  bit 1: RTC
  bit 3: KEYSC
"""

CPG_BASE = 0xA4150000
CPG_SIZE = 0x100   # covers all CPG + power registers

# Register offsets
CPG_FRQCR_OFF   = 0x000
CPG_FRQCRA_OFF  = 0x010
CPG_FRQCRB_OFF  = 0x014
CPG_PLL0_OFF    = 0x020
CPG_PLL1_OFF    = 0x024
CPG_PLL2_OFF    = 0x028
CPG_FLLFRQ_OFF  = 0x030
CPG_MSTPCR0_OFF = 0x030  # Note: overlaps with FLLFRQ? No -- MSTPCR0 is at 0xA4150030
# Actually, from cp-emu:
#   defineReg("PLL0", PLL0, 0xa4150020)
#   defineReg("PLL1", PLL1, 0xa4150024)
#   defineReg("PLL2", PLL2, 0xa4150028)
#   defineReg("FLLFRQ", FLLFRQ, 0xa4150030)
#   defineReg("MSTPCR0", MSTPCR0, 0xa4150030)  -- same address? No, that can't be right.
# Let me check cp-emu more carefully:
#   defineReg("Module stop control register 0", MSTPCR0, 0xa4150030)
#   defineReg("Module stop control register 2", MSTPCR2, 0xa4150038)
# So MSTPCR0 is at 0xA4150030, same as FLLFRQ? That seems like a bug in cp-emu.
# Actually on the SH7305, FLLFRQ might be at a different address.
# Let's just use a simple register file and let the OS write whatever it wants.


class CPG:
    """
    Clock Pulse Generator + Power (MSTPCR) peripheral.

    Simple register file.  The OS writes FRQCR and MSTPCR during boot.
    We store all values and let peripherals query them if needed.
    """

    def __init__(self):
        self._regs = bytearray(CPG_SIZE)
        # Default MSTPCR0: all peripherals stopped except TMU
        # Default MSTPCR2: all stopped
        # The OS will set these during boot.

    def read8(self, addr):
        offset = (addr - CPG_BASE) & 0xFF
        return self._regs[offset]

    def read16(self, addr):
        offset = (addr - CPG_BASE) & 0xFF
        if offset + 2 <= len(self._regs):
            return int.from_bytes(self._regs[offset:offset+2], 'big')
        return 0

    def read32(self, addr):
        offset = (addr - CPG_BASE) & 0xFF
        if offset + 4 <= len(self._regs):
            return int.from_bytes(self._regs[offset:offset+4], 'big')
        return 0

    def write8(self, addr, val):
        offset = (addr - CPG_BASE) & 0xFF
        if offset < len(self._regs):
            self._regs[offset] = val & 0xFF

    def write16(self, addr, val):
        offset = (addr - CPG_BASE) & 0xFF
        if offset + 2 <= len(self._regs):
            self._regs[offset:offset+2] = (val & 0xFFFF).to_bytes(2, 'big')

    def write32(self, addr, val):
        offset = (addr - CPG_BASE) & 0xFF
        if offset + 4 <= len(self._regs):
            self._regs[offset:offset+4] = (val & 0xFFFFFFFF).to_bytes(4, 'big')

    @property
    def mstpcr0(self):
        return self.read32(CPG_BASE + 0x30)

    @property
    def mstpcr2(self):
        return self.read32(CPG_BASE + 0x38)
