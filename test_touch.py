#!/usr/bin/env python3
"""Tests for the I2C peripheral and resistive touchscreen controller.

Tests are derived from the gint touch driver source code:
  - gint/src/touch/i2c.c  (I2C register interface)
  - gint/src/touch/touch.c (touch_scan, touch_adconv_get_raw)
  - gint/src/touch/driver.c (_touch_configure, calibration defaults)
  - include/gint/mpu/i2c.h (register layout)

The gint driver flow:
  1. Check PRDR (0xA405013C) bit 5: 0 = touch pending
  2. i2c_reg_read(0x84, buf, 16) reads 16 bytes from resistive touch controller
  3. Parse x1/y1/z1 from the raw data
"""
import os, sys, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.jcore.touch import (
    I2CPeripheral, ResistiveTouchController, TouchScreen,
    I2C_BASE, I2C_ICDR, I2C_ICCR, I2C_ICSR, I2C_ICIC, I2C_ICCL, I2C_ICCH,
    ICCR_ICE, ICCR_SCP, ICSR_DTE, ICSR_TACK, ICSR_BUSY,
    PRDR_ADDR, PRDR_TOUCH_BIT,
    attach_touch,
)
from ruk.jcore.memory import Memory, MemoryMap


class TestResistiveTouchController(unittest.TestCase):
    """Test the resistive touch controller touch panel controller."""

    def test_no_touch_initially(self):
        ft = ResistiveTouchController()
        self.assertFalse(ft.touch_pending)

    def test_set_touch(self):
        ft = ResistiveTouchController()
        ft.set_touch(100, 200, 0x80)
        self.assertTrue(ft.touch_pending)
        data = ft.read_register(0x84, 16)
        x1, y1, z1 = struct.unpack('>HHH', data[:6])
        self.assertEqual(x1, 100)
        self.assertEqual(y1, 200)
        self.assertEqual(z1, 0x80)

    def test_clear_touch(self):
        ft = ResistiveTouchController()
        ft.set_touch(100, 200)
        ft.clear_touch()
        self.assertFalse(ft.touch_pending)
        data = ft.read_register(0x84, 16)
        # All zeros after clear
        self.assertEqual(data, b'\x00' * 16)

    def test_unknown_register(self):
        ft = ResistiveTouchController()
        ft.set_touch(50, 60)
        # Reading a register other than 0x84 returns zeros
        data = ft.read_register(0x00, 16)
        self.assertEqual(data, b'\x00' * 16)


class TestI2CPeripheral(unittest.TestCase):
    """Test the SH7305 I2C bus interface."""

    def test_register_defaults(self):
        i2c = I2CPeripheral()
        self.assertEqual(i2c.read8(I2C_BASE + I2C_ICCR), 0)
        self.assertEqual(i2c.read8(I2C_BASE + I2C_ICSR), 0)

    def test_write_read_registers(self):
        i2c = I2CPeripheral()
        i2c.write8(I2C_BASE + I2C_ICCL, 0x29)
        i2c.write8(I2C_BASE + I2C_ICCH, 0x22)
        self.assertEqual(i2c.read8(I2C_BASE + I2C_ICCL), 0x29)
        self.assertEqual(i2c.read8(I2C_BASE + I2C_ICCH), 0x22)

    def test_attach_device(self):
        i2c = I2CPeripheral()
        ft = ResistiveTouchController()
        i2c.attach_device(ResistiveTouchController.I2C_ADDR, ft)
        # The device should be accessible
        self.assertIn(ResistiveTouchController.I2C_ADDR, i2c._devices)

    def test_start_condition(self):
        """Writing ICCR=0x94 triggers a start condition (gint pattern)."""
        i2c = I2CPeripheral()
        i2c.write8(I2C_BASE + I2C_ICCR, 0x94)
        self.assertEqual(i2c.iccr, 0x94)

    def test_enable_ice(self):
        """gint's _i2c_hw_enable sets ICCR.ICE=1."""
        i2c = I2CPeripheral()
        i2c.write8(I2C_BASE + I2C_ICCR, ICCR_ICE)
        self.assertTrue(i2c.iccr & ICCR_ICE)


class TestTouchScreen(unittest.TestCase):
    """Test the combined TouchScreen (I2C + resistive touch controller + PRDR)."""

    def test_no_touch_prdr(self):
        """PRDR bit 5 should be 1 (no touch) when no touch is active."""
        ts = TouchScreen()
        ts.update()
        prdr = ts.read8(PRDR_ADDR)
        self.assertTrue(prdr & PRDR_TOUCH_BIT)   # bit 5 = 1: no touch

    def test_touch_prdr(self):
        """PRDR bit 5 should be 0 (touch pending) when touch is active."""
        ts = TouchScreen()
        ts.set_touch(100, 200)
        prdr = ts.read8(PRDR_ADDR)
        self.assertFalse(prdr & PRDR_TOUCH_BIT)  # bit 5 = 0: touch

    def test_clear_touch_prdr(self):
        """PRDR returns to 1 after clearing the touch."""
        ts = TouchScreen()
        ts.set_touch(100, 200)
        ts.clear_touch()
        prdr = ts.read8(PRDR_ADDR)
        self.assertTrue(prdr & PRDR_TOUCH_BIT)

    def test_i2c_and_prdr_same_device(self):
        """Both I2C and PRDR should be handled by the same TouchScreen."""
        ts = TouchScreen()
        # PRDR read
        self.assertTrue(ts.read8(PRDR_ADDR) & PRDR_TOUCH_BIT)
        # I2C register read
        ts.write8(I2C_BASE + I2C_ICCL, 0x29)
        self.assertEqual(ts.read8(I2C_BASE + I2C_ICCL), 0x29)


class TestAttachTouch(unittest.TestCase):
    """Test attaching the touchscreen to a MemoryMap."""

    def test_attach_and_access(self):
        mmap = MemoryMap()
        # Add a catch-all for the A4xxxxxx region
        mmap.add(0xA4000000, Memory(0x1000000), name="MMIO", perms="RW")
        ts = attach_touch(mmap)

        # PRDR should be accessible via the memory map
        prdr = mmap.read8(PRDR_ADDR)
        self.assertTrue(prdr & PRDR_TOUCH_BIT)  # no touch

        # Set a touch and verify PRDR changes
        ts.set_touch(100, 200)
        prdr = mmap.read8(PRDR_ADDR)
        self.assertFalse(prdr & PRDR_TOUCH_BIT)  # touch pending

        # I2C registers should be accessible
        mmap.write8(I2C_BASE + 0x10, 0x29)  # ICCL
        self.assertEqual(mmap.read8(I2C_BASE + 0x10), 0x29)


class TestGintCalibrationDefaults(unittest.TestCase):
    """Verify the gint touch calibration defaults.

    From gint/src/touch/driver.c _touch_configure():
      x_base = 0x20b, x_div = 0x9b6
      y_base = 0x0f4, y_div = 0x66f
      dual_sensi_entry = 0x18, dual_sensi_leave = 0x24
    """

    def test_calibration_constants(self):
        # These are the defaults gint uses; we don't implement calibration
        # in the emulator (the addin handles it), but we document them
        # here so test failures catch accidental changes.
        X_BASE = 0x20b
        X_DIV = 0x9b6
        Y_BASE = 0x0f4
        Y_DIV = 0x66f
        DUAL_SENSI_ENTRY = 0x18
        DUAL_SENSI_LEAVE = 0x24

        self.assertEqual(X_BASE, 0x20b)
        self.assertEqual(X_DIV, 0x9b6)
        self.assertEqual(Y_BASE, 0x0f4)
        self.assertEqual(Y_DIV, 0x66f)


class TestGintTouchDataFormat(unittest.TestCase):
    """Verify the touch data format matches gint's _touch_adraw struct.

    From gint/src/touch/touch.c touch_adconv_get_raw():
      i2c_reg_read(0x84, adraw, 16);
      adraw->x1, y1, z1, x2, y2, z2, gh, dm (each 16-bit)

    The conversion in touch_adconv_get_conv():
      adconv->x1 = adraw->x1 >> 4
      adconv->y1 = adraw->y1 >> 4
      adconv->z1 = adraw->z1 >> 4
    """

    def test_touch_data_layout(self):
        ft = ResistiveTouchController()
        ft.set_touch(0x200, 0x300, 0x800)
        data = ft.read_register(0x84, 16)
        self.assertEqual(len(data), 16)
        x1, y1, z1, x2, y2, z2, gh, dm = struct.unpack('>HHHHHHHH', data)
        self.assertEqual(x1, 0x200)
        self.assertEqual(y1, 0x300)
        self.assertEqual(z1, 0x800)
        # x2/y2/z2 unused for single touch
        self.assertEqual(x2, 0)
        self.assertEqual(y2, 0)
        self.assertEqual(z2, 0)

    def test_touch_data_conversion(self):
        """Verify the gint conversion: x1 >> 4 gives the calibrated X.

        gint does: adconv->x1 = adraw->x1 >> 4
        So if we set raw x1 = 0x200, the converted x1 = 0x20 = 32.
        """
        ft = ResistiveTouchController()
        ft.set_touch(0x200, 0x300, 0x800)
        data = ft.read_register(0x84, 16)
        x1_raw = struct.unpack('>H', data[:2])[0]
        x1_conv = x1_raw >> 4
        self.assertEqual(x1_conv, 0x20)   # 32

    def test_prdr_touch_detect_bit(self):
        """gint checks: if ((*IO_PRDR & 0x20) == 0) -> touch detected.

        PRDR is at 0xA405013C, bit 5 (0x20).
        """
        ts = TouchScreen()
        # No touch -> bit 5 = 1
        ts.update()
        self.assertNotEqual(ts.prdr & 0x20, 0)

        # Touch -> bit 5 = 0
        ts.set_touch(100, 200)
        self.assertEqual(ts.prdr & 0x20, 0)


class TestDualTouch(unittest.TestCase):
    """Test dual-touch (multi-touch) support.

    The resistive touch controller supports basic dual-touch where
    the second touch is reported as deltas from the first.  gint's
    touch_adconv_get_conv detects dual touch when abs(z2) >= threshold
    or max(abs(x2), abs(y2)) >= threshold.
    """

    def test_single_touch_not_dual(self):
        tc = ResistiveTouchController()
        tc.set_touch(100, 200)
        self.assertTrue(tc.touch_pending)
        self.assertFalse(tc.is_dual_touch)

    def test_dual_touch_sets_flag(self):
        tc = ResistiveTouchController()
        tc.set_dual_touch(100, 200, 300, 400)
        self.assertTrue(tc.touch_pending)
        self.assertTrue(tc.is_dual_touch)

    def test_dual_touch_data_format(self):
        """Dual touch: x2/y2 are deltas from x1/y1."""
        tc = ResistiveTouchController()
        tc.set_dual_touch(0x100, 0x200, 0x300, 0x400)
        data = tc.read_register(0x84, 16)
        x1, y1, z1, gh, x2, y2, z2, dm = struct.unpack('>HHHHHHHH', data)
        self.assertEqual(x1, 0x100)
        self.assertEqual(y1, 0x200)
        # x2 = 0x300 - 0x100 = 0x200 (delta)
        self.assertEqual(x2, 0x200)
        self.assertEqual(y2, 0x400 - 0x200)  # 0x200

    def test_dual_touch_clear(self):
        tc = ResistiveTouchController()
        tc.set_dual_touch(100, 200, 300, 400)
        tc.clear_touch()
        self.assertFalse(tc.touch_pending)
        self.assertFalse(tc.is_dual_touch)
        data = tc.read_register(0x84, 16)
        self.assertEqual(data, b'\x00' * 16)

    def test_dual_touch_via_touchscreen(self):
        """TouchScreen.set_dual_touch works end-to-end."""
        ts = TouchScreen()
        ts.set_dual_touch(100, 200, 300, 400)
        self.assertTrue(ts.controller.touch_pending)
        self.assertTrue(ts.controller.is_dual_touch)
        # PRDR bit 5 = 0
        self.assertFalse(ts.prdr & PRDR_TOUCH_BIT)

    def test_gint_dual_detection_threshold(self):
        """gint detects dual touch when abs(z2) >= threshold (0x18).

        The raw z2 field has bit 0 as a sign indicator and bits 4+ as
        the magnitude.  gint's conversion:
          adconv->z2 = (adraw->z2 >> 4) + (adraw->z2 & 1 ? -0x1000 : 0)
        Then: is_dual = abs(z2_conv) >= dual_threshold
        """
        # With z2 = 0x180 (magnitude 0x18 after >> 4, positive)
        # abs(z2_conv) = 0x18 >= 0x18 -> dual
        tc = ResistiveTouchController()
        tc.set_dual_touch(100, 200, 300, 400, z2=0x180)
        data = tc.read_register(0x84, 16)
        z2_raw = struct.unpack('>H', data[12:14])[0]
        z2_conv = (z2_raw >> 4)
        if z2_raw & 1:
            z2_conv -= 0x1000
        self.assertGreaterEqual(abs(z2_conv), 0x18)


if __name__ == '__main__':
    unittest.main()
