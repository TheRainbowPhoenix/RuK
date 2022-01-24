import ctypes
import os
import sys
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk
from typing import Dict, Callable
import re

from ruk.gui.preferences import Preferences
from ruk.gui.resources import ResourceManager
from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.utils import HookToolTip
from ruk.jcore.cpu import CPU


class ControlsFrame(BaseFrame):
    def __init__(self, cpu: CPU, resources: ResourceManager, **kw):
        self._cpu = cpu
        self.resources = resources

        self.continue_until = [
            'Continue until call',
            'Continue until syscall',
        ]

        self.continue_until_mode = 0
        self.except_pause = 1

        def noop():
            pass

        self.on_step_callback: Callable = noop
        self.on_stop_callback: Callable = noop

    def set_widgets(self, root):
        """
        Setup base widgets
        """

        widget = tk.Frame(root, bd=2)
        widget.pack(fill='both', expand=1)
        self.start_btn = ttk.Button(
            master=widget,
            image=self.resources['start'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_run
        )
        HookToolTip(self.start_btn, "Start")

        self.stop_btn = ttk.Button(
            master=widget,
            image=self.resources['stop'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_stop
        )
        HookToolTip(self.stop_btn, "Stop")

        self.continue_until_btn = ttk.Button(
            widget,
            image=self.resources['continue_until_syscall'],
            width=28,
            style="Titlebar.TButton",
            command=self.continue_until_changed,
        )
        self.continue_until_btn_tooltip = HookToolTip(self.continue_until_btn, "Continue until Syscall")

        self.step_over_btn = ttk.Button(
            master=widget,
            image=self.resources['step_over'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_step_over
        )
        HookToolTip(self.step_over_btn, "Step over")

        self.step_into_btn = ttk.Button(
            master=widget,
            image=self.resources['step_into'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_step_into
        )
        HookToolTip(self.step_into_btn, "Step into")

        self.except_pause_btn = ttk.Button(
            master=widget,
            image=self.resources['except_pause_on'],
            width=28,
            command=self.except_pause_changed,
            style="Titlebar.TButton",
        )
        self.except_pause_btn_tooltip = HookToolTip(self.except_pause_btn, "Pause on exceptions")

        col = 0
        self.start_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.continue_until_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.continue_until_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.step_over_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.step_into_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.stop_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.except_pause_btn.grid(row=0, column=col, padx=2)
        col += 1

    def continue_until_changed(self):
        if self.continue_until_mode == 1:
            self.continue_until_mode = 0
            self.continue_until_btn.configure(image=self.resources['continue_until_syscall'])
            self.continue_until_btn_tooltip.text = "Continue until Syscall"
        else:
            self.continue_until_mode = 1
            self.continue_until_btn.configure(image=self.resources['continue_until_call'])
            self.continue_until_btn_tooltip.text = "Continue until Call"

    def except_pause_changed(self):
        if self.except_pause == 1:
            self.except_pause = 0
            self.except_pause_btn.configure(image=self.resources['except_pause_off'])
            self.except_pause_btn_tooltip.text = "Don't pause on exceptions"
        else:
            self.except_pause = 1
            self.except_pause_btn.configure(image=self.resources['except_pause_on'])
            self.except_pause_btn_tooltip.text = "Pause on exceptions"

    def do_step(self):
        try:
            self._cpu.step()
            self.on_step_callback()
        except Exception as e:
            print(f"!!! CPU Error : {e} !!!")

    def do_step_over(self):
        self.do_step()

    def do_step_into(self):
        self.do_step()

    def do_run(self):
        while not self._cpu.ebreak:
            self.do_step()

    def do_stop(self):
        self._cpu.reset()
        self.on_stop_callback()

    def hook(self, root: tk.Frame):
        self.set_widgets(root)

    def refresh(self):
        pass
