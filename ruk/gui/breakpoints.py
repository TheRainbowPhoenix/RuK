"""
Breakpoints window for RuK debugger.

Shows a list of all breakpoints (software and hardware) and allows
adding, editing, and deleting them.

Software breakpoints are unlimited and checked by the emulator before
each CPU step.  Hardware breakpoints use the UBC (User Break
Controller) and are limited to 2 channels per CPU specs.
"""

import tkinter as tk
from tkinter import ttk, messagebox


class BreakpointsWindow:
    """A window for managing breakpoints."""

    def __init__(self, root: tk.Tk, control_ctrl):
        """Create the breakpoints window.

        Args:
            root: The parent Tk root.
            control_ctrl: The ControlsFrame instance that manages
                          breakpoints.
        """
        self._control = control_ctrl
        self._root = tk.Toplevel(root)
        self._root.title("Breakpoints :: RuK")
        self._root.geometry("500x400")
        self._root.transient(root)
        self._root.grab_set()

        self._setup()

    def _setup(self):
        """Set up the window widgets."""
        # Toolbar
        toolbar = ttk.Frame(self._root)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="Add Soft", command=self._add_soft).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Add Hardware", command=self._add_hw).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete", command=self._delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Refresh", command=self._refresh_list).pack(side=tk.LEFT, padx=2)

        # Breakpoints list
        columns = ("addr", "type", "channel")
        self._tree = ttk.Treeview(self._root, columns=columns, show='headings', height=15)
        self._tree.heading("addr", text="Address")
        self._tree.heading("type", text="Type")
        self._tree.heading("channel", text="Channel")
        self._tree.column("addr", width=150)
        self._tree.column("type", width=100)
        self._tree.column("channel", width=100)
        self._tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Add a scrollbar
        scrollbar = ttk.Scrollbar(self._root, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind double-click to edit
        self._tree.bind('<Double-1>', self._edit_selected)

        self._refresh_list()

    def _refresh_list(self):
        """Refresh the breakpoints list."""
        # Clear existing items
        for item in self._tree.get_children():
            self._tree.delete(item)

        # Add all breakpoints
        bps = self._control.get_all_breakpoints()
        for addr in sorted(bps.keys()):
            btype = bps[addr]
            if btype == 'hw':
                channel = self._control._hw_breakpoints.get(addr, '?')
            else:
                channel = '-'
            self._tree.insert('', tk.END, values=(f"0x{addr:08X}", btype, str(channel)))

    def _add_soft(self):
        """Add a software breakpoint."""
        addr = self._prompt_address("Add Software Breakpoint")
        if addr is not None:
            self._control.add_soft_breakpoint(addr)
            self._refresh_list()

    def _add_hw(self):
        """Add a hardware breakpoint."""
        addr = self._prompt_address("Add Hardware Breakpoint")
        if addr is not None:
            ch = self._control.add_hw_breakpoint(addr)
            if ch < 0:
                messagebox.showerror("Error",
                    "Both hardware breakpoint channels are in use.\n"
                    "The SH-4 UBC supports only 2 hardware breakpoints.\n"
                    "Delete an existing hardware breakpoint first.")
            else:
                self._refresh_list()

    def _delete_selected(self):
        """Delete the selected breakpoint."""
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        addr_str = item['values'][0]
        # Parse address (might be a string like "0x80000000" or an int)
        if isinstance(addr_str, str):
            addr = int(addr_str, 16) if addr_str.startswith('0x') else int(addr_str)
        else:
            addr = int(addr_str)

        btype = item['values'][1]
        if btype == 'hw':
            self._control.remove_hw_breakpoint(addr)
        else:
            self._control.remove_soft_breakpoint(addr)
        self._refresh_list()

    def _edit_selected(self, event):
        """Edit the selected breakpoint (currently just shows info)."""
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        addr_str = item['values'][0]
        btype = item['values'][1]
        messagebox.showinfo("Breakpoint Info",
            f"Address: {addr_str}\n"
            f"Type: {btype}\n"
            f"Use Delete to remove, or Clear All to remove all breakpoints.")

    def _clear_all(self):
        """Clear all breakpoints."""
        if messagebox.askyesno("Confirm", "Delete all breakpoints?"):
            self._control.clear_all_breakpoints()
            self._refresh_list()

    def _prompt_address(self, title):
        """Show a dialog prompting for an address.

        Returns the address as an int, or None if cancelled.
        """
        dialog = tk.Toplevel(self._root)
        dialog.title(title)
        dialog.geometry("300x120")
        dialog.transient(self._root)
        dialog.grab_set()

        ttk.Label(dialog, text="Address (hex, e.g. 0x80000000):").pack(pady=5)

        var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=var, width=30)
        entry.pack(pady=5)
        entry.focus_set()

        result = [None]

        def on_ok():
            try:
                addr_str = var.get().strip()
                if addr_str.startswith('0x') or addr_str.startswith('0X'):
                    addr = int(addr_str, 16)
                else:
                    addr = int(addr_str, 16)  # default to hex
                result[0] = addr
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid address format")

        def on_cancel():
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=5)

        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())

        self._root.wait_window(dialog)
        return result[0]
