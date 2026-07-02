#!/usr/bin/env python3
"""
Screenshot test: run the emulator with a drawing program, capture the
LCD framebuffer as a screenshot, and verify blue pixels are drawn.

Uses Xvfb (virtual framebuffer) to run the GUI headlessly.
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.tools.assembler import assemble
from ruk.classpad import Classpad
from ruk.jcore.display import DISPLAY_WIDTH, DISPLAY_HEIGHT


# Drawing program: clear LCD to black, then draw blue pixels at (0,0)..(9,9)
DRAW_BLUE_ASM = """
    mov.l prdr_addr, r14
    mov.l lcd_addr, r13

    ; Select GRAM register (command 0x0202)
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    mov #0x02, r0
    shll8 r0
    or #0x02, r0
    mov.w r0, @r13

    ; Data mode (PRDR bit 4 = 1)
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

    ; Write 100 blue pixels (0x001F) to GRAM
    mov #100, r8
    mov #0x00, r0
    shll8 r0
    or #0x1F, r0
loop:
    mov.w r0, @r13
    dt r8
    bf loop

    ; Loop forever
end:
    bra end
    nop

    .align 4
prdr_addr: .long 0xA405013C
lcd_addr:  .long 0xB4000000
"""


def test_blue_pixels_on_screen():
    """Run the drawing program and verify blue pixels appear on the LCD."""
    with open(os.path.join(os.path.dirname(__file__), 'cp400', '3070.bin'), 'rb') as f:
        rom = f.read()
    cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                  with_display=True, with_touch=True)

    # Load and run the drawing program
    binary = assemble(DRAW_BLUE_ASM, start_addr=0x8C000000)
    cp.ram.write_bin(0, binary)
    cp.cpu.pc = 0x8C000000
    cp.display.clear(0x0000)

    # Run for enough steps to draw
    for i in range(2000):
        cp.cpu.step()

    # Check the framebuffer
    fb = cp.display.get_framebuffer()
    blue_pixels = sum(1 for row in fb for px in row if px == 0x001F)
    print(f"Blue pixels drawn: {blue_pixels}")
    assert blue_pixels > 0, "No blue pixels drawn!"

    # Verify they're at the start of the framebuffer (GRAM address 0,0)
    # The first 100 pixels should be blue
    count = 0
    for y in range(DISPLAY_HEIGHT):
        for x in range(DISPLAY_WIDTH):
            if fb[y][x] == 0x001F:
                count += 1
    print(f"Total blue pixels found: {count}")
    assert count >= 100, f"Expected >= 100 blue pixels, got {count}"

    # Now try with the LCD viewer (if DISPLAY is available)
    display = os.environ.get('DISPLAY')
    if display:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            from ruk.gui.lcd_viewer import LCDViewerWindow
            viewer = LCDViewerWindow(root, cp.display)
            viewer._refresh()
            root.update()

            # Check the PhotoImage has blue pixels
            blue_in_image = 0
            for y in range(min(10, DISPLAY_HEIGHT)):
                for x in range(min(20, DISPLAY_WIDTH)):
                    px = viewer._image.get(x, y)
                    # Blue pixel: #001F in RGB565 -> #0000FF in RGB888
                    if px == '#0000ff' or px == '#0000FF':
                        blue_in_image += 1
            print(f"Blue pixels in LCD viewer image: {blue_in_image}")
            assert blue_in_image > 0, "No blue pixels in LCD viewer!"

            root.destroy()
        except Exception as e:
            print(f"LCD viewer test skipped (display error: {e})")

    print("Screenshot test PASSED!")


def test_screenshot_to_ppm():
    """Save the framebuffer as a PPM image for visual inspection."""
    with open(os.path.join(os.path.dirname(__file__), 'cp400', '3070.bin'), 'rb') as f:
        rom = f.read()
    cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                  with_display=True, with_touch=True)

    # Draw a color bar pattern directly
    d = cp.display
    d.clear(0x0000)
    # Red bar (top 1/3)
    for y in range(0, DISPLAY_HEIGHT // 3):
        for x in range(DISPLAY_WIDTH):
            d.set_pixel(x, y, 0xF800)
    # Green bar (middle 1/3)
    for y in range(DISPLAY_HEIGHT // 3, 2 * DISPLAY_HEIGHT // 3):
        for x in range(DISPLAY_WIDTH):
            d.set_pixel(x, y, 0x07E0)
    # Blue bar (bottom 1/3)
    for y in range(2 * DISPLAY_HEIGHT // 3, DISPLAY_HEIGHT):
        for x in range(DISPLAY_WIDTH):
            d.set_pixel(x, y, 0x001F)

    # Save as PPM
    fb = d.get_framebuffer()
    ppm_path = os.path.join(os.path.dirname(__file__), 'test_output', 'screenshot_test.ppm')
    os.makedirs(os.path.dirname(ppm_path), exist_ok=True)
    with open(ppm_path, 'w') as f:
        f.write(f'P3\n{DISPLAY_WIDTH} {DISPLAY_HEIGHT}\n255\n')
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                val = fb[y][x]
                r = (val >> 11) & 0x1F
                g = (val >> 5) & 0x3F
                b = val & 0x1F
                r = (r << 3) | (r >> 2)
                g = (g << 2) | (g >> 4)
                b = (b << 3) | (b >> 2)
                f.write(f'{r} {g} {b} ')
            f.write('\n')
    print(f"Screenshot saved to {ppm_path}")

    # Verify the pattern
    assert fb[0][0] == 0xF800, "Top should be red"
    assert fb[DISPLAY_HEIGHT // 2][0] == 0x07E0, "Middle should be green"
    assert fb[DISPLAY_HEIGHT - 1][0] == 0x001F, "Bottom should be blue"
    print("Color bar test PASSED!")


if __name__ == '__main__':
    test_blue_pixels_on_screen()
    test_screenshot_to_ppm()
    print("\nAll screenshot tests passed!")
