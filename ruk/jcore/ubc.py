"""
UBC (User Break Controller) for the SH-4.

The UBC is a hardware debugger peripheral that monitors instruction
fetches and data accesses on the SH-4's buses.  When a configured
match condition is met (e.g. "instruction fetch from address X"), it
raises a UBC break exception -- the CPU vectors through DBR (if
CBCR.UBDE=1) or through VBR+0x100, with EXPEVT set to 0x1E0 (channel 0
match) or 0x1A0 (channel 1 match).

This makes the UBC an ideal hardware breakpoint mechanism: set a
channel's CAR to the address you want to break at, enable the channel,
and the CPU will trap when it tries to execute that instruction.

Layout (from gint/include/gint/mpu/ubc.h):

    Base address: 0xFF200000

    Channel 0 (offsets 0x00..0x0F):
      +0x00  CBR0   32-bit  Match condition setting
      +0x04  CRR0   32-bit  Match operation setting
      +0x08  CAR0   32-bit  Match address
      +0x0C  CAMR0  32-bit  Match address mask
      +0x10..0x1F  (pad, 0x10 bytes)

    Channel 1 (offsets 0x20..0x3F):
      +0x20  CBR1   32-bit  Match condition setting
      +0x24  CRR1   32-bit  Match operation setting
      +0x28  CAR1   32-bit  Match address
      +0x2C  CAMR1  32-bit  Match address mask
      +0x30  CDR1   32-bit  Match data (channel 1 only)
      +0x34  CDMR1  32-bit  Match data mask (channel 1 only)
      +0x38  CETR1  32-bit  Execution count break (channel 1 only)
      +0x3C..0x5BF  (pad, 0x5C4 bytes -- big gap!)

    Shared registers:
      +0x5C0  CCMFR  32-bit  Channel match flag (MF0=bit 0, MF1=bit 1)
      +0x5C1..0x5DB  (pad, 0x1C bytes)
      +0x5DC  CBCR   32-bit  Break control (UBDE=bit 31)

CBR bit layout (channel 0 -- channel 1 has additional data-value bits):
    bit 0     CE     Channel Enable
    bits 1-2  RW     Bus Command Select (1=read)
    bit 3     (reserved)
    bits 4-5  ID     Ins. Fetch / Operand Access Select (1=instruction fetch)
    bits 6-7  CD     Bus Select
    bits 8-11 (reserved)
    bits 12-14 SZ     Operand Size Select (0=any)
    bit 15     (reserved for ch0; DBE for ch1)
    bits 16-23 AIV    ASID Specify (unused -- AIE=0)
    bits 24-29 MFI    Match Flag Specify (unused -- MFE=0)
    bit 30     AIE    ASID Enable (0)
    bit 31     MFE    Match Flag Enable (0)

CRR bit layout:
    bit 0     BIE    Break Enable (1=break on match)
    bit 1     PCB    PC Break Select (0=before, 1=after instruction)
    bits 2-30 (reserved)
    bit 31    _1     Always set to 1 (we ignore this on read)

Reference:
  - gint/src/ubc/ubc.c (high-level UBC API)
  - gint/src/ubc/ubc.S (UBC debug handler assembly)
  - gint/include/gint/mpu/ubc.h (struct layout, bit fields)
  - hollyhock-3/demos/breakpoint_util/breakpoint_handler_stub.S (handler stub)
"""

from typing import Optional, Callable


# ===========================================================================
# Constants
# ===========================================================================

UBC_BASE = 0xFF200000
UBC_SIZE = 0x600   # covers everything from CBR0 through CBCR

# Channel register offsets (relative to UBC_BASE)
UBC_CBR0_OFF  = 0x00
UBC_CRR0_OFF  = 0x04
UBC_CAR0_OFF  = 0x08
UBC_CAMR0_OFF = 0x0C
# pad 0x10
UBC_CBR1_OFF  = 0x20
UBC_CRR1_OFF  = 0x24
UBC_CAR1_OFF  = 0x28
UBC_CAMR1_OFF = 0x2C
UBC_CDR1_OFF  = 0x30
UBC_CDMR1_OFF = 0x34
UBC_CETR1_OFF = 0x38
# pad 0x5C4
UBC_CCMFR_OFF = 0x5C0   # actually 0xFF200000 + 0x5C0 = 0xFF2005C0
UBC_CBCR_OFF  = 0x5DC   # 0xFF2005DC

# CBR bit fields
CBR_CE   = 1 << 0       # Channel Enable
CBR_RW_M = 0x06          # bits 1-2: Bus Command (1=read)
CBR_ID_M = 0x30          # bits 4-5: Ins. Fetch / Operand (1=instruction fetch)
CBR_ID_S = 4
CBR_SZ_M = 0x7000        # bits 12-14: Operand Size (0=any)
CBR_SZ_S = 12
CBR_CD_M = 0xC0          # bits 6-7: Bus Select

# CRR bit fields
CRR_BIE  = 1 << 0       # Break Enable
CRR_PCB  = 1 << 1       # PC Break Select (0=before, 1=after)

# CCMFR bit fields
CCMFR_MF0 = 1 << 0
CCMFR_MF1 = 1 << 1

# CBCR bit fields
CBCR_UBDE = 1 << 31     # User Break Debugging Support Enable

# EXPEVT codes for UBC breaks
UBC_EXPEVT_CH0 = 0x1E0   # channel 0 condition match
UBC_EXPEVT_CH1 = 0x1A0   # channel 1 condition match


# ===========================================================================
# UBC peripheral
# ===========================================================================

class UBCChannel:
    """A single UBC channel (0 or 1)."""

    def __init__(self, chan_id: int):
        self.chan_id = chan_id
        self.cbr = 0
        self.crr = 0
        self.car = 0
        self.camr = 0
        # Channel 1 only:
        self.cdr = 0
        self.cdmr = 0
        self.cetr = 0

    @property
    def enabled(self) -> bool:
        return bool(self.cbr & CBR_CE)

    @property
    def break_enabled(self) -> bool:
        return bool(self.crr & CRR_BIE)

    @property
    def match_instruction_fetch(self) -> bool:
        """True if this channel matches on instruction fetches."""
        return ((self.cbr >> CBR_ID_S) & 0x3) == 1

    @property
    def pc_break_after(self) -> bool:
        """True if the break should happen AFTER the instruction executes."""
        return bool(self.crr & CRR_PCB)

    def matches_address(self, addr: int) -> bool:
        """
        Check if `addr` matches this channel's address condition.
        CAMR is a mask: bits that are 0 in CAMR are compared, bits that
        are 1 are "don't care".
        """
        return (addr & ~self.camr) == (self.car & ~self.camr)

    def reset(self):
        self.cbr = 0
        self.crr = 0
        self.car = 0
        self.camr = 0
        self.cdr = 0
        self.cdmr = 0
        self.cetr = 0


class UBC:
    """
    SH-4 User Break Controller.

    Two channels (0 and 1) can independently monitor instruction fetches
    and data accesses.  When a match condition is met, the CPU takes a
    UBC break exception (see cpu.py's `_check_ubc()` and
    `_deliver_ubc_break()`).

    The host (CPU) calls `check_instruction_fetch(pc)` before each
    instruction; it returns the channel number (0 or 1) that matched, or
    None if no match.
    """

    def __init__(self):
        self.channels = [UBCChannel(0), UBCChannel(1)]
        self.ccmfr = 0   # Channel match flag register
        self.cbcr = 0    # Break control register

    @property
    def ubde(self) -> bool:
        """User Break Debugging Support Enable (CBCR.UBDE)."""
        return bool(self.cbcr & CBCR_UBDE)

    def check_instruction_fetch(self, pc: int, pcb_after: bool = False) -> Optional[int]:
        """
        Check if an instruction fetch at `pc` matches any enabled UBC
        channel that's configured for instruction-fetch matching.

        If `pcb_after` is True, only channels with PCB=1 (break after)
        are checked.  If False, only channels with PCB=0 (break before)
        are checked.

        Returns the channel index (0 or 1) if a match is found, else None.
        """
        for ch in self.channels:
            if not ch.enabled:
                continue
            if not ch.break_enabled:
                continue
            if not ch.match_instruction_fetch:
                continue
            # Only check channels whose PCB matches the requested mode
            if ch.pc_break_after != pcb_after:
                continue
            if ch.matches_address(pc):
                # Set the match flag
                if ch.chan_id == 0:
                    self.ccmfr |= CCMFR_MF0
                else:
                    self.ccmfr |= CCMFR_MF1
                return ch.chan_id
        return None

    def clear_match_flag(self, channel: int):
        """Clear the match flag for the given channel."""
        if channel == 0:
            self.ccmfr &= ~CCMFR_MF0 & 0xFFFFFFFF
        elif channel == 1:
            self.ccmfr &= ~CCMFR_MF1 & 0xFFFFFFFF

    def set_breakpoint(self, channel: int, addr: int,
                       break_after: bool = False):
        """
        Convenience method: configure a channel for an instruction-fetch
        breakpoint at `addr`.

        Mirrors gint's `ubc_set_breakpoint()` in src/ubc/ubc.c.
        """
        ch = self.channels[channel]
        ch.car = addr & 0xFFFFFFFF
        ch.camr = 0   # match all address bits
        ch.crr = CRR_BIE | (CRR_PCB if break_after else 0)
        # Match on instruction fetch, read cycle, any operand size
        ch.cbr = (1 << CBR_ID_S) | (1 << 1) | CBR_CE

    def disable_channel(self, channel: int):
        """Disable a UBC channel."""
        self.channels[channel].cbr &= ~CBR_CE & 0xFFFFFFFF

    # ---- MMIO read/write ----

    def _chan_offsets(self, ch: int):
        if ch == 0:
            return (UBC_CBR0_OFF, UBC_CRR0_OFF, UBC_CAR0_OFF, UBC_CAMR0_OFF)
        else:
            return (UBC_CBR1_OFF, UBC_CRR1_OFF, UBC_CAR1_OFF, UBC_CAMR1_OFF)

    def read8(self, addr: int) -> int:
        return self.read32(addr) & 0xFF

    def read16(self, addr: int) -> int:
        return self.read32(addr) & 0xFFFF

    def read32(self, addr: int) -> int:
        off = addr - UBC_BASE
        if off == UBC_CBR0_OFF:  return self.channels[0].cbr
        if off == UBC_CRR0_OFF:  return self.channels[0].crr
        if off == UBC_CAR0_OFF:  return self.channels[0].car
        if off == UBC_CAMR0_OFF: return self.channels[0].camr
        if off == UBC_CBR1_OFF:  return self.channels[1].cbr
        if off == UBC_CRR1_OFF:  return self.channels[1].crr
        if off == UBC_CAR1_OFF:  return self.channels[1].car
        if off == UBC_CAMR1_OFF: return self.channels[1].camr
        if off == UBC_CDR1_OFF:  return self.channels[1].cdr
        if off == UBC_CDMR1_OFF: return self.channels[1].cdmr
        if off == UBC_CETR1_OFF: return self.channels[1].cetr
        if off == UBC_CCMFR_OFF: return self.ccmfr
        if off == UBC_CBCR_OFF:  return self.cbcr
        return 0

    def write8(self, addr: int, val: int):
        self.write32(addr, val)

    def write16(self, addr: int, val: int):
        self.write32(addr, val)

    def write32(self, addr: int, val: int):
        val &= 0xFFFFFFFF
        off = addr - UBC_BASE
        if off == UBC_CBR0_OFF:
            self.channels[0].cbr = val
        elif off == UBC_CRR0_OFF:
            self.channels[0].crr = val
        elif off == UBC_CAR0_OFF:
            self.channels[0].car = val
        elif off == UBC_CAMR0_OFF:
            self.channels[0].camr = val
        elif off == UBC_CBR1_OFF:
            self.channels[1].cbr = val
        elif off == UBC_CRR1_OFF:
            self.channels[1].crr = val
        elif off == UBC_CAR1_OFF:
            self.channels[1].car = val
        elif off == UBC_CAMR1_OFF:
            self.channels[1].camr = val
        elif off == UBC_CDR1_OFF:
            self.channels[1].cdr = val
        elif off == UBC_CDMR1_OFF:
            self.channels[1].cdmr = val
        elif off == UBC_CETR1_OFF:
            self.channels[1].cetr = val
        elif off == UBC_CCMFR_OFF:
            # CCMFR is write-0-to-clear (writing 0 clears the flag, writing 1 has no effect)
            if (val & CCMFR_MF0) == 0:
                self.ccmfr &= ~CCMFR_MF0 & 0xFFFFFFFF
            if (val & CCMFR_MF1) == 0:
                self.ccmfr &= ~CCMFR_MF1 & 0xFFFFFFFF
        elif off == UBC_CBCR_OFF:
            self.cbcr = val

    # ---- introspection ----

    def dump(self) -> str:
        lines = ["UBC:"]
        for ch in self.channels:
            lines.append(
                f"  CH{ch.chan_id}: CE={int(ch.enabled)} BIE={int(ch.break_enabled)} "
                f"ID={int(ch.match_instruction_fetch)} PCB={int(ch.pc_break_after)} "
                f"CAR=0x{ch.car:08X} CAMR=0x{ch.camr:08X} "
                f"CBR=0x{ch.cbr:08X} CRR=0x{ch.crr:08X}"
            )
        lines.append(f"  CCMFR=0x{self.ccmfr:08X} CBCR=0x{self.cbcr:08X} (UBDE={int(self.ubde)})")
        return "\n".join(lines)
