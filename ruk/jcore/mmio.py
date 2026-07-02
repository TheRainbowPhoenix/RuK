"""
MMIO device wrapper for RuK's MemoryMap.

Provides an `MMIODevice` class that wraps a peripheral object so it can
be registered with `MemoryMap.add()`, and an `attach_tmu()` helper that
maps a TMU peripheral into the memory map.

Also provides `attach_rtc()` and `attach_ubc()` helpers (see rtc.py and
ubc.py).
"""

from typing import Callable, Optional

from ruk.jcore.memory import Memory, MemoryMap


class MMIODevice(Memory):
    """
    A Memory-like object whose reads/writes are delegated to a peripheral.

    The peripheral must expose `read8/read16/read32/write8/write16/write32`
    methods taking a single ABSOLUTE address (not offset within this
    device).  This lets one peripheral span multiple non-contiguous
    address ranges (e.g. the TMU lives at both 0xA4490000 and 0xA44D0030).

    We extend `Memory` so it can be registered with `MemoryMap.add()`.
    The MemoryMap calls `Memory.read8/read16/read32` and
    `Memory.write_bin` with the offset (address - region_start); we
    translate back to absolute addresses before calling the peripheral.
    """

    def __init__(self, base_addr: int, size: int, peripheral, name: str = "MMIO"):
        # Don't call super().__init__ -- we don't want a bytearray.
        self._base_addr = base_addr
        self._size = size
        self._peripheral = peripheral
        self._ptr = 0
        self._name = name

    # ---- the Memory interface RuK's MemoryMap actually uses ----

    def read8(self, addr: int) -> int:
        return self._peripheral.read8(self._base_addr + addr) & 0xFF

    def read16(self, addr: int) -> int:
        return self._peripheral.read16(self._base_addr + addr) & 0xFFFF

    def read32(self, addr: int) -> int:
        return self._peripheral.read32(self._base_addr + addr) & 0xFFFFFFFF

    def write8(self, addr: int, val: int) -> int:
        self._peripheral.write8(self._base_addr + addr, val & 0xFF)
        return val

    def write16(self, addr: int, val: int):
        self._peripheral.write16(self._base_addr + addr, val & 0xFFFF)

    def write32(self, addr: int, val: int):
        self._peripheral.write32(self._base_addr + addr, val & 0xFFFFFFFF)

    def write_bin(self, addr: int, data) -> None:
        """Accept both bytes and int (for backwards compatibility)."""
        # RuK's MemoryMap.write32/16/8 call this with already-serialized data
        # (bytes).  But the emulator's MOVBS/MOVWS/MOVLS handlers call
        # write8/write16/write32 with an int directly -- which goes through
        # MemoryMap.write8/write16/write32, which call write_bin with the
        # raw int.  So we accept both int and bytes here.
        if isinstance(data, int):
            # Treat as a single byte
            self._peripheral.write8(self._base_addr + addr, data & 0xFF)
            self._ptr = addr + 1
            return
        if len(data) == 1:
            self._peripheral.write8(self._base_addr + addr, data[0])
        elif len(data) == 2:
            val = int.from_bytes(data, "big")
            self._peripheral.write16(self._base_addr + addr, val)
        elif len(data) == 4:
            val = int.from_bytes(data, "big")
            self._peripheral.write32(self._base_addr + addr, val)
        else:
            # Fallback: byte-by-byte
            for i, b in enumerate(data):
                self._peripheral.write8(self._base_addr + addr + i, b)
        self._ptr = addr + len(data)

    def __len__(self):
        return self._size


# ---------------------------------------------------------------------------
# Attach helpers
# ---------------------------------------------------------------------------

def attach_tmu(memory_map: MemoryMap, tmu) -> None:
    """
    Map a TMU (and its ETMU channels) into a RuK MemoryMap.

    Casio SH7305 addresses (from cp-emu/src/hardware/timers/timers.c):
      - 0xA4490000 .. 0xA4490030   (standard 3-channel TMU)
      - 0xA44D0030 .. 0xA44D00F0   (Casio 6-channel ETMU)

    Both regions are registered with the same `TMU` peripheral object, so
    reads/writes in either region are dispatched to the same instance.
    """
    from ruk.jcore.tmu import TMU_BASE, TMU_SIZE, ETMU_BASE, ETMU_REGION_SIZE

    # Standard TMU region (we use a single MMIODevice object spanning the
    # whole 0x30-byte block, even though only some offsets are valid).
    tmu_dev = MMIODevice(TMU_BASE, TMU_SIZE, tmu, name="TMU")
    memory_map.add(TMU_BASE, tmu_dev, name="TMU", perms="RW")

    # ETMU region: 6 channels at 0x20 stride starting at 0xA44D0030.
    # We map a single 0x100-byte region to cover all 6 channels.
    etmu_dev = MMIODevice(ETMU_BASE, ETMU_REGION_SIZE, tmu, name="ETMU")
    memory_map.add(ETMU_BASE, etmu_dev, name="ETMU", perms="RW")

    # CMT (Compare Match Timer) at 0xA44A0000
    # Map a small region covering CMSTR (0xA44A0000) and CMCSR/CMCNT/CMCOR (0xA44A0060)
    cmt_dev1 = MMIODevice(0xA44A0000, 4, tmu, name="CMT")
    memory_map.add(0xA44A0000, cmt_dev1, name="CMT", perms="RW")
    cmt_dev2 = MMIODevice(0xA44A0060, 0x10, tmu, name="CMT")
    memory_map.add(0xA44A0060, cmt_dev2, name="CMT", perms="RW")


def attach_rtc(memory_map: MemoryMap, rtc) -> None:
    """
    Map an RTC peripheral into a RuK MemoryMap.

    Casio SH7305 RTC is at 0xA413FEC0 (see gint/mpu/rtc.h).
    """
    from ruk.jcore.rtc import RTC_BASE, RTC_SIZE

    rtc_dev = MMIODevice(RTC_BASE, RTC_SIZE, rtc, name="RTC")
    memory_map.add(RTC_BASE, rtc_dev, name="RTC", perms="RW")


def attach_ubc(memory_map: MemoryMap, ubc) -> None:
    """
    Map a UBC (User Break Controller) peripheral into a RuK MemoryMap.

    SH-4 UBC is at 0xFF200000 (see gint/mpu/ubc.h).
    """
    from ruk.jcore.ubc import UBC_BASE, UBC_SIZE

    ubc_dev = MMIODevice(UBC_BASE, UBC_SIZE, ubc, name="UBC")
    memory_map.add(UBC_BASE, ubc_dev, name="UBC", perms="RW")


def attach_dma(memory_map: MemoryMap, dma) -> None:
    """
    Map a DMA controller into a RuK MemoryMap.

    SH-4 DMA registers are at 0xFE008020 (see cp-emu/src/hardware/dma/dma.c).
    """
    from ruk.jcore.dma import DMA_BASE, DMA_SIZE

    dma_dev = MMIODevice(DMA_BASE, DMA_SIZE, dma, name="DMA")
    memory_map.add(DMA_BASE, dma_dev, name="DMA", perms="RW")
    # Give the DMA controller access to the memory map so it can perform transfers
    dma.set_memory(memory_map)


def attach_display(memory_map: MemoryMap, display, with_touch: bool = False) -> None:
    """
    Map an R61523 LCD display into a RuK MemoryMap.

    Two regions:
      - PRDR at 0xA405013C (8-bit, Port R data register)
      - Display interface at 0xB4000000 (16-bit, register/pixel data)

    If `with_touch` is True, the PRDR register (0xA405013C) is NOT
    mapped here -- it will be mapped by attach_touch() instead, which
    shares PRDR between the LCD (bit 4 RS/DCX) and the touch controller
    (bit 5 touch-detect).
    """
    if not with_touch:
        from ruk.jcore.display import PRDR_ADDR

        # PRDR (1 byte at 0xA405013C)
        prdr_dev = MMIODevice(PRDR_ADDR, 1, display, name="PRDR")
        memory_map.add(PRDR_ADDR, prdr_dev, name="PRDR", perms="RW")

    # Display interface (4 bytes at 0xB4000000, enough for 16/32-bit access)
    disp_dev = MMIODevice(0xB4000000, 4, display, name="Display")
    memory_map.add(0xB4000000, disp_dev, name="Display", perms="RW")


def attach_bsc(memory_map: MemoryMap, bsc) -> None:
    """Map a BSC (Bus State Controller) at 0xFEC10000."""
    from ruk.jcore.bsc import BSC_BASE, BSC_SIZE
    bsc_dev = MMIODevice(BSC_BASE, BSC_SIZE, bsc, name="BSC")
    memory_map.add(BSC_BASE, bsc_dev, name="BSC", perms="RW")


def attach_cpg(memory_map: MemoryMap, cpg) -> None:
    """Map a CPG (Clock Pulse Generator) at 0xA4150000."""
    from ruk.jcore.cpg import CPG_BASE, CPG_SIZE
    cpg_dev = MMIODevice(CPG_BASE, CPG_SIZE, cpg, name="CPG")
    memory_map.add(CPG_BASE, cpg_dev, name="CPG", perms="RW")
