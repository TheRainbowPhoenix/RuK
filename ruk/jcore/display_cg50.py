"""
R61523 LCD Display controller for the Casio fx-CG50 / CP-400.

The display is a 640x224 pixel TFT LCD interfaced through a parallel
bus at address 0xB4000000.  The PRDR (Port R Data Register) at
0xA405013C controls the RS pin: when PRDR bit 4 = 0, writes to
0xB4000000 set the register index; when PRDR bit 4 = 1, writes send
pixel data or read register values.

Layout:
  PRDR @ 0xA405013C  (8-bit: bit 4 = RS select)
  Display interface @ 0xB4000000 (16-bit writes)

When RS=0: write selects the register index (mode).
When RS=1: write/read accesses the selected register.
  Register 0x202: GRAM (pixel data, 16-bit RGB565)
  Register 0x200: RAM address horizontal (actually sets vertical in cp-emu)
  Register 0x201: RAM address vertical (actually sets horizontal in cp-emu)
  Register 0x210: Horizontal RAM start position
  Register 0x211: Horizontal RAM end position
  Register 0x212: Vertical RAM start position
  Register 0x213: Vertical RAM end position
  Register 0x002: Driving wave control
  Register 0x003: Entry mode
  Register 0x00B: Low power control
  Register 0x5A1: Brightness
  Register 0x403: Unknown bitfield

The display is 640 pixels wide x 360 pixels tall.  Each pixel is 16-bit
RGB565 (5 bits red, 6 bits green, 5 bits blue).
"""

from typing import Callable, Optional


# ===========================================================================
# Constants
# ===========================================================================

DISPLAY_WIDTH  = 360
DISPLAY_HEIGHT = 640

# Physical addresses
DISPLAY_IFACE_ADDR = 0xB4000000   # 16-bit display interface
PRDR_ADDR          = 0xA405013C   # Port R Data Register (8-bit)

# Register indices (set when PRDR bit 4 = 0)
REG_DRIVING_WAVE = 0x002
REG_ENTRY_MODE   = 0x003
REG_LOW_POWER    = 0x00B
REG_RAM_ADDR_H   = 0x200   # actually vertical in cp-emu
REG_RAM_ADDR_V   = 0x201   # actually horizontal in cp-emu
REG_GRAM         = 0x202   # pixel data read/write
REG_H_RAM_START  = 0x210
REG_H_RAM_END    = 0x211
REG_V_RAM_START  = 0x212
REG_V_RAM_END    = 0x213
REG_UNKNOWN_403  = 0x403
REG_BRIGHTNESS   = 0x5A1


# ===========================================================================
# Display peripheral
# ===========================================================================

class Display:
    """
    R61523 LCD controller.

    Stores a 640x224 pixel framebuffer as a list of 16-bit RGB565 values.
    The host can call `get_framebuffer()` to retrieve the current pixel
    data for rendering in a GUI.
    """

    def __init__(self):
        # Port R Data Register (controls RS pin)
        self.prdr = 0

        # Current register index (set when PRDR bit 4 = 0)
        self.mode = 0

        # Display registers
        self.driving_wave_control = 0
        self.entry_mode = 0
        self.low_power_control = 0
        self.unknown_403 = 0
        self.brightness = 255

        # RAM address counters
        self.ram_addr_h = 0   # horizontal counter
        self.ram_addr_v = 0   # vertical counter

        # Window (subset of the display that receives pixel writes)
        self.h_ram_start = 0
        self.h_ram_end = DISPLAY_WIDTH - 1
        self.v_ram_start = 0
        self.v_ram_end = DISPLAY_HEIGHT - 1

        # Framebuffer: 360 rows x 640 columns of 16-bit RGB565
        # Initialized to white (0xFFFF)
        self._fb = [[0xFFFF] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]

        # Callback invoked when pixels change (for GUI live update)
        self.on_update: Optional[Callable[[], None]] = None

    # ---- framebuffer access ----

    def get_framebuffer(self):
        """Return the 2D framebuffer (360 rows x 640 cols, 16-bit RGB565)."""
        return self._fb

    def get_pixel(self, x: int, y: int) -> int:
        """Get a single pixel (16-bit RGB565)."""
        if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
            return self._fb[y][x]
        return 0

    def set_pixel(self, x: int, y: int, rgb565: int):
        """Set a single pixel."""
        if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
            self._fb[y][x] = rgb565 & 0xFFFF

    def clear(self, color: int = 0xFFFF):
        """Clear the framebuffer to a solid color."""
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                self._fb[y][x] = color

    # ---- display interface (0xB4000000) ----

    def disp_read16(self) -> int:
        """Read from the display interface (when PRDR bit 4 = 1)."""
        if self.mode == REG_RAM_ADDR_H:
            return self.ram_addr_h
        if self.mode == REG_RAM_ADDR_V:
            return self.ram_addr_v
        if self.mode == REG_GRAM:
            return self.get_pixel(self.ram_addr_h + self.h_ram_start,
                                  self.ram_addr_v + self.v_ram_start)
        if self.mode == REG_DRIVING_WAVE:
            return self.driving_wave_control
        if self.mode == REG_ENTRY_MODE:
            return self.entry_mode
        if self.mode == REG_LOW_POWER:
            return self.low_power_control
        if self.mode == REG_H_RAM_START:
            return self.h_ram_start
        if self.mode == REG_H_RAM_END:
            return self.h_ram_end
        if self.mode == REG_V_RAM_START:
            return self.v_ram_start
        if self.mode == REG_V_RAM_END:
            return self.v_ram_end
        if self.mode == REG_BRIGHTNESS:
            return self.brightness
        if self.mode == REG_UNKNOWN_403:
            return self.unknown_403
        return 0

    def disp_write16(self, value: int):
        """Write to the display interface."""
        value &= 0xFFFF
        if not (self.prdr & 0x10):
            # RS=0: set the register index
            self.mode = value
        else:
            # RS=1: write to the selected register
            if self.mode == REG_DRIVING_WAVE:
                self.driving_wave_control = value
            elif self.mode == REG_ENTRY_MODE:
                self.entry_mode = value
            elif self.mode == REG_LOW_POWER:
                self.low_power_control = value
            elif self.mode == REG_RAM_ADDR_H:
                # cp-emu: writing to 0x200 sets the vertical address
                self.ram_addr_v = value
            elif self.mode == REG_RAM_ADDR_V:
                # cp-emu: writing to 0x201 sets the horizontal address
                self.ram_addr_h = value
            elif self.mode == REG_H_RAM_START:
                # cp-emu inverts: horizontal_ram_end = 395 - value
                self.h_ram_end = (DISPLAY_WIDTH - 1) - value
            elif self.mode == REG_H_RAM_END:
                # cp-emu inverts: horizontal_ram_start = 395 - value
                self.h_ram_start = (DISPLAY_WIDTH - 1) - value
            elif self.mode == REG_V_RAM_START:
                self.v_ram_start = value
            elif self.mode == REG_V_RAM_END:
                self.v_ram_end = value
            elif self.mode == REG_UNKNOWN_403:
                self.unknown_403 = value
            elif self.mode == REG_BRIGHTNESS:
                self.brightness = value
            elif self.mode == REG_GRAM:
                # Write a pixel
                x = self.ram_addr_h + self.h_ram_start
                y = self.ram_addr_v + self.v_ram_start
                self.set_pixel(x, y, value)

                # Auto-increment the address
                self.ram_addr_h += 1
                if self.ram_addr_h > (self.h_ram_end - self.h_ram_start):
                    self.ram_addr_h = 0
                    self.ram_addr_v += 1
                    if self.ram_addr_v > (self.v_ram_end - self.v_ram_start):
                        self.ram_addr_v = 0

                # Notify the GUI
                if self.on_update is not None:
                    self.on_update()

    def disp_write32(self, value: int):
        """32-bit write splits into two 16-bit writes."""
        self.disp_write16((value >> 16) & 0xFFFF)
        self.disp_write16(value & 0xFFFF)

    # ---- MMIO read/write ----
    # The display has two MMIO regions:
    #   1. PRDR at 0xA405013C (8-bit)
    #   2. Display interface at 0xB4000000 (16-bit, but also accepts 8/32)

    def read8(self, addr: int) -> int:
        if addr == PRDR_ADDR:
            return self.prdr & 0xFF
        return 0

    def read16(self, addr: int) -> int:
        if (addr & 0xFF000000) == 0xB4000000:
            return self.disp_read16()
        return 0

    def read32(self, addr: int) -> int:
        if (addr & 0xFF000000) == 0xB4000000:
            return self.disp_read16()  # simplified
        return 0

    def write8(self, addr: int, val: int):
        val &= 0xFF
        if addr == PRDR_ADDR:
            self.prdr = val

    def write16(self, addr: int, val: int):
        if (addr & 0xFF000000) == 0xB4000000:
            self.disp_write16(val)

    def write32(self, addr: int, val: int):
        if (addr & 0xFF000000) == 0xB4000000:
            self.disp_write32(val)
