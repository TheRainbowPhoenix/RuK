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
        memory_list: all memory maps
        """

        tree = ttk.Treeview(self.root, columns=("Offset Start", "Offset End", "Name", "Permission"), show="headings")
        tree.heading("Offset Start", text="Offset Start")
        tree.heading("Offset End", text="Offset End")
        tree.heading("Name", text="Name")
        tree.heading("Permission", text="Permission")

        tree.column("Offset Start", width=80)
        tree.column("Offset End", width=80)
        tree.column("Name", width=200)
        tree.column("Permission", width=80)

        print(self.cpu)

        maps = []

        for start, end, name, perms in self.cpu.mem.get_mapped_areas():
            maps.append({
                "Offset Start": f"0x{start:04X}",
                "Offset End": f"0x{end - 1:04X}",
                "Name": name,
                "Permission": perms
            })


        for m in maps:
            tree.insert("", "end", values=(m["Offset Start"], m["Offset End"], m["Name"], m["Permission"]))

        tree.grid(row=0, column=0, sticky='nsew')

        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky='ns')

        tree.columnconfigure(0, weight=1)
        tree.rowconfigure(0, weight=1)

        self.root.deiconify()


    def setup_callbacks(self):
        pass

    def attach(self, cp):
        pass


