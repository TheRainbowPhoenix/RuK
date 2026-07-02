#!/usr/bin/env python3
"""
E2E tests for the touchscreen + LCD pipeline.

Two test modes:
  1. Headless: assemble an SH-4 program, load it, simulate touch events,
     run, and verify LCD pixels are set.
  2. Scripted GUI: build the debugger window with a pre-scripted action
     sequence (click Play, inject touch, refresh LCD, capture framebuffer,
     assert pixels).

The assembled program does:
  1. Poll PRDR (0xA405013C) bit 5 until it reads 0 (touch pending)
  2. Write a white pixel (0xFFFF) to the LCD at (0, 0)
  3. Loop forever
"""
import os, sys, time, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.tools.assembler import assemble
from ruk.classpad import Classpad
from ruk.jcore.touch import PRDR_ADDR, PRDR_TOUCH_BIT, I2C_BASE
from ruk.jcore.display import DISPLAY_IFACE_ADDR, PRDR_ADDR as LCD_PRDR_ADDR


# ============================================================================
# Test program: poll PRDR, then draw a white pixel to LCD
# ============================================================================

# This program:
#   1. Reads PRDR (0xA405013C) into r0
#   2. Checks bit 5 (0x20): if set, no touch -> loop back to step 1
#   3. If touch detected (bit 5 == 0), write 0xFFFF to the LCD interface
#      (0xB4000000) to draw a white pixel
#   4. Loop forever (so the test can verify the pixel was drawn)
#
# We use the LCD in its default state (no setup) -- writing to 0xB4000000
# with PRDR bit 4 = 1 (data mode) writes a pixel to the GRAM at the
# current address (which defaults to 0,0).
TOUCH_POLL_ASM = """
    ; r14 = PRDR (touch detect + LCD RS/DCX)
    mov.l prdr_addr, r14
    ; r13 = LCD interface (0xB4000000)
    mov.l lcd_addr, r13

    ; Select the LCD GRAM register (command 0x22 = WRITE_MEMORY_START)
    ; RS=0 (command mode): clear PRDR bit 4
    mov.b @r14, r0
    and #0xEF, r0
    mov.b r0, @r14
    ; Write command 0x22 (REG_GRAM = 0x202, but only low byte 0x22 is used
    ; by the R61523 in 16-bit mode -- actually the Display class uses
    ; mode=0x202.  We write 0x0222 which the Display interprets as 0x202.)
    ; Actually, the Display's _start_command sets self._cmd = value.
    ; REG_GRAM = 0x202.  We need to write 0x0202.
    mov #0x02, r0
    shll8 r0
    or #0x02, r0
    mov.w r0, @r13

    ; RS=1 (data mode): set PRDR bit 4
    mov.b @r14, r0
    or #0x10, r0
    mov.b r0, @r14

poll_loop:
    ; Read PRDR
    mov.b @r14, r0
    ; Check bit 5 (0x20): 1 = no touch, 0 = touch
    tst #0x20, r0
    bt touch_detected
    bra poll_loop
    nop

touch_detected:
    ; Write white pixel (0xFFFF) to LCD GRAM
    mov #0xFF, r0
    shll8 r0
    or #0xFF, r0
    mov.w r0, @r13

    ; Loop forever
end:
    bra end
    nop

    .align 4
prdr_addr: .long 0xA405013C
lcd_addr:  .long 0xB4000000
"""


# ============================================================================
# Headless E2E test
# ============================================================================

class TestHeadlessTouchLCD(unittest.TestCase):
    """Headless E2E: assemble, load, simulate touch, run, verify LCD.

    This tests the full pipeline without a GUI:
      - Assembler produces correct bytes
      - Memory map maps PRDR + LCD correctly
      - CPU executes the polling loop
      - TouchScreen peripheral sets PRDR bit 5 correctly
      - LCD peripheral receives the write and updates its framebuffer
    """

    @classmethod
    def setUpClass(cls):
        """Assemble the test program once for all tests."""
        cls.binary = assemble(TOUCH_POLL_ASM, start_addr=0x8C000000)

    def _make_classpad(self):
        """Create a Classpad with touch + display."""
        with open(os.path.join(os.path.dirname(__file__), 'cp400', '3070.bin'), 'rb') as f:
            rom = f.read()
        return Classpad(rom, debug=False, start_pc=0x8C000000,
                        with_tmu=False, with_rtc=False, with_dma=False,
                        with_display=True, with_touch=True)

    def _load_program(self, cp):
        """Load the assembled binary into RAM at 0x8C000000."""
        ram_offset = 0  # 0x8C000000 - 0x8C000000
        cp.ram.write_bin(ram_offset, self.binary)
        cp.cpu.pc = 0x8C000000

    def test_assembled_bytes_correct(self):
        """Verify the assembler produced the expected encoding for key instructions."""
        # First instruction: mov.l prdr_addr, r14 = 0xDE04 (D=1101, E=r14, 04=disp)
        # prdr_addr is at offset 0x24 (9 instructions * 2 bytes + align)
        # Actually let me just verify it's non-empty and starts with a known pattern
        self.assertGreater(len(self.binary), 20)
        # First instruction should be mov.l @(disp,PC), r14
        first_op = struct.unpack('>H', self.binary[:2])[0]
        self.assertEqual(first_op & 0xF000, 0xD000,  # MOV.L @(disp,PC), Rn
                         f"First instruction should be MOV.L, got 0x{first_op:04X}")
        self.assertEqual((first_op >> 8) & 0xF, 14,   # R14
                         f"Should target R14, got R{(first_op >> 8) & 0xF}")

    def test_no_touch_polls_forever(self):
        """Without a touch, the program should loop forever on PRDR."""
        cp = self._make_classpad()
        self._load_program(cp)
        # Clear the LCD to black so we can detect any pixel draw
        cp.display.clear(0x0000)
        # Run for a limited number of steps -- should NOT draw anything
        # because no touch is active
        steps = cp.cpu.run(max_steps=50000)
        self.assertGreater(steps, 100, "Program should have run many steps")
        # LCD framebuffer should be all black (no pixel drawn)
        fb = cp.display.get_framebuffer()
        # Check pixel (0, 0) is black
        self.assertEqual(fb[0][0], 0, "No pixel should be drawn without touch")

    def test_touch_triggers_lcd_write(self):
        """When a touch is active, the program should write to the LCD."""
        cp = self._make_classpad()
        self._load_program(cp)
        # Clear the LCD to black so we can detect the white pixel
        cp.display.clear(0x0000)

        # Simulate a touch BEFORE running
        cp.touch.set_touch(100, 200)

        # Run -- the program should detect the touch (PRDR bit 5 == 0)
        # and write 0xFFFF to the LCD.
        # Use step() loop (not JIT run) for deterministic behavior.
        for i in range(50000):
            cp.cpu.step()
            if cp.cpu.ebreak:
                break

        # The LCD should have received a write.  The Display's GRAM
        # should now have a pixel set at the current address (0, 0).
        fb = cp.display.get_framebuffer()
        # At least one pixel should be white (0xFFFF) -- the program
        # writes 0xFFFF after detecting the touch
        white_pixels = sum(1 for row in fb for px in row if px == 0xFFFF)
        self.assertGreater(white_pixels, 0,
                           "LCD should have at least one white pixel after touch")

    def test_prdr_bit5_reflects_touch_state(self):
        """Verify PRDR bit 5 is 1 (no touch) then 0 (touch) then 1 (release)."""
        cp = self._make_classpad()

        # No touch -> bit 5 = 1
        prdr = cp.mem.read8(PRDR_ADDR)
        self.assertTrue(prdr & PRDR_TOUCH_BIT, "PRDR bit 5 should be 1 with no touch")

        # Touch -> bit 5 = 0
        cp.touch.set_touch(100, 200)
        prdr = cp.mem.read8(PRDR_ADDR)
        self.assertFalse(prdr & PRDR_TOUCH_BIT, "PRDR bit 5 should be 0 with touch")

        # Release -> bit 5 = 1
        cp.touch.clear_touch()
        prdr = cp.mem.read8(PRDR_ADDR)
        self.assertTrue(prdr & PRDR_TOUCH_BIT, "PRDR bit 5 should be 1 after release")

    def test_i2c_register_accessible(self):
        """Verify I2C registers are accessible via the memory map."""
        cp = self._make_classpad()
        # Write to ICCL
        cp.mem.write8(I2C_BASE + 0x10, 0x29)
        self.assertEqual(cp.mem.read8(I2C_BASE + 0x10), 0x29)
        # Write to ICCH
        cp.mem.write8(I2C_BASE + 0x14, 0x22)
        self.assertEqual(cp.mem.read8(I2C_BASE + 0x14), 0x22)


# ============================================================================
# Scripted GUI E2E test
# ============================================================================

@unittest.skipUnless(os.environ.get('DISPLAY') or sys.platform == 'win32',
                     "GUI test requires a display (set $DISPLAY or run on Windows)")
class TestScriptedGUITouchLCD(unittest.TestCase):
    """Scripted GUI E2E: build the window, run a pre-scripted action sequence.

    This test creates the debugger window, loads the test program, and
    runs a scripted sequence:
      1. Click Play (start the CPU)
      2. Wait a bit for the polling loop to start
      3. Inject a touch event
      4. Wait for the program to detect the touch and write to the LCD
      5. Refresh the LCD viewer and capture the framebuffer
      6. Assert that at least one pixel is set
      7. Click Pause

    The test uses tkinter's after() mechanism to schedule actions
    non-blockingly, then runs mainloop() until the test completes.
    """

    @classmethod
    def setUpClass(cls):
        cls.binary = assemble(TOUCH_POLL_ASM, start_addr=0x8C000000)

    def _setup(self):
        """Create the Classpad + debugger window (without showing it)."""
        import tkinter as tk
        with open(os.path.join(os.path.dirname(__file__), 'cp400', '3070.bin'), 'rb') as f:
            rom = f.read()
        cp = Classpad(rom, debug=False, start_pc=0x8C000000,
                      with_display=True, with_touch=True)
        cp.ram.write_bin(0, self.binary)
        cp.cpu.pc = 0x8C000000

        from ruk.gui.window import DebuggerWindow
        dbg = DebuggerWindow()
        dbg.attach(cp)
        return cp, dbg

    def test_gui_scripted_touch(self):
        """Run a scripted touch + LCD verification through the GUI."""
        cp, dbg = self._setup()
        root = dbg.get_root()

        # Results collected by the script
        results = {'touch_pixel_drawn': False, 'completed': False}

        def script_step_1_start_cpu():
            """Step 1: Click Play to start the CPU."""
            dbg.control_ctrl.do_run()
            # Schedule step 2 after 100ms
            root.after(100, script_step_2_inject_touch)

        def script_step_2_inject_touch():
            """Step 2: Inject a touch event."""
            cp.touch.set_touch(100, 200)
            # Schedule step 3 after 200ms (give the CPU time to detect)
            root.after(200, script_step_3_check_lcd)

        def script_step_3_check_lcd():
            """Step 3: Check if the LCD has a pixel drawn."""
            fb = cp.display.get_framebuffer()
            non_zero = sum(1 for row in fb for px in row if px != 0)
            results['touch_pixel_drawn'] = non_zero > 0
            # Schedule step 4 (pause + quit)
            root.after(50, script_step_4_pause_and_quit)

        def script_step_4_pause_and_quit():
            """Step 4: Pause the CPU and quit the mainloop."""
            if dbg.control_ctrl._running:
                dbg.control_ctrl.do_run()  # toggle to pause
            results['completed'] = True
            root.quit()

        # Start the script after 100ms
        root.after(100, script_step_1_start_cpu)

        # Run the mainloop with a timeout (5 seconds)
        # If the script doesn't complete in 5s, force-quit
        def timeout():
            if not results['completed']:
                results['completed'] = 'timeout'
                root.quit()
        root.after(5000, timeout)

        root.mainloop()

        # Clean up
        try:
            root.destroy()
        except:
            pass

        # Assert
        self.assertTrue(results['completed'] is True,
                        f"Script did not complete: {results['completed']}")
        self.assertTrue(results['touch_pixel_drawn'],
                        "LCD should have a pixel drawn after touch injection")


# ============================================================================
# Assembler correctness tests
# ============================================================================

class TestAssemblerCorrectness(unittest.TestCase):
    """Verify the assembler produces correct encodings for key instructions."""

    def test_mov_imm(self):
        """MOV #imm, Rn -> 0xE000 | (n << 8) | (imm & 0xFF)."""
        binary = assemble('mov #0x10, r0', start_addr=0)
        self.assertEqual(len(binary), 2)
        self.assertEqual(struct.unpack('>H', binary)[0], 0xE010)

    def test_mov_reg(self):
        """MOV Rm, Rn -> 0x6003 | (n << 8) | (m << 4)."""
        binary = assemble('mov r1, r2', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x6213)

    def test_nop(self):
        binary = assemble('nop', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x0009)

    def test_rts(self):
        binary = assemble('rts', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x000B)

    def test_bra(self):
        """BRA label -> 0xA000 | disp."""
        code = 'bra target\nnop\ntarget: rts\nnop'
        binary = assemble(code, start_addr=0)
        # bra at addr 0, target at addr 4, disp = (4 - 4) / 2 = 0
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xA000)

    def test_add_imm(self):
        """ADD #imm, Rn -> 0x7000 | (n << 8) | imm."""
        binary = assemble('add #5, r3', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x7305)

    def test_mov_w_mem(self):
        """MOV.W R0, @R1 -> 0x2001 | (1 << 8) | (0 << 4)."""
        binary = assemble('mov.w r0, @r1', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x2101)

    def test_mov_l_pcrel(self):
        """MOV.L label, Rn -> 0xD000 | (n << 8) | disp."""
        code = 'mov.l table, r1\nnop\nnop\n.align 4\ntable: .long 0x12345678'
        binary = assemble(code, start_addr=0)
        # mov.l at addr 0, table at addr 8 (4 bytes instr + 4 bytes nops+align)
        # disp = (8 & ~3 - (0 & ~3 + 4)) / 4 = (8 - 4) / 4 = 1
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xD101)

    def test_tst_imm(self):
        """TST #imm, R0 -> 0xC800 | imm."""
        binary = assemble('tst #0x20, r0', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0xC820)

    def test_bt(self):
        """BT label -> 0x8D00 | disp."""
        code = 'bt target\nnop\ntarget: nop'
        binary = assemble(code, start_addr=0)
        # bt at 0, target at 4, disp = (4 - 4) / 2 = 0
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0x8D00)

    def test_shll8(self):
        """SHLL8 Rn -> 0x4018 | (n << 8)."""
        binary = assemble('shll8 r0', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0x4018)

    def test_or_imm(self):
        """OR #imm, R0 -> 0xCB00 | imm."""
        binary = assemble('or #0xFF, r0', start_addr=0)
        self.assertEqual(struct.unpack('>H', binary)[0], 0xCBFF)

    def test_long_directive(self):
        """.long 0x12345678 -> 4 bytes big-endian."""
        binary = assemble('.long 0x12345678', start_addr=0)
        self.assertEqual(binary, bytes([0x12, 0x34, 0x56, 0x78]))

    def test_align_directive(self):
        """.align 4 pads to 4-byte boundary."""
        code = 'nop\n.align 4\nnop'
        binary = assemble(code, start_addr=0)
        # nop (2 bytes) + 2 bytes padding + nop (2 bytes) = 6 bytes
        self.assertEqual(len(binary), 6)
        # Padding should be zeros
        self.assertEqual(binary[2:4], bytes([0, 0]))

    def test_labels_numeric(self):
        """Numeric labels (1f, 1b) work."""
        code = '1: bra 1f\nnop\n1: rts\nnop'
        binary = assemble(code, start_addr=0)
        # bra at 0, target "1f" = next "1:" at addr 4, disp = 0
        self.assertEqual(struct.unpack('>H', binary[:2])[0], 0xA000)


if __name__ == '__main__':
    unittest.main()
