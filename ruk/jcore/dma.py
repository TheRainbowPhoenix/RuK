"""
DMA (Direct Memory Access) controller for the SH-4 / Casio SH7305.

6 channels, each with Source Address (SAR), Destination Address (DAR),
Transfer Count (TCR), and Control Register (CHCR).  Plus a shared
DMA Operation Register (DMAOR).

Layout
    Base: 0xFE008020 (note: channel 3 is skipped -- there's a gap)

    Channel 0: 0xFE008020..0xFE00802F  SAR0/DAR0/TCR0/CHCR0  (0x10 bytes each)
    Channel 1: 0xFE008030..0xFE00803F  SAR1/DAR1/TCR1/CHCR1
    Channel 2: 0xFE008040..0xFE00804F  SAR2/DAR2/TCR2/CHCR2
    Channel 3: 0xFE008050..0xFE00805F  SAR3/DAR3/TCR3/CHCR3  (actually channel 4 in HW)
    (gap at 0xFE008060 = DMAOR)
    Channel 4: 0xFE008070..0xFE00807F  SAR4/DAR4/TCR4/CHCR4
    Channel 5: 0xFE008080..0xFE00808F  SAR5/DAR5/TCR5/CHCR5

    DMAOR:      0xFE008060  (16-bit, shared operation register)


CHCR bit layout:
  bit 0:     DE  (DMA Enable)
  bit 1:     TE  (Transfer End flag)
  bit 2:     IE  (Interrupt Enable)
  bits 3-4:  TS_10 (Transfer Size, lower 2 bits)
  bit 5:     TB  (Transfer Bus Mode)
  bit 6:     DS  (DREQ Source select)
  bit 7:     DL  (DREQ Level)
  bits 8-11: RS  (Resource Select)
  bits 12-13: SM (Source address Mode: 00=fixed, 01=increment, 10=decrement)
  bits 14-15: DM (Destination address Mode)
  bits 16-17: AL/AM (Acknowledge)
  bit 18:    HIE (Half-end Interrupt Enable)
  bit 19:    HE  (Half-End flag)
  bits 20-21: TS_32 (Transfer Size, upper 2 bits)
  ...

Transfer Size encoding (TS = TS_32 << 2 | TS_10):
  0 = 1 byte, 1 = 2 bytes, 2 = 4 bytes, 7 = 8 bytes
  3 = 16 bytes, 4 = 32 bytes, 11 = 16B (divided), 12 = 32B (divided)

INTEVT codes for DMA end-of-transfer:
  DEI0=0x800, DEI1=0x820, DEI2=0x840, DEI3=0x860 (ch3 unused)
  DEI4=0x860, DEI5=0x880 (approximate -- cp-emu doesn't model these)
"""

from typing import Callable, Optional, List


# ===========================================================================
# Constants
# ===========================================================================

DMA_BASE = 0xFE008020
DMA_SIZE = 0x80   # covers 6 channels + DMAOR

# Per-channel register offsets (relative to channel base)
DMA_SAR_OFF  = 0x00   # Source Address Register (32-bit)
DMA_DAR_OFF  = 0x04   # Destination Address Register (32-bit)
DMA_TCR_OFF  = 0x08   # Transfer Count Register (32-bit)
DMA_CHCR_OFF = 0x0C   # Channel Control Register (32-bit)

# Channel base addresses (note the gap after ch3 for DMAOR)
DMA_CHAN_BASES = [
    0xFE008020,    # ch0
    0xFE008030,    # ch1
    0xFE008040,    # ch2
    0xFE008050,    # ch3
    # 0xFE008060 = DMAOR (gap)
    0xFE008070,    # ch4
    0xFE008080,    # ch5
]

DMA_DMAOR_ADDR = 0xFE008060   # 16-bit

# CHCR bit masks
CHCR_DE       = 1 << 0       # DMA Enable
CHCR_TE       = 1 << 1       # Transfer End flag
CHCR_IE       = 1 << 2       # Interrupt Enable
CHCR_TS10_M   = 0x18          # bits 3-4: Transfer Size (lower)
CHCR_TS10_S   = 3
CHCR_TS32_M   = 0x300000      # bits 20-21: Transfer Size (upper)
CHCR_TS32_S   = 20
CHCR_SM_M     = 0x3000        # bits 12-13: Source address Mode
CHCR_SM_S     = 12
CHCR_DM_M     = 0xC000         # bits 14-15: Destination address Mode
CHCR_DM_S     = 14

# DMAOR bit masks
DMAOR_DME     = 1 << 7       # DMA Master Enable
DMAOR_NMIF    = 1 << 6       # NMI Flag
DMAOR_AE      = 1 << 5       # Address Error flag
DMAOR_PR_M    = 0x0C          # bits 2-3: Priority mode
DMAOR_CMS_M   = 0x03          # bits 0-1: Cycle steal Mode Select

# Address modes
ADDR_MODE_FIXED     = 0
ADDR_MODE_INCREMENT = 1
ADDR_MODE_DECREMENT = 2

# Transfer size lookup (TS value -> bytes per transfer)
TS_SIZES = {
    0: 1,    # 1 byte
    1: 2,    # 2 bytes
    2: 4,    # 4 bytes
    7: 8,    # 8 bytes
    3: 16,   # 16 bytes
    4: 32,   # 32 bytes
    11: 16,  # 16 bytes (divided)
    12: 32,  # 32 bytes (divided)
}

# INTEVT codes for DMA transfer-end interrupts
DMA_INTEVT = [0x800, 0x820, 0x840, 0x860, 0x860, 0x880]


# ===========================================================================
# DMA channel
# ===========================================================================

class DMAChannel:
    """A single DMA channel."""

    def __init__(self, chan_id: int):
        self.chan_id = chan_id
        self.sar = 0       # Source Address Register
        self.dar = 0       # Destination Address Register
        self.tcr = 0       # Transfer Count Register
        self.chcr = 0      # Channel Control Register

    @property
    def enabled(self) -> bool:
        return bool(self.chcr & CHCR_DE)

    @property
    def transfer_end(self) -> bool:
        return bool(self.chcr & CHCR_TE)

    @property
    def interrupt_enable(self) -> bool:
        return bool(self.chcr & CHCR_IE)

    @property
    def transfer_size(self) -> int:
        """Return the transfer size in bytes (1, 2, 4, 8, 16, or 32)."""
        ts10 = (self.chcr & CHCR_TS10_M) >> CHCR_TS10_S
        ts32 = (self.chcr & CHCR_TS32_M) >> CHCR_TS32_S
        ts = (ts32 << 2) | ts10
        return TS_SIZES.get(ts, 0)

    @property
    def src_addr_mode(self) -> int:
        return (self.chcr & CHCR_SM_M) >> CHCR_SM_S

    @property
    def dst_addr_mode(self) -> int:
        return (self.chcr & CHCR_DM_M) >> CHCR_DM_S


# ===========================================================================
# DMA controller
# ===========================================================================

class DMA:
    """
    SH-4 DMA controller with 6 channels.

    When a channel's CHCR.DE bit transitions from 0 to 1, the DMA
    transfer starts immediately (we model it as instant, like cp-emu).
    The transfer copies `TCR` blocks of `transfer_size` bytes from SAR
    to DAR, with address increment/decrement modes applied per block.

    After the transfer completes:
      - CHCR.TE is set (Transfer End)
      - CHCR.DE is cleared (DMA no longer enabled)
      - If CHCR.IE is set, an interrupt is raised (INTEVT = DMA_INTEVT[ch])
    """

    def __init__(self):
        self.channels: List[DMAChannel] = [DMAChannel(i) for i in range(6)]
        self.dmaor = 0    # 16-bit DMA Operation Register
        self.on_irq: Optional[Callable[[int], None]] = None

    def _raise_irq(self, intevt: int):
        if self.on_irq is not None:
            self.on_irq(intevt)

    def _do_transfer(self, channel: int):
        """Perform the DMA transfer for the given channel (instant)."""
        ch = self.channels[channel]
        ts = ch.transfer_size
        if ts == 0:
            return   # invalid transfer size

        blocks = ch.tcr
        if blocks == 0:
            blocks = 0x1000000   # TCR=0 means 16M blocks (2^24)

        # Use the CPU's memory map for reads/writes.  We access it via
        # the callback -- the host (Classpad) sets this up.
        # For now, we just record the transfer and let the host execute it.
        # Actually, we need access to the MemoryMap.  Let's store it.
        if not hasattr(self, '_mem') or self._mem is None:
            return

        src = ch.sar
        dst = ch.dar
        real_ts = min(ts, 4)   # actual memory access size (max 4 bytes)

        for _ in range(blocks):
            # Read `ts` bytes from src (in real_ts-sized chunks)
            remaining = ts
            offset = 0
            while remaining > 0:
                access_size = min(real_ts, remaining)
                val = self._mem_read(src + offset, access_size)
                self._mem_write(dst + offset, access_size, val)
                remaining -= access_size
                offset += access_size

            # Update addresses based on address mode
            if ch.dst_addr_mode == ADDR_MODE_INCREMENT:
                dst += ts
            elif ch.dst_addr_mode == ADDR_MODE_DECREMENT:
                dst -= ts

            if ch.src_addr_mode == ADDR_MODE_INCREMENT:
                src += ts
            elif ch.src_addr_mode == ADDR_MODE_DECREMENT:
                src -= ts

        # Set Transfer End flag, clear DMA Enable
        ch.chcr |= CHCR_TE
        ch.chcr &= ~CHCR_DE & 0xFFFFFFFF

        # Raise interrupt if enabled
        if ch.interrupt_enable:
            self._raise_irq(DMA_INTEVT[channel])

    def _mem_read(self, addr: int, size: int) -> int:
        """Read from the memory map."""
        if size == 1:
            return self._mem.read8(addr)
        elif size == 2:
            return self._mem.read16(addr)
        elif size == 4:
            return self._mem.read32(addr)
        return 0

    def _mem_write(self, addr: int, size: int, val: int):
        """Write to the memory map."""
        if size == 1:
            self._mem.write8(addr, val)
        elif size == 2:
            self._mem.write16(addr, val)
        elif size == 4:
            self._mem.write32(addr, val)

    def set_memory(self, mem):
        """Set the MemoryMap used for DMA transfers."""
        self._mem = mem

    # ---- MMIO read/write ----

    def _find_channel(self, addr: int) -> Optional[int]:
        """Find which channel a given address belongs to."""
        for i, base in enumerate(DMA_CHAN_BASES):
            if base <= addr < base + 0x10:
                return i
        return None

    def read8(self, addr: int) -> int:
        return self.read32(addr) & 0xFF

    def read16(self, addr: int) -> int:
        if addr == DMA_DMAOR_ADDR:
            return self.dmaor & 0xFFFF
        return self.read32(addr) & 0xFFFF

    def read32(self, addr: int) -> int:
        ch_idx = self._find_channel(addr)
        if ch_idx is None:
            if addr == DMA_DMAOR_ADDR:
                return self.dmaor & 0xFFFF
            return 0
        ch = self.channels[ch_idx]
        off = addr - DMA_CHAN_BASES[ch_idx]
        if off == DMA_SAR_OFF:   return ch.sar
        if off == DMA_DAR_OFF:   return ch.dar
        if off == DMA_TCR_OFF:   return ch.tcr
        if off == DMA_CHCR_OFF:  return ch.chcr
        return 0

    def write8(self, addr: int, val: int):
        self.write32(addr, val)

    def write16(self, addr: int, val: int):
        if addr == DMA_DMAOR_ADDR:
            self.dmaor = val & 0xFFFF
            return
        self.write32(addr, val)

    def write32(self, addr: int, val: int):
        val &= 0xFFFFFFFF
        ch_idx = self._find_channel(addr)
        if ch_idx is None:
            if addr == DMA_DMAOR_ADDR:
                self.dmaor = val & 0xFFFF
            return
        ch = self.channels[ch_idx]
        off = addr - DMA_CHAN_BASES[ch_idx]
        if off == DMA_SAR_OFF:
            ch.sar = val
        elif off == DMA_DAR_OFF:
            ch.dar = val
        elif off == DMA_TCR_OFF:
            ch.tcr = val
        elif off == DMA_CHCR_OFF:
            old = ch.chcr
            ch.chcr = val
            # If DE transitions from 0 to 1, start the DMA transfer
            if (val & CHCR_DE) and not (old & CHCR_DE):
                # Check DMAOR.DME (master enable)
                if self.dmaor & DMAOR_DME:
                    self._do_transfer(ch_idx)

    # ---- introspection ----

    def dump(self) -> str:
        lines = [f"DMA (DMAOR=0x{self.dmaor:04X} DME={int(bool(self.dmaor & DMAOR_DME))}):"]
        for ch in self.channels:
            lines.append(
                f"  CH{ch.chan_id}: DE={int(ch.enabled)} TE={int(ch.transfer_end)} "
                f"IE={int(ch.interrupt_enable)} TS={ch.transfer_size}B "
                f"SAR=0x{ch.sar:08X} DAR=0x{ch.dar:08X} TCR=0x{ch.tcr:08X} "
                f"SM={ch.src_addr_mode} DM={ch.dst_addr_mode} CHCR=0x{ch.chcr:08X}"
            )
        return "\n".join(lines)
