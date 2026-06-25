#!/usr/bin/env python3
"""
RTC test for RuK.

Tests the Casio SH7305 RTC peripheral:
  1. BCD conversion helpers (bcd8/int8, bcd16/int16)
  2. Tick the RTC by 128 ticks and verify a second has elapsed
  3. Verify date rollover (second -> minute -> hour -> day -> month -> year)
  4. Verify RCR1.CF (carry flag) is set on rollover
  5. Verify periodic interrupt fires at the configured rate
  6. Verify alarm interrupt fires when the alarm matches

Run with:
    python3 test_rtc.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.rtc import (
    RTC_BASE, RTC_SIZE,
    RTC_R64CNT, RTC_RSECCNT, RTC_RMINCNT, RTC_RHRCNT,
    RTC_RWKCNT, RTC_RDAYCNT, RTC_RMONCNT, RTC_RYRCNT,
    RTC_RCR1, RTC_RCR2,
    RCR1_CF, RCR1_CIE, RCR1_AIE, RCR1_AF,
    RCR2_PEF, RCR2_START,
    RTC_INTEVT_PRI, RTC_INTEVT_CARRY, RTC_INTEVT_ALARM,
    bcd8_to_int, int_to_bcd8, bcd16_to_int, int_to_bcd16,
)


def test_bcd_helpers():
    """Test BCD <-> int conversion."""
    print("\n[test] BCD conversion helpers")
    # 8-bit
    assert bcd8_to_int(0x59) == 59
    assert bcd8_to_int(0x00) == 0
    assert bcd8_to_int(0x99) == 99
    assert bcd8_to_int(0x10) == 10
    assert int_to_bcd8(59) == 0x59
    assert int_to_bcd8(0) == 0x00
    assert int_to_bcd8(99) == 0x99
    # Round-trip
    for n in range(100):
        assert bcd8_to_int(int_to_bcd8(n)) == n, f"bcd8 round-trip failed for {n}"
    # 16-bit
    assert bcd16_to_int(0x2010) == 2010
    assert bcd16_to_int(0x0000) == 0
    assert bcd16_to_int(0x9999) == 9999
    assert int_to_bcd16(2010) == 0x2010
    assert int_to_bcd16(0) == 0x0000
    assert int_to_bcd16(9999) == 0x9999
    for n in range(10000):
        assert bcd16_to_int(int_to_bcd16(n)) == n, f"bcd16 round-trip failed for {n}"
    print(f"  PASS: bcd8/bcd16 conversions all correct")


def test_basic_tick():
    """Test that ticking 128 times advances R64CNT and sets CF."""
    print("\n[test] Basic 128-Hz tick")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # Set a known starting time: 2024-01-01 00:00:00
    rtc.set_time(0, 0, 0, 0, 1, 1, 2024)
    # Start the RTC
    rtc.rcr2 = RCR2_START
    assert rtc.rcr2 & RCR2_START, "RTC should be started"

    # Tick 50 times -- R64CNT should be 50, no carry yet
    rtc.tick_128hz(50)
    assert rtc.r64cnt == 50, f"R64CNT should be 50 after 50 ticks, got {rtc.r64cnt}"
    assert not (rtc.rcr1 & RCR1_CF), "CF should not be set before rollover"
    t = rtc.get_time()
    assert t['seconds'] == 0, f"Seconds should still be 0, got {t['seconds']}"

    # Tick 78 more times (total 128) -- should roll over to 0 and set CF
    rtc.tick_128hz(78)
    assert rtc.r64cnt == 0, f"R64CNT should be 0 after 128 ticks, got {rtc.r64cnt}"
    assert rtc.rcr1 & RCR1_CF, "CF should be set after R64CNT rollover"
    t = rtc.get_time()
    assert t['seconds'] == 1, f"Seconds should be 1 after one rollover, got {t['seconds']}"
    print(f"  PASS: 128 ticks -> R64CNT rolled over, seconds incremented, CF set")
    print(f"  Time after 1 second: {t}")


def test_minute_rollover():
    """Test that 60 seconds rolls over to a minute."""
    print("\n[test] Second -> minute rollover")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # Set time to 00:00:59
    rtc.set_time(59, 0, 0, 0, 1, 1, 2024)
    rtc.rcr2 = RCR2_START
    # Tick 128 times (1 second)
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['seconds'] == 0, f"Seconds should be 0 after rollover, got {t['seconds']}"
    assert t['minutes'] == 1, f"Minutes should be 1 after rollover, got {t['minutes']}"
    print(f"  PASS: 00:00:59 + 1s -> 00:01:00")


def test_hour_rollover():
    """Test that 60 minutes rolls over to an hour."""
    print("\n[test] Minute -> hour rollover")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    rtc.set_time(0, 59, 0, 0, 1, 1, 2024)
    rtc.rcr2 = RCR2_START
    # Need 60 seconds = 60*128 ticks to roll over to the next hour
    rtc.tick_128hz(60 * 128)
    t = rtc.get_time()
    assert t['minutes'] == 0 and t['hours'] == 1, f"Expected 01:00:00, got {t}"
    print(f"  PASS: 00:59:00 + 60s -> 01:00:00")


def test_day_rollover():
    """Test that 24 hours rolls over to a new day."""
    print("\n[test] Hour -> day rollover")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # 2024-01-01 23:59:59, Monday (week_day=1)
    rtc.set_time(59, 59, 23, 1, 1, 1, 2024)
    rtc.rcr2 = RCR2_START
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['hours'] == 0 and t['minutes'] == 0 and t['seconds'] == 0, f"Time should be 00:00:00, got {t}"
    assert t['month_day'] == 2, f"Day should be 2, got {t['month_day']}"
    assert t['week_day'] == 2, f"Weekday should be 2 (Tue), got {t['week_day']}"
    print(f"  PASS: 2024-01-01 23:59:59 + 1s -> 2024-01-02 00:00:00 (Tue)")


def test_month_rollover():
    """Test that Jan 31 -> Feb 1."""
    print("\n[test] Day -> month rollover (Jan 31 -> Feb 1)")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    rtc.set_time(59, 59, 23, 3, 31, 1, 2024)   # Wed Jan 31 23:59:59
    rtc.rcr2 = RCR2_START
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['month'] == 2 and t['month_day'] == 1, f"Expected Feb 1, got month={t['month']} day={t['month_day']}"
    print(f"  PASS: Jan 31 + 1s -> Feb 1")


def test_year_rollover():
    """Test that Dec 31 23:59:59 -> Jan 1 next year."""
    print("\n[test] Month -> year rollover (Dec 31 -> Jan 1 next year)")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    rtc.set_time(59, 59, 23, 2, 31, 12, 2024)   # Tue Dec 31 2024 23:59:59
    rtc.rcr2 = RCR2_START
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['year'] == 2025, f"Expected 2025, got {t['year']}"
    assert t['month'] == 1 and t['month_day'] == 1, f"Expected Jan 1, got month={t['month']} day={t['month_day']}"
    print(f"  PASS: Dec 31 2024 + 1s -> Jan 1 2025")


def test_leap_year():
    """Test Feb 29 on a leap year, and Feb 28 on a non-leap year."""
    print("\n[test] Leap year handling")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # 2024 is a leap year. Feb 28 + 1 day = Feb 29.
    rtc.set_time(59, 59, 23, 3, 28, 2, 2024)   # Wed Feb 28 2024
    rtc.rcr2 = RCR2_START
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['month'] == 2 and t['month_day'] == 29, f"Expected Feb 29 (leap year), got month={t['month']} day={t['month_day']}"
    print(f"  PASS: Feb 28 2024 (leap) + 1s -> Feb 29 2024")

    # 2023 is not a leap year. Feb 28 + 1 day = Mar 1.
    rtc.set_time(59, 59, 23, 2, 28, 2, 2023)
    rtc.rcr2 = RCR2_START
    rtc.tick_128hz(128)
    t = rtc.get_time()
    assert t['month'] == 3 and t['month_day'] == 1, f"Expected Mar 1 (non-leap), got month={t['month']} day={t['month_day']}"
    print(f"  PASS: Feb 28 2023 (non-leap) + 1s -> Mar 1 2023")


def test_periodic_interrupt():
    """Test that the periodic interrupt fires at the configured rate."""
    print("\n[test] Periodic interrupt (1 Hz)")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    rtc.set_time(0, 0, 0, 0, 1, 1, 2024)
    # Start RTC + enable periodic interrupt at 1 Hz (PES=6)
    # PES is bits 4-6 of RCR2, so PES=6 -> 0x60
    rtc.rcr2 = RCR2_START | (6 << 4)
    # Clear the INTC queue
    cp.intc.clear()
    # Tick 128 times (1 second) -- should fire 1 periodic IRQ
    rtc.tick_128hz(128)
    # Check INTC queue
    assert not cp.intc._queue.empty(), "Periodic IRQ should have been queued"
    intevt = cp.intc._queue.get_nowait()
    assert intevt == RTC_INTEVT_PRI, f"Expected INTEVT=0x{RTC_INTEVT_PRI:X}, got 0x{intevt:X}"
    assert rtc.rcr2 & RCR2_PEF, "PEF should be set after periodic IRQ"
    print(f"  PASS: 128 ticks at PES=6 (1 Hz) -> 1 periodic IRQ (INTEVT=0x{intevt:X})")

    # Tick 128 more times -- another IRQ
    cp.intc.clear()
    rtc.tick_128hz(128)
    assert not cp.intc._queue.empty(), "Second periodic IRQ should fire"
    print(f"  PASS: Another 128 ticks -> 2nd periodic IRQ")


def test_carry_interrupt():
    """Test that the carry interrupt fires when CIE is set."""
    print("\n[test] Carry interrupt")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    rtc.set_time(0, 0, 0, 0, 1, 1, 2024)
    # Start RTC + enable carry interrupt
    rtc.rcr2 = RCR2_START
    rtc.rcr1 = RCR1_CIE
    cp.intc.clear()
    # Tick 128 times -- should fire carry IRQ
    rtc.tick_128hz(128)
    assert not cp.intc._queue.empty(), "Carry IRQ should have been queued"
    intevt = cp.intc._queue.get_nowait()
    assert intevt == RTC_INTEVT_CARRY, f"Expected INTEVT=0x{RTC_INTEVT_CARRY:X}, got 0x{intevt:X}"
    print(f"  PASS: 128 ticks with CIE=1 -> carry IRQ (INTEVT=0x{intevt:X})")


def test_alarm_interrupt():
    """Test that the alarm interrupt fires when the alarm matches."""
    print("\n[test] Alarm interrupt")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # Set time to 00:00:00, alarm to 00:00:02
    rtc.set_time(0, 0, 0, 0, 1, 1, 2024)
    # RSECAR: ENB=1 (bit 0), value=0x02 (bits 4-7 are the BCD tens/ones)
    # Actually the alarm register layout is: ENB(1) | TENS(3) | ONES(4)
    # So for "02 seconds": ENB=1, value=0x20 (BCD 02 in bits 4-7, ENB in bit 0)
    # Wait -- let me re-check gint's struct:
    #   byte_union(RSECAR, uint8_t ENB:1; uint8_t TENS:3; uint8_t ONES:4;)
    # So bit 0 = ENB, bits 1-3 = TENS, bits 4-7 = ONES.
    # For 02 seconds: ENB=1, TENS=0, ONES=2 -> 0b0010_0001 = 0x21
    rtc.rsecar = 0x21   # ENB=1, seconds=02
    rtc.rhrar = 0       # don't care
    rtc.rminar = 0      # don't care
    rtc.rwkar = 0
    rtc.rdayar = 0
    rtc.rmonar = 0
    rtc.rcr1 = RCR1_AIE
    rtc.rcr2 = RCR2_START
    cp.intc.clear()
    # Tick 2 seconds (256 ticks)
    rtc.tick_128hz(256)
    # The alarm should have fired when seconds hit 02
    assert not cp.intc._queue.empty(), "Alarm IRQ should have been queued"
    intevt = cp.intc._queue.get_nowait()
    assert intevt == RTC_INTEVT_ALARM, f"Expected INTEVT=0x{RTC_INTEVT_ALARM:X}, got 0x{intevt:X}"
    assert rtc.rcr1 & RCR1_AF, "AF should be set after alarm"
    print(f"  PASS: alarm at 00:00:02, time reached -> alarm IRQ (INTEVT=0x{intevt:X})")


def test_mmio_read_write():
    """Test that we can read/write RTC registers via the memory map."""
    print("\n[test] MMIO read/write")
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_rtc=True)
    rtc = cp.rtc
    # Write to RSECCNT via the memory map (offset 0x02 from RTC_BASE)
    cp.cpu.mem.write8(RTC_BASE + RTC_RSECCNT, 0x59)   # 59 seconds
    assert rtc.rseccnt == 0x59, f"RSECCNT should be 0x59 via MMIO, got 0x{rtc.rseccnt:02X}"
    # Read it back
    val = cp.cpu.mem.read8(RTC_BASE + RTC_RSECCNT)
    assert val == 0x59, f"Read back should be 0x59, got 0x{val:02X}"
    # Write RYRCNT (16-bit)
    cp.cpu.mem.write16(RTC_BASE + RTC_RYRCNT, 0x2024)
    assert rtc.ryrcnt == 0x2024, f"RYRCNT should be 0x2024, got 0x{rtc.ryrcnt:04X}"
    val = cp.cpu.mem.read16(RTC_BASE + RTC_RYRCNT)
    assert val == 0x2024, f"Read back should be 0x2024, got 0x{val:04X}"
    print(f"  PASS: MMIO read/write works for both 8-bit and 16-bit registers")


def main():
    tests = [
        test_bcd_helpers,
        test_basic_tick,
        test_minute_rollover,
        test_hour_rollover,
        test_day_rollover,
        test_month_rollover,
        test_year_rollover,
        test_leap_year,
        test_periodic_interrupt,
        test_carry_interrupt,
        test_alarm_interrupt,
        test_mmio_read_write,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except (AssertionError, Exception) as e:
            failed += 1
            print(f"  FAIL: {e}")
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
