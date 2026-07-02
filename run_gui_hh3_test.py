#!/usr/bin/env python3
"""
RuK GUI launcher with HH3 (Hollyhock-3) addin support.

Features:
  - File menu with "Open HH3..." to load .hh3 addins
  - Loads the OS ROM (cp400/3070.bin) automatically for the memory map
  - When an HH3 is opened, loads it via run_hh3() and jumps PC to the
    addin's entry point -- you can immediately see its disassembly in
    the debugger and run it with the Play button
  - The LCD viewer (toolbar "LCD" button) shows what the addin draws
  - Run uses the JIT for ~10-50x speedup over step-by-step

Usage:
    python3 run_gui.py                     # opens with OS ROM loaded
    python3 run_gui.py path/to/addin.hh3   # opens and loads the addin
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruk.classpad import Classpad
from ruk.gui.window import DebuggerWindow
from ruk.jcore.hh3 import run_hh3, parse_elf, get_metadata, HH3Error


# Default OS ROM path (relative to the project root)
ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'cp400', '3070.bin')


class RuKDebuggerWindow(DebuggerWindow):
    """DebuggerWindow with a File menu for loading HH3 addins."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._hh3_path = None

    def setup_workspace(self):
        super().setup_workspace()
        self._setup_menu()

    def _setup_menu(self):
        """Add a menu bar with File -> Open HH3."""
        menubar = tk.Menu(self.root)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open HH3...", command=self.open_hh3,
                              accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        self.root.config(menu=menubar)
        self.root.bind('<Control-o>', lambda e: self.open_hh3())

    def open_hh3(self):
        """Show a file dialog and load the selected .hh3 file."""
        initial_dir = os.path.dirname(self._hh3_path) if self._hh3_path else \
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hh3')
        path = filedialog.askopenfilename(
            title="Open HH3 addin",
            initialdir=initial_dir,
            filetypes=[
                ("HH3 addins", "*.hh3"),
                ("ELF files", "*.elf"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.load_hh3(path)

    def load_hh3(self, path: str):
        """Load an .hh3 file into the attached Classpad.

        - Parses the ELF header to show metadata in a dialog
        - Calls run_hh3() to load segments + set up CPU state (PC, SP, args)
        - Refreshes the disassembly view to show the entry point
        - Opens the LCD viewer so the user can see what the addin draws
        """
        if self._cp is None:
            messagebox.showerror("Error", "No Classpad attached")
            return

        try:
            with open(path, 'rb') as f:
                data = f.read()
            parsed = parse_elf(data)
            meta = get_metadata(parsed)
        except HH3Error as e:
            messagebox.showerror("HH3 load error", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read {path}:\n{e}")
            return

        # Load the addin -- this writes segments to memory and sets
        # PC/SP/argc/argv/envp.
        try:
            entry = run_hh3(self._cp, path,
                            argv=[os.path.basename(path)],
                            envp={'HHK_SYMBOL_TABLE': '0',
                                  'HHK_SYMBOL_TABLE_LEN': '0'})
        except Exception as e:
            messagebox.showerror("HH3 load error", str(e))
            return

        self._hh3_path = path

        # Refresh all GUI views so the user sees the new PC and registers
        self.refresh_all()

        # Open the LCD viewer so the user can watch the addin draw
        if hasattr(self.reg_ctrl_frame, 'show_lcd'):
            self.reg_ctrl_frame.show_lcd()

        # Show a info dialog with the addin's metadata
        info_lines = [f"Loaded: {os.path.basename(path)}",
                      f"Entry: 0x{entry:08X}",
                      f"Segments: {parsed['e_phnum']}"]
        for i, phdr in enumerate(parsed['phdrs']):
            if phdr['p_type'] == 1:  # PT_LOAD
                flags = ''
                if phdr['p_flags'] & 4: flags += 'R'
                if phdr['p_flags'] & 2: flags += 'W'
                if phdr['p_flags'] & 1: flags += 'X'
                info_lines.append(
                    f"  [{i}] 0x{phdr['p_vaddr']:08X} "
                    f"size=0x{phdr['p_memsz']:X} {flags}")
        if any(meta.values()):
            info_lines.append("")
            for k, v in meta.items():
                if v:
                    info_lines.append(f"{k}: {v}")
        info_lines.append("")
        info_lines.append("Click Play to run, or Step to single-step.")
        messagebox.showinfo("HH3 loaded", "\n".join(info_lines))


def make_classpad(rom_path: str = ROM_PATH) -> Classpad:
    """Create a Classpad with all peripherals for addin development."""
    if not os.path.exists(rom_path):
        raise FileNotFoundError(
            f"OS ROM not found at {rom_path}.  The OS ROM is needed for "
            f"the memory map even when running addins.")
    with open(rom_path, 'rb') as f:
        rom = f.read()
    return Classpad(
        rom, debug=False,
        with_tmu=True, with_rtc=True, with_dma=True,
        with_display=True, with_bsc=True, with_cpg=True,
    )


def main():
    # Parse args: optional path to an .hh3 file to load on startup
    hh3_path = None
    if len(sys.argv) > 1:
        hh3_path = sys.argv[1]
        if not os.path.exists(hh3_path):
            print(f"Error: {hh3_path} not found")
            sys.exit(1)

    # Set up the Classpad with the OS ROM
    try:
        cp = make_classpad()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Create the debugger window and attach the Classpad
    dbg = RuKDebuggerWindow()
    dbg.attach(cp)

    # If an HH3 was specified on the command line, load it now
    if hh3_path:
        # Defer the load until after the main loop starts so the window
        # is fully initialized
        def _load_on_start():
            try:
                dbg.load_hh3(hh3_path)
            except Exception as e:
                print(f"Error loading {hh3_path}: {e}")
        dbg.root.after(100, _load_on_start)

    dbg.show()


if __name__ == '__main__':
    main()
