import ctypes
import os
import sys
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk
from typing import Dict
import re

from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.flex import FlexGrid
from ruk.jcore.cpu import Register

PLATFORM = sys.platform


class RegisterWrapper(BaseWrapper):
    def __init__(self, name: str, reg_reg: Register):
        self.name = name
        self._ref: Register = reg_reg
        self._font = tkFont.Font(family='Consolas', size=10)
        self._font_change = tkFont.Font(family="Consolas", size=10, weight="bold")
        self._value_cache = None
        self._value_display = "???"
        self._value_changed = False

    def set_widget(self, frame: tk.Frame):
        self.regLabel = ttk.Label(frame)
        self.regLabel["text"] = f"{self.name}"
        self.regLabel["justify"] = "right"
        self.regLabel["font"] = self._font
        self.regLabel.grid(row=0, column=0, padx=5, pady=5)

        self.regEdit = ttk.Entry(frame)
        # RegEdit["borderwidth"] = "1px"
        self.regEdit["font"] = self._font
        self.regEdit["justify"] = "left"
        self.regEdit.grid(row=0, column=1)

        self.regEdit.bind("<FocusOut>", self._validate_change)

    def update_values(self, step=False):
        value = self._ref[self.name]
        if value != self._value_cache:
            self._value_display = f'{hex(value)}'
            self._value_cache = value
            self.regEdit.delete(0, tk.END)
            self.regEdit.insert(0, self._value_display)

            if step:
                # Hack to show value as "changed"
                self.regEdit["foreground"] = "#107C10"
                self.regEdit["font"] = self._font_change
                self._value_changed = True
        else:
            if self._value_changed:
                self.regEdit["foreground"] = ""
                self.regEdit["font"] = self._font
                self._value_changed = False

            if self.regEdit.state() == "invalid":
                self.regEdit.state([""])

    def _set_value(self, value: str, base: int = 16):
        try:
            intval = int(value, base)
            self.regEdit.state([""])

            self._ref[self.name] = intval
            self.update_values()
            return True

        except ValueError as _:
            return False

    def _validate_change(self, *_):
        """
        Validate input register value
        """
        val = self.regEdit.get()
        if val != "":

            # Try to set the 0xVal
            if re.match(
                    r"^0x(?:[0-9a-fA-F]{1,8})$", val
            ) and self._set_value(value=val, base=16):
                return

            # Try to set it as int
            if self._set_value(value=val, base=10):
                return

            # Try to set it as hex, without 0x ?
            if re.match(
                    r"^(?:[0-9a-fA-F]{1,8})$", val
            ) and self._set_value(value=val, base=16):
                return

        self.regEdit.state(["invalid"])


class RegisterFrame(BaseFrame):
    def __init__(self, registers: Register, **kw):
        self._regs = registers
        self.regs_wrapper: Dict[str, RegisterWrapper] = {}

    def set_widgets(self, root):
        """
        Setup base widgets
        """
        self._setup_registers(root)

        # TODO: remove me !
        self._test_buttons(root)

    def _setup_registers(self, root: tk.Frame):
        """
        Create TK registers view
        """
        self.regFrame = ttk.Labelframe(root, width=300, height=500, padding=(8, 4))
        self.regFrame["text"] = "Registers"

        items_per_col = 12

        i = 0
        for reg in self._regs:
            frame = tk.Frame(
                master=self.regFrame,
                relief=tk.FLAT,
                borderwidth=0,
                padx=10,
                pady=4,
            )
            col = 1 if i >= items_per_col else 0
            row = i if i < items_per_col else i - items_per_col

            frame.grid(row=row, column=col)

            reg_wrap = RegisterWrapper(reg, self._regs)
            reg_wrap.set_widget(frame)
            self.regs_wrapper[reg] = reg_wrap

            i += 1

        self.regFrame.pack(fill=tk.BOTH, side=tk.TOP, expand=True, padx=10, pady=10)

    def _test_buttons(self, root: tk.Frame):
        """
        Just some test buttons.
        """
        widget = tk.Frame(root, bd=12)
        widget.pack(fill='both', expand=1, anchor=tk.SE)
        refresh = ttk.Button(widget,
                             text="Refresh",
                             style="Accent.TButton",
                             width=28,
                             )

        refresh.pack(fill=tk.Y, expand=0, anchor=tk.SE)

        def reload_regs():
            self.do_refresh()

        refresh["command"] = reload_regs

    def do_refresh(self):
        for reg_name in self.regs_wrapper:
            self.regs_wrapper[reg_name].update_values()

    def do_step(self):
        for reg_name in self.regs_wrapper:
            self.regs_wrapper[reg_name].update_values(step=True)

    def hook(self, root: tk.Frame):
        self.set_widgets(root)

    def refresh(self):
        self.do_refresh()
