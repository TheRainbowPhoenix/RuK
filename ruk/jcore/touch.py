"""
I2C bus peripheral and resistive touchscreen controller for the SH7305.

The ClassPad II (CP400) uses an unnamed resistive touchscreen controller
accessed via the SH7305 I2C bus interface at 0xA4470000.  The touch
controller responds to I2C register 0x84 reads with 16 bytes of raw
touch data.

The gint touch driver (gint/src/touch/) talks to this controller:
  1. touch_adconv_get_raw() checks IO_PRDR (0xA405013C) bit 5.
     If bit 5 == 0, a touch is pending.
  2. i2c_reg_read(0x84, buf, 16) reads 16 bytes of touch data.
  3. The 16 bytes contain 8 x 16-bit big-endian fields:
       x1, y1, z1, gh   -- first touch (absolute position + pressure)
       x2, y2, z2, dm   -- second touch (deltas from first touch + pressure)

Raw data format (struct _touch_adraw from gint/drivers/touch.h):
  offset  0:  x1 (u16 BE) -- first touch X (raw ADC value)
  offset  2:  y1 (u16 BE) -- first touch Y (raw ADC value)
  offset  4:  z1 (u16 BE) -- first touch pressure
  offset  6:  gh (u16 BE) -- gesture
  offset  8:  x2 (u16 BE) -- second touch X (delta from x1)
  offset 10:  y2 (u16 BE) -- second touch Y (delta from y1)
  offset 12:  z2 (u16 BE) -- second touch pressure
  offset 14:  dm (u16 BE) -- display mode

gint's conversion (touch_adconv_get_conv):
  adconv->x1 = adraw->x1 >> 4
  adconv->y1 = adraw->y1 >> 4
  adconv->z1 = adraw->z1 >> 4
  adconv->x2 = (adraw->x2 >> 6) + (adraw->x2 & 1 ? -0x400 : 0)
  adconv->y2 = (adraw->y2 >> 6) + (adraw->y2 & 1 ? -0x400 : 0)
  adconv->z2 = (adraw->z2 >> 4) + (adraw->z2 & 1 ? -0x1000 : 0)

Multi-touch: gint detects dual touch when abs(z2) >= dual_threshold
or max(abs(x2), abs(y2)) >= dual_threshold.  The second touch is
reported as deltas from the first touch position.

This module provides:
  - I2CPeripheral: SH7305 I2C register interface
  - ResistiveTouchController: the touch chip (responds to I2C reg 0x84)
  - TouchScreen: combines I2C + touch + PRDR touch-detect pin
  - attach_touch(): wire both into a MemoryMap
"""

from typing import Optional, List, Tuple
import struct

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.mmio import MMIODevice


# ---------------------------------------------------------------------------
# I2C register addresses (SH7305)
# ---------------------------------------------------------------------------

I2C_BASE = 0xA4470000
I2C_SIZE = 0x20   # 32 bytes covers ICDR..ICCH + padding

# Register offsets within the I2C block
I2C_ICDR = 0x00   # Data register (read/write)
I2C_ICCR = 0x04   # Control register
I2C_ICSR = 0x08   # Status register
I2C_ICIC = 0x0C   # Interrupt control register
I2C_ICCL = 0x10   # Clock control low
I2C_ICCH = 0x14   # Clock control high

# ICCR bits
ICCR_ICE   = 0x01   # I2C enable
ICCR_RACK  = 0x02   # Receive acknowledge
ICCR_TRS   = 0x08   # Transmit/receive select
ICCR_BBSY  = 0x20   # Bus busy
ICCR_SCP   = 0x80   # Start/stop condition control

# ICSR bits
ICSR_SCLM  = 0x01
ICSR_SDAM  = 0x02
ICSR_BUSY  = 0x08
ICSR_AL    = 0x10   # Arbitration lost
ICSR_TACK  = 0x20   # Transmit acknowledge
ICSR_WAIT  = 0x40   # Wait
ICSR_DTE   = 0x80   # Data transfer end

# ICIC bits
ICIC_ALE   = 0x10   # Arbitration-lost interrupt enable
ICIC_TACKE = 0x20   # Transmit-acknowledge interrupt enable
ICIC_WAITE = 0x40   # Wait interrupt enable
ICIC_DTEE  = 0x80   # Data-transfer-end interrupt enable

# PRDR address (touch detect pin)
PRDR_ADDR = 0xA405013C
PRDR_TOUCH_BIT = 0x20   # bit 5: 0 = touch pending


# ---------------------------------------------------------------------------
# Resistive touch controller (unnamed chip, accessed via I2C reg 0x84)
# ---------------------------------------------------------------------------

class ResistiveTouchController:
    """Virtual resistive touchscreen controller.

    Responds to I2C register reads.  The gint driver reads register 0x84
    to get 16 bytes of raw touch data (see module docstring for format).

    Supports single and dual touch.  For dual touch, the second touch
    is reported as deltas from the first touch (matching gint's
    touch_adconv_get_conv logic).
    """

    # The I2C slave address used by the touch controller.
    # gint doesn't document this explicitly, but the SH7305 I2C driver
    # transmits the slave address as the first byte of each transaction.
    # The Casio OS uses address 0x38 for the touch controller.
    I2C_ADDR = 0x38

    def __init__(self):
        self._touch_active = False
        self._dual_touch = False
        # First touch (absolute position)
        self._x1 = 0
        self._y1 = 0
        self._z1 = 0
        # Second touch (deltas from first touch for dual-touch)
        self._x2 = 0   # delta X
        self._y2 = 0   # delta Y
        self._z2 = 0   # pressure
        # Gesture and display mode (unused, always 0)
        self._gh = 0
        self._dm = 0

    def set_touch(self, x: int, y: int, z: int = 0x80):
        """Signal a single touch event at (x, y) with pressure z.

        x and y are raw ADC values (before the >> 4 conversion).
        Typical range: x=0..0xFFF, y=0..0xFFF, z=0..0xFFF.
        """
        self._touch_active = True
        self._dual_touch = False
        self._x1 = x & 0xFFFF
        self._y1 = y & 0xFFFF
        self._z1 = z & 0xFFFF
        self._x2 = 0
        self._y2 = 0
        self._z2 = 0

    def set_dual_touch(self, x1: int, y1: int, x2: int, y2: int,
                       z1: int = 0x80, z2: int = 0x80):
        """Signal a dual touch event.

        (x1, y1) is the first touch (absolute position).
        (x2, y2) is the second touch (absolute position).
        The controller stores x2/y2 as deltas from x1/y1, matching
        gint's touch_adconv_get_conv which interprets them as signed
        offsets.
        """
        self._touch_active = True
        self._dual_touch = True
        self._x1 = x1 & 0xFFFF
        self._y1 = y1 & 0xFFFF
        self._z1 = z1 & 0xFFFF
        # Store deltas (the raw register reports deltas, not absolutes)
        self._x2 = (x2 - x1) & 0xFFFF
        self._y2 = (y2 - y1) & 0xFFFF
        self._z2 = z2 & 0xFFFF

    def clear_touch(self):
        """Clear the current touch (release)."""
        self._touch_active = False
        self._dual_touch = False
        self._x1 = self._y1 = self._z1 = 0
        self._x2 = self._y2 = self._z2 = 0
        self._gh = self._dm = 0

    @property
    def touch_pending(self) -> bool:
        """True if a touch is active (PRDR bit 5 == 0)."""
        return self._touch_active

    @property
    def is_dual_touch(self) -> bool:
        """True if dual touch is active."""
        return self._dual_touch

    def read_register(self, reg: int, size: int) -> bytes:
        """Read `size` bytes from the touch controller register `reg`.

        Only register 0x84 (touch data) is implemented; others return 0.
        The data format matches gint's struct _touch_adraw:
          x1, y1, z1, gh, x2, y2, z2, dm (8 x 16-bit big-endian)
        """
        if reg == 0x84 and size >= 16:
            data = struct.pack('>HHHHHHHH',
                               self._x1, self._y1, self._z1, self._gh,
                               self._x2, self._y2, self._z2, self._dm)
            return data[:size]
        return b'\x00' * size


# ---------------------------------------------------------------------------
# I2C peripheral
# ---------------------------------------------------------------------------

class I2CPeripheral:
    """SH7305 I2C bus interface peripheral.

    Models the ICDR/ICCR/ICSR/ICIC/ICCL/ICCH registers.  When the addin
    initiates an I2C transaction (write ICCR=0x94 for start, then write
    slave address + register to ICDR), this peripheral simulates the
    bus protocol and feeds data back from attached devices.
    """

    def __init__(self):
        self.icdr = 0
        self.iccr = 0
        self.icsr = 0
        self.icic = 0
        self.iccl = 0
        self.icch = 0

        # Transaction state
        self._devices = {}   # slave_addr -> device (has read_register)
        self._current_device = None
        self._current_reg = 0
        self._read_buffer = b''
        self._read_pos = 0
        self._tx_count = 0   # how many bytes written in this transaction

    def attach_device(self, slave_addr: int, device):
        """Attach an I2C device at the given 7-bit slave address."""
        self._devices[slave_addr & 0x7F] = device

    def read8(self, addr: int) -> int:
        offset = addr - I2C_BASE
        if offset == I2C_ICDR:
            if self._read_pos < len(self._read_buffer):
                val = self._read_buffer[self._read_pos]
                self._read_pos += 1
                self.icdr = val
                self.icsr |= ICSR_DTE
                return val
            return self.icdr
        elif offset == I2C_ICCR:
            return self.iccr
        elif offset == I2C_ICSR:
            return self.icsr
        elif offset == I2C_ICIC:
            return self.icic
        elif offset == I2C_ICCL:
            return self.iccl
        elif offset == I2C_ICCH:
            return self.icch
        return 0

    def read16(self, addr: int) -> int:
        return self.read8(addr)

    def read32(self, addr: int) -> int:
        return self.read8(addr)

    def write8(self, addr: int, val: int):
        val &= 0xFF
        offset = addr - I2C_BASE
        if offset == I2C_ICDR:
            self._write_icdr(val)
        elif offset == I2C_ICCR:
            self._write_iccr(val)
        elif offset == I2C_ICSR:
            self.icsr = val
        elif offset == I2C_ICIC:
            self.icic = val
        elif offset == I2C_ICCL:
            self.iccl = val
        elif offset == I2C_ICCH:
            self.icch = val

    def write16(self, addr: int, val: int):
        self.write8(addr, val & 0xFF)

    def write32(self, addr: int, val: int):
        self.write8(addr, val & 0xFF)

    def _write_iccr(self, val: int):
        old = self.iccr
        self.iccr = val
        if val == 0x94 and not (old & ICCR_SCP):
            self._tx_count = 0
            self._current_device = None
            self._read_buffer = b''
            self._read_pos = 0
            self.icsr &= ~(ICSR_DTE | ICSR_TACK)
        if old & ICCR_SCP and not (val & ICCR_SCP):
            self._current_device = None
            self._read_buffer = b''
            self._read_pos = 0

    def _write_icdr(self, val: int):
        self.icdr = val
        self._tx_count += 1
        if self._tx_count == 1:
            slave_addr = (val >> 1) & 0x7F
            self._current_device = self._devices.get(slave_addr)
            if self._current_device is None:
                self.icsr |= ICSR_TACK
            else:
                self.icsr &= ~ICSR_TACK
                self.icsr |= ICSR_DTE
        elif self._tx_count == 2:
            if self._current_device is not None:
                self._current_reg = val
                self.icsr |= ICSR_DTE
        else:
            self.icsr |= ICSR_DTE

    def start_read(self, size: int):
        if self._current_device is not None:
            self._read_buffer = self._current_device.read_register(
                self._current_reg, size)
            self._read_pos = 0
            self.icsr |= ICSR_DTE
            if size == 0:
                self.icsr &= ~ICSR_BUSY


# ---------------------------------------------------------------------------
# TouchScreen peripheral (combines touch controller + PRDR touch detect)
# ---------------------------------------------------------------------------

class TouchScreen:
    """Touchscreen peripheral: resistive touch controller + PRDR detect pin.

    The PRDR register at 0xA405013C bit 5 indicates touch state:
      0 = touch pending (data available to read via I2C)
      1 = no touch

    The addin checks PRDR first, then reads 16 bytes from the touch
    controller's register 0x84 via I2C.

    If a Display is attached, the TouchScreen updates the Display's
    `prdr` field so the Display can see bit 4 (RS/DCX) writes.
    """

    def __init__(self, display=None):
        self.controller = ResistiveTouchController()
        self.i2c = I2CPeripheral()
        self.i2c.attach_device(ResistiveTouchController.I2C_ADDR, self.controller)
        self.prdr = 0xFF  # no touch (bit 5 = 1)
        self._display = display

    # Backwards-compatible alias for code that used the old FT6206 name
    @property
    def ft6206(self):
        """Deprecated alias for `controller`."""
        return self.controller

    def update(self):
        """Sync PRDR bit 5 with the touch state and propagate to Display."""
        if self.controller.touch_pending:
            self.prdr &= ~PRDR_TOUCH_BIT
        else:
            self.prdr |= PRDR_TOUCH_BIT
        if self._display is not None:
            self._display.prdr = self.prdr

    def set_touch(self, x: int, y: int, z: int = 0x80):
        """Signal a single touch at (x, y) with pressure z."""
        self.controller.set_touch(x, y, z)
        self.update()

    def set_dual_touch(self, x1: int, y1: int, x2: int, y2: int,
                       z1: int = 0x80, z2: int = 0x80):
        """Signal a dual touch at (x1,y1) and (x2,y2)."""
        self.controller.set_dual_touch(x1, y1, x2, y2, z1, z2)
        self.update()

    def clear_touch(self):
        """Release the touch."""
        self.controller.clear_touch()
        self.update()

    # ---- PRDR MMIO ----

    def _read_prdr(self, addr: int) -> int:
        self.update()
        return self.prdr

    def _write_prdr(self, addr: int, val: int):
        self.prdr = (self.prdr & PRDR_TOUCH_BIT) | (val & ~PRDR_TOUCH_BIT)
        self.update()

    # ---- Combined MMIO interface ----

    def read8(self, addr: int) -> int:
        if addr == PRDR_ADDR or (addr & 0xFFFFFFF0) == (PRDR_ADDR & 0xFFFFFFF0):
            return self._read_prdr(addr)
        if I2C_BASE <= addr < I2C_BASE + I2C_SIZE:
            return self.i2c.read8(addr)
        return 0

    def read16(self, addr: int) -> int:
        return self.read8(addr)

    def read32(self, addr: int) -> int:
        return self.read8(addr)

    def write8(self, addr: int, val: int):
        if addr == PRDR_ADDR:
            self._write_prdr(addr, val)
            return
        if I2C_BASE <= addr < I2C_BASE + I2C_SIZE:
            self.i2c.write8(addr, val)
            return

    def write16(self, addr: int, val: int):
        self.write8(addr, val & 0xFF)

    def write32(self, addr: int, val: int):
        self.write8(addr, val & 0xFF)


# ---------------------------------------------------------------------------
# Attach helper
# ---------------------------------------------------------------------------

def attach_touch(memory_map: MemoryMap, touch: Optional[TouchScreen] = None,
                  display=None) -> TouchScreen:
    """Attach a TouchScreen (I2C + resistive touch + PRDR) to the memory map.

    Returns the TouchScreen instance so the caller can push touch events.
    """
    if touch is None:
        touch = TouchScreen(display=display)
    elif display is not None:
        touch._display = display

    i2c_dev = MMIODevice(I2C_BASE, I2C_SIZE, touch, name="I2C")
    memory_map.add(I2C_BASE, i2c_dev, name="I2C", perms="RW")

    prdr_dev = MMIODevice(PRDR_ADDR, 1, touch, name="PRDR")
    memory_map.add(PRDR_ADDR, prdr_dev, name="PRDR (touch+LCD)", perms="RW")

    return touch
