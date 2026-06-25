import string
import tkinter as tk
from binascii import unhexlify
from tkinter import ttk

from ruk.gui.window import BaseWindow, ModalWindow
from ruk.jcore.cpu import CPU



class MemoryMapWindow(BaseWindow):
    def __init__(self, root: tk.Tk, cpu: CPU):
        super().__init__(title="Memory Map :: RuK")
        self.cpu = cpu

        self._setup()

    def _setup(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        """
        memory_list: all memory maps, including MMIO peripherals
        """

        tree = ttk.Treeview(self.root, columns=("Start", "End", "Name", "Perm", "Type"), show="headings")
        tree.heading("Start", text="Start Address")
        tree.heading("End", text="End Address")
        tree.heading("Name", text="Name")
        tree.heading("Perm", text="Perm")
        tree.heading("Type", text="Type")

        tree.column("Start", width=100)
        tree.column("End", width=100)
        tree.column("Name", width=200)
        tree.column("Perm", width=50)
        tree.column("Type", width=80)

        maps = []

        for start, end, name, perms in self.cpu.mem.get_mapped_areas():
            # Determine the type based on the address range
            mem_type = self._classify_region(start, end, name)
            maps.append({
                "Start": f"0x{start:08X}",
                "End": f"0x{end - 1:08X}",
                "Name": name,
                "Perm": perms,
                "Type": mem_type
            })

        for m in maps:
            tree.insert("", "end", values=(m["Start"], m["End"], m["Name"], m["Perm"], m["Type"]))

        tree.grid(row=0, column=0, sticky='nsew')

        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky='ns')

        tree.columnconfigure(0, weight=1)
        tree.rowconfigure(0, weight=1)

        self.root.deiconify()

    @staticmethod
    def _classify_region(start: int, end: int, name: str) -> str:
        """Classify a memory region as RAM, ROM, MMIO, etc."""
        if name in ("TMU", "ETMU"):
            return "MMIO (TMU)"
        if name == "RTC":
            return "MMIO (RTC)"
        if name == "UBC":
            return "MMIO (UBC)"
        if name == "DMA":
            return "MMIO (DMA)"
        if 0xA4490000 <= start <= 0xA44FFFFF:
            return "MMIO (Timer)"
        if 0xA44D0000 <= start <= 0xA44DFFFF:
            return "MMIO (ETMU)"
        if 0xA4130000 <= start <= 0xA413FFFF:
            return "MMIO (RTC)"
        if 0xFF200000 <= start <= 0xFF20FFFF:
            return "MMIO (UBC)"
        if 0xFE000000 <= start <= 0xFEFFFFFF:
            return "MMIO (Peripheral)"
        if 0xA4000000 <= start <= 0xA4FFFFFF:
            return "MMIO"
        if 0x80000000 <= start <= 0x9FFFFFFF:
            return "ROM (P1)"
        if 0xA0000000 <= start <= 0xBFFFFFFF:
            return "ROM (P2)"
        if 0x8C000000 <= start <= 0x8CFFFFFF:
            return "RAM (P1)"
        if 0xAC000000 <= start <= 0xACFFFFFF:
            return "RAM (P2)"
        if start < 0x100000:
            return "Null page"
        return "Unknown"

    def setup_callbacks(self):
        pass

    def attach(self, cp):
        pass

