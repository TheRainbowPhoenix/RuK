#!/usr/bin/env python3
"""
DMA test for RuK.

Tests the SH-4 DMA controller:
  1. Basic memory-to-memory copy (channel 0)
  2. Address increment/decrement modes
  3. Transfer size variations (1, 2, 4 bytes)
  4. Transfer End flag (CHCR.TE) is set after completion
  5. DMA Enable (CHCR.DE) is cleared after completion
  6. Interrupt is raised when IE is set
  7. DMAOR master enable/disable

Run with:
    python3 test_dma.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.dma import (
    DMA_BASE, DMA_CHAN_BASES,
    DMA_SAR_OFF, DMA_DAR_OFF, DMA_TCR_OFF, DMA_CHCR_OFF,
    DMA_DMAOR_ADDR,
    CHCR_DE, CHCR_TE, CHCR_IE,
    CHCR_TS10_M, CHCR_TS10_S, CHCR_TS32_M, CHCR_TS32_S,
    CHCR_SM_M, CHCR_SM_S, CHCR_DM_M, CHCR_DM_S,
    DMAOR_DME,
    DMA_INTEVT,
)


def make_cp():
    """Create a Classpad with DMA + INTC."""
    cp = Classpad(b'\x00\x09', debug=False, with_tmu=True, with_dma=True)
    return cp


def write_chcr(cp, channel, value):
    """Write to a channel's CHCR register."""
    cp.cpu.mem.write32(DMA_CHAN_BASES[channel] + DMA_CHCR_OFF, value)


def read_chcr(cp, channel) -> int:
    """Read a channel's CHCR register."""
    return cp.cpu.mem.read32(DMA_CHAN_BASES[channel] + DMA_CHCR_OFF)


def setup_dma_transfer(cp, channel, src, dst, count, size_bytes,
                       src_mode=1, dst_mode=1, enable_irq=False):
    """
    Configure a DMA channel for a transfer.
    size_bytes: 1, 2, 4, 8, 16, or 32
    src_mode/dst_mode: 0=fixed, 1=increment, 2=decrement
    """
    # Map size_bytes to TS encoding
    ts_map = {1: 0, 2: 1, 4: 2, 8: 7, 16: 3, 32: 4}
    ts = ts_map.get(size_bytes, 0)
    ts10 = ts & 0x3
    ts32 = (ts >> 2) & 0x3

    # Set SAR, DAR, TCR
    cp.cpu.mem.write32(DMA_CHAN_BASES[channel] + DMA_SAR_OFF, src)
    cp.cpu.mem.write32(DMA_CHAN_BASES[channel] + DMA_DAR_OFF, dst)
    cp.cpu.mem.write32(DMA_CHAN_BASES[channel] + DMA_TCR_OFF, count)

    # Build CHCR: DE=0 (not yet), IE=enable_irq, TS=ts, SM=src_mode, DM=dst_mode
    chcr = (ts10 << CHCR_TS10_S) | (ts32 << CHCR_TS32_S) | \
           (src_mode << CHCR_SM_S) | (dst_mode << CHCR_DM_S)
    if enable_irq:
        chcr |= CHCR_IE
    cp.cpu.mem.write32(DMA_CHAN_BASES[channel] + DMA_CHCR_OFF, chcr)

    # Enable DMAOR master enable
    cp.cpu.mem.write16(DMA_DMAOR_ADDR, DMAOR_DME)


def start_dma(cp, channel):
    """Start a DMA transfer by setting CHCR.DE=1."""
    old = read_chcr(cp, channel)
    write_chcr(cp, channel, old | CHCR_DE)


def test_basic_copy():
    """Test a basic 4-byte memory-to-memory DMA copy."""
    print("\n[test] Basic 4-byte DMA copy (channel 0)")
    cp = make_cp()

    # Source data at 0x8C001000: 0xDEADBEEF, 0xCAFEBABE
    cp.ram.write_bin(0x1000, b'\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE')

    # Destination at 0x8C002000
    setup_dma_transfer(cp, 0,
                       src=0x8C001000,
                       dst=0x8C002000,
                       count=2,        # 2 blocks
                       size_bytes=4,   # 4 bytes per block = 8 bytes total
                       src_mode=1, dst_mode=1)

    start_dma(cp, 0)

    # Verify the copy
    val1 = cp.cpu.mem.read32(0x8C002000)
    val2 = cp.cpu.mem.read32(0x8C002004)
    assert val1 == 0xDEADBEEF, f"First word should be 0xDEADBEEF, got 0x{val1:08X}"
    assert val2 == 0xCAFEBABE, f"Second word should be 0xCAFEBABE, got 0x{val2:08X}"

    # Check CHCR.TE is set, CHCR.DE is cleared
    chcr = read_chcr(cp, 0)
    assert chcr & CHCR_TE, "TE should be set after transfer"
    assert not (chcr & CHCR_DE), "DE should be cleared after transfer"
    print(f"  PASS: Copied 0xDEADBEEF, 0xCAFEBABE -> dest. TE set, DE cleared.")


def test_byte_copy():
    """Test 1-byte DMA copy (string copy)."""
    print("\n[test] 1-byte DMA copy")
    cp = make_cp()

    # Source: "Hello, DMA!" at 0x8C001000
    src_data = b'Hello, DMA!\x00'
    cp.ram.write_bin(0x1000, src_data)

    setup_dma_transfer(cp, 0,
                       src=0x8C001000,
                       dst=0x8C002000,
                       count=len(src_data),
                       size_bytes=1,
                       src_mode=1, dst_mode=1)
    start_dma(cp, 0)

    # Read back
    result = bytes(cp.ram.read8(0x2000 + i) for i in range(len(src_data)))
    assert result == src_data, f"Expected {src_data!r}, got {result!r}"
    print(f"  PASS: Copied {len(src_data)} bytes: {result.decode('ascii', 'replace')}")


def test_decrement_mode():
    """Test decrement address mode (copy backwards)."""
    print("\n[test] Decrement address mode")
    cp = make_cp()

    # Source at 0x8C001000: 0x11223344
    cp.ram.write_bin(0x1000, b'\x11\x22\x33\x44')
    # Destination at 0x8C002004 (we'll decrement from here)
    setup_dma_transfer(cp, 0,
                       src=0x8C001000,
                       dst=0x8C002004,
                       count=1,
                       size_bytes=4,
                       src_mode=0,     # fixed source
                       dst_mode=2)     # decrement destination
    start_dma(cp, 0)

    # The DMA should have written to 0x8C002004 (then decremented, but only 1 block)
    val = cp.cpu.mem.read32(0x8C002004)
    assert val == 0x11223344, f"Expected 0x11223344 at 0x8C002004, got 0x{val:08X}"
    print(f"  PASS: Decrement mode wrote 0x{val:08X} to 0x8C002004")


def test_interrupt():
    """Test that DMA raises an interrupt when IE is set."""
    print("\n[test] DMA interrupt")
    cp = make_cp()

    cp.ram.write_bin(0x1000, b'\xAA\xBB\xCC\xDD')
    setup_dma_transfer(cp, 0,
                       src=0x8C001000,
                       dst=0x8C002000,
                       count=1,
                       size_bytes=4,
                       enable_irq=True)
    cp.intc.clear()
    start_dma(cp, 0)

    # Check the interrupt was queued
    assert not cp.intc._queue.empty(), "DMA interrupt should have been queued"
    intevt = cp.intc._queue.get_nowait()
    assert intevt == DMA_INTEVT[0], f"Expected INTEVT=0x{DMA_INTEVT[0]:X}, got 0x{intevt:X}"
    print(f"  PASS: DMA interrupt queued (INTEVT=0x{intevt:X})")


def test_dmaor_disabled():
    """Test that DMA doesn't transfer when DMAOR.DME=0."""
    print("\n[test] DMAOR master disable")
    cp = make_cp()

    cp.ram.write_bin(0x1000, b'\xDE\xAD\xBE\xEF')
    setup_dma_transfer(cp, 0,
                       src=0x8C001000,
                       dst=0x8C002000,
                       count=1,
                       size_bytes=4)
    # Disable DMAOR
    cp.cpu.mem.write16(DMA_DMAOR_ADDR, 0)   # DME=0
    start_dma(cp, 0)

    # The transfer should NOT have happened
    val = cp.cpu.mem.read32(0x8C002000)
    assert val == 0, f"Transfer should not have occurred (DMAOR disabled), got 0x{val:08X}"
    chcr = read_chcr(cp, 0)
    assert chcr & CHCR_DE, "DE should still be set (transfer didn't complete)"
    assert not (chcr & CHCR_TE), "TE should NOT be set"
    print(f"  PASS: DMAOR disabled -> no transfer occurred")


def test_two_channels():
    """Test two DMA channels operating independently."""
    print("\n[test] Two DMA channels")
    cp = make_cp()

    # Channel 0: copy 0x12345678 from 0x8C001000 -> 0x8C002000
    cp.ram.write_bin(0x1000, b'\x12\x34\x56\x78')
    setup_dma_transfer(cp, 0,
                       src=0x8C001000, dst=0x8C002000,
                       count=1, size_bytes=4)

    # Channel 1: copy 0xAABBCCDD from 0x8C003000 -> 0x8C004000
    cp.ram.write_bin(0x3000, b'\xAA\xBB\xCC\xDD')
    setup_dma_transfer(cp, 1,
                       src=0x8C003000, dst=0x8C004000,
                       count=1, size_bytes=4)

    start_dma(cp, 0)
    start_dma(cp, 1)

    val0 = cp.cpu.mem.read32(0x8C002000)
    val1 = cp.cpu.mem.read32(0x8C003000)
    assert val0 == 0x12345678, f"CH0: expected 0x12345678, got 0x{val0:08X}"
    assert val1 == 0xAABBCCDD, f"CH1: expected 0xAABBCCDD, got 0x{val1:08X}"
    print(f"  PASS: CH0=0x{val0:08X}, CH1=0x{val1:08X}")


def test_mmio_read_write():
    """Test MMIO read/write of DMA registers."""
    print("\n[test] DMA MMIO read/write")
    cp = make_cp()
    # Write SAR0
    cp.cpu.mem.write32(DMA_CHAN_BASES[0] + DMA_SAR_OFF, 0x8C001234)
    assert cp.dma.channels[0].sar == 0x8C001234, f"SAR0 should be 0x8C001234, got 0x{cp.dma.channels[0].sar:08X}"
    # Read back
    val = cp.cpu.mem.read32(DMA_CHAN_BASES[0] + DMA_SAR_OFF)
    assert val == 0x8C001234, f"Read back should be 0x8C001234, got 0x{val:08X}"
    # Write DMAOR
    cp.cpu.mem.write16(DMA_DMAOR_ADDR, DMAOR_DME)
    assert cp.dma.dmaor & DMAOR_DME, "DMAOR.DME should be set"
    print(f"  PASS: MMIO read/write works for SAR and DMAOR")


def main():
    tests = [
        test_basic_copy,
        test_byte_copy,
        test_decrement_mode,
        test_interrupt,
        test_dmaor_disabled,
        test_two_channels,
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
            import traceback
            traceback.print_exc()
            print(f"  FAIL: {e}")
    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
