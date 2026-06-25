"""
TMU (Timer Unit) and ETMU (Extra Timer Unit) for the Casio SH7305 / SH-4A.

This module emulates:
  * The 3 standard SH-4 TMU channels at 0xFFD80000.
  * The 6 Casio-extended ETMU channels at 0xA44D0000.

Reference sources:
  - Renesas HEW `IodllForTMU.pmi`:
      SH-4A_TMU_CH0  start=0xFFD80000  size=0x30   (standard TMU, 3 channels)
      SH-4A_TMU_CH3  start=0xFFDC0004  size=0x26   (extended TMU, 6 channels
                                                     on the standard SH-4A)
      SH4AL-DSP_TMU  start=0xFFD80000  size=0x30
      SH4AL-DSP_INTC start=0xA4700000  size=0x4    <- Casio's INTC lives here
      SH4AL-DSP_INTC2 start=0xA4080000 size=0xF1   <- Casio's INTC2 lives here
  - gint `inth-etmu.s`:
      RTCR4 = 0xA44D00BC  <- ETMU4 TCR register on Casio
  - gint `tmu.c`:
      etmu_event[6] = { 0x9e0, 0xc20, 0xc40, 0x900, 0xd00, 0xfa0 }
      ETMU struct layout: TSTR(8) | TCOR(32) | TCNT(32) | TCR(8)
      (with 1-byte alignment / holes in between, see etmu_t in gint/mpu/tmu.h)

The Casio SH7305 has the ETMU mapped at 0xA44D0000 (NOT 0xFFDC0004 as on a
vanilla SH-4A).  We adopt that mapping because RuK targets the Classpad II,
which uses the Casio part.

Per-channel register layout (ETMU, 16 bytes per channel, base 0xA44D0000):
    +0x00  TSTR   8-bit    bit0=STR (start), bits1-7 reserved
    +0x01  TCR    8-bit    bit0=UNIE, bit1=UNF (write-0-to-clear), bits2-7 reserved
    +0x02  (reserved, 2 bytes)
    +0x04  TCOR  32-bit    constant reload value (counts DOWN from this)
    +0x08  TCNT  32-bit    current counter
    +0x0C  (reserved, 4 bytes)

The 6 ETMU channels are NOT contiguous in physical memory on the Casio part:
they're spread across the 0xA44D0000-0xA44D00FF area, with each channel's
block starting at:
    ch0: 0xA44D0000   (RTSTR0 @ 0xA44D0000, RTCR0 @ 0xA44D0001, RTCOR0 @ 0xA44D0004, RTCNT0 @ 0xA44D0008)
    ch1: 0xA44D0010
    ch2: 0xA44D0020
    ch3: 0xA44D0030
    ch4: 0xA44D00B0   (matches the gint-reported RTCR4 = 0xA44D00BC = base + 0x0C...
                       actually gint's etmu_t has TSTR at offset 0, so 0xA44D00BC
                       would be RTCR4 if base=0xA44D00BC. But the libCPU73050
                       decomp shows the channels are at 0x20-byte stride and
                       the 0xA44D00BC value in gint is itself the TCR address,
                       i.e. ETMU4 base = 0xA44D00B8 with TCR at +0x04.
                       Hmm. Let's go with what libCPU73050 shows, since that's
                       the actual decomp of the Casio emulator: stride 0x20,
                       TSTR at +0x00, TCR at +0x01, TCOR at +0x04, TCNT at +0x08.)
    ch5: 0xA44D00D0

For the standard TMU (3 channels at 0xFFD80000), the layout is the
documented SH-4 one:
    0xFFD80000  TSTR  8-bit   bit0=STR0, bit1=STR1, bit2=STR2 (shared register)
    0xFFD80004  TCOR0 32-bit
    0xFFD80008  TCNT0 32-bit
    0xFFD8000C  TCR0  16-bit  bit0=UNF, bit1=UNIE, bits2-7=TPSC, bit8=ICPE, ...
    0xFFD80010  TCOR1 32-bit
    0xFFD80014  TCNT1 32-bit
    0xFFD80018  TCR1  16-bit
    0xFFD8001C  TCOR2 32-bit
    0xFFD80020  TCNT2 32-bit
    0xFFD80024  TCR2  16-bit

The TMU channels are clocked from Pphi (the peripheral clock) with a
prescaler selected by TCR.TPSC (Pphi/4, /16, /64, /256).  The ETMU channels
are clocked from the RTC clock (32768 Hz on real hardware).

Because RuK doesn't model Pphi or RTC clocks yet, we expose a
`tick(count)` method so the host can advance TMU/ETMU time explicitly.  The
test harness uses this to fire interrupts deterministically.
"""

from typing import Callable, Optional, List


# ===========================================================================
# Constants
# ===========================================================================
#
# Addresses are taken from cp-emu/src/hardware/timers/timers.c, which is
# the most authoritative open-source reference for the Casio SH7305's
# TMU/ETMU physical layout.  The Casio part DOESN'T match the vanilla
# SH-4 manual -- Casio moved TSTR to +0x04 of the TMU block (leaving
# +0x00..+0x03 reserved), and the ETMU channels live in a totally
# different place (0xA44D0030+) than the SH-4 manual's 0xFFDC0004.
#
# Standard SH-4 TMU (3 channels):
#   0xA4490000  reserved (4 bytes)
#   0xA4490004  TSTR      8-bit   bit n = STR for channel n
#   0xA4490008  TCOR0     32-bit
#   0xA449000C  TCNT0     32-bit
#   0xA4490010  TCR0      16-bit
#   0xA4490014  TCOR1     (channel 1, stride 0x0C from TCOR0)
#   ...
#   0xA4490020  TCOR2
#   0xA4490024  TCNT2
#   0xA4490028  TCR2
#
# Casio ETMU (6 channels), at 0x20 stride starting at 0xA44D0030:
#   0xA44D0030 + i*0x20  TSTR_i    8-bit   bit 0 = STR
#   0xA44D0034 + i*0x20  TCOR_i    32-bit
#   0xA44D0038 + i*0x20  TCNT_i    32-bit
#   0xA44D003C + i*0x20  TCR_i     8-bit   bit 0 = UNIE, bit 1 = UNF
# Verified: for i=4, TCR is at 0xA44D00BC, which matches gint's
# inth-etmu.s line 72 (.long 0xa44d00bc /* RTCR4 */).

# Standard SH-4 TMU -- Casio SH7305 physical address space
TMU_BASE      = 0xA4490000
TMU_TSTR      = 0xA4490004   # 8-bit, shared STR for ch0/1/2
TMU_CHAN_BASE = 0xA4490008   # base of channel 0's TCOR
TMU_CHAN_STRIDE = 0x0C       # 12 bytes per channel (TCOR/TCNT/TCR)
TMU_SIZE      = 0x30         # total span we map

# Compare Match Timer (CMT) addresses
CMT_CMSTR_ADDR = 0xA44A0000   # 16-bit
CMT_CMCSR_ADDR = 0xA44A0060   # 16-bit
CMT_CMCNT_ADDR = 0xA44A0064   # 16-bit (32-bit, but SH-4 CMT uses 16-bit)
CMT_CMCOR_ADDR = 0xA44A0068   # 16-bit
CMT_CMCSR_CMF  = 0x8000       # bit 15: compare match flag
CMT_CMCSR_OVF  = 0x4000       # bit 14: overflow flag
CMT_CMCSR_CMIE = 0x0020       # bit 5: compare match interrupt enable
CMT_CMCSR_AUTOSTOP = 0x0100   # bit 8: if 0, auto-stop on compare match
CMT_CMSTR_STR  = 0x20          # bit 5: compare match start

# CMT interrupt INTEVT code (from IntEvt2_Table / gint)
# On SH7305, CMT interrupt is at 0x400 (same priority group as TMU0,
# but different vector).  Actually, looking at gint and the Casio OS,
# the CMT uses INTEVT 0x400 for channel 0.
CMT_INTEVT = 0x400

# CMT clock divider ratios (from CMTDivRatio_Table in libCPU73050)
# Indexed by CMCSR bits 0-2:
#   0-3: disabled (0)
#   4:   divide by 8
#   5:   divide by 32
#   6:   divide by 128
#   7:   disabled (0)
CMT_DIV_RATIO = [0, 0, 0, 0, 8, 32, 128, 0]

# Casio SH7305 ETMU -- physical address space.
# 6 channels at 0x20 stride starting at 0xA44D0030.
ETMU_CHAN_COUNT = 6
ETMU_CHAN_BASE   = 0xA44D0030   # base of channel 0's TSTR
ETMU_CHAN_STRIDE = 0x20         # 32 bytes per channel
ETMU_BASE        = ETMU_CHAN_BASE
# Total span: 6 * 0x20 = 0xC0.  Round up to 0x100 for MMIO.
ETMU_REGION_SIZE = 0x100

# Per-channel register offsets (relative to channel base).
# Both TMU and ETMU use the same layout:
#   +0x00  TSTR  8-bit
#   +0x04  TCOR  32-bit
#   +0x08  TCNT  32-bit
#   +0x0C  TCR   16-bit (TMU) or 8-bit (ETMU)
# For the standard TMU, TSTR is shared (one register for all 3 channels),
# so only the TCOR/TCNT/TCR offsets apply per-channel.
ETMU_TSTR_OFF = 0x00   # 8-bit
ETMU_TCR_OFF  = 0x0C   # 8-bit
ETMU_TCOR_OFF = 0x04   # 32-bit
ETMU_TCNT_OFF = 0x08   # 32-bit

# INTEVT codes (the value written to the SH-4 INTEVT register when the IRQ
# is taken).  Source: gint tmu.c line 330 (which matches the
# IntEvt2_Table extraction from CPU73050.dll).
TMU_INTEVT  = [0x400, 0x420, 0x440]                              # TUNI0/1/2
ETMU_INTEVT = [0x9E0, 0xC20, 0xC40, 0x900, 0xD00, 0xFA0]         # ETMUn

# TSTR bit positions for the standard TMU (one bit per channel)
TMU_TSTR_STR0 = 1 << 0
TMU_TSTR_STR1 = 1 << 1
TMU_TSTR_STR2 = 1 << 2

# TCR bit positions (standard TMU, 16-bit register).
# Per the SH-4 hardware manual and gint's tmu.h struct:
#   bit 0-2: TPSC (timer prescaler)
#   bit 3:   reserved
#   bit 4-5: CKEG (clock edge)
#   bit 6:   reserved
#   bit 7:   UNIE (underflow interrupt enable)
#   bit 8:   UNF  (underflow flag, write-0-to-clear)
TMU_TCR_UNIE = 1 << 7     # underflow interrupt enable
TMU_TCR_UNF  = 1 << 8     # underflow flag (write-0-to-clear)

# ETMU TCR bit positions (8-bit register, per gint's inth-etmu.s):
#   bit 0: UNIE
#   bit 1: UNF (write-0-to-clear)
# (gint's inth-etmu.s tests bit 1 with `tst #0x02, r0` and clears it
#  with `and #0xfd, r0`, confirming UNF=bit 1.)
ETMU_TCR_UNIE = 1 << 0
ETMU_TCR_UNF  = 1 << 1


# ===========================================================================
# Channel model
# ===========================================================================

class TMUChannel:
    """
    A single standard SH-4 TMU channel.

    Has a 32-bit down-counter (TCNT) fed by a prescaled Pphi clock,
    a 32-bit reload register (TCOR), and a 16-bit control register (TCR).
    The STR bit lives in the shared TSTR register at 0xFFD80000.
    """

    def __init__(self, chan_id: int, intevt: int):
        self.chan_id = chan_id
        self.intevt = intevt

        self.tcor = 0xFFFFFFFF
        self.tcnt = 0xFFFFFFFF
        self.tcr = 0x0000         # UNF=0, UNIE=0, TPSC=0
        self.running = False      # mirror of TSTR bit
        self.prescaler_shift = 0  # TPSC: 0=>/4, 1=>/16, 2=>/64, 3=>/256
        self.prescaler_counter = 0  # counts Pphi ticks until next TCNT decrement
        self.irq_pending = False

    # ---- register access ----

    def read_tcor(self) -> int:
        return self.tcor & 0xFFFFFFFF

    def write_tcor(self, val: int):
        self.tcor = val & 0xFFFFFFFF

    def read_tcnt(self) -> int:
        return self.tcnt & 0xFFFFFFFF

    def write_tcnt(self, val: int):
        self.tcnt = val & 0xFFFFFFFF

    def read_tcr(self) -> int:
        return self.tcr & 0xFFFF

    def write_tcr(self, val: int):
        val &= 0xFFFF
        # UNF is write-0-to-clear; the rest is write-anywhere
        if (val & TMU_TCR_UNF) == 0:
            self.tcr &= ~TMU_TCR_UNF
            self.irq_pending = False
        # UNIE / TPSC / CKEG / ICPE are taken as-written (with mask of valid bits)
        self.tcr = (self.tcr & TMU_TCR_UNF) | (val & ~TMU_TCR_UNF)
        # decode TPSC (bits 0-2)
        tpsc = val & 0x07
        self.prescaler_shift = {0: 2, 1: 4, 2: 6, 3: 8, 4: 10, 5: 12, 6: 14, 7: 16}.get(tpsc, 2)

    # ---- ticking ----

    def tick(self, pphi_cycles: int):
        """
        Advance this channel by `pphi_cycles` Pphi ticks.  When the prescaler
        underflows, decrement TCNT; when TCNT underflows, set UNF, reload
        from TCOR, and raise an IRQ if UNIE is set.
        """
        if not self.running:
            return None

        # Add the cycles to the prescaler counter, decrementing TCNT for
        # each completed prescaler period.
        self.prescaler_counter += pphi_cycles
        prescaler_period = 1 << self.prescaler_shift
        decr = self.prescaler_counter // prescaler_period
        if decr == 0:
            return None
        self.prescaler_counter %= prescaler_period

        # Decrement TCNT, handling underflow
        old_tcnt = self.tcnt
        if decr >= self.tcnt:
            # underflow(s)
            self.tcnt = (self.tcnt - decr) & 0xFFFFFFFF
            # reload from TCOR (may underflow again if TCOR is small)
            # For simplicity, assume a single underflow per tick batch.
            self.tcnt = (self.tcor - (-self.tcnt & 0xFFFFFFFF)) & 0xFFFFFFFF
            self.tcr |= TMU_TCR_UNF
            self.irq_pending = bool(self.tcr & TMU_TCR_UNIE)
            return self.intevt if self.irq_pending else None
        else:
            self.tcnt -= decr
            return None


class ETMUChannel:
    """
    A single Casio ETMU channel.

    Per-channel register layout (offset from channel base):
        +0x00  TSTR  8-bit   bit0=STR
        +0x01  TCR   8-bit   bit0=UNIE, bit1=UNF (write-0-to-clear)
        +0x04  TCOR  32-bit  reload constant
        +0x08  TCNT  32-bit  current counter

    Clocked from the RTC clock (32768 Hz on real hardware).  The host
    advances time via `tick(rtc_cycles)`.
    """

    def __init__(self, chan_id: int, intevt: int, base_addr: int):
        self.chan_id = chan_id
        self.intevt = intevt
        self.base_addr = base_addr

        self.tstr = 0
        self.tcr = 0
        self.tcor = 0xFFFFFFFF
        self.tcnt = 0xFFFFFFFF
        self.irq_pending = False

    @property
    def running(self) -> bool:
        return bool(self.tstr & 0x01)

    # ---- per-register access ----

    def read_tstr(self) -> int:
        return self.tstr & 0xFF

    def write_tstr(self, val: int):
        self.tstr = val & 0x01   # only bit 0 is meaningful

    def read_tcr(self) -> int:
        return self.tcr & 0xFF

    def write_tcr(self, val: int):
        val &= 0xFF
        # UNF (bit 1) is write-0-to-clear
        if (val & ETMU_TCR_UNF) == 0:
            self.tcr &= ~ETMU_TCR_UNF
            self.irq_pending = False
        self.tcr = (self.tcr & ETMU_TCR_UNF) | (val & ~ETMU_TCR_UNF)

    def read_tcor(self) -> int:
        return self.tcor & 0xFFFFFFFF

    def write_tcor(self, val: int):
        self.tcor = val & 0xFFFFFFFF

    def read_tcnt(self) -> int:
        return self.tcnt & 0xFFFFFFFF

    def write_tcnt(self, val: int):
        self.tcnt = val & 0xFFFFFFFF

    # ---- ticking ----

    def tick(self, rtc_cycles: int):
        if not self.running:
            return None

        old_tcnt = self.tcnt
        if rtc_cycles >= self.tcnt:
            # underflow
            self.tcnt = (self.tcnt - rtc_cycles) & 0xFFFFFFFF
            self.tcnt = (self.tcor - (-self.tcnt & 0xFFFFFFFF)) & 0xFFFFFFFF
            self.tcr |= ETMU_TCR_UNF
            self.irq_pending = bool(self.tcr & ETMU_TCR_UNIE)
            return self.intevt if self.irq_pending else None
        else:
            self.tcnt -= rtc_cycles
            return None


# ===========================================================================
# Top-level TMU+ETMU peripheral
# ===========================================================================

class TMU:
    """
    Combined TMU (3 standard channels) + ETMU (6 Casio channels) peripheral.

    Plug into RuK's MemoryMap by calling `attach(memory_map)` and feed time
    via `tick(pphi_cycles, rtc_cycles)` from your main loop or test harness.
    """

    def __init__(self):
        # Standard TMU
        self.tmu_channels: List[TMUChannel] = [
            TMUChannel(i, TMU_INTEVT[i]) for i in range(3)
        ]
        self.tstr = 0  # shared STR register for standard TMU

        # Casio ETMU.  Channel i's base is at ETMU_CHAN_BASE + i*ETMU_CHAN_STRIDE.
        self.etmu_channels: List[ETMUChannel] = [
            ETMUChannel(i, ETMU_INTEVT[i],
                        ETMU_CHAN_BASE + i * ETMU_CHAN_STRIDE)
            for i in range(ETMU_CHAN_COUNT)
        ]

        # Compare Match Timer (CMT) at 0xA44A0000
        # CMSTR at 0xA44A0000 (16-bit), CMCSR at 0xA44A0060 (16-bit),
        # CMCNT at 0xA44A0064 (32-bit), CMCOR at 0xA44A0068 (32-bit)
        self.cmstr = 0     # bit 5 = compare match enable
        self.cmcsr = 0     # bit 15 = compare match flag, bit 14 = overflow
        self.cmcnt = 0
        self.cmcor = 0

        # Callback the host can register to deliver IRQs to the CPU/INTC.
        # Signature: on_irq(intevt_code: int) -> None
        self.on_irq: Optional[Callable[[int], None]] = None

    # ---- address helpers ----

    @staticmethod
    def _tmu_chan_addr(chan: int, offset: int) -> int:
        """Compute the physical address of a TMU channel register."""
        return TMU_CHAN_BASE + chan * TMU_CHAN_STRIDE + offset

    # ---- IRQ delivery ----

    def _raise_irq(self, intevt: int):
        if self.on_irq is not None:
            self.on_irq(intevt)

    # ---- ticking (called by host) ----

    def tick(self, pphi_cycles: int = 0, rtc_cycles: int = 0):
        """
        Advance all running timers.  Calls `on_irq(intevt)` for each pending
        interrupt, in priority order (TMU0 first, then TMU1, TMU2, then the
        6 ETMUs in channel order).
        """
        # Standard TMU
        for ch in self.tmu_channels:
            intevt = ch.tick(pphi_cycles)
            if intevt is not None:
                self._raise_irq(intevt)
        # Casio ETMU
        for ch in self.etmu_channels:
            intevt = ch.tick(rtc_cycles)
            if intevt is not None:
                self._raise_irq(intevt)

    def tick_cmt(self, cycles: int = 1):
        """Advance the Compare Match Timer by `cycles` ticks.

        Per the CPU_CMT_Check decomp from libCPU73050:
          1. CMCNT increments by 1 each tick
          2. When CMCNT reaches CMCOR, CMF (bit 15) is set in CMCSR
          3. If CMIE (bit 5) is set, a CMT interrupt is raised
          4. If AUTOSTOP bit (bit 8) is NOT set, STR (bit 5 of CMSTR)
             is cleared, stopping the CMT
          5. CMCNT resets to 0 after a compare match

        CMCNT and CMCOR are 16-bit registers (0xFFFF max).
        """
        if not (self.cmstr & CMT_CMSTR_STR):
            return   # CMT not running
        for _ in range(cycles):
            self.cmcnt = (self.cmcnt + 1) & 0xFFFF  # 16-bit
            if self.cmcnt == 0:
                self.cmcsr |= CMT_CMCSR_OVF
            # Compare match: when CMCNT reaches CMCOR
            if self.cmcnt == self.cmcor or self.cmcor == 0:
                self.cmcsr |= CMT_CMCSR_CMF
                self.cmcnt = 0
                # Raise interrupt if CMIE is set
                if self.cmcsr & CMT_CMCSR_CMIE:
                    self._raise_irq(CMT_INTEVT)
                # Auto-stop: if bit 8 (AUTOSTOP) is NOT set, clear STR
                if not (self.cmcsr & CMT_CMCSR_AUTOSTOP):
                    self.cmstr &= ~CMT_CMSTR_STR & 0xFFFF

    # ---- MMIO read/write ----

    def read8(self, addr: int) -> int:
        if addr == TMU_TSTR:
            return self.tstr & 0xFF
        # CMT registers (8-bit access)
        if addr == CMT_CMSTR_ADDR:
            return self.cmstr & 0xFF
        if addr == CMT_CMSTR_ADDR + 1:
            return (self.cmstr >> 8) & 0xFF
        if addr == CMT_CMCSR_ADDR:
            return self.cmcsr & 0xFF
        if addr == CMT_CMCSR_ADDR + 1:
            return (self.cmcsr >> 8) & 0xFF
        # ETMU TSTR / TCR (8-bit registers)
        for ch in self.etmu_channels:
            if addr == ch.base_addr + ETMU_TSTR_OFF:
                return ch.read_tstr()
            if addr == ch.base_addr + ETMU_TCR_OFF:
                return ch.read_tcr()
        return 0x00

    def read16(self, addr: int) -> int:
        # Standard TMU TCR0/1/2 are 16-bit, at offset 0x08 of each channel
        # (channel base = TCOR, so TCR = base + 0x08).
        for i, ch in enumerate(self.tmu_channels):
            if addr == self._tmu_chan_addr(i, 0x08):
                return ch.read_tcr()
        # CMT registers
        if addr == CMT_CMSTR_ADDR:
            return self.cmstr & 0xFFFF
        if addr == CMT_CMCSR_ADDR:
            return self.cmcsr & 0xFFFF
        # CMCNT and CMCOR can also be read as 16-bit
        if addr == CMT_CMCNT_ADDR:
            return self.cmcnt & 0xFFFF
        if addr == CMT_CMCNT_ADDR + 2:
            return (self.cmcnt >> 16) & 0xFFFF
        if addr == CMT_CMCOR_ADDR:
            return self.cmcor & 0xFFFF
        if addr == CMT_CMCOR_ADDR + 2:
            return (self.cmcor >> 16) & 0xFFFF
        return 0x0000

    def read32(self, addr: int) -> int:
        # Standard TMU TCOR/TCNT (at offsets 0x00 and 0x04 of each channel)
        for i, ch in enumerate(self.tmu_channels):
            if addr == self._tmu_chan_addr(i, 0x00):
                return ch.read_tcor()
            if addr == self._tmu_chan_addr(i, 0x04):
                return ch.read_tcnt()
        # ETMU TCOR/TCNT
        for ch in self.etmu_channels:
            if addr == ch.base_addr + ETMU_TCOR_OFF:
                return ch.read_tcor()
            if addr == ch.base_addr + ETMU_TCNT_OFF:
                return ch.read_tcnt()
        # CMT registers (32-bit)
        if addr == CMT_CMCNT_ADDR:
            return self.cmcnt & 0xFFFFFFFF
        if addr == CMT_CMCOR_ADDR:
            return self.cmcor & 0xFFFFFFFF
        return 0x00000000

    def write8(self, addr: int, val: int):
        val &= 0xFF
        if addr == TMU_TSTR:
            self._write_tstr(val)
            return
        # CMT registers can be written as 8-bit too
        if addr == CMT_CMSTR_ADDR:
            self.cmstr = (self.cmstr & 0xFF00) | val
            return
        if addr == CMT_CMSTR_ADDR + 1:
            self.cmstr = (self.cmstr & 0x00FF) | (val << 8)
            return
        if addr == CMT_CMCSR_ADDR:
            self.cmcsr = (self.cmcsr & 0xFF00) | val
            return
        if addr == CMT_CMCSR_ADDR + 1:
            self.cmcsr = (self.cmcsr & 0x00FF) | (val << 8)
            return
        for ch in self.etmu_channels:
            if addr == ch.base_addr + ETMU_TSTR_OFF:
                ch.write_tstr(val)
                return
            if addr == ch.base_addr + ETMU_TCR_OFF:
                ch.write_tcr(val)
                return

    def write16(self, addr: int, val: int):
        val &= 0xFFFF
        for i, ch in enumerate(self.tmu_channels):
            if addr == self._tmu_chan_addr(i, 0x08):
                ch.write_tcr(val)
                return
        # Tolerate 16-bit writes to TSTR (8-bit register)
        if addr == TMU_TSTR:
            self._write_tstr(val & 0xFF)
            return
        # CMT registers (16-bit)
        if addr == CMT_CMSTR_ADDR:
            self.cmstr = val
            return
        if addr == CMT_CMCSR_ADDR:
            # CMF and OVF are write-0-to-clear
            if (val & CMT_CMCSR_CMF) == 0:
                self.cmcsr &= ~CMT_CMCSR_CMF & 0xFFFF
            if (val & CMT_CMCSR_OVF) == 0:
                self.cmcsr &= ~CMT_CMCSR_OVF & 0xFFFF
            self.cmcsr = (self.cmcsr & (CMT_CMCSR_CMF | CMT_CMCSR_OVF)) | (val & ~(CMT_CMCSR_CMF | CMT_CMCSR_OVF) & 0xFFFF)
            return
        # CMCNT and CMCOR can also be written as 16-bit (low half)
        if addr == CMT_CMCNT_ADDR:
            self.cmcnt = (self.cmcnt & 0xFFFF0000) | (val & 0xFFFF)
            return
        if addr == CMT_CMCNT_ADDR + 2:
            self.cmcnt = (self.cmcnt & 0x0000FFFF) | ((val & 0xFFFF) << 16)
            return
        if addr == CMT_CMCOR_ADDR:
            self.cmcor = (self.cmcor & 0xFFFF0000) | (val & 0xFFFF)
            return
        if addr == CMT_CMCOR_ADDR + 2:
            self.cmcor = (self.cmcor & 0x0000FFFF) | ((val & 0xFFFF) << 16)
            return

    def write32(self, addr: int, val: int):
        val &= 0xFFFFFFFF
        for i, ch in enumerate(self.tmu_channels):
            if addr == self._tmu_chan_addr(i, 0x00):    # TCOR
                ch.write_tcor(val)
                return
            if addr == self._tmu_chan_addr(i, 0x04):    # TCNT
                ch.write_tcnt(val)
                return
            # Some programs (and our test) accidentally use MOV.L (32-bit)
            # to write the 16-bit TCR.  Tolerate this by treating a 32-bit
            # write to the TCR address as a 16-bit write (low 16 bits).
            if addr == self._tmu_chan_addr(i, 0x08):    # TCR (16-bit)
                ch.write_tcr(val & 0xFFFF)
                return
        # Tolerate 32-bit writes to TSTR (8-bit register)
        if addr == TMU_TSTR:
            self._write_tstr(val & 0xFF)
            return
        for ch in self.etmu_channels:
            if addr == ch.base_addr + ETMU_TCOR_OFF:
                ch.write_tcor(val)
                return
            if addr == ch.base_addr + ETMU_TCNT_OFF:
                ch.write_tcnt(val)
                return
        # CMT registers (32-bit)
        if addr == CMT_CMCNT_ADDR:
            self.cmcnt = val
            return
        if addr == CMT_CMCOR_ADDR:
            self.cmcor = val
            return

    def _write_tstr(self, val: int):
        old = self.tstr
        self.tstr = val & 0x07   # only bits 0/1/2 are STR0/1/2
        # Update running flags
        for i, ch in enumerate(self.tmu_channels):
            was_running = ch.running
            ch.running = bool(self.tstr & (1 << i))
            if ch.running and not was_running:
                # Restart: reset prescaler counter
                ch.prescaler_counter = 0

    # ---- introspection (for tests/debugging) ----

    def dump(self) -> str:
        lines = []
        lines.append(f"TMU  TSTR=0x{self.tstr:02X}")
        for i, ch in enumerate(self.tmu_channels):
            lines.append(
                f"  TMU{i} running={int(ch.running)} TCOR=0x{ch.tcor:08X} "
                f"TCNT=0x{ch.tcnt:08X} TCR=0x{ch.tcr:04X} "
                f"(UNIE={int(bool(ch.tcr & TMU_TCR_UNIE))} "
                f"UNF={int(bool(ch.tcr & TMU_TCR_UNF))})"
            )
        lines.append(f"ETMU (Casio SH7305) -- {ETMU_CHAN_COUNT} channels:")
        for ch in self.etmu_channels:
            lines.append(
                f"  ETMU{ch.chan_id} @0x{ch.base_addr:08X} "
                f"TSTR=0x{ch.tstr:02X} TCR=0x{ch.tcr:02X} "
                f"TCOR=0x{ch.tcor:08X} TCNT=0x{ch.tcnt:08X} "
                f"(STR={ch.running} UNIE={int(bool(ch.tcr & ETMU_TCR_UNIE))} "
                f"UNF={int(bool(ch.tcr & ETMU_TCR_UNF))})"
            )
        return "\n".join(lines)
