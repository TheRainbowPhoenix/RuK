"""
Project Loader window for RuK emulator.

A PyCharm-style project picker.  The main window shows only the recent
projects list with two buttons: "New Project" (opens a full config modal)
and "Assemble & Run" (pick an .asm, assemble, launch).  Right-click on
the list gives context-menu options (Open, Remove, Refresh).

Usage:
    python3 run_gui.py
"""

import os
import sys
import time as _time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ruk.gui.project_config import (
    Project, AddIn, load_projects, save_projects,
    add_or_update_project, remove_project, get_config_dir
)
from ruk.gui.window import BaseWindow, ModalWindow


# ============================================================================
# New Project configuration dialog (modal)
# ============================================================================

class NewProjectDialog(ModalWindow):
    """Full configuration modal for creating/editing a project."""

    def __init__(self, parent: tk.Tk, project: Project = None):
        super().__init__(parent=parent, title="New Project" if project is None else "Edit Project")
        self.result: Project = None
        self._current_addins: list = []

        self.root.geometry("650x620")
        self.root.transient(parent)
        self.root.grab_set()

        self._build_ui()

        if project is not None:
            self._load_project(project)
        else:
            self._set_defaults()

        parent.wait_window(self.root)

    # ---- UI ----

    def _build_ui(self):
        top = self.root
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        # Scrollable body
        canvas = tk.Canvas(top, highlightthickness=0)
        scroll = ttk.Scrollbar(top, orient=tk.VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')

        self._build_fields(body)

        # Bottom button bar
        bar = ttk.Frame(top, padding=(10, 5))
        bar.grid(row=1, column=0, columnspan=2, sticky='ew')
        ttk.Button(bar, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="Save & Open", command=self._save).pack(side=tk.RIGHT, padx=4)

    def _build_fields(self, parent):
        row = 0
        parent.columnconfigure(1, weight=1)

        # --- General ---
        ttk.Label(parent, text="General", font=('Segoe UI', 11, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=8, pady=(8, 4))
        row += 1

        ttk.Label(parent, text="Project Name:").grid(row=row, column=0, sticky='w', padx=8, pady=2)
        self._name_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self._name_var).grid(row=row, column=1, sticky='ew', padx=8, pady=2)
        row += 1

        ttk.Label(parent, text="ROM / Program:").grid(row=row, column=0, sticky='w', padx=8, pady=2)
        rom_f = ttk.Frame(parent)
        rom_f.grid(row=row, column=1, sticky='ew', padx=8, pady=2)
        self._rom_var = tk.StringVar()
        ttk.Entry(rom_f, textvariable=self._rom_var).pack(side='left', fill='x', expand=True)
        ttk.Button(rom_f, text="Browse…", command=self._browse_rom).pack(side='left', padx=2)
        ttk.Button(rom_f, text="Assemble…", command=self._browse_asm_and_assemble).pack(side='left', padx=2)
        row += 1

        ttk.Label(parent, text="Start PC:").grid(row=row, column=0, sticky='w', padx=8, pady=2)
        self._pc_var = tk.StringVar(value="0x80000000")
        ttk.Entry(parent, textvariable=self._pc_var, width=22).grid(row=row, column=1, sticky='w', padx=8, pady=2)
        row += 1

        ttk.Label(parent, text="SR Value:").grid(row=row, column=0, sticky='w', padx=8, pady=2)
        self._sr_var = tk.StringVar(value="0x400001F0")
        ttk.Entry(parent, textvariable=self._sr_var, width=22).grid(row=row, column=1, sticky='w', padx=8, pady=2)
        row += 1

        # --- Peripherals ---
        ttk.Label(parent, text="Peripherals", font=('Segoe UI', 11, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=8, pady=(12, 4))
        row += 1

        pf = ttk.Frame(parent)
        pf.grid(row=row, column=0, columnspan=2, sticky='w', padx=8, pady=2)
        self._tmu_var = tk.BooleanVar(value=True)
        self._rtc_var = tk.BooleanVar(value=True)
        self._dma_var = tk.BooleanVar(value=True)
        self._disp_var = tk.BooleanVar(value=True)
        self._ubc_var = tk.BooleanVar(value=True)
        for i, (txt, var) in enumerate([("TMU", self._tmu_var), ("RTC", self._rtc_var),
                                         ("DMA", self._dma_var), ("Display", self._disp_var),
                                         ("UBC", self._ubc_var)]):
            ttk.Checkbutton(pf, text=txt, variable=var).grid(row=0, column=i, padx=6)
        row += 1

        # --- Add-in programs ---
        ttk.Label(parent, text="Add-in Programs", font=('Segoe UI', 11, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=8, pady=(12, 4))
        row += 1

        af = ttk.Frame(parent)
        af.grid(row=row, column=0, columnspan=2, sticky='nsew', padx=8, pady=2)
        parent.grid_rowconfigure(row, weight=1)

        self._addin_list = ttk.Treeview(af, columns=('path', 'addr', 'desc'),
                                        show='headings', height=4)
        self._addin_list.heading('path', text='File')
        self._addin_list.heading('addr', text='Load Address')
        self._addin_list.heading('desc', text='Description')
        self._addin_list.column('path', width=220)
        self._addin_list.column('addr', width=90)
        self._addin_list.column('desc', width=140)
        asc = ttk.Scrollbar(af, orient='vertical', command=self._addin_list.yview)
        self._addin_list.configure(yscrollcommand=asc.set)
        self._addin_list.pack(side='left', fill='both', expand=True)
        asc.pack(side='right', fill='y')
        row += 1

        ab = ttk.Frame(parent)
        ab.grid(row=row, column=0, columnspan=2, sticky='w', padx=8, pady=2)
        ttk.Button(ab, text="Add…", command=self._add_addin).pack(side='left', padx=2)
        ttk.Button(ab, text="Remove", command=self._remove_addin).pack(side='left', padx=2)
        row += 1

        # --- Assembly source ---
        ttk.Label(parent, text="Assembly Source (optional)", font=('Segoe UI', 11, 'bold')).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=8, pady=(12, 4))
        row += 1

        asf = ttk.Frame(parent)
        asf.grid(row=row, column=0, columnspan=2, sticky='ew', padx=8, pady=2)
        self._asm_var = tk.StringVar()
        ttk.Entry(asf, textvariable=self._asm_var).pack(side='left', fill='x', expand=True)
        ttk.Button(asf, text="Browse…", command=self._browse_asm).pack(side='left', padx=2)
        ttk.Button(asf, text="Assemble to .bin", command=self._do_assemble).pack(side='left', padx=2)
        row += 1

        # Info label
        self._info = ttk.Label(parent, text="", foreground='gray')
        self._info.grid(row=row, column=0, columnspan=2, sticky='w', padx=8, pady=6)
        row += 1

    # ---- defaults / load ----

    def _set_defaults(self):
        self._name_var.set("New Project")
        self._rom_var.set("")
        self._pc_var.set("0x80000000")
        self._sr_var.set("0x400001F0")

    def _load_project(self, p: Project):
        self._name_var.set(p.name)
        self._rom_var.set(p.rom_path)
        self._pc_var.set(f"0x{p.start_pc:08X}")
        self._sr_var.set(f"0x{p.sr_value:08X}")
        self._tmu_var.set(p.with_tmu)
        self._rtc_var.set(p.with_rtc)
        self._dma_var.set(p.with_dma)
        self._disp_var.set(p.with_display)
        self._ubc_var.set(p.with_ubc)
        self._current_addins = list(p.addins)
        for a in self._current_addins:
            self._addin_list.insert('', tk.END, values=(a.path, f"0x{a.load_addr:08X}", a.description))

    # ---- browse / assemble ----

    def _browse_rom(self):
        p = filedialog.askopenfilename(title="Select ROM / binary",
                                       filetypes=[("Binary", "*.bin"), ("ROM", "*.rom"), ("All", "*.*")])
        if p:
            self._rom_var.set(p)
            if not self._name_var.get() or self._name_var.get() == "New Project":
                self._name_var.set(os.path.splitext(os.path.basename(p))[0])

    def _browse_asm(self):
        p = filedialog.askopenfilename(title="Select assembly source",
                                       filetypes=[("Assembly", "*.asm *.s"), ("All", "*.*")])
        if p:
            self._asm_var.set(p)

    def _browse_asm_and_assemble(self):
        p = filedialog.askopenfilename(title="Select assembly to assemble",
                                       filetypes=[("Assembly", "*.asm *.s"), ("All", "*.*")])
        if p:
            self._asm_var.set(p)
            self._do_assemble()

    def _do_assemble(self):
        asm_path = self._asm_var.get().strip()
        if not asm_path or not os.path.exists(asm_path):
            messagebox.showerror("Error", "Select a valid assembly source file.", parent=self.root)
            return
        try:
            with open(asm_path, 'r') as f:
                code = f.read()
            from ruk.tools.assembler import assemble
            start = int(self._pc_var.get(), 0)
            binary = assemble(code, start_addr=start)
            bin_path = os.path.splitext(asm_path)[0] + '.bin'
            with open(bin_path, 'wb') as f:
                f.write(binary)
            self._rom_var.set(bin_path)
            self._info.config(text=f"Assembled {len(binary)} bytes → {os.path.basename(bin_path)}", foreground='green')
            if not self._name_var.get() or self._name_var.get() == "New Project":
                self._name_var.set(os.path.splitext(os.path.basename(asm_path))[0])
        except Exception as e:
            messagebox.showerror("Assembly Error", str(e), parent=self.root)
            self._info.config(text=f"Assembly failed: {e}", foreground='red')

    # ---- add-ins ----

    def _add_addin(self):
        p = filedialog.askopenfilename(title="Select add-in", parent=self.root,
                                       filetypes=[("Binary", "*.bin"), ("All", "*.*")])
        if not p:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Load Address")
        dlg.geometry("340x110")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=f"File: {os.path.basename(p)}").pack(pady=4)
        ttk.Label(dlg, text="Load address:").pack()
        av = tk.StringVar(value="0x8CFF0000")
        ttk.Entry(dlg, textvariable=av, width=20).pack(pady=4)
        def ok():
            try:
                addr = int(av.get(), 0)
                self._current_addins.append(AddIn(path=p, load_addr=addr, description=os.path.basename(p)))
                self._addin_list.insert('', tk.END, values=(p, f"0x{addr:08X}", os.path.basename(p)))
                dlg.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid address", parent=dlg)
        ttk.Button(dlg, text="OK", command=ok).pack(pady=4)
        dlg.bind('<Return>', lambda e: ok())

    def _remove_addin(self):
        sel = self._addin_list.selection()
        if not sel:
            return
        idx = self._addin_list.index(sel[0])
        if idx < len(self._current_addins):
            self._current_addins.pop(idx)
        self._addin_list.delete(sel)

    # ---- save / cancel ----

    def _collect(self) -> Project:
        return Project(
            name=self._name_var.get(),
            rom_path=self._rom_var.get(),
            start_pc=int(self._pc_var.get(), 0),
            sr_value=int(self._sr_var.get(), 0),
            addins=list(self._current_addins),
            with_tmu=self._tmu_var.get(),
            with_rtc=self._rtc_var.get(),
            with_dma=self._dma_var.get(),
            with_display=self._disp_var.get(),
            with_ubc=self._ubc_var.get(),
            is_assembly=bool(self._asm_var.get().strip()),
        )

    def _save(self):
        p = self._collect()
        if not p.rom_path or not os.path.exists(p.rom_path):
            messagebox.showerror("Error", "Select a valid ROM / program file.", parent=self.root)
            return
        self.result = p
        self.root.destroy()

    def _cancel(self):
        self.result = None
        self.root.destroy()


# ============================================================================
# Assemble & Run dialog (quick launch)
# ============================================================================

class AssembleAndRunDialog(ModalWindow):
    """Quick-launch: pick .asm, give it a name, assemble, and go."""

    def __init__(self, parent: tk.Tk):
        super().__init__(parent=parent, title="Assemble & Run")
        self.result: Project = None

        self._top = self.root
        self._top.geometry("350x250")
        self._top.transient(parent)
        self._top.grab_set()

        body = ttk.Frame(self._top, padding=16)
        body.pack(fill='both', expand=True)

        ttk.Label(body, text="Quick Assemble & Run", font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(0, 8))

        ttk.Label(body, text="Project name:").pack(anchor='w')
        self._name_var = tk.StringVar(value="Assembled Program")
        ttk.Entry(body, textvariable=self._name_var).pack(fill='x', pady=(0, 8))

        ttk.Label(body, text="Assembly source (.asm / .s):").pack(anchor='w')
        f = ttk.Frame(body)
        f.pack(fill='x', pady=(0, 8))
        self._asm_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._asm_var).pack(side='left', fill='x', expand=True)
        ttk.Button(f, text="Browse…", command=self._browse).pack(side='left', padx=4)

        self._info = ttk.Label(body, text="", foreground='gray')
        self._info.pack(anchor='w')

        bar = ttk.Frame(self._top)
        bar.pack(fill='x', padx=16, pady=(0, 12))
        ttk.Button(bar, text="Cancel", command=self._cancel).pack(side='right', padx=4)
        ttk.Button(bar, text="Assemble & Run", command=self._go).pack(side='right', padx=4)

        parent.wait_window(self._top)

    def _browse(self):
        p = filedialog.askopenfilename(title="Select assembly source", parent=self._top,
                                       filetypes=[("Assembly", "*.asm *.s"), ("All", "*.*")])
        if p:
            self._asm_var.set(p)
            base = os.path.splitext(os.path.basename(p))[0]
            if base:
                self._name_var.set(base)

    def _go(self):
        asm_path = self._asm_var.get().strip()
        if not asm_path or not os.path.exists(asm_path):
            messagebox.showerror("Error", "Select a valid .asm file.", parent=self._top)
            return
        try:
            with open(asm_path, 'r') as f:
                code = f.read()
            from ruk.tools.assembler import assemble
            binary = assemble(code, start_addr=0x80000000)
            bin_path = os.path.splitext(asm_path)[0] + '.bin'
            with open(bin_path, 'wb') as f:
                f.write(binary)
            self._info.config(text=f"Assembled {len(binary)} bytes → {os.path.basename(bin_path)}", foreground='green')
            self.result = Project(
                name=self._name_var.get(),
                rom_path=bin_path,
                start_pc=0x80000000,
                sr_value=0x400001F0,
                with_tmu=True, with_rtc=True, with_dma=True,
                with_display=True, with_ubc=True,
                is_assembly=True,
            )
            self._top.destroy()
        except Exception as e:
            messagebox.showerror("Assembly Error", str(e), parent=self._top)
            self._info.config(text=f"Failed: {e}", foreground='red')

    def _cancel(self):
        self.result = None
        self._top.destroy()


# ============================================================================
# Main project loader window
# ============================================================================

class ProjectLoaderWindow(BaseWindow):
    """PyCharm-style project picker — shows recent projects and launch buttons."""

    def __init__(self):
        super().__init__(title="Projects :: RuK")
        self.root.geometry("900x560")
        self.root.minsize(700, 420)

        self.selected_project: Project = None
        self._projects: list = []

        self._setup_ui()
        self._refresh()

    # ---- UI ----

    def _setup_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill='both', expand=True)

        # Header
        hdr = ttk.Frame(main)
        hdr.pack(fill='x', pady=(0, 8))
        ttk.Label(hdr, text="RuK SH4AL-DSP Emulator",
                  font=('Segoe UI', 18, 'bold')).pack(side='left')

        # Toolbar
        tb = ttk.Frame(main)
        tb.pack(fill='x', pady=(0, 6))
        ttk.Button(tb, text="+  New Project", command=self._new_project).pack(side='left', padx=2)
        ttk.Button(tb, text="⚡  Assemble & Run", command=self._assemble_run).pack(side='left', padx=2)

        # Project list
        lf = ttk.LabelFrame(main, text="Recent Projects", padding=6)
        lf.pack(fill='both', expand=True)

        self._tree = ttk.Treeview(lf, columns=('name', 'rom', 'date'),
                                  show='headings', height=14)
        self._tree.heading('name', text='Name')
        self._tree.heading('rom', text='ROM / Program')
        self._tree.heading('date', text='Last Opened')
        self._tree.column('name', width=160)
        self._tree.column('rom', width=340)
        self._tree.column('date', width=140)

        sb = ttk.Scrollbar(lf, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # Bindings
        self._tree.bind('<Double-1>', lambda e: self._open_selected())
        self._tree.bind('<Button-3>', self._on_right_click)

        # Context menu
        self._ctx = tk.Menu(self.root, tearoff=0)
        self._ctx.add_command(label="Open", command=self._open_selected)
        self._ctx.add_command(label="Edit…", command=self._edit_selected)
        self._ctx.add_separator()
        self._ctx.add_command(label="Remove", command=self._remove_selected)
        self._ctx.add_separator()
        self._ctx.add_command(label="Refresh", command=self._refresh)

        # Bottom hint
        ttk.Label(main, text="Double-click a project to open  •  Right-click for options",
                  foreground='gray').pack(anchor='w', pady=(4, 0))

    # ---- list management ----

    def _refresh(self):
        self._projects = load_projects()
        self._tree.delete(*self._tree.get_children())
        for p in self._projects:
            date_str = _time.strftime('%Y-%m-%d %H:%M', _time.localtime(p.last_opened)) if p.last_opened else 'Never'
            rom_display = os.path.basename(p.rom_path) if p.rom_path else '(none)'
            if p.is_assembly:
                rom_display += '  [ASM]'
            self._tree.insert('', tk.END, values=(p.name, rom_display, date_str))

    def _selected_project(self) -> Project:
        sel = self._tree.selection()
        if not sel:
            return None
        name = self._tree.item(sel[0])['values'][0]
        for p in self._projects:
            if p.name == name:
                return p
        return None

    # ---- context menu ----

    def _on_right_click(self, event):
        item = self._tree.identify_row(event.y)
        if item:
            self._tree.selection_set(item)
            self._ctx.entryconfig("Open", state='normal')
            self._ctx.entryconfig("Edit…", state='normal')
            self._ctx.entryconfig("Remove", state='normal')
        else:
            self._tree.selection_remove(self._tree.selection())
            self._ctx.entryconfig("Open", state='disabled')
            self._ctx.entryconfig("Edit…", state='disabled')
            self._ctx.entryconfig("Remove", state='disabled')
        self._ctx.tk_popup(event.x_root, event.y_root)

    # ---- actions ----

    def _new_project(self):
        dlg = NewProjectDialog(self.root)
        if dlg.result:
            add_or_update_project(dlg.result)
            self._refresh()
            self._launch(dlg.result)

    def _edit_selected(self):
        p = self._selected_project()
        if not p:
            return
        dlg = NewProjectDialog(self.root, project=p)
        if dlg.result:
            remove_project(p)  # remove old
            add_or_update_project(dlg.result)
            self._refresh()
            self._launch(dlg.result)

    def _assemble_run(self):
        dlg = AssembleAndRunDialog(self.root)
        if dlg.result:
            add_or_update_project(dlg.result)
            self._refresh()
            self._launch(dlg.result)

    def _open_selected(self):
        p = self._selected_project()
        if p:
            self._launch(p)

    def _remove_selected(self):
        p = self._selected_project()
        if p:
            remove_project(p)
            self._refresh()

    # ---- launch ----

    def _launch(self, project: Project):
        if not project.rom_path or not os.path.exists(project.rom_path):
            messagebox.showerror("Error", f"ROM file not found:\n{project.rom_path}")
            return
        add_or_update_project(project)
        self.selected_project = project
        self.root.quit()
        self.root.destroy()

    # ---- public ----

    def show(self):
        self.root.mainloop()
        return self.selected_project
