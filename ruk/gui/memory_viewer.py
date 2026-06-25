"""
Enhanced Memory Viewer for RuK.

Features:
  - Byte size: 1/2/4/8 byte units (changes grid spacing)
  - Format: Hex/Dec/Signed Dec/Oct/Binary
  - Right column: ASCII/UTF-8/SJIS/JIS/EUC/UTF-16LE/UTF-16BE/Float/Double/16-fixed/32-fixed
  - Auto-refresh with configurable interval
  - Edit mode: grid-based editor mimicking hexdump layout
  - Search functionality with Next/Prev navigation
  - Goto address dialog
"""

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import struct

from ruk.gui.window import BaseWindow
from ruk.jcore.cpu import CPU


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------

def _signed(val: int, bits: int) -> int:
    mask = 1 << (bits - 1)
    if val & mask:
        return val - (1 << bits)
    return val


# Fixed-width format specs: (width_chars, formatter)
FORMAT_SPECS = {
    ('Hex', 1):        (2,  lambda v: f"{v:02X}"),
    ('Hex', 2):        (4,  lambda v: f"{v:04X}"),
    ('Hex', 4):        (8,  lambda v: f"{v:08X}"),
    ('Hex', 8):        (16, lambda v: f"{v:016X}"),
    ('Dec', 1):        (3,  lambda v: f"{v:3d}"),
    ('Dec', 2):        (5,  lambda v: f"{v:5d}"),
    ('Dec', 4):        (10, lambda v: f"{v:10d}"),
    ('Dec', 8):        (20, lambda v: f"{v:20d}"),
    ('Signed Dec', 1): (4,  lambda v: f"{_signed(v,8):4d}"),
    ('Signed Dec', 2): (6,  lambda v: f"{_signed(v,16):6d}"),
    ('Signed Dec', 4): (11, lambda v: f"{_signed(v,32):11d}"),
    ('Signed Dec', 8): (20, lambda v: f"{_signed(v,64):20d}"),
    ('Oct', 1):        (3,  lambda v: f"{v:03o}"),
    ('Oct', 2):        (6,  lambda v: f"{v:06o}"),
    ('Oct', 4):        (12, lambda v: f"{v:012o}"),
    ('Oct', 8):        (24, lambda v: f"{v:024o}"),
    ('Binary', 1):     (8,  lambda v: f"{v:08b}"),
    ('Binary', 2):     (16, lambda v: f"{v:016b}"),
    ('Binary', 4):     (32, lambda v: f"{v:032b}"),
    ('Binary', 8):     (64, lambda v: f"{v:064b}"),
}

RIGHT_COL_OPTIONS = [
    'ASCII', 'UTF-8', 'SJIS', 'JIS', 'EUC',
    'UTF-16LE', 'UTF-16BE',
    'Float', 'Double', '16-fixed', '32-fixed'
]

ENCODING_MAP = {
    'ASCII': 'ascii',
    'UTF-8': 'utf-8',
    'SJIS': 'shift_jis',
    'JIS': 'iso2022_jp',
    'EUC': 'euc_jp',
    'UTF-16LE': 'utf-16-le',
    'UTF-16BE': 'utf-16-be',
}


class MemoryViewerWindow(BaseWindow):
    """An enhanced hex/memory viewer with editing, formatting, and search."""

    BYTE_SIZES = [1, 2, 4, 8]
    FORMATS = ['Hex', 'Dec', 'Signed Dec', 'Oct', 'Binary']

    def __init__(self, root: tk.Tk, cpu: CPU):
        super().__init__(title="Memory Viewer :: RuK", root=tk.Toplevel(root))
        self.cpu = cpu
        self._address = 0x80000000
        self._bytes_per_row = 16
        self._num_rows = 24
        self._auto_refresh = False
        self._after_id = None
        self._refresh_interval = 200  # ms

        self._edit_mode = False
        self._edit_entries = []       # list of (addr, hex_entry, right_entry) per row
        self._edit_selected = None    # (addr, widget_type)

        # Settings
        self._byte_size = 1
        self._format_name = 'Hex'
        self._right_col = 'ASCII'

        # Search state
        self._search_pattern = b''
        self._search_results = []
        self._search_idx = -1

        self._setup()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _setup(self):
        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)

        # ---- Row 1: Navigation + Display settings ----
        toolbar1 = ttk.Frame(self.root)
        toolbar1.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=2)

        # Address
        ttk.Label(toolbar1, text="Addr:").pack(side=tk.LEFT, padx=2)
        self._addr_var = tk.StringVar(value=f"0x{self._address:08X}")
        addr_entry = ttk.Entry(toolbar1, textvariable=self._addr_var, width=12)
        addr_entry.pack(side=tk.LEFT, padx=2)
        addr_entry.bind("<Return>", lambda e: self._goto())
        ttk.Button(toolbar1, text="Goto", command=self._goto, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Navigation
        ttk.Button(toolbar1, text="↑", command=self._page_up, width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar1, text="↓", command=self._page_down, width=3).pack(side=tk.LEFT, padx=1)

        ttk.Separator(toolbar1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Byte size
        ttk.Label(toolbar1, text="Size:").pack(side=tk.LEFT, padx=2)
        self._size_var = tk.IntVar(value=1)
        size_combo = ttk.Combobox(toolbar1, textvariable=self._size_var,
                                   values=self.BYTE_SIZES, width=3, state='readonly')
        size_combo.pack(side=tk.LEFT, padx=2)
        size_combo.bind("<<ComboboxSelected>>", self._on_size_changed)

        # Format
        ttk.Label(toolbar1, text="Fmt:").pack(side=tk.LEFT, padx=2)
        self._fmt_var = tk.StringVar(value='Hex')
        fmt_combo = ttk.Combobox(toolbar1, textvariable=self._fmt_var,
                                  values=self.FORMATS, width=10, state='readonly')
        fmt_combo.pack(side=tk.LEFT, padx=2)
        fmt_combo.bind("<<ComboboxSelected>>", self._on_fmt_changed)

        # Right column (unified: encoding + numeric)
        ttk.Label(toolbar1, text="Right:").pack(side=tk.LEFT, padx=2)
        self._right_var = tk.StringVar(value='ASCII')
        right_combo = ttk.Combobox(toolbar1, textvariable=self._right_var,
                                    values=RIGHT_COL_OPTIONS, width=10, state='readonly')
        right_combo.pack(side=tk.LEFT, padx=2)
        right_combo.bind("<<ComboboxSelected>>", self._on_right_changed)

        ttk.Separator(toolbar1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Refresh
        ttk.Button(toolbar1, text="Refresh", command=self._refresh, width=8).pack(side=tk.LEFT, padx=2)
        self._auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar1, text="Auto", variable=self._auto_var,
                        command=self._toggle_auto).pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar1, text="Int(ms):").pack(side=tk.LEFT, padx=2)
        self._int_var = tk.StringVar(value="200")
        int_entry = ttk.Entry(toolbar1, textvariable=self._int_var, width=5)
        int_entry.pack(side=tk.LEFT, padx=2)
        int_entry.bind("<Return>", lambda e: self._on_interval_changed())

        # ---- Row 2: Tools + Edit toolbar ----
        toolbar2 = ttk.Frame(self.root)
        toolbar2.grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=2)

        ttk.Button(toolbar2, text="Edit Mode", command=self._toggle_edit, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar2, text="Search", command=self._search_dialog, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar2, text="Next", command=self._search_next, width=5).pack(side=tk.LEFT, padx=1)
        ttk.Button(toolbar2, text="Prev", command=self._search_prev, width=5).pack(side=tk.LEFT, padx=1)

        ttk.Separator(toolbar2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Edit info (hidden in view mode)
        self._edit_info = ttk.Label(toolbar2, text="")
        self._edit_info.pack(side=tk.LEFT, padx=10)
        self._edit_write_btn = ttk.Button(toolbar2, text="Write", command=self._edit_write, width=8)
        self._edit_write_btn.pack(side=tk.LEFT, padx=2)
        self._edit_cancel_btn = ttk.Button(toolbar2, text="Cancel", command=self._edit_cancel, width=8)
        self._edit_cancel_btn.pack(side=tk.LEFT, padx=2)
        self._edit_write_btn.pack_forget()
        self._edit_cancel_btn.pack_forget()

        # ---- Content area ----
        # View mode: single Text widget
        self._text = tk.Text(self.root, font=('Consolas', 10), wrap=tk.NONE,
                             state=tk.DISABLED, width=100, height=self._num_rows)
        self._text.grid(row=2, column=0, sticky='nsew', padx=5, pady=5)

        # Edit mode: scrollable frame with grid of Entry widgets
        self._edit_canvas = tk.Canvas(self.root, highlightthickness=0)
        self._edit_canvas.grid(row=2, column=0, sticky='nsew', padx=5, pady=5)
        self._edit_canvas.grid_remove()

        self._edit_frame = ttk.Frame(self._edit_canvas)
        self._edit_canvas.create_window((0, 0), window=self._edit_frame, anchor='nw')
        self._edit_frame.bind("<Configure>", lambda e: self._edit_canvas.configure(
            scrollregion=self._edit_canvas.bbox('all')))

        # Scrollbar (shared)
        scroll = ttk.Scrollbar(self.root, orient=tk.VERTICAL)
        scroll.grid(row=2, column=1, sticky='ns')
        self._text.configure(yscrollcommand=scroll.set)
        self._edit_canvas.configure(yscrollcommand=scroll.set)
        scroll.configure(command=self._on_scroll)

        # Bind scroll wheel
        self._text.bind('<MouseWheel>', self._on_mousewheel)
        self._edit_canvas.bind('<MouseWheel>', self._on_mousewheel)

        self.root.deiconify()
        self._refresh()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _goto(self):
        try:
            addr = int(self._addr_var.get(), 0)
            self._address = addr & 0xFFFFFFFF
            self._addr_var.set(f"0x{self._address:08X}")
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

    def _on_scroll(self, *args):
        if self._edit_mode:
            self._edit_canvas.yview(*args)
        else:
            self._text.yview(*args)

    def _on_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        step = self._bytes_per_row
        self._address = (self._address + delta * step) & 0xFFFFFFFF
        self._addr_var.set(f"0x{self._address:08X}")
        self._refresh()

    # ------------------------------------------------------------------
    # Settings callbacks
    # ------------------------------------------------------------------
    def _on_size_changed(self, event=None):
        self._byte_size = self._size_var.get()
        # Ensure bytes_per_row is a multiple of byte_size
        self._bytes_per_row = max(self._byte_size, (self._bytes_per_row // self._byte_size) * self._byte_size)
        if self._bytes_per_row == 0:
            self._bytes_per_row = self._byte_size
        self._refresh()

    def _on_fmt_changed(self, event=None):
        self._format_name = self._fmt_var.get()
        self._refresh()

    def _on_right_changed(self, event=None):
        self._right_col = self._right_var.get()
        self._refresh()

    def _on_interval_changed(self):
        try:
            self._refresh_interval = max(50, int(self._int_var.get()))
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _refresh(self):
        if self._edit_mode:
            self._refresh_edit()
        else:
            self._refresh_hex()

    def _refresh_hex(self):
        """Display stable, aligned hexdump."""
        self._text.config(state=tk.NORMAL)
        self._text.delete('1.0', tk.END)

        sz = self._byte_size
        row_bytes = self._bytes_per_row
        row_bytes = (row_bytes // sz) * sz
        if row_bytes == 0:
            row_bytes = sz

        # Get formatter
        fmt_key = (self._format_name, sz)
        if fmt_key not in FORMAT_SPECS:
            fmt_key = ('Hex', sz)
        width, fmt_fn = FORMAT_SPECS[fmt_key]

        # Build each row
        for row in range(self._num_rows):
            addr = (self._address + row * row_bytes) & 0xFFFFFFFF
            hex_parts = []
            right_parts = []

            for col in range(0, row_bytes, sz):
                cell_addr = (addr + col) & 0xFFFFFFFF
                try:
                    val = self._read_value(cell_addr, sz)
                    hex_str = fmt_fn(val)
                    hex_parts.append(hex_str)

                    # Right column interpretation
                    right_str = self._format_right(cell_addr, sz, val)
                    right_parts.append(right_str)
                except Exception:
                    hex_parts.append('?' * width)
                    right_parts.append('?')

            # Assemble line with fixed spacing
            addr_str = f"0x{addr:08X}"
            hex_str = ' '.join(hex_parts)
            right_str = ''.join(right_parts)

            # Pad right column to ensure alignment
            line = f"{addr_str}:  {hex_str:<{row_bytes//sz * (width+1)}}  |{right_str}|\n"
            self._text.insert(tk.END, line)

        self._text.config(state=tk.DISABLED)

    def _refresh_edit(self):
        """Build grid of Entry widgets mimicking hexdump."""
        # Clear existing entries
        for widget in self._edit_frame.winfo_children():
            widget.destroy()
        self._edit_entries = []

        sz = self._byte_size
        row_bytes = self._bytes_per_row
        row_bytes = (row_bytes // sz) * sz
        if row_bytes == 0:
            row_bytes = sz

        fmt_key = (self._format_name, sz)
        if fmt_key not in FORMAT_SPECS:
            fmt_key = ('Hex', sz)
        width, fmt_fn = FORMAT_SPECS[fmt_key]

        # Grid layout: col 0 = address, cols 1..N = hex values, col N+1 = spacer, col N+2..M = right values
        num_hex = row_bytes // sz
        hex_col_start = 1
        right_col_start = hex_col_start + num_hex + 1

        # Configure columns
        self._edit_frame.columnconfigure(0, minsize=90)  # Address
        for c in range(hex_col_start, right_col_start - 1):
            self._edit_frame.columnconfigure(c, minsize=width * 7 + 4)  # ~7px per char
        self._edit_frame.columnconfigure(right_col_start - 1, minsize=10)  # Spacer
        # Right column width depends on content type
        if self._right_col in ('Float', 'Double'):
            right_width = 120
        elif self._right_col in ('16-fixed', '32-fixed'):
            right_width = 100
        else:
            right_width = 12 * 7  # ~12 chars for text
        self._edit_frame.columnconfigure(right_col_start, minsize=right_width)

        for row in range(self._num_rows):
            addr = (self._address + row * row_bytes) & 0xFFFFFFFF

            # Address label
            addr_lbl = ttk.Label(self._edit_frame, text=f"0x{addr:08X}",
                                  font=('Consolas', 10))
            addr_lbl.grid(row=row, column=0, sticky='w', padx=2, pady=1)

            hex_entries_row = []
            right_entries_row = []

            for col in range(0, row_bytes, sz):
                cell_addr = (addr + col) & 0xFFFFFFFF
                c = hex_col_start + col // sz

                try:
                    val = self._read_value(cell_addr, sz)
                    hex_str = fmt_fn(val)
                except:
                    hex_str = '?' * width
                    val = 0

                # Hex entry
                hex_var = tk.StringVar(value=hex_str)
                hex_entry = tk.Entry(self._edit_frame, textvariable=hex_var,
                                      font=('Consolas', 10), width=width,
                                      justify='center', relief='flat',
                                      highlightthickness=1, highlightcolor='#4a9eff')
                hex_entry.grid(row=row, column=c, sticky='ew', padx=1, pady=1)
                hex_entry.bind('<Return>', lambda e, a=cell_addr, s=sz, v=hex_var: self._edit_hex_commit(a, s, v))
                hex_entry.bind('<FocusIn>', lambda e, a=cell_addr: self._on_edit_focus(a, 'hex'))
                hex_entries_row.append((cell_addr, hex_entry, hex_var))

                # Right column entry (one per value for numeric, one per row for string)
                if col == 0:
                    rc = right_col_start
                    try:
                        right_str = self._format_right_row(addr, row_bytes)
                    except:
                        right_str = '???'

                    right_var = tk.StringVar(value=right_str)
                    right_entry = tk.Entry(self._edit_frame, textvariable=right_var,
                                            font=('Consolas', 10), width=16,
                                            justify='left', relief='flat',
                                            highlightthickness=1, highlightcolor='#4a9eff')
                    right_entry.grid(row=row, column=rc, sticky='ew', padx=4, pady=1)
                    right_entry.bind('<Return>', lambda e, a=addr, rb=row_bytes, v=right_var: self._edit_right_commit(a, rb, v))
                    right_entry.bind('<FocusIn>', lambda e, a=addr: self._on_edit_focus(a, 'right'))
                    right_entries_row.append((addr, right_entry, right_var))

            self._edit_entries.append((addr, hex_entries_row, right_entries_row))

        self._edit_frame.update_idletasks()
        self._edit_canvas.configure(scrollregion=self._edit_canvas.bbox('all'))

    # ------------------------------------------------------------------
    # Read / format helpers
    # ------------------------------------------------------------------
    def _read_value(self, addr: int, size: int) -> int:
        if size == 1:
            v = self.cpu.mem.read8(addr)
            if isinstance(v, bytes):
                v = v[0] if len(v) > 0 else 0
            return v & 0xFF
        elif size == 2:
            v = self.cpu.mem.read16(addr)
            if isinstance(v, bytes):
                v = int.from_bytes(v, "big")
            return v & 0xFFFF
        elif size == 4:
            v = self.cpu.mem.read32(addr)
            if isinstance(v, bytes):
                v = int.from_bytes(v, "big")
            return v & 0xFFFFFFFF
        elif size == 8:
            hi = self.cpu.mem.read32(addr)
            lo = self.cpu.mem.read32((addr + 4) & 0xFFFFFFFF)
            if isinstance(hi, bytes):
                hi = int.from_bytes(hi, "big")
            if isinstance(lo, bytes):
                lo = int.from_bytes(lo, "big")
            return ((hi & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)
        return 0

    def _write_value(self, addr: int, size: int, val: int):
        val = int(val)
        if size == 1:
            self.cpu.mem.write8(addr, val & 0xFF)
        elif size == 2:
            self.cpu.mem.write16(addr, val & 0xFFFF)
        elif size == 4:
            self.cpu.mem.write32(addr, val & 0xFFFFFFFF)
        elif size == 8:
            self.cpu.mem.write32(addr, (val >> 32) & 0xFFFFFFFF)
            self.cpu.mem.write32((addr + 4) & 0xFFFFFFFF, val & 0xFFFFFFFF)

    def _format_right(self, addr: int, size: int, val: int) -> str:
        """Format a single value for the right column."""
        rc = self._right_col
        if rc in ENCODING_MAP:
            # For per-byte display in view mode
            try:
                raw = bytearray()
                for i in range(size):
                    b = self.cpu.mem.read8((addr + i) & 0xFFFFFFFF)
                    if isinstance(b, bytes):
                        b = b[0] if len(b) > 0 else 0
                    raw.append(b & 0xFF)
                if rc == 'ASCII':
                    return ''.join(chr(b) if 0x20 <= b < 0x7F else '.' for b in raw)
                else:
                    enc = ENCODING_MAP[rc]
                    s = raw.decode(enc, errors='replace')
                    return s.replace('\x00', ' ').replace('\n', ' ').replace('\r', ' ')
            except:
                return '?' * size
        elif rc == 'Float' and size == 4:
            try:
                b = struct.pack('>I', val & 0xFFFFFFFF)
                return f"{struct.unpack('>f', b)[0]:.6g}"
            except:
                return '???'
        elif rc == 'Double' and size == 8:
            try:
                b = struct.pack('>Q', val & 0xFFFFFFFFFFFFFFFF)
                return f"{struct.unpack('>d', b)[0]:.10g}"
            except:
                return '???'
        elif rc == '16-fixed' and size == 2:
            return f"{val / 256:.3f}"
        elif rc == '32-fixed' and size == 4:
            return f"{val / 65536:.5f}"
        else:
            return '·' * size

    def _format_right_row(self, addr: int, row_bytes: int) -> str:
        """Format the right column for a full row (edit mode)."""
        rc = self._right_col
        try:
            raw = bytearray()
            for i in range(row_bytes):
                b = self.cpu.mem.read8((addr + i) & 0xFFFFFFFF)
                if isinstance(b, bytes):
                    b = b[0] if len(b) > 0 else 0
                raw.append(b & 0xFF)

            if rc in ENCODING_MAP:
                if rc == 'ASCII':
                    return ''.join(chr(b) if 0x20 <= b < 0x7F else '.' for b in raw)
                else:
                    enc = ENCODING_MAP[rc]
                    s = raw.decode(enc, errors='replace')
                    return s.replace('\x00', ' ').replace('\n', ' ').replace('\r', ' ')
            elif rc == 'Float':
                vals = []
                for i in range(0, row_bytes, 4):
                    v = self._read_value((addr + i) & 0xFFFFFFFF, 4)
                    b = struct.pack('>I', v)
                    vals.append(f"{struct.unpack('>f', b)[0]:.4g}")
                return ' '.join(vals)
            elif rc == 'Double':
                vals = []
                for i in range(0, row_bytes, 8):
                    v = self._read_value((addr + i) & 0xFFFFFFFF, 8)
                    b = struct.pack('>Q', v)
                    vals.append(f"{struct.unpack('>d', b)[0]:.6g}")
                return ' '.join(vals)
            elif rc == '16-fixed':
                vals = []
                for i in range(0, row_bytes, 2):
                    v = self._read_value((addr + i) & 0xFFFFFFFF, 2)
                    vals.append(f"{v/256:.2f}")
                return ' '.join(vals)
            elif rc == '32-fixed':
                vals = []
                for i in range(0, row_bytes, 4):
                    v = self._read_value((addr + i) & 0xFFFFFFFF, 4)
                    vals.append(f"{v/65536:.4f}")
                return ' '.join(vals)
        except Exception:
            pass
        return '???'

    # ------------------------------------------------------------------
    # Edit mode
    # ------------------------------------------------------------------
    def _toggle_edit(self):
        self._edit_mode = not self._edit_mode
        if self._edit_mode:
            self._edit_btn_text = "View Mode"
            # Find the Edit Mode button and change its text
            for child in self.root.winfo_children():
                if isinstance(child, ttk.Frame):
                    for btn in child.winfo_children():
                        if isinstance(btn, ttk.Button) and btn.cget('text') == 'Edit Mode':
                            btn.configure(text='View Mode')
            self._text.grid_remove()
            self._edit_canvas.grid()
            self._edit_write_btn.pack(side=tk.LEFT, padx=2)
            self._edit_cancel_btn.pack(side=tk.LEFT, padx=2)
        else:
            for child in self.root.winfo_children():
                if isinstance(child, ttk.Frame):
                    for btn in child.winfo_children():
                        if isinstance(btn, ttk.Button) and btn.cget('text') == 'View Mode':
                            btn.configure(text='Edit Mode')
            self._edit_canvas.grid_remove()
            self._text.grid()
            self._edit_write_btn.pack_forget()
            self._edit_cancel_btn.pack_forget()
            self._edit_info.configure(text="")
            self._edit_selected = None
        self._refresh()

    def _on_edit_focus(self, addr, widget_type):
        self._edit_selected = (addr, widget_type)
        self._edit_info.configure(text=f"Selected: 0x{addr:08X}")

    def _edit_hex_commit(self, addr, size, var):
        """Parse hex entry and write to memory."""
        try:
            val_str = var.get().strip()
            if val_str.startswith('0x') or val_str.startswith('0X'):
                val = int(val_str, 16)
            elif val_str.startswith('0b') or val_str.startswith('0B'):
                val = int(val_str, 2)
            elif val_str.startswith('0') and len(val_str) > 1:
                val = int(val_str, 8)
            else:
                val = int(val_str, 10)
            self._write_value(addr, size, val)
            self._refresh()
        except Exception as e:
            messagebox.showerror("Edit Error", f"Invalid value: {e}")

    def _edit_right_commit(self, addr, row_bytes, var):
        """Parse right column entry and write to memory."""
        try:
            text = var.get()
            rc = self._right_col

            if rc in ENCODING_MAP:
                if rc == 'ASCII':
                    data = text.encode('ascii', errors='replace')
                else:
                    enc = ENCODING_MAP[rc]
                    data = text.encode(enc, errors='replace')
                for i, b in enumerate(data[:row_bytes]):
                    self.cpu.mem.write8((addr + i) & 0xFFFFFFFF, b)
            elif rc == 'Float':
                vals = text.split()
                for i, vstr in enumerate(vals):
                    if i * 4 >= row_bytes:
                        break
                    v = float(vstr)
                    b = struct.pack('>f', v)
                    u = int.from_bytes(b, 'big')
                    self._write_value((addr + i * 4) & 0xFFFFFFFF, 4, u)
            elif rc == 'Double':
                vals = text.split()
                for i, vstr in enumerate(vals):
                    if i * 8 >= row_bytes:
                        break
                    v = float(vstr)
                    b = struct.pack('>d', v)
                    u = int.from_bytes(b, 'big')
                    self._write_value((addr + i * 8) & 0xFFFFFFFF, 8, u)
            elif rc == '16-fixed':
                vals = text.split()
                for i, vstr in enumerate(vals):
                    if i * 2 >= row_bytes:
                        break
                    v = int(float(vstr) * 256)
                    self._write_value((addr + i * 2) & 0xFFFFFFFF, 2, v)
            elif rc == '32-fixed':
                vals = text.split()
                for i, vstr in enumerate(vals):
                    if i * 4 >= row_bytes:
                        break
                    v = int(float(vstr) * 65536)
                    self._write_value((addr + i * 4) & 0xFFFFFFFF, 4, v)

            self._refresh()
        except Exception as e:
            messagebox.showerror("Edit Error", f"Invalid value: {e}")

    def _edit_write(self):
        if self._edit_selected is None:
            messagebox.showinfo("Edit", "Click a cell first, then press Enter or click Write.")
            return
        addr, wtype = self._edit_selected
        # Find the entry and trigger its Return binding
        for row_addr, hex_entries, right_entries in self._edit_entries:
            if wtype == 'hex':
                for a, entry, var in hex_entries:
                    if a == addr:
                        entry.event_generate('<Return>')
                        return
            elif wtype == 'right':
                for a, entry, var in right_entries:
                    if a == addr:
                        entry.event_generate('<Return>')
                        return

    def _edit_cancel(self):
        self._edit_selected = None
        self._edit_info.configure(text="")
        self._refresh()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _search_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Search Memory")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("400x200")

        ttk.Label(dlg, text="Pattern (hex: '48 65 6C 6C 6F' or text: 'Hello'):").pack(padx=10, pady=5)
        pattern_var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=pattern_var, width=40)
        entry.pack(padx=10, pady=5)
        entry.focus()

        type_frame = ttk.Frame(dlg)
        type_frame.pack(padx=10, pady=5)
        search_type = tk.StringVar(value='hex')
        ttk.Radiobutton(type_frame, text="Hex bytes", variable=search_type, value='hex').pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="ASCII text", variable=search_type, value='ascii').pack(side=tk.LEFT, padx=5)

        range_frame = ttk.Frame(dlg)
        range_frame.pack(padx=10, pady=5)
        ttk.Label(range_frame, text="Start:").pack(side=tk.LEFT)
        start_var = tk.StringVar(value=self._addr_var.get())
        ttk.Entry(range_frame, textvariable=start_var, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Label(range_frame, text="Size:").pack(side=tk.LEFT)
        size_var = tk.StringVar(value="0x10000")
        ttk.Entry(range_frame, textvariable=size_var, width=12).pack(side=tk.LEFT, padx=5)

        def do_search():
            pattern = pattern_var.get().strip()
            if not pattern:
                return
            try:
                start = int(start_var.get(), 0)
                size = int(size_var.get(), 0)
            except ValueError:
                messagebox.showerror("Error", "Invalid address or size")
                return

            if search_type.get() == 'hex':
                hex_str = pattern.replace(' ', '').replace('0x', '')
                try:
                    self._search_pattern = bytes.fromhex(hex_str)
                except ValueError:
                    messagebox.showerror("Error", "Invalid hex pattern")
                    return
            else:
                self._search_pattern = pattern.encode('ascii', errors='replace')

            if len(self._search_pattern) == 0:
                messagebox.showerror("Error", "Empty pattern")
                return

            self._search_results = []
            self._search_idx = -1

            for offset in range(size - len(self._search_pattern) + 1):
                addr = (start + offset) & 0xFFFFFFFF
                match = True
                for i, b in enumerate(self._search_pattern):
                    try:
                        val = self.cpu.mem.read8((addr + i) & 0xFFFFFFFF)
                        if isinstance(val, bytes):
                            val = val[0] if len(val) > 0 else 0
                        if (val & 0xFF) != b:
                            match = False
                            break
                    except:
                        match = False
                        break
                if match:
                    self._search_results.append(addr)

            dlg.destroy()
            if self._search_results:
                self._search_idx = 0
                self._goto_search_result()
                messagebox.showinfo("Search", f"Found {len(self._search_results)} match(es)")
            else:
                messagebox.showinfo("Search", "No matches found")

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Search", command=do_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", lambda e: do_search())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _search_next(self):
        if not self._search_results:
            messagebox.showinfo("Search", "No search results. Use Search first.")
            return
        self._search_idx = (self._search_idx + 1) % len(self._search_results)
        self._goto_search_result()

    def _search_prev(self):
        if not self._search_results:
            messagebox.showinfo("Search", "No search results. Use Search first.")
            return
        self._search_idx = (self._search_idx - 1) % len(self._search_results)
        self._goto_search_result()

    def _goto_search_result(self):
        if 0 <= self._search_idx < len(self._search_results):
            addr = self._search_results[self._search_idx]
            self._address = addr & 0xFFFFFFFF
            self._addr_var.set(f"0x{self._address:08X}")
            self._refresh()

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------
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
            self._after_id = self.root.after(self._refresh_interval, self._schedule_refresh)

    def setup_callbacks(self):
        pass

    def attach(self, cp):
        pass