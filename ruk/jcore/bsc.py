"""
BSC (Bus State Controller) for the Casio SH7305.

At 0xFEC10000, controls memory bus timing for CS0-CS6, SDRAM, etc.
The OS writes to these registers during boot to configure memory access.

Register layout:
  +0x00 CMNCR    (32-bit)  Common Control
  +0x04 CS0BCR   (32-bit)  CS0 Bus Control (Flash ROM)
  +0x08 CS2BCR   (32-bit)  CS2 Bus Control
  +0x0C CS3BCR   (32-bit)  CS3 Bus Control
  +0x10 CS4BCR   (32-bit)  CS4 Bus Control
  +0x14 CS5ABCR  (32-bit)  CS5A Bus Control
  +0x18 CS5BBCR  (32-bit)  CS5B Bus Control
  +0x1C CS6ABCR  (32-bit)  CS6A Bus Control
  +0x20 CS6BBCR  (32-bit)  CS6B Bus Control
  +0x24 CS0WCR   (32-bit)  CS0 Wait Control
  +0x28 CS2WCR   (32-bit)  CS2 Wait Control
  +0x2C CS3WCR   (32-bit)  CS3 Wait Control
  +0x30 CS4WCR   (32-bit)  CS4 Wait Control
  +0x34 CS5AWCR  (32-bit)  CS5A Wait Control
  +0x38 CS5BWCR  (32-bit)  CS5B Wait Control
  +0x3C CS6AWCR  (32-bit)  CS6A Wait Control
  +0x40 CS6BWCR  (32-bit)  CS6B Wait Control
  +0x44 SDCR     (32-bit)  SDRAM Control
  +0x48 RTCSR    (32-bit)  Refresh Timer Control/Status
  +0x4C RTCNT    (32-bit)  Refresh Timer Counter
  +0x50 RTCOR    (32-bit)  Refresh Timer Constant
  +0x54 RFCR     (32-bit)  Refresh Counter (read-only)
"""

BSC_BASE = 0xFEC10000
BSC_SIZE = 0x1000  # 4KB covers all BSC registers


class BSC:
    """Bus State Controller -- simple register file."""

    def __init__(self):
        self._regs = bytearray(BSC_SIZE)
        # Set some default values that the OS expects
        # CMNCR default: 0x00000073 (from cp-emu/hardware manual)
        self._write32(0x00, 0x00000073)

    def _read32(self, offset):
        offset &= 0xFFF
        if offset + 4 <= len(self._regs):
            return int.from_bytes(self._regs[offset:offset+4], 'big')
        return 0

    def _write32(self, offset, val):
        offset &= 0xFFF
        if offset + 4 <= len(self._regs):
            self._regs[offset:offset+4] = (val & 0xFFFFFFFF).to_bytes(4, 'big')

    def read8(self, addr):
        offset = addr - BSC_BASE
        if 0 <= offset < len(self._regs):
            return self._regs[offset]
        return 0

    def read16(self, addr):
        offset = addr - BSC_BASE
        if 0 <= offset + 2 <= len(self._regs):
            return int.from_bytes(self._regs[offset:offset+2], 'big')
        return 0

    def read32(self, addr):
        return self._read32(addr - BSC_BASE)

    def write8(self, addr, val):
        offset = addr - BSC_BASE
        if 0 <= offset < len(self._regs):
            self._regs[offset] = val & 0xFF

    def write16(self, addr, val):
        offset = addr - BSC_BASE
        if 0 <= offset + 2 <= len(self._regs):
            self._regs[offset:offset+2] = (val & 0xFFFF).to_bytes(2, 'big')

    def write32(self, addr, val):
        self._write32(addr - BSC_BASE, val)
