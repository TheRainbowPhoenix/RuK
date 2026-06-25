"""
RTC (Real-Time Clock) for the Casio SH7305.

Layout (from gint/include/gint/mpu/rtc.h and cp-emu/src/hardware/rtc/rtc.c):

    Base address: 0xA413FEC0 on SH7305 (0xFFFFFEC0 on SH7705)

    +0x00  R64CNT   8-bit   64-Hz counter (actually 128 Hz; rolls over at 128)
    +0x01  (pad)
    +0x02  RSECCNT  8-bit   Seconds (BCD, 2-digit packed in one byte with 1-byte pad)
    +0x04  RMINCNT  8-bit   Minutes (BCD)
    +0x06  RHRCNT   8-bit   Hours (BCD, 24-hour)
    +0x08  RWKCNT   8-bit   Day of week (0=Sun, 1=Mon, ..., 6=Sat)
    +0x09  (pad)
    +0x0A  RDAYCNT  8-bit   Day of month (BCD)
    +0x0C  RMONCNT  8-bit   Month (BCD)
    +0x0E  RYRCNT   16-bit  Year (BCD, 4-digit)
    +0x10..0x1B  alarm registers (RSECAR, RMINAR, RHRAR, RWKAR, RDAYAR, RMONAR)
    +0x1C  RCR1     8-bit   Control register 1
    +0x1D  (pad)
    +0x1E  RCR2     8-bit   Control register 2
    +0x1F  (pad)
    +0x20  RYRAR    16-bit  Year alarm
    +0x22  (pad x2)
    +0x24  RCR3     8-bit   Control register 3

Note: The BCD counters (RSECCNT, RMINCNT, RHRCNT, RDAYCNT, RMONCNT, RYRCNT)
use packed BCD: the low nibble holds the ones digit, the high nibble holds
the tens digit.  So 0x59 = 59 seconds.

The RTC ticks at 128 Hz.  Each tick:
  1. R64CNT++ (modulo 128)
  2. When R64CNT rolls over to 0:
     - Set RCR1.CF (carry flag)
     - Increment RSECCNT (BCD)
     - When seconds reaches 60: reset to 0, increment minutes
     - When minutes reaches 60: reset to 0, increment hours
     - When hours reaches 24: reset to 0, increment day-of-week (mod 7)
       and day-of-month (BCD), with proper month/year rollover
     - Set RCR2.PEF (periodic interrupt flag) at the rate selected by RCR2.PES
     - If RCR1.CIE: raise carry interrupt (INTEVT 0x4C0)
     - If RCR1.AIE and alarm matches: raise alarm interrupt (INTEVT 0x4E0)

The periodic interrupt (RCR2.PES) fires at one of 8 selectable rates:
  0 = disabled, 1 = 1/256 Hz, 2 = 1/64 Hz, 3 = 1/16 Hz, 4 = 1/4 Hz,
  5 = 1/2 Hz, 6 = 1 Hz, 7 = 2 Hz.

Reference:
  - gint/src/rtc/rtc.c (BCD conversion, periodic interrupt handling)
  - cp-emu/src/hardware/rtc/rtc.c (RTC tick logic, register addresses)
  - gint/include/gint/mpu/rtc.h (struct layout, bit fields)
"""

import calendar
import datetime
from typing import Callable, Optional


# ===========================================================================
# Constants
# ===========================================================================

RTC_BASE = 0xA413FEC0
RTC_SIZE = 0x30   # covers R64CNT through RCR3

# Register offsets (relative to RTC_BASE)
RTC_R64CNT  = 0x00
RTC_RSECCNT = 0x02
RTC_RMINCNT = 0x04
RTC_RHRCNT  = 0x06
RTC_RWKCNT  = 0x08
RTC_RDAYCNT = 0x0A
RTC_RMONCNT = 0x0C
RTC_RYRCNT  = 0x0E
RTC_RSECAR  = 0x10
RTC_RMINAR  = 0x12
RTC_RHRAR   = 0x14
RTC_RWKAR   = 0x16
RTC_RDAYAR  = 0x18
RTC_RMONAR  = 0x1A
RTC_RCR1    = 0x1C
RTC_RCR2    = 0x1E
RTC_RYRAR   = 0x20
RTC_RCR3    = 0x24

# RCR1 bit positions
RCR1_CF  = 1 << 7   # Carry flag (set when any time register carries)
RCR1_CIE = 1 << 4   # Carry interrupt enable
RCR1_AIE = 1 << 3   # Alarm interrupt enable
RCR1_AF  = 1 << 0   # Alarm flag

# RCR2 bit positions (per gint/include/gint/mpu/rtc.h):
#   bit 7: PEF (periodic interrupt flag)
#   bits 4-6: PES (periodic interrupt interval select)
#   bit 3: (reserved)
#   bit 2: ADJ (30-second adjustment)
#   bit 1: RESET (reset trigger)
#   bit 0: START (start bit)
RCR2_PEF   = 1 << 7   # Periodic interrupt flag
RCR2_PES   = 0x70     # Periodic interrupt interval select (bits 4-6, mask)
RCR2_PES_S = 4        # shift for PES field
RCR2_ADJ   = 1 << 2   # 30-second adjustment
RCR2_RESET = 1 << 1   # Reset trigger (writing 1 resets all counters to 0)
RCR2_START = 1 << 0   # Start bit (1 = RTC running, 0 = stopped)

# INTEVT codes
RTC_INTEVT_PRI   = 0x4A0   # periodic interrupt
RTC_INTEVT_CARRY = 0x4C0   # carry interrupt
RTC_INTEVT_ALARM = 0x4E0   # alarm interrupt

# Periodic interrupt rates (Hz).  Index = PES field value (1..7).
RTC_PERIODIC_RATES = [0, 1/256, 1/64, 1/16, 1/4, 1/2, 1, 2]


# ===========================================================================
# BCD helpers (from gint/src/rtc/rtc.c)
# ===========================================================================

def bcd8_to_int(bcd: int) -> int:
    """Convert a packed-BCD byte to an integer. 0x59 -> 59."""
    return (bcd & 0x0F) + 10 * ((bcd >> 4) & 0x0F)


def int_to_bcd8(n: int) -> int:
    """Convert an integer to a packed-BCD byte. 59 -> 0x59."""
    n %= 100
    return ((n // 10) << 4) | (n % 10)


def bcd16_to_int(bcd: int) -> int:
    """Convert a packed-BCD 16-bit value to an integer. 0x2010 -> 2010."""
    return (bcd & 0xF) + 10 * ((bcd >> 4) & 0xF) + 100 * ((bcd >> 8) & 0xF) + 1000 * ((bcd >> 12) & 0xF)


def int_to_bcd16(n: int) -> int:
    """Convert an integer to a packed-BCD 16-bit value. 2010 -> 0x2010."""
    n %= 10000
    return (int_to_bcd8(n // 100) << 8) | int_to_bcd8(n % 100)


# ===========================================================================
# RTC peripheral
# ===========================================================================

class RTC:
    """
    Casio SH7305 Real-Time Clock.

    The host advances time by calling `tick_128hz(cycles=128)` once per
    second (or in smaller chunks).  Each tick increments R64CNT; when it
    rolls over, the date/time counters advance and the carry/periodic/alarm
    interrupts may fire.
    """

    def __init__(self, init_to_system_time: bool = True):
        """Initialize the RTC.

        Args:
            init_to_system_time: If True (default), populate the date/time
                counters with the current system time.  This is important
                because the Casio OS boot code polls R64CNT waiting for it
                to change, and also reads the date/time registers during
                initialization.  Starting with the system time ensures
                the OS sees meaningful values instead of all-zeros.

                If False, the RTC starts at the cp-emu defaults
                (2010-01-01 00:00:00).
        """
        if init_to_system_time:
            self._init_to_system_time()
        else:
            self._init_to_defaults()

        # Alarm registers
        self.rsecar = 0
        self.rminar = 0
        self.rhrar  = 0
        self.rwkar  = 0
        self.rdayar = 0
        self.rmonar = 0
        self.ryrar  = 0

        # Control registers
        self.rcr1 = 0
        self.rcr2 = 0   # START=0 by default (RTC stopped until started)
        self.rcr3 = 0

        # Periodic interrupt tracking
        self._periodic_counter = 0   # counts 128 Hz ticks since last periodic IRQ

        # Callback for delivering IRQs to the INTC
        self.on_irq: Optional[Callable[[int], None]] = None

    def _init_to_defaults(self):
        """Initialize counters to the cp-emu defaults (2010-01-01 00:00:00)."""
        # Time counters (all in BCD except R64CNT and RWKCNT)
        self.r64cnt  = 0           # 0..127 (128 Hz counter)
        self.rseccnt = int_to_bcd8(0)
        self.rmincnt = int_to_bcd8(0)
        self.rhrcnt  = int_to_bcd8(0)
        self.rwkcnt  = 0           # 0=Sun..6=Sat (plain binary, not BCD)
        self.rdaycnt = int_to_bcd8(1)    # default to day 1
        self.rmoncnt = int_to_bcd8(1)    # default to month 1
        self.ryrcnt  = int_to_bcd16(2010)  # cp-emu default

    def _init_to_system_time(self):
        """Initialize counters to the current system time.

        This populates the BCD date/time registers (RSECCNT, RMINCNT,
        RHRCNT, RWKCNT, RDAYCNT, RMONCNT, RYRCNT) with the host's
        current local time.  R64CNT starts at a non-zero value (so the
        OS polling loop sees an immediate change on the first read).
        """
        now = datetime.datetime.now()
        # Python's weekday(): Monday=0..Sunday=6
        # SH-4 RTC RWKCNT: Sunday=0..Saturday=6
        sh_wkday = (now.weekday() + 1) % 7   # Mon=1, Tue=2, ..., Sun=0

        self.r64cnt  = (now.microsecond // (1_000_000 // 128)) & 0x7F
        self.rseccnt = int_to_bcd8(now.second)
        self.rmincnt = int_to_bcd8(now.minute)
        self.rhrcnt  = int_to_bcd8(now.hour)
        self.rwkcnt  = sh_wkday
        self.rdaycnt = int_to_bcd8(now.day)
        self.rmoncnt = int_to_bcd8(now.month)
        self.ryrcnt  = int_to_bcd16(now.year)

    # ---- IRQ delivery ----
    def _raise_irq(self, intevt: int):
        if self.on_irq is not None:
            self.on_irq(intevt)

    # ---- BCD increment helper ----
    @staticmethod
    def _bcd8_inc(val: int) -> int:
        """Increment a packed-BCD byte by 1 (with no carry-out check)."""
        return int_to_bcd8(bcd8_to_int(val) + 1)

    # ---- Ticking (called by host) ----
    def tick_128hz(self, cycles: int = 1):
        """
        Advance the RTC by `cycles` 128-Hz ticks.

        One tick = 1/128 second.  The standard calling rate is 128
        ticks per second (i.e. once per ~7.8 ms).

        The R64CNT counter (64-Hz / 128-Hz divider) ALWAYS advances,
        regardless of the RCR2.START bit -- it's a free-running counter
        that the OS polls to detect elapsed time.  The date/time
        registers (RSECCNT, RMINCNT, etc.) only advance when START=1.

        This is important for OS boot: the Casio OS polls R64CNT
        waiting for it to change BEFORE it sets RCR2.START.  If we
        gate R64CNT on START, the OS hangs forever in the polling loop.
        """
        for _ in range(cycles):
            self._tick_one()

    def _tick_one(self):
        """Advance the RTC by one 128-Hz tick.

        R64CNT always advances (free-running).  The date/time registers
        only advance when RCR2.START=1.
        """
        # R64CNT always advances (it's a free-running 128-Hz counter)
        self.r64cnt = (self.r64cnt + 1) & 0xFF

        # Check periodic interrupt (always checked, regardless of START)
        self._check_periodic()

        if self.r64cnt < 128:
            # Still within the same second
            return

        # R64CNT rolled over: a new second has begun.
        # Set the carry flag (always, even if START=0 -- the carry flag
        # indicates R64CNT wrapped, not that the time advanced).
        self.r64cnt = 0
        # Set the carry flag
        self.rcr1 |= RCR1_CF

        # Only advance the date/time registers if START=1
        if not (self.rcr2 & RCR2_START):
            # START=0: RTC time is stopped, but R64CNT still ticks.
            # Still fire the carry interrupt if RCR1.CIE is set.
            if self.rcr1 & RCR1_CIE:
                self._raise_irq(RTC_INTEVT_CARRY)
            return

        # Increment seconds
        sec = bcd8_to_int(self.rseccnt) + 1
        if sec >= 60:
            self.rseccnt = int_to_bcd8(0)
            # Increment minutes
            minute = bcd8_to_int(self.rmincnt) + 1
            if minute >= 60:
                self.rmincnt = int_to_bcd8(0)
                # Increment hours
                hour = bcd8_to_int(self.rhrcnt) + 1
                if hour >= 24:
                    self.rhrcnt = int_to_bcd8(0)
                    # Increment day of week (0..6, plain binary)
                    self.rwkcnt = (self.rwkcnt + 1) % 7
                    # Increment day of month, with month/year rollover
                    self._increment_day()
                else:
                    self.rhrcnt = int_to_bcd8(hour)
            else:
                self.rmincnt = int_to_bcd8(minute)
        else:
            self.rseccnt = int_to_bcd8(sec)

        # Carry interrupt
        if self.rcr1 & RCR1_CIE:
            self._raise_irq(RTC_INTEVT_CARRY)

        # Alarm check
        if self.rcr1 & RCR1_AIE:
            if self._alarm_matches():
                self.rcr1 |= RCR1_AF
                self._raise_irq(RTC_INTEVT_ALARM)

        # Periodic interrupt (also checked at the second boundary)
        self._check_periodic()

    def _increment_day(self):
        """Increment RDAYCNT, handling month/year rollover."""
        day = bcd8_to_int(self.rdaycnt) + 1
        month = bcd8_to_int(self.rmoncnt)
        year = bcd16_to_int(self.ryrcnt)

        # Days in this month (handle leap years for February)
        if month == 2:
            leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
            dim = 29 if leap else 28
        elif month in (4, 6, 9, 11):
            dim = 30
        else:
            dim = 31

        if day > dim:
            # Roll over to next month
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
                self.ryrcnt = int_to_bcd16(year)
            self.rmoncnt = int_to_bcd8(month)
        self.rdaycnt = int_to_bcd8(day)

    def _check_periodic(self):
        """Check if the periodic interrupt should fire."""
        pes = (self.rcr2 & RCR2_PES) >> RCR2_PES_S
        if pes == 0:
            return   # periodic interrupt disabled
        # The periodic interrupt fires every (128 / rate) ticks.
        # rate is in Hz (e.g. pes=6 -> 1 Hz -> every 128 ticks).
        rate = RTC_PERIODIC_RATES[pes]
        if rate == 0:
            return
        period = int(128 / rate)
        self._periodic_counter += 1
        if self._periodic_counter >= period:
            self._periodic_counter = 0
            self.rcr2 |= RCR2_PEF
            self._raise_irq(RTC_INTEVT_PRI)

    def _alarm_matches(self) -> bool:
        """Check if the current time matches the alarm settings."""
        # Each alarm register has an ENB bit (bit 0).  If ENB=0, that
        # field is "don't care".  If all enabled fields match, the alarm
        # fires.
        if self.rsecar & 1 and (self.rsecar >> 4) != self.rseccnt:
            return False
        if self.rminar & 1 and (self.rminar >> 4) != self.rmincnt:
            return False
        if self.rhrar & 1 and (self.rhrar >> 4) != self.rhrcnt:
            return False
        if self.rwkar & 1 and (self.rwkar & 0x07) != self.rwkcnt:
            return False
        if self.rdayar & 1 and (self.rdayar >> 4) != self.rdaycnt:
            return False
        if self.rmonar & 1 and (self.rmonar >> 4) != self.rmoncnt:
            return False
        return True

    # ---- MMIO read/write ----

    def read8(self, addr: int) -> int:
        offset = addr - RTC_BASE
        if offset == RTC_R64CNT:   return self.r64cnt
        if offset == RTC_RSECCNT:  return self.rseccnt
        if offset == RTC_RMINCNT:  return self.rmincnt
        if offset == RTC_RHRCNT:   return self.rhrcnt
        if offset == RTC_RWKCNT:   return self.rwkcnt
        if offset == RTC_RDAYCNT:  return self.rdaycnt
        if offset == RTC_RMONCNT:  return self.rmoncnt
        if offset == RTC_RSECAR:   return self.rsecar
        if offset == RTC_RMINAR:   return self.rminar
        if offset == RTC_RHRAR:    return self.rhrar
        if offset == RTC_RWKAR:    return self.rwkar
        if offset == RTC_RDAYAR:   return self.rdayar
        if offset == RTC_RMONAR:   return self.rmonar
        if offset == RTC_RCR1:     return self.rcr1
        if offset == RTC_RCR2:     return self.rcr2
        if offset == RTC_RCR3:     return self.rcr3
        return 0

    def read16(self, addr: int) -> int:
        offset = addr - RTC_BASE
        if offset == RTC_RYRCNT:   return self.ryrcnt
        if offset == RTC_RYRAR:    return self.ryrar
        return 0

    def read32(self, addr: int) -> int:
        return 0   # no 32-bit RTC registers

    def write8(self, addr: int, val: int):
        val &= 0xFF
        offset = addr - RTC_BASE
        if offset == RTC_R64CNT:
            pass   # R64CNT is read-only
        elif offset == RTC_RSECCNT: self.rseccnt = val
        elif offset == RTC_RMINCNT: self.rmincnt = val
        elif offset == RTC_RHRCNT:  self.rhrcnt  = val
        elif offset == RTC_RWKCNT:  self.rwkcnt  = val & 0x07
        elif offset == RTC_RDAYCNT: self.rdaycnt = val
        elif offset == RTC_RMONCNT: self.rmoncnt = val
        elif offset == RTC_RSECAR:  self.rsecar  = val
        elif offset == RTC_RMINAR:  self.rminar  = val
        elif offset == RTC_RHRAR:   self.rhrar   = val
        elif offset == RTC_RWKAR:   self.rwkar   = val
        elif offset == RTC_RDAYAR:  self.rdayar  = val
        elif offset == RTC_RMONAR:  self.rmonar  = val
        elif offset == RTC_RCR1:
            # CF and AF are write-0-to-clear
            if (val & RCR1_CF) == 0:
                self.rcr1 &= ~RCR1_CF & 0xFF
            if (val & RCR1_AF) == 0:
                self.rcr1 &= ~RCR1_AF & 0xFF
            # CIE and AIE are write-anywhere
            self.rcr1 = (self.rcr1 & (RCR1_CF | RCR1_AF)) | (val & ~(RCR1_CF | RCR1_AF) & 0xFF)
        elif offset == RTC_RCR2:
            # PEF is write-0-to-clear
            if (val & RCR2_PEF) == 0:
                self.rcr2 &= ~RCR2_PEF & 0xFF
            old = self.rcr2
            self.rcr2 = (self.rcr2 & RCR2_PEF) | (val & ~RCR2_PEF & 0xFF)
            # Handle RESET: writing 1 to RESET bit resets all counters
            if val & RCR2_RESET:
                self.r64cnt = 0
                self.rseccnt = 0
                self.rmincnt = 0
                self.rhrcnt = 0
                self.rwkcnt = 0
                self.rdaycnt = int_to_bcd8(1)
                self.rmoncnt = int_to_bcd8(1)
                self.ryrcnt = int_to_bcd16(2000)
                self.rcr2 &= ~RCR2_RESET & 0xFF
            # When START transitions from 0 to 1, reset the periodic counter
            if (val & RCR2_START) and not (old & RCR2_START):
                self._periodic_counter = 0
        elif offset == RTC_RCR3:
            self.rcr3 = val

    def write16(self, addr: int, val: int):
        val &= 0xFFFF
        offset = addr - RTC_BASE
        if offset == RTC_RYRCNT:   self.ryrcnt = val
        elif offset == RTC_RYRAR:  self.ryrar = val

    def write32(self, addr: int, val: int):
        # No 32-bit registers; tolerate 32-bit writes by ignoring them
        pass

    # ---- introspection ----

    def get_time(self) -> dict:
        """Return the current time as a dict of plain integers (not BCD)."""
        return {
            'ticks':    self.r64cnt,
            'seconds':  bcd8_to_int(self.rseccnt),
            'minutes':  bcd8_to_int(self.rmincnt),
            'hours':    bcd8_to_int(self.rhrcnt),
            'week_day': self.rwkcnt,
            'month_day': bcd8_to_int(self.rdaycnt),
            'month':    bcd8_to_int(self.rmoncnt),
            'year':     bcd16_to_int(self.ryrcnt),
        }

    def set_time(self, seconds: int = 0, minutes: int = 0, hours: int = 0,
                 week_day: int = 0, month_day: int = 1, month: int = 1,
                 year: int = 2000):
        """Set the RTC time (plain integers, converted to BCD internally)."""
        self.r64cnt = 0
        self.rseccnt = int_to_bcd8(seconds)
        self.rmincnt = int_to_bcd8(minutes)
        self.rhrcnt  = int_to_bcd8(hours)
        self.rwkcnt  = week_day & 0x07
        self.rdaycnt = int_to_bcd8(month_day)
        self.rmoncnt = int_to_bcd8(month)
        self.ryrcnt  = int_to_bcd16(year)

    def dump(self) -> str:
        t = self.get_time()
        return (f"RTC: {t['year']:04d}-{t['month']:02d}-{t['month_day']:02d} "
                f"(wkday {t['week_day']}) {t['hours']:02d}:{t['minutes']:02d}:{t['seconds']:02d} "
                f"+ {t['ticks']}/128 s  "
                f"RCR1=0x{self.rcr1:02X} RCR2=0x{self.rcr2:02X}")
