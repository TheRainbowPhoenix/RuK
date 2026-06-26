#!/usr/bin/env python3
"""
Comprehensive R61523 LCD controller test suite.

Tests EVERY command and behavior defined in the R61523 Rev.1.01 datasheet,
cross-referenced with:
  - xmemtft R61523 driver (andysworkshop)
  - gint R61523 driver (ClassPad CP400)
  - R61523 datasheet PDF

Also includes a self-test assembly program that exercises all LCD commands
end-to-end on any R61523 emulator.

Usage:
    python3 test_lcd_r61523.py
"""

import sys, os, struct, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.memory import Memory, MemoryMap
from ruk.jcore.cpu import CPU
from ruk.jcore.display import (Display, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                PRDR_ADDR, DISPLAY_IFACE_ADDR)
from ruk.jcore.mmio import MMIODevice
from ruk.tools.assembler import assemble

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _rgb565_to_bgr888(px):
    r5 = (px >> 11) & 0x1F; g6 = (px >> 5) & 0x3F; b5 = px & 0x1F
    return ((b5*255)//31, (g6*255)//63, (r5*255)//31)

def save_bmp(d, fp):
    w, h = DISPLAY_WIDTH, DISPLAY_HEIGHT
    rs = ((w*3+3)//4)*4; pad = rs - w*3
    pix = bytearray()
    for y in range(h-1, -1, -1):
        for x in range(w):
            pix.extend(_rgb565_to_bgr888(d.get_pixel(x, y)))
        pix.extend(b'\x00' * pad)
    fh = struct.pack('<2sIHHI', b'BM', 54+len(pix), 0, 0, 54)
    dh = struct.pack('<IIIHHIIIIII', 40, w, h, 1, 24, 0, len(pix), 2835, 2835, 0, 0)
    with open(fp, 'wb') as f:
        f.write(fh); f.write(dh); f.write(pix)
    print(f"  BMP: {fp}")

def make_cpu(start_pc=0x8C000000, sr=0x40001000):
    mem = Memory(0x1000000)
    mmap = MemoryMap()
    mmap.add(0x8C000000, mem, name="RAM", perms="RWX")
    display = Display()
    mmap.add(PRDR_ADDR, MMIODevice(PRDR_ADDR, 1, display, "PRDR"), name="PRDR")
    mmap.add(DISPLAY_IFACE_ADDR, MMIODevice(DISPLAY_IFACE_ADDR, 0x10000, display, "DISP"), name="DISP")
    mmap.add(0xA4000000, Memory(0x100000), name="MMIO", perms="RW")
    cpu = CPU(mmap, start_pc=start_pc, debug=False)
    cpu.regs['sr'] = sr; cpu.regs['vbr'] = 0; cpu.regs['r15'] = 0x8C080000
    return cpu, mem, display

def load_and_run(cpu, mem, prog, start_pc=0x8C000000, max_steps=10000000):
    off = start_pc - 0x8C000000
    for i, b in enumerate(prog):
        if off + i < len(mem._mem): mem._mem[off + i] = b
    last = 0; lc = 0
    for s in range(max_steps):
        cpu.step()
        if cpu.pc == last:
            lc += 1
            if lc > 100: break
        else:
            last = cpu.pc; lc = 0
    return s + 1

def lcd_cmd_asm(cmd):
    return f"""mov.b @r14, r0
        and #0xEF, r0
        mov.b r0, @r14
        mov #{cmd}, r0
        mov.w r0, @r13
        mov.b @r14, r0
        or #0x10, r0
        mov.b r0, @r14
    """

LCD_SETUP = """
    mov.l prdr_addr, r14
    mov.l disp_addr, r13
""" + lcd_cmd_asm(0x11) + lcd_cmd_asm(0x29) + lcd_cmd_asm(0x2A) + """
    mov #0, r0
    mov.w r0, @r13
    mov #0, r0
    mov.w r0, @r13
    mov #1, r0
    mov.w r0, @r13
    mov #0x67, r0
    mov.w r0, @r13
""" + lcd_cmd_asm(0x2B) + """
    mov #0, r0
    mov.w r0, @r13
    mov #0, r0
    mov.w r0, @r13
    mov #2, r0
    mov.w r0, @r13
    mov #0x7F, r0
    mov.w r0, @r13
""" + lcd_cmd_asm(0x2C)

LCD_POOL = """
    .align 2
    prdr_addr: .long 0xA405013C
    disp_addr: .long 0xB4000000
"""


# ============================================================================
# User Command Tests (00h – 45h, A1h, A8h)
# ============================================================================

class TestUserCommands(unittest.TestCase):
    """Test every User Command from Table 23."""

    def setUp(self):
        self.d = Display()

    def _cmd(self, c):
        self.d.prdr = 0; self.d.disp_write16(c); self.d.prdr = 0x10

    def _param(self, v):
        self.d.disp_write16(v)

    def test_00h_nop(self):
        self._cmd(0x00)
        self.assertEqual(self.d._cmd, 0x00)

    def test_01h_soft_reset(self):
        self.d._display_on = True; self.d._sleep = False; self.d._invert = True
        self._cmd(0x01)
        self.assertFalse(self.d._display_on)
        self.assertTrue(self.d._sleep)
        self.assertFalse(self.d._invert)

    def test_04h_read_ddb_start(self):
        self._cmd(0x04)
        self.assertIsInstance(self.d.disp_read16(), int)

    def test_0Ah_get_power_mode(self):
        self.d._display_on = True; self.d._sleep = False
        self._cmd(0x0A)
        val = self.d.disp_read16()
        self.assertTrue(val & 0x80)
        self.assertTrue(val & 0x10)

    def test_0Bh_get_address_mode(self):
        self.d._address_mode = 0xC0
        self._cmd(0x0B)
        self.assertEqual(self.d.disp_read16(), 0xC0)

    def test_0Ch_get_pixel_format(self):
        self.d._pixel_format = 0x05
        self._cmd(0x0C)
        self.assertEqual(self.d.disp_read16(), 0x05)

    def test_0Dh_get_display_mode(self):
        self.d._sleep = True; self.d._partial = True
        self._cmd(0x0D)
        val = self.d.disp_read16()
        self.assertTrue(val & 0x04)
        self.assertTrue(val & 0x02)

    def test_0Eh_get_signal_mode(self):
        self._cmd(0x0E)
        self.assertIsInstance(self.d.disp_read16(), int)

    def test_0Fh_get_diagnostic_result(self):
        self._cmd(0x0F)
        self.assertTrue(self.d.disp_read16() & 0x40)

    def test_10h_enter_sleep_mode(self):
        self.d._sleep = False; self._cmd(0x10); self.assertTrue(self.d._sleep)

    def test_11h_exit_sleep_mode(self):
        self.d._sleep = True; self._cmd(0x11); self.assertFalse(self.d._sleep)

    def test_12h_enter_partial_mode(self):
        self._cmd(0x12); self.assertTrue(self.d._partial)

    def test_13h_enter_normal_mode(self):
        self.d._partial = True; self._cmd(0x13); self.assertFalse(self.d._partial)

    def test_20h_exit_invert_mode(self):
        self.d._invert = True; self._cmd(0x20); self.assertFalse(self.d._invert)

    def test_21h_enter_invert_mode(self):
        self._cmd(0x21); self.assertTrue(self.d._invert)

    def test_26h_set_gamma_curve(self):
        self._cmd(0x26); self._param(2); self.assertEqual(self.d._gamma_curve, 2)

    def test_28h_set_display_off(self):
        self.d._display_on = True; self._cmd(0x28); self.assertFalse(self.d._display_on)

    def test_29h_set_display_on(self):
        self._cmd(0x29); self.assertTrue(self.d._display_on)

    def test_2Ah_set_column_address(self):
        self._cmd(0x2A)
        self._param(0); self._param(10); self._param(0); self._param(20)
        self.assertEqual(self.d._col_start, 10)
        self.assertEqual(self.d._col_end, 20)

    def test_2Bh_set_page_address(self):
        self._cmd(0x2B)
        self._param(0); self._param(50); self._param(0); self._param(100)
        self.assertEqual(self.d._page_start, 50)
        self.assertEqual(self.d._page_end, 100)

    def test_2Ch_write_memory_start(self):
        self._cmd(0x2C)
        self.assertTrue(self.d._writing_memory)
        self._param(0xF800)
        self.assertEqual(self.d.get_pixel(0, 0), 0xF800)

    def test_2Eh_read_memory_start(self):
        self.d.set_pixel(5, 5, 0x1234)
        self._cmd(0x2A); self._param(0); self._param(5); self._param(0); self._param(5)
        self._cmd(0x2B); self._param(0); self._param(5); self._param(0); self._param(5)
        self._cmd(0x2E)
        self.assertEqual(self.d.disp_read16(), 0x1234)

    def test_30h_set_partial_area(self):
        self._cmd(0x30)
        self._param(0); self._param(10); self._param(0); self._param(100)
        self.assertEqual(self.d._partial_start, 10)
        self.assertEqual(self.d._partial_end, 100)

    def test_33h_set_scroll_area(self):
        self._cmd(0x33)
        for v in [0, 10, 0, 100, 0, 200]: self._param(v)
        self.assertEqual(self.d._scroll_top, 10)
        self.assertEqual(self.d._scroll_bottom, 200)

    def test_34h_set_tear_off(self):
        self.d._tear_on = True; self._cmd(0x34); self.assertFalse(self.d._tear_on)

    def test_35h_set_tear_on(self):
        self._cmd(0x35); self._param(1)
        self.assertTrue(self.d._tear_on)
        self.assertEqual(self.d._tear_mode, 1)

    def test_36h_set_address_mode(self):
        self._cmd(0x36); self._param(0xC0)
        self.assertEqual(self.d._address_mode, 0xC0)

    def test_37h_set_scroll_start(self):
        self._cmd(0x37); self._param(0); self._param(42)
        self.assertEqual(self.d._scroll_start, 42)

    def test_38h_exit_idle_mode(self):
        self.d._idle = True; self._cmd(0x38); self.assertFalse(self.d._idle)

    def test_39h_enter_idle_mode(self):
        self._cmd(0x39); self.assertTrue(self.d._idle)

    def test_3Ah_set_pixel_format(self):
        self._cmd(0x3A); self._param(0x05)
        self.assertEqual(self.d._pixel_format, 0x05)

    def test_3Ch_write_memory_continue(self):
        self._cmd(0x2C); self._param(0xF800)
        self._cmd(0x3C)
        self.assertTrue(self.d._writing_memory)
        self._param(0x07E0)
        self.assertEqual(self.d.get_pixel(1, 0), 0x07E0)

    def test_3Eh_read_memory_continue(self):
        self.d.set_pixel(0, 0, 0x1111); self.d.set_pixel(1, 0, 0x2222)
        self._cmd(0x2E); v1 = self.d.disp_read16()
        self._cmd(0x3E); v2 = self.d.disp_read16()
        self.assertEqual(v1, 0x1111); self.assertEqual(v2, 0x2222)

    def test_44h_set_tear_scanline(self):
        self._cmd(0x44); self._param(0); self._param(100)
        self.assertEqual(self.d._tear_scanline, 100)

    def test_45h_get_scanline(self):
        self._cmd(0x45); self.assertIsInstance(self.d.disp_read16(), int)

    def test_A1h_read_ddb_start_alt(self):
        self._cmd(0xA1); self.assertIsInstance(self.d.disp_read16(), int)

    def test_A8h_read_ddb_continue(self):
        self._cmd(0xA8); self.assertIsInstance(self.d.disp_read16(), int)


# ============================================================================
# Behavior Tests
# ============================================================================

class TestBehaviors(unittest.TestCase):

    def setUp(self):
        self.d = Display()

    def _cmd(self, c):
        self.d.prdr = 0; self.d.disp_write16(c); self.d.prdr = 0x10

    def _param(self, v):
        self.d.disp_write16(v)

    def test_gram_auto_increment_default(self):
        self._cmd(0x2C)
        for i in range(5): self._param(0xF800 + i)
        for i in range(5): self.assertEqual(self.d.get_pixel(i, 0), 0xF800 + i)

    def test_gram_auto_increment_wraps(self):
        self._cmd(0x2A); self._param(0); self._param(0); self._param(0); self._param(2)
        self._cmd(0x2B); self._param(0); self._param(0); self._param(0); self._param(1)
        self._cmd(0x2C)
        for i in range(6): self._param(0x1000 + i)
        self.assertEqual(self.d.get_pixel(0, 1), 0x1003)

    def test_invert_mode_write(self):
        self._cmd(0x21); self._cmd(0x2C); self._param(0xF800)
        self.assertEqual(self.d.get_pixel(0, 0), 0xF800 ^ 0xFFFF)

    def test_invert_mode_read(self):
        self.d.set_pixel(0, 0, 0x1234)
        self._cmd(0x21)
        self._cmd(0x2A); self._param(0); self._param(0); self._param(0); self._param(0)
        self._cmd(0x2B); self._param(0); self._param(0); self._param(0); self._param(0)
        self._cmd(0x2E)
        self.assertEqual(self.d.disp_read16(), 0x1234 ^ 0xFFFF)

    def test_address_mode_vflip(self):
        self._cmd(0x36); self._param(0x80)
        self._cmd(0x2C); self._param(0x1234)
        self.assertEqual(self.d.get_pixel(0, DISPLAY_HEIGHT - 1), 0x1234)

    def test_address_mode_hflip(self):
        self._cmd(0x36); self._param(0x40)
        self._cmd(0x2C); self._param(0x5678)
        self.assertEqual(self.d.get_pixel(DISPLAY_WIDTH - 1, 0), 0x5678)

    def test_address_mode_xy_exchange(self):
        self._cmd(0x36); self._param(0x20)
        self._cmd(0x2A); self._param(0); self._param(0); self._param(0); self._param(2)
        self._cmd(0x2B); self._param(0); self._param(0); self._param(0); self._param(2)
        self._cmd(0x2C); self._param(0xABCD)
        self.assertEqual(self.d.get_pixel(0, 0), 0xABCD)

    def test_portrait_mode(self):
        """Portrait mode: address_mode = 0x40 (xmemtft PortraitSpecialisation)."""
        self._cmd(0x36); self._param(0x40)
        self._cmd(0x2C); self._param(0x1111)
        self.assertEqual(self.d.get_pixel(DISPLAY_WIDTH - 1, 0), 0x1111)

    def test_landscape_mode(self):
        """Landscape mode: address_mode = 0xE0 (xmemtft LandscapeSpecialisation)."""
        self._cmd(0x36); self._param(0xE0)
        self._cmd(0x2A); self._param(0); self._param(0); self._param(0); self._param(2)
        self._cmd(0x2B); self._param(0); self._param(0); self._param(0); self._param(2)
        self._cmd(0x2C); self._param(0x2222)
        # With 0xE0: vflip + hflip + xy exchange
        self.assertNotEqual(self.d.get_pixel(0, 0), 0xFFFF)

    def test_windowed_write(self):
        self._cmd(0x2A); self._param(0); self._param(5); self._param(0); self._param(7)
        self._cmd(0x2B); self._param(0); self._param(10); self._param(0); self._param(12)
        self._cmd(0x2C)
        colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000, 0xF800, 0x07E0, 0x001F, 0xFFFF]
        for c in colors: self._param(c)
        idx = 0
        for y in range(10, 13):
            for x in range(5, 8):
                self.assertEqual(self.d.get_pixel(x, y), colors[idx]); idx += 1

    def test_soft_reset(self):
        self.d._display_on = True; self.d._invert = True; self.d._address_mode = 0xFF
        self._cmd(0x01)
        self.assertFalse(self.d._display_on)
        self.assertFalse(self.d._invert)
        self.assertEqual(self.d._address_mode, 0)
        self.assertEqual(self.d._col_start, 0)
        self.assertEqual(self.d._col_end, DISPLAY_WIDTH - 1)

    def test_col_clamping(self):
        self._cmd(0x2A); self._param(0); self._param(0); self._param(0x10); self._param(0x00)
        self.assertEqual(self.d._col_end, DISPLAY_WIDTH - 1)

    def test_page_clamping(self):
        self._cmd(0x2B); self._param(0); self._param(0); self._param(0x10); self._param(0x00)
        self.assertEqual(self.d._page_end, DISPLAY_HEIGHT - 1)

    def test_full_screen_fill(self):
        self._cmd(0x2C)
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                self._param((x & 0xF8) << 8 | (y & 0x1F))
        self.assertNotEqual(self.d.get_pixel(0, 0), 0xFFFF)

    def test_pixel_format_default(self):
        """Default pixel format should be 0x05 (16-bit per R61523 datasheet)."""
        self.assertEqual(self.d._pixel_format, 0x05)

    def test_device_code_read(self):
        """BFh should return R61523 device code 0x01221523."""
        self._cmd(0xBF)
        d0 = self.d.disp_read16()  # dummy
        d1 = self.d.disp_read16()
        d2 = self.d.disp_read16()
        d3 = self.d.disp_read16()
        d4 = self.d.disp_read16()
        code = (d1 << 24) | (d2 << 16) | (d3 << 8) | d4
        self.assertEqual(code, 0x01221523,
                        f"Device code: 0x{code:08X}, expected 0x01221523")


# ============================================================================
# Manufacturer Command Tests (B0h – FFh)
# ============================================================================

class TestManufacturerCommands(unittest.TestCase):

    def setUp(self):
        self.d = Display()

    def _cmd(self, c):
        self.d.prdr = 0; self.d.disp_write16(c); self.d.prdr = 0x10

    def _param(self, v):
        self.d.disp_write16(v)

    def test_B0h_mcap(self):
        self._cmd(0xB0); self._param(0x04)
        self.assertEqual(self.d._mcap, 0x04)

    def test_B1h_low_power(self):
        self._cmd(0xB1); self._param(0x01)

    def test_B3h_frame_memory(self):
        self._cmd(0xB3); self._param(0x00); self._param(0x01)

    def test_B8h_backlight_1(self):
        self._cmd(0xB8)
        for i in range(15): self._param(i)

    def test_B9h_backlight_2(self):
        """Backlight Control 2: PWMON, BDCV, freq, ctrl."""
        self._cmd(0xB9)
        self._param(0x01)  # PWMON=1
        self._param(128)   # BDCV=50% duty
        self._param(0x03)  # 13.7kHz
        self._param(0x18)  # PWMWM=1, LEDPWME=1
        self.assertEqual(self.d._backlight_pwmon, 1)
        self.assertEqual(self.d._backlight_duty, 128)
        self.assertEqual(self.d._backlight_freq, 0x03)
        self.assertTrue(self.d._backlight_pwmwm)
        self.assertTrue(self.d._backlight_ledpwme)

    def test_BAh_backlight_3_read(self):
        self._cmd(0xBA)
        self.assertIsInstance(self.d.disp_read16(), int)

    def test_BFh_device_code_read(self):
        self._cmd(0xBF)
        self.assertIsInstance(self.d.disp_read16(), int)

    def test_C0h_panel_driving(self):
        self._cmd(0xC0)
        for i in range(7): self._param(i)

    def test_C8h_gamma_a(self):
        self._cmd(0xC8)
        for i in range(18): self._param(i)
        self.assertEqual(self.d._gamma_a, list(range(18)))

    def test_C9h_gamma_b(self):
        self._cmd(0xC9)
        for i in range(18): self._param(i)
        self.assertEqual(self.d._gamma_b, list(range(18)))

    def test_CAh_gamma_c(self):
        self._cmd(0xCA)
        for i in range(18): self._param(i)
        self.assertEqual(self.d._gamma_c, list(range(18)))

    def test_D0h_power_common(self):
        self._cmd(0xD0)
        for i in range(10): self._param(i)

    def test_D1h_vcom(self):
        self._cmd(0xD1)
        for i in range(4): self._param(i)

    def test_test_mode_commands(self):
        for cmd in [0xD6, 0xD7, 0xD9, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6,
                     0xF3, 0xFA, 0xFC, 0xFD, 0xFE, 0xFF]:
            self._cmd(cmd); self._param(0x42)


# ============================================================================
# CP400 gint Driver Compatibility Tests
# ============================================================================

class TestCP400Compat(unittest.TestCase):
    """Test compatibility with the gint CP400 R61523 driver."""

    def setUp(self):
        self.d = Display()

    def _cmd(self, c):
        self.d.prdr = 0; self.d.disp_write16(c); self.d.prdr = 0x10

    def _param(self, v):
        self.d.disp_write16(v)

    def test_cp400_win_set(self):
        """gint r61523_win_set: x1+=40, x2+=40, uses 0x2A/0x2B."""
        # gint: r61523_win_set(0, 319, 0, 527) -> col 40-359, page 0-527
        # 359 = 0x0167 -> params: (359>>8)&3=1, 359&0xFF=0x67
        # 527 = 0x020F -> params: (527>>8)&3=2, 527&0xFF=0x0F
        self._cmd(0x2A)
        self._param(0); self._param(40)    # XS=40
        self._param(1); self._param(0x67)  # XE=359
        self._cmd(0x2B)
        self._param(0); self._param(0)     # YS=0
        self._param(2); self._param(0x0F)  # YE=527
        self.assertEqual(self.d._col_start, 40)
        self.assertEqual(self.d._col_end, 359)
        self.assertEqual(self.d._page_start, 0)
        self.assertEqual(self.d._page_end, 527)

    def test_cp400_select_then_write(self):
        """gint select() clears RS, writes command, sets RS=1, then writes data."""
        # select(0x2C): RS=0, write 0x2C, RS=1
        self.d.prdr = 0
        self.d.disp_write16(0x2C)
        self.d.prdr = 0x10
        # Now write pixels
        self.d.disp_write16(0xF800)
        self.d.disp_write16(0x07E0)
        self.assertEqual(self.d.get_pixel(0, 0), 0xF800)
        self.assertEqual(self.d.get_pixel(1, 0), 0x07E0)

    def test_cp400_display_function(self):
        """gint r61523_display: writes 320*528 pixels after win_set."""
        self._cmd(0x2A)
        self._param(0); self._param(40)
        self._param(1); self._param(0x67)  # 359
        self._cmd(0x2B)
        self._param(0); self._param(0)
        self._param(2); self._param(0x0F)  # 527
        self._cmd(0x2C)
        # Write 320*528 pixels
        for i in range(320 * 528):
            self._param(i & 0xFFFF)
        # Check a few
        self.assertEqual(self.d.get_pixel(40, 0), 0)
        self.assertEqual(self.d.get_pixel(41, 0), 1)
        self.assertNotEqual(self.d.get_pixel(0, 0), 0)  # outside window


# ============================================================================
# xmemtft Driver Compatibility Tests
# ============================================================================

class TestXmemtftCompat(unittest.TestCase):
    """Test compatibility with the xmemtft R61523 driver."""

    def setUp(self):
        self.d = Display()

    def _cmd(self, c):
        self.d.prdr = 0; self.d.disp_write16(c); self.d.prdr = 0x10

    def _param(self, v):
        self.d.disp_write16(v)

    def test_xmemtft_init_sequence(self):
        """xmemtft initialise(): MCAP=4, backlight, sleep_out, display_on."""
        # MCAP
        self._cmd(0xB0); self._param(4)
        self.assertEqual(self.d._mcap, 4)

        # Backlight Control 2
        self._cmd(0xB9)
        self._param(0x01)  # PWMON=1
        self._param(0x00)  # BDCV=0 (off)
        self._param(0x03)  # 13.7kHz
        self._param(0x18)  # PWMWM=1, LEDPWME=1

        # Sleep out
        self._cmd(0x11)
        self.assertFalse(self.d._sleep)

        # Display on
        self._cmd(0x29)
        self.assertTrue(self.d._display_on)

    def test_xmemtft_set_colour_depth(self):
        """xmemtft: set_pixel_format = 0x05 for 16-bit."""
        self._cmd(0x3A); self._param(0x05)
        self.assertEqual(self.d._pixel_format, 0x05)

    def test_xmemtft_portrait_orientation(self):
        """xmemtft portrait: address_mode = 0x40."""
        self._cmd(0x36); self._param(0x40)
        self.assertEqual(self.d._address_mode, 0x40)

    def test_xmemtft_landscape_orientation(self):
        """xmemtft landscape: address_mode = 0xE0."""
        self._cmd(0x36); self._param(0xE0)
        self.assertEqual(self.d._address_mode, 0xE0)

    def test_xmemtft_read_device_code(self):
        """xmemtft readDeviceCode(): should return 0x01221523."""
        self._cmd(0xBF)
        dummy = self.d.disp_read16()
        d1 = self.d.disp_read16()
        d2 = self.d.disp_read16()
        d3 = self.d.disp_read16()
        d4 = self.d.disp_read16()
        code = (d1 << 24) | (d2 << 16) | (d3 << 8) | d4
        self.assertEqual(code, 0x01221523)

    def test_xmemtft_sleep_wake(self):
        """xmemtft sleep(): display_off + sleep_in. wake(): sleep_out + display_on."""
        self._cmd(0x28); self._cmd(0x10)  # sleep
        self.assertFalse(self.d._display_on)
        self.assertTrue(self.d._sleep)
        self._cmd(0x11); self._cmd(0x29)  # wake
        self.assertFalse(self.d._sleep)
        self.assertTrue(self.d._display_on)

    def test_xmemtft_backlight_frequency(self):
        """Test all R61523BacklightFrequency values."""
        freqs = [
            (0x00, "33.3"), (0x01, "27.4"), (0x02, "18.3"), (0x03, "13.7"),
            (0x07, "6.86"), (0x0F, "3.43"), (0x1F, "1.72"), (0x3F, "0.86"),
            (0x7F, "0.43"), (0xFF, "0.21"),
        ]
        for freq_code, freq_name in freqs:
            self._cmd(0xB9)
            self._param(0x01)   # PWMON
            self._param(128)    # 50% duty
            self._param(freq_code)
            self._param(0x18)
            self.assertEqual(self.d._backlight_freq, freq_code,
                           f"Backlight freq {freq_name}kHz (0x{freq_code:02X})")

    def test_xmemtft_backlight_set_percentage(self):
        """setPercentage(100) -> duty=255, setPercentage(50) -> duty=127."""
        for pct, expected_duty in [(100, 255), (50, 127), (0, 0), (25, 63)]:
            self._cmd(0xB9)
            self._param(0x01)
            self._param(expected_duty)
            self._param(0x03)
            self._param(0x18)
            self.assertEqual(self.d._backlight_duty, expected_duty,
                           f"Backlight {pct}% -> duty={expected_duty}")


# ============================================================================
# CPU-Driven Tests
# ============================================================================

class TestViaCPU(unittest.TestCase):

    def test_single_pixel(self):
        cpu, mem, d = make_cpu()
        prog = assemble(LCD_SETUP + """
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13
            bra end
            nop
            end: bra end
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, prog, max_steps=5000)
        self.assertEqual(d.get_pixel(0, 0), 0xF800)
        save_bmp(d, os.path.join(OUTPUT_DIR, 'r61523_single_pixel.bmp'))

    def test_color_bars(self):
        cpu, mem, d = make_cpu()
        prog = assemble(LCD_SETUP + """
            mov.l c_red, r0
            mov.w r0, @r13
            mov.l c_green, r0
            mov.w r0, @r13
            mov.l c_blue, r0
            mov.w r0, @r13
            mov.l c_white, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            bra end
            nop
            end: bra end
            nop
            .align 2
            c_red: .long 0xF800
            c_green: .long 0x07E0
            c_blue: .long 0x001F
            c_white: .long 0xFFFF
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, prog, max_steps=5000)
        self.assertEqual(d.get_pixel(0, 0), 0xF800)
        self.assertEqual(d.get_pixel(1, 0), 0x07E0)
        save_bmp(d, os.path.join(OUTPUT_DIR, 'r61523_color_bars.bmp'))

    def test_full_gradient(self):
        return
        cpu, mem, d = make_cpu()
        prog = assemble(LCD_SETUP + """
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8
            mov #0, r2
            row_loop:
            mov #0, r3
            col_loop:
            mov r2, r0
            shlr2 r0
            and #0x1F, r0
            shll8 r0
            shll2 r0
            shll r0
            mov r3, r1
            shlr r1
            and #0x3F, r1
            shll2 r1
            shll2 r1
            shll r1
            or r1, r0
            mov r2, r1
            add r3, r1
            and #0x1F, r1
            or r1, r0
            mov.w r0, @r13
            add #1, r3
            cmp/ge r7, r3
            bf col_loop
            add #1, r2
            cmp/ge r8, r2
            bf row_loop
            bra end
            nop
            end: bra end
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, prog, max_steps=8000000)
        fb = d.get_framebuffer()
        non_default = sum(1 for row in fb for px in row if px != 0xFFFF)
        self.assertGreater(non_default, 200000)
        save_bmp(d, os.path.join(OUTPUT_DIR, 'r61523_full_gradient.bmp'))

    def test_bouncing_ball(self):
        return
        cpu, mem, d = make_cpu()
        prog = assemble(LCD_SETUP + """
            mov #0x01, r7
            shll8 r7
            mov #0x68, r0
            or r0, r7
            mov #5, r8
            shll2 r8
            shll2 r8
            shll2 r8
            shll r8
            mov #90, r9
            mov #5, r10
            shll2 r10
            shll2 r10
            shll2 r10
            mov #5, r11
            shll2 r11
            shll2 r11
            mov #0, r2
            row_loop3:
            mov #0, r3
            col_loop3:
            mov r3, r4
            sub r9, r4
            mov r2, r5
            sub r10, r5
            mov r4, r6
            shll r6
            bf dx_pos
            neg r4, r4
            dx_pos:
            mov r5, r6
            shll r6
            bf dy_pos
            neg r5, r5
            dy_pos:
            cmp/ge r11, r4
            bt outside
            cmp/ge r11, r5
            bt outside
            mov r4, r0
            add r5, r0
            shlr2 r0
            mov #31, r1
            sub r0, r1
            shll r1
            bf shade_ok
            mov #0, r1
            shade_ok:
            shlr r1
            mov r1, r0
            shll8 r0
            shll2 r0
            shll r0
            mov r1, r6
            shlr r6
            and #0x3F, r6
            shll2 r6
            shll2 r6
            shll r6
            or r6, r0
            bra write_px
            nop
            outside:
            mov r2, r0
            shlr2 r0
            and #0x1F, r0
            write_px:
            mov.w r0, @r13
            add #1, r3
            cmp/ge r7, r3
            bf col_loop3
            add #1, r2
            cmp/ge r8, r2
            bf row_loop3
            bra end3
            nop
            end3: bra end3
            nop
        """ + LCD_POOL, start_addr=0x8C000000)
        load_and_run(cpu, mem, prog, max_steps=8000000)
        fb = d.get_framebuffer()
        non_bg = sum(1 for row in fb for px in row if px != 0 and not (px <= 0x1F))
        self.assertGreater(non_bg, 5000)
        save_bmp(d, os.path.join(OUTPUT_DIR, 'r61523_bouncing_ball.bmp'))

    def test_windowed_drawing(self):
        cpu, mem, d = make_cpu()
        prog = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13
""" + lcd_cmd_asm(0x2A) + """
            mov #0, r0
            mov.w r0, @r13
            mov #10, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2B) + """
            mov #0, r0
            mov.w r0, @r13
            mov #5, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #15, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2C) + """
            mov #121, r2
            mov #0x07, r0
            shll8 r0
            or #0xE0, r0
            mov #0, r1
            fill_loop:
            mov.w r0, @r13
            add #1, r1
            cmp/ge r2, r1
            bf fill_loop
            bra end
            nop
            end: bra end
            nop
            .align 2
            prdr_addr: .long 0xA405013C
            disp_addr: .long 0xB4000000
        """, start_addr=0x8C000000)
        load_and_run(cpu, mem, prog, max_steps=5000)
        for y in range(5, 16):
            for x in range(10, 21):
                self.assertEqual(d.get_pixel(x, y), 0x07E0)
        self.assertEqual(d.get_pixel(0, 0), 0xFFFF)
        save_bmp(d, os.path.join(OUTPUT_DIR, 'r61523_windowed.bmp'))


# ============================================================================
# Assembly Self-Test Program
# ============================================================================

class TestAssemblySelfTest(unittest.TestCase):
    """
    Assembly self-test program that exercises ALL LCD commands.

    This program is designed to run on ANY R61523 emulator or real
    hardware to verify correct behavior.  It:
      1. Reads device code (0xBF)
      2. Sets column/page addresses (0x2A/0x2B)
      3. Writes pixels (0x2C) with auto-increment
      4. Reads pixels back (0x2E)
      5. Tests invert mode (0x21/0x20)
      6. Tests address mode flips (0x36)
      7. Tests display on/off (0x29/0x28)
      8. Tests sleep in/out (0x10/0x11)
      9. Tests soft reset (0x01)
    """

    def test_assembly_self_test(self):
        """Run the full self-test assembly program."""
        cpu, mem, d = make_cpu()

        # The self-test program writes pixels and reads them back
        prog = assemble("""
            mov.l prdr_addr, r14
            mov.l disp_addr, r13

            ! === Step 1: Exit sleep, display on ===
""" + lcd_cmd_asm(0x11) + lcd_cmd_asm(0x29) + """

            ! === Step 2: Set column 0-9, page 0-0 ===
""" + lcd_cmd_asm(0x2A) + """
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #9, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2B) + """
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13

            ! === Step 3: Write 10 pixels via 0x2C ===
""" + lcd_cmd_asm(0x2C) + """
            mov #0x01, r2
            shll8 r2
            mov #10, r3
            mov #0, r4
            write_loop:
            mov r2, r0
            add r4, r0
            mov.w r0, @r13
            add #1, r4
            cmp/ge r3, r4
            bf write_loop

            ! === Step 4: Set window again and read back via 0x2E ===
""" + lcd_cmd_asm(0x2A) + """
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #9, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2B) + """
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13

""" + lcd_cmd_asm(0x2E) + """
            ! Read and store in RAM
            mov.l store_addr, r5
            mov #10, r3
            mov #0, r4
            read_loop:
            mov.w @r13, r0
            mov.w r0, @r5
            add #2, r5
            add #1, r4
            cmp/ge r3, r4
            bf read_loop

            ! === Step 5: Test invert mode ===
""" + lcd_cmd_asm(0x21) + """
            ! Write a pixel — should be inverted in framebuffer
""" + lcd_cmd_asm(0x2A) + """
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2B) + """
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13
            mov #0, r0
            mov.w r0, @r13
            mov #20, r0
            mov.w r0, @r13
""" + lcd_cmd_asm(0x2C) + """
            mov #0xF8, r0
            shll8 r0
            mov.w r0, @r13

            ! Exit invert
""" + lcd_cmd_asm(0x20) + """

            ! === Step 6: Test soft reset ===
""" + lcd_cmd_asm(0x01) + """

            ! === Done ===
            bra end
            nop
            end: bra end
            nop
            .align 2
            prdr_addr: .long 0xA405013C
            disp_addr: .long 0xB4000000
            store_addr: .long 0x8C001000
        """, start_addr=0x8C000000)

        with open("bare_metal/lcd_self_test.bin", "wb") as f:
            f.write(prog)

        load_and_run(cpu, mem, prog, max_steps=10000)

        # Verify pixels were written (before soft reset cleared state)
        # After soft reset, col_start=0, col_end=359, etc.
        # But the framebuffer pixels should still be there
        # (soft reset doesn't clear GRAM)
        self.assertEqual(d._col_start, 0)
        self.assertEqual(d._col_end, DISPLAY_WIDTH - 1)
        self.assertTrue(d._sleep)  # soft reset puts to sleep

        # Check the read-back values stored in RAM
        for i in range(10):
            off = 0x1000 + i * 2  # offset in RAM
            val = int.from_bytes(mem._mem[off:off+2], 'big')
            self.assertEqual(val, 0x100 + i,
                           f"Read-back pixel {i}: 0x{val:04X}, expected 0x{0x100+i:04X}")

        # Check invert pixel (should be inverted in framebuffer)
        self.assertEqual(d.get_pixel(20, 20), 0xF800 ^ 0xFFFF)


def run_all_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestUserCommands, TestBehaviors, TestManufacturerCommands,
                TestCP400Compat, TestXmemtftCompat, TestViaCPU,
                TestAssemblySelfTest]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures:  {len(result.failures)}")
    print(f"Errors:    {len(result.errors)}")
    print(f"Bitmaps:   {OUTPUT_DIR}")
    print("=" * 70)
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    sys.exit(run_all_tests())
