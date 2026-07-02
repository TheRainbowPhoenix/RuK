# Test Addin Sources for RuK Emulator

This folder contains C source code for test addins that can be compiled
with the gint SDK + fxsdk into .hh3 files, then loaded into the RuK
emulator to verify that the LCD, touchscreen, and other peripherals
work correctly.

## Prerequisites

To compile these addins you need:
- [gint](https://gitea.planet-casio.com/Lephenixnoir/gint)
- [fxsdk](https://gitea.planet-casio.com/Lephenixnoir/fxsdk)
- A SH4 cross-compiler (sh4a-nofpu-elf-gcc)

Install gint for the CP target first:
```bash
fxsdk new --platform cp test_screen
# ... copy the source from this folder ...
fxsdk build-cp
# Output: test_screen.hh3
```

## Tests

### test_screen.c
Draws a full-screen gradient (red gradient top-to-bottom, green
left-to-right, blue diagonal) to verify the R61523 LCD controller
works.  No touchscreen input needed.

### test_touch.c
Draws a crosshair at the current touch position.  Verifies that:
- PRDR touch detect (0xA405013C bit 5) works
- I2C register read from FT6206 (register 0x84) returns correct data
- Touch coordinates map to screen pixels

### test_hello.c
Minimal "Hello World" — writes a pattern to the LCD and loops.
Useful as a smoke test that the hh3 loader + symbol table + entry
point are all correct.

## Running in RuK

```bash
# Compile the addin (produces .hh3)
fxsdk build-cp

# Run in the RuK GUI
python3 run_gui.py
# Click "Open Addin" → select test_screen.hh3

# Or run headless
python3 run_hh3.py test_screen.hh3 1000000
```

## Notes

- These addins use the gint API (`dclear`, `dupdate`, `drect`, etc.)
  which talks to the R61523 LCD via the 0xB4000000 interface.
- The touchscreen test uses `touch_scan()` which reads PRDR + I2C.
- The addins are compiled as ET_EXEC ELF32 big-endian SH executables
  (.hh3 format), loaded by RuK's `ruk.jcore.hh3` module.
- RuK provides a synthetic HHK symbol table (see `hh3.py`) so that
  gint's `hhk3_entry()` doesn't panic.  All 16 syscalls point to a
  stub that returns 0 — file/memory operations will fail, but LCD
  and touch work since they talk to hardware directly.
