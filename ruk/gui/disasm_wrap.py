import time
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk
from typing import Dict, Callable, List
import re
from io import BytesIO

from ruk.gui.preferences import Preferences
from ruk.gui.resources import ResourceManager
from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.utils import HookToolTip
from ruk.jcore.cpu import CPU
from ruk.jcore.disassembly import Disassembler


class DisasmFrame(BaseFrame):
    def __init__(self, cpu: CPU, resources: ResourceManager, **kw):
        self._cpu = cpu
        self.resources = resources

        self.disasm = Disassembler()

        self._buffer_var: List[tk.StringVar] = []
        self._buffer_text: List[tk.StringVar] = []

        self._cursor = None
        self._cursor_pos = {
            'x': 0,
            'y': 5
        }

        self.font_size = 14

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


        self._cursor = self.canvas.create_rectangle(self._cursor_pos['x'],
                                                    self._cursor_pos['y'],
                                                    self._cursor_pos['x'] + 4500,
                                                    self._cursor_pos['y'] + (self.font_size + 6),
                                                    fill='#571A07', outline="")

        for i in range(64):
            buffer_var = tk.StringVar(value=f'--- {i}')
            self._buffer_var.append(buffer_var)
            buffer_text = self.canvas.create_text(12, 5 + (self.font_size + 6) * i, fill="#ED9366",
                                                  font=f"Consolas {self.font_size}",
                                                  anchor=tk.NW,
                                                  text=buffer_var.get())
            self._buffer_text.append(buffer_text)

    def refresh_cusor(self):
        self.canvas.coords(self._cursor,
                           self._cursor_pos['x'],
                           self._cursor_pos['y'],
                           self._cursor_pos['x'] + 4500,
                           self._cursor_pos['y'] + (self.font_size + 6),)

    def refresh_display(self):
        for i in range(len(self._buffer_text)):
            buffer_text = self._buffer_text[i]
            buffer_var = self._buffer_var[i]
            self.canvas.itemconfigure(buffer_text, text=buffer_var.get())

        self.refresh_cusor()

    def refresh_asm(self):
        # First get the memory

        line = ""

        try:
            start_p, end_p, mem = self._cpu.get_surrounding_memory()
            memory = BytesIO(mem)
        except IndexError:
            # TODO: chage this !
            start_p, end_p = 0, 0
            # Looks like default behaviour
            memory = BytesIO(b'\x0f'*20*2)

        index = 0
        # Read it two bytes by two bytes
        for chunk in iter((lambda: memory.read(2)), ''):
            if index >= len(self._buffer_var):
                break

            addr_str = f"0x{start_p + (index * 2):08x}"
            val = int.from_bytes(chunk, "big")
            try:
                op_str, args = self.disasm.disasm(val, trace_only=True)

                op_mod = op_str % args
                ops = op_mod.split(" ")
                op_name = ops[0]
                op_args = ' '.join(ops[1:]) if len(ops) > 1 else ''
                line = f"{addr_str} {op_name:<8} {op_args}"

            except IndexError:
                line = f"{addr_str} {'.word':<8} 0x{val:08x}"

            # f'{i:04X} - {int(time.time())}'

            try:
                self._buffer_var[index].set(line)
            except Exception:
                continue

            index += 1

        addr_diff = self._cpu.pc - start_p
        self.move_cursor_to_line(addr_diff//2)

        self.refresh_display()

    def hook(self, root: tk.Frame):
        self.set_widgets(root)

        self.refresh_asm()

    def do_step(self):
        # TODO
        self.refresh_asm()

    def move_cursor_to_line(self, addr_diff: int):
        self._cursor_pos['y'] = 6 + (self.font_size + 6) * addr_diff

# self.canvas = Canvas(root, width=800, height=650, bg = '#afeeee')
# self.canvas.create_text(100,10,fill="darkblue",font="Times 20 italic bold",
#                         text="Click the bubbles that are multiples of two.")
