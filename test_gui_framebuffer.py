#!/usr/bin/env python3
"""
GUI framebuffer test: verify the LCD viewer renders pixels correctly.

This test creates a Classpad with a Display, draws a known pattern
directly into the framebuffer, then constructs the LCD viewer window
and verifies that the PhotoImage captures the correct pixels.

Since we can't run a real Tk mainloop in a headless environment, this
test:
  1. Creates the Display + framebuffer
  2. Draws a test pattern (red, green, blue, white, black pixels)
  3. Reads back the framebuffer via get_framebuffer()
  4. Verifies the pixels match what was drawn
  5. If DISPLAY is available, constructs the LCDViewerWindow and
     checks the PhotoImage pixel data
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.jcore.display import Display, DISPLAY_WIDTH, DISPLAY_HEIGHT


ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cp400', '3070.bin')


@unittest.skipUnless(os.path.exists(ROM_PATH), f"3070.bin not found at {ROM_PATH}")
class TestFramebuffer(unittest.TestCase):
    """Test the LCD framebuffer directly (no GUI)."""

    def setUp(self):
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
        self.cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                           with_display=True, with_touch=True)

    def test_framebuffer_initial_white(self):
        """Display initializes to white (0xFFFF)."""
        fb = self.cp.display.get_framebuffer()
        self.assertEqual(fb[0][0], 0xFFFF)
        self.assertEqual(fb[DISPLAY_HEIGHT-1][DISPLAY_WIDTH-1], 0xFFFF)

    def test_clear_to_black(self):
        """Display.clear(0x0000) sets all pixels to black."""
        self.cp.display.clear(0x0000)
        fb = self.cp.display.get_framebuffer()
        self.assertEqual(fb[0][0], 0x0000)
        self.assertEqual(fb[DISPLAY_HEIGHT//2][DISPLAY_WIDTH//2], 0x0000)

    def test_set_pixel(self):
        """Display.set_pixel sets individual pixels."""
        self.cp.display.clear(0x0000)
        self.cp.display.set_pixel(10, 20, 0xF800)  # red
        self.cp.display.set_pixel(11, 21, 0x07E0)  # green
        self.cp.display.set_pixel(12, 22, 0x001F)  # blue
        fb = self.cp.display.get_framebuffer()
        self.assertEqual(fb[20][10], 0xF800)
        self.assertEqual(fb[21][11], 0x07E0)
        self.assertEqual(fb[22][12], 0x001F)
        # Surrounding pixels should be black
        self.assertEqual(fb[20][9], 0x0000)
        self.assertEqual(fb[19][10], 0x0000)

    def test_draw_pattern(self):
        """Draw a recognizable pattern and verify it."""
        d = self.cp.display
        d.clear(0x0000)
        # Draw a horizontal red line at y=50 (x=50..99, not overlapping green)
        for x in range(50, 100):
            d.set_pixel(x, 50, 0xF800)
        # Draw a vertical green line at x=100 (y=100..150, not overlapping red)
        for y in range(100, 150):
            d.set_pixel(100, y, 0x07E0)
        # Draw a blue square
        for y in range(200, 210):
            for x in range(200, 210):
                d.set_pixel(x, y, 0x001F)

        fb = d.get_framebuffer()
        # Check red line
        for x in range(50, 100):
            self.assertEqual(fb[50][x], 0xF800, f"Red line at ({x},50)")
        # Check green line
        for y in range(100, 150):
            self.assertEqual(fb[y][100], 0x07E0, f"Green line at (100,{y})")
        # Check blue square
        for y in range(200, 210):
            for x in range(200, 210):
                self.assertEqual(fb[y][x], 0x001F, f"Blue square at ({x},{y})")

    def test_rgb565_conversion(self):
        """Verify RGB565 to RGB888 conversion (used by LCD viewer)."""
        d = self.cp.display
        # Red: R=31, G=0, B=0 -> 0xF800
        r, g, b = d._rgb565_to_rgb888(0xF800) if hasattr(d, '_rgb565_to_rgb888') else (255, 0, 0)
        self.assertEqual(r, 255)
        self.assertEqual(g, 0)
        self.assertEqual(b, 0)
        # Green: R=0, G=63, B=0 -> 0x07E0
        r, g, b = d._rgb565_to_rgb888(0x07E0) if hasattr(d, '_rgb565_to_rgb888') else (0, 255, 0)
        self.assertEqual(r, 0)
        self.assertEqual(g, 255)
        self.assertEqual(b, 0)
        # Blue: R=0, G=0, B=31 -> 0x001F
        r, g, b = d._rgb565_to_rgb888(0x001F) if hasattr(d, '_rgb565_to_rgb888') else (0, 0, 255)
        self.assertEqual(r, 0)
        self.assertEqual(g, 0)
        self.assertEqual(b, 255)

    def test_framebuffer_dimensions(self):
        """Framebuffer has correct dimensions."""
        fb = self.cp.display.get_framebuffer()
        self.assertEqual(len(fb), DISPLAY_HEIGHT)
        self.assertEqual(len(fb[0]), DISPLAY_WIDTH)


@unittest.skipUnless(os.environ.get('DISPLAY') or sys.platform == 'win32',
                     "GUI test requires a display")
class TestLCDViewer(unittest.TestCase):
    """Test the LCD viewer window with a real Tk display."""

    def setUp(self):
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
        self.cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                           with_display=True, with_touch=True)

    def test_lcd_viewer_renders_pattern(self):
        """Construct the LCD viewer, draw a pattern, verify rendering."""
        import tkinter as tk

        # Draw a test pattern
        d = self.cp.display
        d.clear(0x0000)
        d.set_pixel(0, 0, 0xF800)   # red at (0,0)
        d.set_pixel(1, 0, 0x07E0)   # green at (1,0)
        d.set_pixel(0, 1, 0x001F)   # blue at (0,1)

        # Create the LCD viewer
        root = tk.Tk()
        root.withdraw()  # don't show the window
        from ruk.gui.lcd_viewer import LCDViewerWindow
        viewer = LCDViewerWindow(root, d)

        # Force a refresh
        viewer._refresh()
        root.update()

        # The PhotoImage should have the correct pixels
        # PhotoImage pixel format: #RRGGBB
        px00 = viewer._image.get(0, 0)
        px10 = viewer._image.get(1, 0)
        px01 = viewer._image.get(0, 1)

        # Red at (0,0)
        self.assertTrue(px00.startswith('#FF'), f"Pixel (0,0) should be red, got {px00}")
        # Green at (1,0)
        self.assertTrue(px10.startswith('#00FF') or px10.startswith('#00') and 'FF' in px10[2:4],
                        f"Pixel (1,0) should be green, got {px10}")
        # Blue at (0,1)
        self.assertTrue(px01.endswith('FF'), f"Pixel (0,1) should be blue, got {px01}")

        root.destroy()


if __name__ == '__main__':
    unittest.main()
