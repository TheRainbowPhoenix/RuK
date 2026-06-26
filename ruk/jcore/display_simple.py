"""
R61523 LCD Display controller for the Casio ClassPad CP400.

The R61523 is a standard MIPI DCS-compatible TFT LCD controller.
The ClassPad II has a 360x640 portrait display (width=360, height=640)
with 16-bit RGB565 pixels.

Hardware interface:
  PRDR @ 0xA405013C  (8-bit: bit 4 = RS select)
  Display interface @ 0xB4000000 (16-bit writes)

When RS=0 (PRDR bit 4 = 0): write selects the command code.
When RS=1 (PRDR bit 4 = 1): write sends parameter/data for the command.

Key R61523 commands (from the datasheet Table 23):
  0x2A  set_column_address    W 4 params (XS_high, XS_low, XE_high, XE_low)
  0x2B  set_page_address      W 4 params (YS_high, YS_low, YE_high, YE_low)
  0x2C  write_memory_start    W variable (pixel data, 16-bit RGB565 each)
  0x2E  read_memory_start     R variable
  0x36  set_address_mode      W 1 param (bit 7: page/column flip, etc.)
  0x3C  write_memory_continue W variable
  0x29  set_display_on        C 0 params
  0x28  set_display_off       C 0 params
  0x11  exit_sleep_mode       C 0 params
  0x10  enter_sleep_mode      C 0 params
  0x3A  set_pixel_format      W 1 param
  0x01  soft_reset            C 0 params

After writing 0x2C, every subsequent 16-bit write (with RS=1) writes
one RGB565 pixel to GRAM.  The address auto-increments column-first,
then wraps to the next row when the column reaches the end of the
set_column_address window.
"""

from typing import Callable, Optional
from collections import deque


# ===========================================================================
# Constants
# ===========================================================================

DISPLAY_WIDTH  = 360
DISPLAY_HEIGHT = 640

DISPLAY_IFACE_ADDR = 0xB4000000
PRDR_ADDR          = 0xA405013C

# R61523 DCS command codes
CMD_NOP                 = 0x00
CMD_SOFT_RESET          = 0x01
CMD_ENTER_SLEEP_MODE    = 0x10
CMD_EXIT_SLEEP_MODE     = 0x11
CMD_SET_DISPLAY_OFF     = 0x28
CMD_SET_DISPLAY_ON      = 0x29
CMD_SET_COLUMN_ADDR     = 0x2A
CMD_SET_PAGE_ADDR       = 0x2B
CMD_WRITE_MEMORY_START  = 0x2C
CMD_READ_MEMORY_START   = 0x2E
CMD_SET_PARTIAL_AREA    = 0x30
CMD_SET_TEAR_OFF        = 0x34
CMD_SET_TEAR_ON         = 0x35
CMD_SET_ADDRESS_MODE    = 0x36
CMD_SET_SCROLL_START    = 0x37
CMD_EXIT_IDLE_MODE      = 0x38
CMD_ENTER_IDLE_MODE     = 0x39
CMD_SET_PIXEL_FORMAT    = 0x3A
CMD_WRITE_MEMORY_CONT   = 0x3C
CMD_READ_MEMORY_CONT    = 0x3E
CMD_SET_TEAR_SCANLINE   = 0x44
CMD_GET_SCANLINE        = 0x45

# Manufacturer commands (B0-BF, C0-FF) - stored but mostly ignored
CMD_MCAP                = 0xB0


# ===========================================================================
# Display peripheral
# ===========================================================================

class Display:
    """
    R61523 LCD controller model.

    Implements the standard MIPI DCS command set with GRAM auto-increment.
    The framebuffer is 360x640 pixels of 16-bit RGB565.
    """

    def __init__(self):
        self.prdr = 0          # Port R Data Register (bit 4 = RS)

        # Command state machine
        self._cmd = 0          # Current command code
        self._params = deque()  # Pending parameter writes
        self._param_count = 0  # Expected parameter count for current cmd
        self._writing_memory = False  # True after 0x2C until new command

        # Column/page address window (set by 0x2A/0x2B)
        self._col_start = 0
        self._col_end = DISPLAY_WIDTH - 1
        self._page_start = 0
        self._page_end = DISPLAY_HEIGHT - 1

        # Current GRAM write position
        self._gram_x = 0
        self._gram_y = 0

        # Address mode (0x36): bit 7 = vertical flip, bit 6 = horizontal flip
        self._address_mode = 0

        # Display state
        self._display_on = False
        self._sleep = True
        self._pixel_format = 0x55  # RGB565

        # Manufacturer command access protect
        self._mcap = 0

        # Framebuffer: DISPLAY_HEIGHT rows x DISPLAY_WIDTH cols of RGB565
        self._fb = [[0xFFFF] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]

        # Callback for GUI live update
        self.on_update: Optional[Callable[[], None]] = None

    # ---- Public framebuffer API ----

    def get_framebuffer(self):
        return self._fb

    def get_pixel(self, x, y):
        if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
            return self._fb[y][x]
        return 0

    def set_pixel(self, x, y, rgb565):
        if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
            self._fb[y][x] = rgb565 & 0xFFFF

    def clear(self, color=0xFFFF):
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                self._fb[y][x] = color

    # ---- Command processing ----

    def _start_command(self, cmd):
        """Called when RS=0: a new command is issued."""
        self._cmd = cmd & 0xFF
        self._writing_memory = False
        self._params.clear()

        # Handle commands with 0 parameters (command-only)
        if self._cmd == CMD_NOP:
            pass
        elif self._cmd == CMD_SOFT_RESET:
            self._soft_reset()
        elif self._cmd == CMD_ENTER_SLEEP_MODE:
            self._sleep = True
        elif self._cmd == CMD_EXIT_SLEEP_MODE:
            self._sleep = False
        elif self._cmd == CMD_SET_DISPLAY_OFF:
            self._display_on = False
        elif self._cmd == CMD_SET_DISPLAY_ON:
            self._display_on = True
        elif self._cmd == CMD_SET_COLUMN_ADDR:
            self._param_count = 4
        elif self._cmd == CMD_SET_PAGE_ADDR:
            self._param_count = 4
        elif self._cmd == CMD_WRITE_MEMORY_START:
            # Reset GRAM pointer to window start
            self._gram_x = self._col_start
            self._gram_y = self._page_start
            self._writing_memory = True
        elif self._cmd == CMD_READ_MEMORY_START:
            self._gram_x = self._col_start
            self._gram_y = self._page_start
        elif self._cmd == CMD_SET_ADDRESS_MODE:
            self._param_count = 1
        elif self._cmd == CMD_SET_PIXEL_FORMAT:
            self._param_count = 1
        elif self._cmd == CMD_WRITE_MEMORY_CONT:
            # Continue writing from current position
            self._writing_memory = True
        elif self._cmd == CMD_MCAP:
            self._param_count = 1
        else:
            # Unknown / manufacturer command: accept params silently
            self._param_count = 0

    def _write_param(self, value):
        """Called when RS=1 and we're expecting command parameters."""
        value &= 0xFFFF

        if self._writing_memory:
            # We're in GRAM write mode (after 0x2C or 0x3C)
            self._write_gram(value)
            return

        self._params.append(value)

        if self._cmd == CMD_SET_COLUMN_ADDR:
            if len(self._params) == 4:
                p = list(self._params)
                self._col_start = (p[0] << 8) | p[1]
                self._col_end = (p[2] << 8) | p[3]
                self._params.clear()

        elif self._cmd == CMD_SET_PAGE_ADDR:
            if len(self._params) == 4:
                p = list(self._params)
                self._page_start = (p[0] << 8) | p[1]
                self._page_end = (p[2] << 8) | p[3]
                self._params.clear()

        elif self._cmd == CMD_SET_ADDRESS_MODE:
            self._address_mode = value & 0xFF
            self._params.clear()

        elif self._cmd == CMD_SET_PIXEL_FORMAT:
            self._pixel_format = value & 0xFF
            self._params.clear()

        elif self._cmd == CMD_MCAP:
            self._mcap = value & 0xFF
            self._params.clear()

    def _write_gram(self, value):
        """Write a pixel to GRAM at the current position and auto-increment."""
        x = self._gram_x
        y = self._gram_y

        # Apply address mode flips
        px = x
        py = y
        if self._address_mode & 0x80:  # bit 7: page address flip (vertical)
            py = DISPLAY_HEIGHT - 1 - y
        if self._address_mode & 0x40:  # bit 6: column address flip (horizontal)
            px = DISPLAY_WIDTH - 1 - x

        self.set_pixel(px, py, value)

        # Auto-increment: column first, then row
        self._gram_x += 1
        if self._gram_x > self._col_end:
            self._gram_x = self._col_start
            self._gram_y += 1
            if self._gram_y > self._page_end:
                self._gram_y = self._page_start  # wrap

        if self.on_update is not None:
            self.on_update()

    def _soft_reset(self):
        """Perform a software reset."""
        self._display_on = False
        self._sleep = True
        self._col_start = 0
        self._col_end = DISPLAY_WIDTH - 1
        self._page_start = 0
        self._page_end = DISPLAY_HEIGHT - 1
        self._address_mode = 0
        self._pixel_format = 0x55

    # ---- Display interface (0xB4000000) ----

    def disp_read16(self):
        """Read from the display interface (RS=1)."""
        if self._cmd == CMD_READ_MEMORY_START or self._cmd == CMD_READ_MEMORY_CONT:
            val = self.get_pixel(self._gram_x, self._gram_y)
            # Auto-increment read pointer
            self._gram_x += 1
            if self._gram_x > self._col_end:
                self._gram_x = self._col_start
                self._gram_y += 1
                if self._gram_y > self._page_end:
                    self._gram_y = self._page_start
            return val
        return 0

    def disp_write16(self, value):
        """Write to the display interface."""
        value &= 0xFFFF
        if not (self.prdr & 0x10):
            # RS=0: command
            self._start_command(value)
        else:
            # RS=1: parameter or GRAM data
            self._write_param(value)

    def disp_write32(self, value):
        """32-bit write splits into two 16-bit writes."""
        self.disp_write16((value >> 16) & 0xFFFF)
        self.disp_write16(value & 0xFFFF)

    # ---- MMIO read/write ----

    def read8(self, addr):
        if addr == PRDR_ADDR:
            return self.prdr & 0xFF
        return 0

    def read16(self, addr):
        if (addr & 0xFF000000) == 0xB4000000:
            return self.disp_read16()
        return 0

    def read32(self, addr):
        if (addr & 0xFF000000) == 0xB4000000:
            return self.disp_read16()
        return 0

    def write8(self, addr, val):
        val &= 0xFF
        if addr == PRDR_ADDR:
            self.prdr = val

    def write16(self, addr, val):
        if (addr & 0xFF000000) == 0xB4000000:
            self.disp_write16(val)

    def write32(self, addr, val):
        if (addr & 0xFF000000) == 0xB4000000:
            self.disp_write32(val)

    # ---- Backward compatibility ----
    # Old code used self.mode = 0x202 and self.ram_addr_h/v directly.
    # Provide compatibility properties so old tests don't crash.

    @property
    def mode(self):
        return self._cmd

    @mode.setter
    def mode(self, val):
        self._cmd = val

    @property
    def ram_addr_h(self):
        return self._gram_x

    @property
    def ram_addr_v(self):
        return self._gram_y

    @property
    def h_ram_start(self):
        return self._col_start

    @property
    def h_ram_end(self):
        return self._col_end

    @property
    def v_ram_start(self):
        return self._page_start

    @property
    def v_ram_end(self):
        return self._page_end
