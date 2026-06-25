"""
Memory Viewer window for RuK.

A basic hex viewer with address navigation.  Shows memory contents as
hex bytes with an ASCII column.

TODO (for future expansion):
  - Byte size group: 1/2/4/8 byte units (changes grid spacing)
  - Format group: Hex/Dec/Signed Dec/Oct/Binary
  - Encoding group (linked with numeric): ASCII/SJIS/JIS/UTF-8/UTF-16/EUC
  - Numeric group (linked with encoding): Float/Double/16-fixed/32-fixed
  - Auto-refresh with configurable interval
  - Edit mode (click to edit bytes)
  - Search functionality
  - Goto address dialog
"""

import tkinter as tk
from tkinter import ttk

from ruk.gui.window import BaseWindow
from ruk.jcore.cpu import CPU


class MemoryViewerWindow(BaseWindow):
    """A basic hex memory viewer window."""

    def __init__(self, root: tk.Tk, cpu: CPU):
        super().__init__(title="Memory Viewer :: RuK", root=tk.Toplevel(root))
        self.cpu = cpu
        self._address = 0x80000000  # start viewing from ROM
        self._bytes_per_row = 16
        self._num_rows = 24
        self._auto_refresh = False
        self._after_id = None
        self._setup()

    def _setup(self):
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        # Toolbar
        toolbar = ttk.Frame(self.root)
        toolbar.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)

        # Address entry
        ttk.Label(toolbar, text="Addr:").pack(side=tk.LEFT, padx=2)
        self._addr_var = tk.StringVar(value=f"0x{self._address:08X}")
        addr_entry = ttk.Entry(toolbar, textvariable=self._addr_var, width=12)
        addr_entry.pack(side=tk.LEFT, padx=2)
        addr_entry.bind("<Return>", lambda e: self._goto())

        # Navigation buttons
        ttk.Button(toolbar, text="↑", command=self._page_up, width=3).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="↓", command=self._page_down, width=3).pack(side=tk.LEFT, padx=2)

        # Refresh
        ttk.Button(toolbar, text="Refresh", command=self._refresh, width=8).pack(side=tk.LEFT, padx=5)

        # Auto-refresh
        self._auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Auto", variable=self._auto_var,
                        command=self._toggle_auto).pack(side=tk.LEFT, padx=2)

        # Text widget for hex display
        self._text = tk.Text(self.root, font=('Consolas', 10), wrap=tk.NONE,
                             state=tk.DISABLED, width=80, height=self._num_rows)
        self._text.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Scrollbar
        scroll = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=self._text.yview)
        self._text.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky='ns')

        # Bind scroll wheel
        self._text.bind('<MouseWheel>', self._on_scroll)

        self.root.deiconify()
        self._refresh()

    def _goto(self):
        try:
            addr = int(self._addr_var.get(), 0)
            self._address = addr & 0xFFFFFFFF
            self._refresh()
        except ValueError:
            pass

    def _page_up(self):
        self._address = (self._address - self._bytes_per_row * self._num_rows) & 0xFFFFFFFF
        self._addr_var.set(f"0x{self._address:08X}")
        self._refresh()

    def _page_down(self):
        self._address = (self._address + self._bytes_per_row * self._num_rows) & 0xFFFFFFFF
        self._addr_var.set(f"0x{self._address:08X}")
        self._refresh()

    def _on_scroll(self, event):
        if event.delta > 0:
            self._address = (self._address - self._bytes_per_row) & 0xFFFFFFFF
        else:
            self._address = (self._address + self._bytes_per_row) & 0xFFFFFFFF
        self._addr_var.set(f"0x{self._address:08X}")
        self._refresh()

    def _refresh(self):
        """Read memory and display as hex dump."""
        self._text.config(state=tk.NORMAL)
        self._text.delete('1.0', tk.END)

        for row in range(self._num_rows):
            addr = (self._address + row * self._bytes_per_row) & 0xFFFFFFFF
            hex_parts = []
            ascii_parts = []

            for col in range(self._bytes_per_row):
                try:
                    val = self.cpu.mem.read8(addr + col)
                    if isinstance(val, bytes):
                        val = val[0] if len(val) > 0 else 0
                    hex_parts.append(f"{val:02X}")
                    if 0x20 <= val < 0x7F:
                        ascii_parts.append(chr(val))
                    else:
                        ascii_parts.append('.')
                except (IndexError, Exception):
                    hex_parts.append("??")
                    ascii_parts.append('?')

            # Format: "0x80000000: FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF  ................"
            hex_str = ' '.join(hex_parts)
            # Split hex into two groups of 8 for readability
            hex_str = hex_str[:23] + ' ' + hex_str[24:]
            ascii_str = ''.join(ascii_parts)
            line = f"0x{addr:08X}: {hex_str}  {ascii_str}\n"
            self._text.insert(tk.END, line)

        self._text.config(state=tk.DISABLED)

    def _toggle_auto(self):
        if self._auto_var.get():
            self._auto_refresh = True
            self._schedule_refresh()
        else:
            self._auto_refresh = False
            if self._after_id:
                self.root.after_cancel(self._after_id)
                self._after_id = None

    def _schedule_refresh(self):
        if self._auto_refresh:
            self._refresh()
            self._after_id = self.root.after(200, self._schedule_refresh)

    def setup_callbacks(self):
        pass

    def attach(self, cp):
        pass
