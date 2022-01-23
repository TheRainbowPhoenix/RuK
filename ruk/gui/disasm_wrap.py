import time
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk
from typing import Dict, Callable, List
import re

from ruk.gui.resources import ResourceManager
from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.utils import HookToolTip
from ruk.jcore.cpu import CPU


class DisasmFrame(BaseFrame):
    def __init__(self, cpu: CPU, resources: ResourceManager, **kw):
        self._cpu = cpu
        self.resources = resources

        self._buffer_var: List[tk.StringVar] = []
        self._buffer_text: List[tk.StringVar] = []

    def refresh(self):
        self.refresh_asm()

    def set_widgets(self, root):
        """
        Setup base widgets
        """
        widget = tk.Frame(root, bd=0)
        widget.pack(fill='both', expand=1)

        self.canvas = tk.Canvas(widget, width=600, height=650, bg='#202020', highlightthickness=0)
        self.canvas.pack(fill='both', expand=1)
        self._setup_text()


    def _setup_text(self):
        font_size = 14

        for i in range(64):
            buffer_var = tk.StringVar(value=f'--- {i}')
            self._buffer_var.append(buffer_var)
            buffer_text = self.canvas.create_text(12, 5 + (font_size + 6) * i, fill="#ED9366", font=f"Consolas {font_size}",
                                    anchor=tk.NW,
                                    text=buffer_var.get())
            self._buffer_text.append(buffer_text)

    def refresh_display(self):
        for i in range(len(self._buffer_text)):
            buffer_text = self._buffer_text[i]
            buffer_var = self._buffer_var[i]
            self.canvas.itemconfigure(buffer_text, text=buffer_var.get())

    def refresh_asm(self):
        for i in range(len(self._buffer_var)):
            self._buffer_var[i].set(f'{i:04X} - {int(time.time())}')

        self.refresh_display()

    def hook(self, root: tk.Frame):
        self.set_widgets(root)

        self.refresh_asm()

    def do_step(self):
        # TODO
        self.refresh_asm()

# self.canvas = Canvas(root, width=800, height=650, bg = '#afeeee')
# self.canvas.create_text(100,10,fill="darkblue",font="Times 20 italic bold",
#                         text="Click the bubbles that are multiples of two.")
