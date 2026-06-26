#!/usr/bin/env python3
"""
RuK SH4AL-DSP Emulator - GUI Launcher

Shows a PyCharm-style project picker first, then launches the debugger
with the selected configuration.

Usage:
    python3 run_gui.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # Show the project loader first
    from ruk.gui.project_loader import ProjectLoaderWindow

    loader = ProjectLoaderWindow()
    project = loader.show()

    if project is None:
        print("No project selected. Exiting.")
        return 0

    # Load the ROM
    with open(project.rom_path, 'rb') as f:
        rom = f.read()
    print(f"Loaded ROM: {project.rom_path} ({len(rom)} bytes)")

    # Create the Classpad with selected peripherals
    from ruk.classpad import Classpad
    cp = Classpad(rom, debug=False, start_pc=project.start_pc,
                  with_tmu=project.with_tmu, with_rtc=project.with_rtc,
                  with_dma=project.with_dma, with_display=project.with_display,
                  with_ubc=project.with_ubc)

    # Override SR
    cp.cpu.regs['sr'] = project.sr_value

    # Load add-in programs
    for addin in project.addins:
        if os.path.exists(addin.path):
            with open(addin.path, 'rb') as f:
                data = f.read()
            ram_offset = addin.load_addr - 0x8C000000
            if 0 <= ram_offset < len(cp.ram._mem) - len(data):
                cp.ram.write_bin(ram_offset, data)
                print(f"  Add-in loaded: {addin.path} at 0x{addin.load_addr:08X} ({len(data)} bytes)")
            else:
                print(f"  WARNING: Add-in {addin.path} doesn't fit at 0x{addin.load_addr:08X}")

    print(f"Starting at PC=0x{cp.cpu.pc:08X} SR=0x{cp.cpu.regs['sr']:08X}")

    # Launch the debugger window
    from ruk.gui.window import DebuggerWindow
    dbg = DebuggerWindow()
    dbg.attach(cp)
    dbg.show()

    return 0


if __name__ == '__main__':
    sys.exit(main())
