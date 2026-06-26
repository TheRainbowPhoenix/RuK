"""
R61523 LCD Display controller — full implementation per Rev.1.01 datasheet.

Implements ALL User Commands (00h–45h, A1h, A8h) and Manufacturer
Commands (B0h–FFh) from the R61523 specification.  Commands that are
not relevant to emulation (power settings, gamma curves, NVM) are
stubbed but accepted without error.

Display: 360×640 RGB565 (ClassPad II portrait).

Interface:
  PRDR @ 0xA405013C  (8-bit: bit 4 = RS/DCX select)
  Display interface @ 0xB4000000 (16-bit)

  RS=0 (DCX=0): command write
  RS=1 (DCX=1): parameter / data write or read
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

# ===========================================================================
# Display peripheral
# ===========================================================================

class Display:
    """
    Full R61523 LCD controller model.

    Every command in the datasheet is handled.  Commands that affect
    display state (sleep, invert, idle, partial, scroll, tear, gamma,
    address mode, pixel format) are tracked.  GRAM writes auto-increment
    per the address_mode bits.
    """

    def __init__(self):
        self.prdr = 0

        # --- Command state machine ---
        self._cmd = 0
        self._params: deque = deque()
        self._writing_memory = False
        self._reading_memory = False

        # --- Column / page window (0x2A / 0x2B) ---
        self._col_start = 0          # SC[9:0]
        self._col_end = DISPLAY_WIDTH - 1   # EC[9:0]
        self._page_start = 0         # SP[9:0]
        self._page_end = DISPLAY_HEIGHT - 1 # EP[9:0]

        # --- GRAM pointer ---
        self._gram_x = 0
        self._gram_y = 0

        # --- Address mode (0x36) ---
        # Bit 7: page address flip (vertical mirror)
        # Bit 6: column address flip (horizontal mirror)
        # Bit 5: page/column exchange (swap X/Y)
        # Bit 4: BGR order (ignored, always RGB565)
        # Bit 3: RL (right-to-left)
        # B5: 0 = 360x640 portrait, 1 = 640x360 landscape
        self._address_mode = 0

        # --- Display state ---
        self._display_on = False
        self._sleep = True
        self._idle = False
        self._invert = False
        self._partial = False
        self._pixel_format = 0x05   # 16-bit RGB565 (0x05 per R61523 datasheet)
        self._gamma_curve = 1

        # --- Partial area (0x30) ---
        self._partial_start = 0
        self._partial_end = DISPLAY_HEIGHT - 1

        # --- Scroll (0x33 / 0x37) ---
        self._scroll_top = 0
        self._scroll_bottom = DISPLAY_HEIGHT - 1
        self._scroll_start = 0     # vertical scroll offset

        # --- Tearing effect (0x34 / 0x35 / 0x44) ---
        self._tear_on = False
        self._tear_mode = 0        # 0=V-blank, 1=V-blank+line
        self._tear_scanline = 0

        # --- Scanline counter ---
        self._scanline = 0

        # --- Manufacturer command access protect (0xB0) ---
        self._mcap = 0

        # --- Backlight control (B8h/B9h/BAh) ---
        self._backlight_pwmon = 0
        self._backlight_duty = 0       # BDCV: 0..255
        self._backlight_freq = 0       # frequency code
        self._backlight_pwmwm = 0      # PWMWM bit
        self._backlight_ledpwme = 0    # LEDPWME bit
        self._backlight_smooth = 0     # dim bit
        self._backlight_polarity = 0   # 0=high lit, 1=low lit

        # --- Gamma curves (C8h/C9h/CAh) ---
        self._gamma_a = [0] * 18
        self._gamma_b = [0] * 18
        self._gamma_c = [0] * 18

        # --- Panel driving / power settings (stored, not modeled) ---
        self._mfr_regs: dict = {}

        # --- Device code (BFh) ---
        # R61523 device code = 0x01221523
        self._device_code = [0x01, 0x22, 0x15, 0x23]

        # --- Framebuffer ---
        self._fb = [[0xFFFF] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]

        # --- Callback for GUI ---
        self.on_update: Optional[Callable[[], None]] = None

    # ==================================================================
    # Public framebuffer API
    # ==================================================================

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

    # ==================================================================
    # Command processing
    # ==================================================================

    def _start_command(self, cmd):
        """RS=0: new command issued."""
        self._cmd = cmd & 0xFF
        self._writing_memory = False
        self._reading_memory = False
        self._params.clear()

        c = self._cmd

        # ---- 0-param commands (execute immediately) ----
        if c == 0x00:   # nop
            pass
        elif c == 0x01: # soft_reset
            self._soft_reset()
        elif c == 0x10: # enter_sleep_mode
            self._sleep = True
        elif c == 0x11: # exit_sleep_mode
            self._sleep = False
        elif c == 0x12: # enter_partial_mode
            self._partial = True
        elif c == 0x13: # enter_normal_mode
            self._partial = False
        elif c == 0x20: # exit_invert_mode
            self._invert = False
        elif c == 0x21: # enter_invert_mode
            self._invert = True
        elif c == 0x28: # set_display_off
            self._display_on = False
        elif c == 0x29: # set_display_on
            self._display_on = True
        elif c == 0x34: # set_tear_off
            self._tear_on = False
        elif c == 0x38: # exit_idle_mode
            self._idle = False
        elif c == 0x39: # enter_idle_mode
            self._idle = True

        # ---- Commands with parameters ----
        elif c == 0x04: # read_DDB_start
            self._param_count = 5
        elif c == 0x0A: # get_power_mode
            self._param_count = 1
        elif c == 0x0B: # get_address_mode
            self._param_count = 1
        elif c == 0x0C: # get_pixel_format
            self._param_count = 1
        elif c == 0x0D: # get_display_mode
            self._param_count = 1
        elif c == 0x0E: # get_signal_mode
            self._param_count = 1
        elif c == 0x0F: # get_diagnostic_result
            self._param_count = 1
        elif c == 0x26: # set_gamma_curve
            self._param_count = 1
        elif c == 0x2A: # set_column_address
            self._param_count = 4
        elif c == 0x2B: # set_page_address
            self._param_count = 4
        elif c == 0x2C: # write_memory_start
            self._gram_x = self._col_start
            self._gram_y = self._page_start
            self._writing_memory = True
        elif c == 0x2D: # write_LUT
            self._param_count = -1  # variable
        elif c == 0x2E: # read_memory_start
            self._gram_x = self._col_start
            self._gram_y = self._page_start
            self._reading_memory = True
        elif c == 0x30: # set_partial_area
            self._param_count = 4
        elif c == 0x33: # set_scroll_area
            self._param_count = 6
        elif c == 0x35: # set_tear_on
            self._param_count = 1
        elif c == 0x36: # set_address_mode
            self._param_count = 1
        elif c == 0x37: # set_scroll_start
            self._param_count = 2
        elif c == 0x3A: # set_pixel_format
            self._param_count = 1
        elif c == 0x3C: # write_memory_continue
            self._writing_memory = True
        elif c == 0x3E: # read_memory_continue
            self._reading_memory = True
        elif c == 0x44: # set_tear_scanline
            self._param_count = 2
        elif c == 0x45: # get_scanline
            self._param_count = 2
        elif c == 0xA1: # read_DDB_start (alt)
            self._param_count = 5
        elif c == 0xA8: # read_DDB_continue
            self._param_count = -1

        # ---- Manufacturer commands (B0h–FFh) ----
        elif c == 0xB0: # MCAP
            self._param_count = 1
        elif c == 0xB1: # Low Power Mode Control
            self._param_count = 1
        elif c == 0xB3: # Frame Memory Access and Interface Setting
            self._param_count = 2
        elif c == 0xB5: # Read Checksum and ECC Error Count
            self._param_count = 3
        elif c == 0xB6: # DSI Control
            self._param_count = 1
        elif c == 0xB8: # Backlight Control 1
            self._param_count = 15
        elif c == 0xB9: # Backlight Control 2
            self._param_count = 4
        elif c == 0xBA: # Backlight Control 3
            self._param_count = 1
        elif c == 0xBF: # Device Code Read
            self._param_count = 4
        elif c == 0xC0: # Panel Driving Setting
            self._param_count = 7
        elif c == 0xC1: # Display Timing Setting Normal/Partial
            self._param_count = 5
        elif c == 0xC3: # Display Timing Setting Idle
            self._param_count = 5
        elif c == 0xC4: # Source/VCOM/Gate Driving Timing
            self._param_count = 5
        elif c == 0xC8: # Gamma Set A
            self._param_count = 18
        elif c == 0xC9: # Gamma Set B
            self._param_count = 18
        elif c == 0xCA: # Gamma Set C
            self._param_count = 18
        elif c == 0xD0: # Power Setting Common
            self._param_count = 10
        elif c == 0xD1: # VCOM Setting
            self._param_count = 4
        elif c == 0xD2: # Power Setting Normal Mode
            self._param_count = 3
        elif c == 0xD4: # Power Setting Idle Mode
            self._param_count = 3
        elif c == 0xE0: # NVM Access Control
            self._param_count = 4
        elif c == 0xE1: # set_write_DDB Control
            self._param_count = 1

        # ---- Test mode commands (D6, D7, D9, E2-E6, F3, FA, FC-FE) ----
        # Access prohibited — silently ignore
        elif c in (0xD6, 0xD7, 0xD9, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6,
                    0xF3, 0xFA, 0xFC, 0xFD, 0xFE, 0xFF):
            self._param_count = 0  # ignore

        else:
            # Unknown command — silently accept
            self._param_count = 0

    def _write_param(self, value):
        """RS=1: parameter or GRAM data."""
        value &= 0xFFFF

        if self._writing_memory:
            self._write_gram(value)
            return

        if self._reading_memory:
            # Reads are handled in disp_read16, ignore writes during read
            return

        self._params.append(value)
        c = self._cmd

        # ---- set_column_address (0x2A) ----
        if c == 0x2A and len(self._params) == 4:
            p = list(self._params)
            sc = (p[0] << 8) | p[1]
            ec = (p[2] << 8) | p[3]
            # Clamp based on address_mode B5
            max_val = 0x27F if (self._address_mode & 0x20) else 0x167
            self._col_start = min(sc, max_val, DISPLAY_WIDTH - 1)
            self._col_end = min(ec, max_val, DISPLAY_WIDTH - 1)
            self._params.clear()

        # ---- set_page_address (0x2B) ----
        elif c == 0x2B and len(self._params) == 4:
            p = list(self._params)
            sp = (p[0] << 8) | p[1]
            ep = (p[2] << 8) | p[3]
            max_val = 0x167 if (self._address_mode & 0x20) else 0x27F
            self._page_start = min(sp, max_val, DISPLAY_HEIGHT - 1)
            self._page_end = min(ep, max_val, DISPLAY_HEIGHT - 1)
            self._params.clear()

        # ---- set_address_mode (0x36) ----
        elif c == 0x36:
            self._address_mode = value & 0xFF
            self._params.clear()

        # ---- set_pixel_format (0x3A) ----
        elif c == 0x3A:
            self._pixel_format = value & 0xFF
            self._params.clear()

        # ---- set_gamma_curve (0x26) ----
        elif c == 0x26:
            self._gamma_curve = value & 0xFF
            self._params.clear()

        # ---- set_partial_area (0x30) ----
        elif c == 0x30 and len(self._params) == 4:
            p = list(self._params)
            self._partial_start = (p[0] << 8) | p[1]
            self._partial_end = (p[2] << 8) | p[3]
            self._params.clear()

        # ---- set_scroll_area (0x33) ----
        elif c == 0x33 and len(self._params) == 6:
            p = list(self._params)
            self._scroll_top = (p[0] << 8) | p[1]
            # p[2],p[3] = middle (scrollable) area
            self._scroll_bottom = (p[4] << 8) | p[5]
            self._params.clear()

        # ---- set_scroll_start (0x37) ----
        elif c == 0x37 and len(self._params) == 2:
            p = list(self._params)
            self._scroll_start = (p[0] << 8) | p[1]
            self._params.clear()

        # ---- set_tear_on (0x35) ----
        elif c == 0x35:
            self._tear_on = True
            self._tear_mode = value & 0x01
            self._params.clear()

        # ---- set_tear_scanline (0x44) ----
        elif c == 0x44 and len(self._params) == 2:
            p = list(self._params)
            self._tear_scanline = (p[0] << 8) | p[1]
            self._params.clear()

        # ---- MCAP (0xB0) ----
        elif c == 0xB0:
            self._mcap = value & 0xFF
            self._params.clear()

        # ---- Backlight Control 1 (0xB8) — 15 params ----
        elif c == 0xB8 and len(self._params) == 15:
            self._mfr_regs[c] = list(self._params)
            self._params.clear()

        # ---- Backlight Control 2 (0xB9) — 4 params ----
        # Per xmemtft R61523PwmBacklight.h:
        #   param[0] = PWMON (bit 0)
        #   param[1] = BDCV (duty cycle 0..255)
        #   param[2] = frequency code
        #   param[3] = PWMWM (bit 4) | LEDPWME (bit 3) | DIM (bit 0) | polarity (bit 2)
        elif c == 0xB9 and len(self._params) == 4:
            p = list(self._params)
            self._backlight_pwmon = p[0] & 0x01
            self._backlight_duty = p[1] & 0xFF
            self._backlight_freq = p[2] & 0xFF
            self._backlight_pwmwm = (p[3] >> 4) & 0x01
            self._backlight_ledpwme = (p[3] >> 3) & 0x01
            self._backlight_polarity = (p[3] >> 2) & 0x01
            self._backlight_smooth = p[3] & 0x01
            self._params.clear()

        # ---- Backlight Control 3 (0xBA) — 1 param (read) ----
        elif c == 0xBA:
            self._mfr_regs[c] = value
            self._params.clear()

        # ---- Gamma Set A/B/C (0xC8/0xC9/0xCA) — 18 params each ----
        elif c in (0xC8, 0xC9, 0xCA) and len(self._params) == 18:
            gamma = list(self._params)
            if c == 0xC8:
                self._gamma_a = gamma
            elif c == 0xC9:
                self._gamma_b = gamma
            else:
                self._gamma_c = gamma
            self._params.clear()

        # ---- Manufacturer registers (store all others) ----
        elif 0xB0 <= c <= 0xFF:
            idx = len(self._params) - 1
            self._mfr_regs[(c, idx)] = value
            if hasattr(self, '_param_count') and self._param_count > 0:
                if len(self._params) >= self._param_count:
                    self._params.clear()

        else:
            # For get_* commands, params are read responses — ignore writes
            pass

    def _write_gram(self, value):
        """Write one RGB565 pixel to GRAM and auto-increment."""
        x = self._gram_x
        y = self._gram_y

        # Apply address_mode flips
        px, py = x, y
        if self._address_mode & 0x80:   # bit 7: page flip (vertical)
            py = DISPLAY_HEIGHT - 1 - y
        if self._address_mode & 0x40:   # bit 6: column flip (horizontal)
            px = DISPLAY_WIDTH - 1 - x
        if self._address_mode & 0x20:   # bit 5: page/column exchange (swap X/Y)
            px, py = y, x

        # Apply invert
        if self._invert:
            value = value ^ 0xFFFF

        self.set_pixel(px, py, value)

        # Auto-increment direction depends on address_mode bits 5-7
        # Default: column increment first, then page
        if self._address_mode & 0x20:  # exchange: page increments first
            self._gram_y += 1
            if self._gram_y > self._page_end:
                self._gram_y = self._page_start
                self._gram_x += 1
                if self._gram_x > self._col_end:
                    self._gram_x = self._col_start
        else:
            self._gram_x += 1
            if self._gram_x > self._col_end:
                self._gram_x = self._col_start
                self._gram_y += 1
                if self._gram_y > self._page_end:
                    self._gram_y = self._page_start

        if self.on_update is not None:
            self.on_update()

    def _read_gram(self):
        """Read one RGB565 pixel from GRAM and auto-increment."""
        x = self._gram_x
        y = self._gram_y

        px, py = x, y
        if self._address_mode & 0x80:
            py = DISPLAY_HEIGHT - 1 - y
        if self._address_mode & 0x40:
            px = DISPLAY_WIDTH - 1 - x
        if self._address_mode & 0x20:
            px, py = y, x

        val = self.get_pixel(px, py)
        if self._invert:
            val = val ^ 0xFFFF

        # Auto-increment (same as write)
        if self._address_mode & 0x20:
            self._gram_y += 1
            if self._gram_y > self._page_end:
                self._gram_y = self._page_start
                self._gram_x += 1
                if self._gram_x > self._col_end:
                    self._gram_x = self._col_start
        else:
            self._gram_x += 1
            if self._gram_x > self._col_end:
                self._gram_x = self._col_start
                self._gram_y += 1
                if self._gram_y > self._page_end:
                    self._gram_y = self._page_start

        return val

    def _soft_reset(self):
        """Software reset — resets display state to defaults."""
        self._display_on = False
        self._sleep = True
        self._idle = False
        self._invert = False
        self._partial = False
        self._col_start = 0
        self._col_end = DISPLAY_WIDTH - 1
        self._page_start = 0
        self._page_end = DISPLAY_HEIGHT - 1
        self._address_mode = 0
        self._pixel_format = 0x05
        self._gamma_curve = 1
        self._tear_on = False
        self._tear_mode = 0
        self._scroll_start = 0
        self._mcap = 0

    # ==================================================================
    # Read responses for get_* commands
    # ==================================================================

    def _get_read_response(self):
        """Return the read response for the current get_* command."""
        c = self._cmd
        if c == 0x0A:  # get_power_mode
            val = 0x01  # booster on
            if self._display_on: val |= 0x80
            if not self._idle: val |= 0x40
            if not self._partial: val |= 0x20
            if not self._sleep: val |= 0x10
            if self._invert: val |= 0x08
            return val
        elif c == 0x0B:  # get_address_mode
            return self._address_mode
        elif c == 0x0C:  # get_pixel_format
            return self._pixel_format
        elif c == 0x0D:  # get_display_mode
            val = 0
            if self._sleep: val |= 0x04
            if self._partial: val |= 0x02
            if self._idle: val |= 0x01
            return val
        elif c == 0x0E:  # get_signal_mode
            return 0x00
        elif c == 0x0F:  # get_diagnostic_result
            return 0x40  # bit 6: oscillator running
        elif c == 0x45:  # get_scanline
            return self._scanline & 0xFFFF
        elif c == 0x04 or c == 0xA1:  # read_DDB_start
            return 0x00
        elif c == 0xA8:  # read_DDB_continue
            return 0x00
        elif c == 0xBF:  # Device Code Read
            # R61523 device code = 0x01221523
            # Return bytes sequentially: dummy, 0x01, 0x22, 0x15, 0x23
            # Use a counter stored in _params deque
            if len(self._params) == 0:
                # First read returns dummy
                self._params.append(0)
                return 0x00
            idx = len(self._params)
            self._params.append(0)
            if idx <= len(self._device_code):
                return self._device_code[idx - 1]
            return 0x00
        elif c == 0xB5:  # Read Checksum
            return 0x00
        elif c == 0xBA:  # Backlight Control 3
            return self._mfr_regs.get(0xBA, 0x00)
        return 0

    # ==================================================================
    # Display interface
    # ==================================================================

    def disp_read16(self):
        """Read from display interface (RS=1)."""
        if self._reading_memory:
            return self._read_gram()
        return self._get_read_response()

    def disp_write16(self, value):
        """Write to display interface."""
        value &= 0xFFFF
        if not (self.prdr & 0x10):
            self._start_command(value)
        else:
            self._write_param(value)

    def disp_write32(self, value):
        self.disp_write16((value >> 16) & 0xFFFF)
        self.disp_write16(value & 0xFFFF)

    # ==================================================================
    # MMIO
    # ==================================================================

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

    # ==================================================================
    # Backward compatibility properties
    # ==================================================================

    @property
    def mode(self): return self._cmd
    @mode.setter
    def mode(self, v): self._cmd = v

    @property
    def ram_addr_h(self): return self._gram_x
    @property
    def ram_addr_v(self): return self._gram_y
    @property
    def h_ram_start(self): return self._col_start
    @property
    def h_ram_end(self): return self._col_end
    @property
    def v_ram_start(self): return self._page_start
    @property
    def v_ram_end(self): return self._page_end
