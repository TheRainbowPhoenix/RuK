import time
import tkinter as tk
import tkinter.font as tkFont
from binascii import unhexlify
from ctypes import c_long
from tkinter import ttk
from typing import Dict, Callable, List, Tuple, Union
import re
from io import BytesIO

from ruk.gui.preferences import preferences
from ruk.gui.resources import ResourceManager
from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.utils import HookToolTip, to_clip
from ruk.jcore.cpu import CPU
from ruk.jcore.disassembly import Disassembler


def line_height() -> int:
    return preferences.current_font.size + max(preferences.current_font.size // 2, 6)


def line_y(pos: int) -> int:
    return max(preferences.current_font.size // 2, 6) + line_height() * pos


class LineWrapper:
    def __init__(self, canvas: tk.Canvas, gutter_size: int):
        self.canvas = canvas

        self.addr_var: tk.StringVar = tk.StringVar(value='---')
        self.op_var: tk.StringVar = tk.StringVar(value='---')
        self.var_var: tk.StringVar = tk.StringVar(value='---')
        self.text_var: tk.StringVar = tk.StringVar(value='---')

        self.addr_id: int = -1
        self.op_id: int = -1
        self.var_id: int = -1
        self.text_id: int = -1

        self._gutter_size = gutter_size

        self._changes: List[bool] = [False, False, False, False]
        self._colors_changes: List[bool] = [False, False, False, False]
        self._colors: List[str] = [
            preferences.current_theme.offset,
            preferences.current_theme.mov,
            preferences.current_theme.num,
            preferences.current_theme.comment
        ]

        self._items: List[Tuple[int, tk.StringVar]] = []

        self._x_pos_factor = [
            0,
            8,
            6,
            12,
        ]

    def setup(self, index: int):
        from ruk.gui.preferences import preferences
        sz = preferences.current_font.size

        x = max(sz // 2, self._gutter_size + 8)
        dy = max(sz // 2, 6)
        self.addr_id = self.canvas.create_text(x,
                                               line_y(index),
                                               fill=self._colors[0],
                                               font=preferences.current_font.string,
                                               anchor=tk.NW,
                                               text=self.addr_var.get())

        x += (sz * self._x_pos_factor[1])
        self.op_id = self.canvas.create_text(x,
                                             line_y(index),
                                             fill=self._colors[1],
                                             font=preferences.current_font.string,
                                             anchor=tk.NW,
                                             text=self.op_var.get())

        x += (sz * self._x_pos_factor[2])
        self.var_id = self.canvas.create_text(x,
                                              line_y(index),
                                              fill=self._colors[2],
                                              font=preferences.current_font.string,
                                              anchor=tk.NW,
                                              text=self.var_var.get())

        x += (sz * self._x_pos_factor[3])
        self.text_id = self.canvas.create_text(x,
                                               line_y(index),
                                               fill=self._colors[3],
                                               font=preferences.current_font.string,
                                               anchor=tk.NW,
                                               text=self.text_var.get())

        self._items = [
            (self.addr_id, self.addr_var),
            (self.op_id, self.op_var),
            (self.var_id, self.var_var),
            (self.text_id, self.text_var),
        ]

    def update_values(self):
        if True in self._changes or True in self._colors_changes:
            for i in range(len(self._items)):
                self.canvas.itemconfigure(
                    self._items[i][0],
                    text=self._items[i][1].get(),
                    fill=self._colors[i]
                )

            self._changes = [False, False, False, False]
            self._colors_changes = [False, False, False, False]

    # TODO: check change ?
    def set_addr(self, addr_str):
        self.addr_var.set(addr_str)
        self._changes[0] = True

    def set_op(self, op_str, color: str = ""):
        if color != "" and color != self._colors[1]:
            self._colors[1] = color
            self._colors_changes[1] = True

        self.op_var.set(op_str)
        self._changes[1] = True

    def set_var(self, var_str):
        self.var_var.set(var_str)
        self._changes[2] = True

    def set_text(self, text_str):
        self.text_var.set(text_str)
        self._changes[3] = True

    def __str__(self):
        return f"{self.addr_var.get()} {self.op_var.get():<8} {self.var_var.get():<12} {self.text_var.get()}"

    def set_gutter_size(self, size: int):
        self._gutter_size = size

        self._refresh_x_coords()

    def _refresh_x_coords(self):
        sz = preferences.current_font.size
        x = max(sz // 2, self._gutter_size + 8)

        for i in range(len(self._items)):
            x += (sz * self._x_pos_factor[i])
            self.canvas.coords(
                self._items[i][0],
                x,
                self.canvas.coords(self._items[i][0])[1]
            )


class DisasmFrame(BaseFrame):
    BUF_SIZE = 64 * 2

    def __init__(self, cpu: CPU, resources: ResourceManager, **kw):
        super().__init__()
        self._cpu = cpu
        self.resources = resources

        self.disasm = Disassembler()

        # Wraps the display buffer (only one color per text):
        # List index is the line number (ordered), LineWrapper list all line elements
        self._buffer: List[LineWrapper] = []

        self._cursors: Dict[
            str, Dict[
                str, Union[int, None, Dict[str, int]]
            ]
        ] = {
            'pc': {
                'ref': None,
                'pos': {
                    'x': 0,
                    'y': 5
                }
            },
            'select': {
                'ref': None,
                'pos': {
                    'x': 0,
                    'y': -50
                },
                'line': 0,
            }
        }
        self.line_size = 0

        self.gutter_size = preferences.get("gutter_size", 32)
        self.gutter = -1

        # Scroll top position
        self._scroll_top = 0

        self._arrows = []
        self._arrows_memo = []

        self._changes = {
            'gutter_size': False,
            'cursor': False,
            'drag': False,
        }

    def refresh(self):
        self.refresh_asm()

    def get_line_from_y(self, y: int):
        start = max(preferences.current_font.size // 2, 6)
        pos = int(abs((y + self._scroll_top) / line_height() - start / line_height()))
        return pos

    def do_click(self, event):
        line = self.get_line_from_y(event.y)
        self._cursors['select']['line'] = line
        self.move_cursor_to_line(line, self._cursors['select'])
        self.refresh_cusor()
        return "break"

    def do_context_menu(self, event):
        line = self.get_line_from_y(event.y)
        self._cursors['select']['line'] = line
        self.move_cursor_to_line(line, self._cursors['select'])
        self.refresh_cusor()

        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()
        return "break"

    def set_widgets(self, root):
        """
        Setup base widgets
        """
        self.widget = tk.Frame(root, bd=0)
        self.widget.pack(fill='both', expand=1)

        sz = preferences.current_font.size

        self._canvas_max_height = line_y(self.BUF_SIZE + 4)
        self.canvas = tk.Canvas(self.widget, width=600, height=650,
                                bg=preferences.current_theme.gui_background,
                                highlightthickness=0,
                                scrollregion=(0, 0, 600, self._canvas_max_height))
        self.canvas.pack(fill='both', expand=1)
        self._setup_text()

        self._setup_ux(root)

    CURSOR_FILL_HEIGHT = 4500

    def _setup_text(self):

        # Create it hidden !
        self._cursors['select']['ref'] = self.canvas.create_rectangle(
            self._cursors['select']['pos']['x'],
            self._cursors['select']['pos']['y'],
            self._cursors['select']['pos']['x'] + self.CURSOR_FILL_HEIGHT,
            self._cursors['select']['pos']['y'] + line_height(),
            fill=preferences.current_theme.line_highlight, outline="")

        # Red cursor of the line
        self._cursors['pc']['ref'] = self.canvas.create_rectangle(
            self._cursors['pc']['pos']['x'],
            self._cursors['pc']['pos']['y'],
            self._cursors['pc']['pos']['x'] + self.CURSOR_FILL_HEIGHT,
            self._cursors['pc']['pos']['y'] + line_height(),
            fill=preferences.current_theme.highlight_PC, outline="")

        for i in range(self.BUF_SIZE):
            line = LineWrapper(canvas=self.canvas, gutter_size=self.gutter_size)
            line.setup(i)

            self._buffer.append(line)

        self.gutter = self.canvas.create_rectangle(
            self.gutter_size,
            0,
            self.gutter_size + 1,
            self.CURSOR_FILL_HEIGHT,
            fill=preferences.current_theme.line_highlight, outline="")

    def _setup_ux(self, root):
        self.canvas.bind("<Button-1>", self.do_click)
        self.canvas.bind("<Button-3>", self.do_context_menu)
        # root.bind_all("<Control-c>", lambda x: self.do_copy_instructions())
        root.bind_all("<Control-Shift-c>", lambda x: self.do_copy_address())
        root.bind_all("<Control-Shift-C>", lambda x: self.do_copy_address())
        root.bind_all("<Home>", lambda x: self.do_back_top())

        self.canvas.bind("<MouseWheel>", self.do_mousewheel)
        self.canvas.bind("<Motion>", self.do_motion)
        self.canvas.bind("<B1-Motion>", self.do_b1_motion)

        self._setup_context_menu(root)

    def do_copy_address(self):
        line_pos: int = self._cursors['select']['line']
        try:
            line = self._buffer[line_pos]
            to_clip(line.addr_var.get())

            return "break"
        except (IndexError, KeyError) as e:
            return

    def do_copy_instructions(self):
        line_pos: int = self._cursors['select']['line']
        try:
            line = self._buffer[line_pos]
            to_clip(str(line))
            return "break"

        except (IndexError, KeyError) as e:
            return

    def do_back_top(self):
        self.canvas.yview_moveto(0)
        self.apply_scroll()
        return "break"

    def do_pc_set(self):
        line_pos: int = self._cursors['select']['line']
        try:
            line = self._buffer[line_pos]
            new_pc = int(line.addr_var.get(), 16)
            self._cpu.pc = new_pc

            self.move_cursor_to_line(line_pos)

            self._refresh_callback()
            self.refresh_cusor()


        except (IndexError, KeyError, ValueError) as e:
            print(f"Set PC error : {e}")
            return

    def do_memory_edit(self):
        line_pos: int = self._cursors['select']['line']
        try:
            line = self._buffer[line_pos]

            self.show_edit_memory(int(line.addr_var.get(), 16))
            to_clip(str(line))

        except (IndexError, KeyError) as e:
            return

        # TODO: finish this...

    def show_edit_memory(self, address: int):
        from ruk.gui.dialogs import EditBytesDialog
        try:
            root = self.widget.master.master
        except:
            root = None

        edit_dialog = EditBytesDialog(root, address, self._cpu)
        edit_dialog.show()
        value = edit_dialog.ret_val
        if value is not None:
            bytes_data = unhexlify(f'{int(value[:4], 16):04x}')
            self._cpu.mem.write16(address, bytes_data)
            self.refresh_asm()

    def _setup_context_menu(self, root):
        # TODO: custom menu, remove the border...
        self._context_menu = tk.Menu(root, tearoff=0)
        self._context_menu.add_command(label="Copy instructions", underline=0, accelerator='Ctrl+C',
                                       command=self.do_copy_instructions)
        self._context_menu.add_command(label="Copy address", underline=0, accelerator='Ctrl+Shift+C',
                                       command=self.do_copy_address)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="Set PC here", underline=0,
                                       command=self.do_pc_set)
        # TODO: self._context_menu.add_command(label="Continue until here")
        self._context_menu.add_separator()
        self._context_menu.add_command(label="Add breakpoint", underline=0, state=tk.DISABLED)
        self._context_menu.add_command(label="Advanced breakpoint...", underline=0, state=tk.DISABLED)
        # TODO: breakpoint
        self._context_menu.add_separator()
        # self._context_menu.add_cascade(label="Edit")

        self._context_menu.add_command(label="Edit Instruction...", state=tk.DISABLED)
        self._context_menu.add_command(label="NOP Instruction", state=tk.DISABLED)
        self._context_menu.add_command(label="Edit bytes...", underline=0,
                                       command=self.do_memory_edit)

    def refresh_cusor(self):
        self.canvas.coords(self._cursors['pc']['ref'],
                           self._cursors['pc']['pos']['x'],
                           self._cursors['pc']['pos']['y'],
                           self._cursors['pc']['pos']['x'] + 4500,
                           self._cursors['pc']['pos']['y'] + line_height()
                           )

        self.canvas.coords(self._cursors['select']['ref'],
                           self._cursors['select']['pos']['x'],
                           self._cursors['select']['pos']['y'],
                           self._cursors['select']['pos']['x'] + 4500,
                           self._cursors['select']['pos']['y'] + line_height()
                           )

    def refresh_gutter(self):
        self.canvas.coords(
            self.gutter,
            self.gutter_size,
            0,
            self.gutter_size + 1,
            self.CURSOR_FILL_HEIGHT)
        self.draw_arrows()

    def refresh_display(self):
        for line in self._buffer:
            line.update_values()
            if self._changes['gutter_size']:
                line.set_gutter_size(self.gutter_size)

        self.refresh_gutter()
        self.refresh_cusor()

    def refresh_asm(self):
        # First get the memory

        line = ""

        self._arrows = []

        try:
            start_p, end_p, mem = self._cpu.get_surrounding_memory(size=self.BUF_SIZE)
            memory = BytesIO(mem)
        except IndexError:
            # TODO: chage this !
            start_p, end_p = 0, 0
            # Looks like default behaviour
            memory = BytesIO(b'\x00' * self.BUF_SIZE * 2)

        index = 0
        # Read it two bytes by two bytes
        for chunk in iter((lambda: memory.read(2)), ''):
            if index >= self.BUF_SIZE:
                break

            addr_str = f"0x{start_p + (index * 2):04x}"
            op_str = '.word'
            var_str = ''
            text_str = ''

            val = int.from_bytes(chunk, "big")
            try:
                op_str, args = self.disasm.disasm(val, trace_only=True)

                op_mod = op_str.format(**args)  # op_str % args
                ops = op_mod.split(" ")
                op_str = ops[0]

                # Recreate address
                if op_str in ['bf', 'bra', 'bt', 'bf.s']:  # TODO: move this to a constant list
                    jmp = args[list(args)[0]]

                    if op_str in ['bra']:
                        if (jmp & 0x800) == 0:
                            jmp = (0x00000FFF & jmp)
                        else:
                            jmp = c_long(0xFFFFF000 | jmp).value

                    var_str = hex(
                        start_p + (index * 2) +  # Addr
                        jmp * 2 +  # Jump of N bytes
                        4
                    )

                    self.queue_arrow(index, jmp + 2)

                else:
                    var_str = ' '.join(ops[1:]) if len(ops) > 1 else ''
                # text_str += 'pseudocode'
                text_str = f'; {val:04X}'
                # line = f"{addr_str} {op_str:<8} {var_str}"

            except IndexError:
                var_str = f'0x{val:04x}'
                # line = f"{addr_str} {'.word':<8} 0x{val:08x}"
            except TypeError as e:
                print(op_str, args)
                raise e

            # f'{i:04X} - {int(time.time())}'

            op_color = self.get_op_color(op_str)

            try:
                line_wrap = self._buffer[index]
                line_wrap.set_addr(addr_str)
                line_wrap.set_op(op_str, color=op_color)
                line_wrap.set_var(var_str)
                line_wrap.set_text(text_str)

                # line_wrap.set_addr ...
                # line_xrap. set changed ..
            except Exception:
                continue

            index += 1

        addr_diff = self._cpu.pc - start_p
        self.move_cursor_to_line(addr_diff // 2)

        self.refresh_display()

    def get_op_color(self, op: str) -> str:
        if op.startswith("mov"):
            return preferences.current_theme.mov
        elif op in ["nop"]:
            return preferences.current_theme.nop
        elif op in ["bf", "bra", "bt", "bf.s", "bt.s"]:
            return preferences.current_theme.jmp
        elif op in ["rts"]:
            return preferences.current_theme.ret
        elif op.startswith("cmp"):
            return preferences.current_theme.cmp
        elif op.startswith("bsr"):
            return preferences.current_theme.call
        elif (op.startswith("add") or
            op.startswith("mul") or
            op.startswith("mac") or
            op.startswith("neg") or
            op.startswith("sub")
        ):  # TODO: sub, etc
            return preferences.current_theme.math
        elif op.startswith("."):
            return preferences.current_theme.trap

        return ""

    def hook(self, root: tk.Frame):
        self.set_widgets(root)

        self.refresh_asm()

    def do_step(self):
        # TODO
        self.refresh_asm()

    def move_cursor_to_line(self, addr_diff: int, cursor=None):
        if cursor is None:
            cursor = self._cursors['pc']
        sz = preferences.current_font.size

        cursor['pos']['y'] = max(sz // 2, 6) + (sz + max(sz // 2, 6)) * addr_diff

    def queue_arrow(self, start: int, size: int):
        self._arrows.append([-1, start, size])

    def draw_arrows(self):
        self.clear_arrows()

        width = preferences.get("lines_width", 1)
        spacing = preferences.get("arrow_spacing", 2)
        spacing_start = preferences.get("arrow_spacing_start", 2)

        starting_pos = []
        starting_pos_x = {}
        ending_pos = []
        ending_pos_x = {}
        pos_color = {}

        for index in range(len(self._arrows)):
            x = self.gutter_size - ((index + 1) * spacing * 2 * width) - spacing_start
            start = line_y(self._arrows[index][1]) + line_height() // 2
            end = line_y(self._arrows[index][1] + self._arrows[index][2] + 1) - line_height() // 2

            fill = preferences.current_theme.flow if start < end else preferences.current_theme.other

            self._arrows[index][0] = self.canvas.create_line(
                x,
                start,
                x,
                end,
                width=width,
                fill=fill)

            if start not in starting_pos:
                starting_pos.append(start)
                starting_pos_x[start] = x
                pos_color[start] = fill
            else:
                starting_pos_x[start] = min(x, starting_pos_x[start])
                if pos_color[end] != fill and fill == preferences.current_theme.flow:
                    pos_color[end] = fill

            if end not in ending_pos:
                ending_pos.append(end)
                ending_pos_x[end] = x
                pos_color[end] = fill
            else:
                ending_pos_x[end] = min(x, ending_pos_x[end])
                if pos_color[end] != fill and fill == preferences.current_theme.flow:
                    pos_color[end] = fill

            self._arrows_memo.append(self._arrows[index])

        for pos in starting_pos:
            arrow_start = self.canvas.create_line(
                starting_pos_x[pos],
                pos,
                self.gutter_size - 1,
                pos,
                width=width,
                fill=pos_color[pos])
            self._arrows_memo.append((arrow_start,))

        for pos in ending_pos:
            arrow_end = self.canvas.create_line(
                ending_pos_x[pos],
                pos,
                self.gutter_size - 1,
                pos,
                width=width,
                fill=pos_color[pos],
                arrow=tk.LAST)
            self._arrows_memo.append((arrow_end,))

    def clear_arrows(self):
        for index in range(len(self._arrows_memo)):
            self.canvas.delete(self._arrows_memo[index][0])
        self._arrows_memo = []

    # Mouse scroll stuff !
    def do_mousewheel(self, event):
        pos = int(-1 * (event.delta / 120))
        self.canvas.yview_scroll(pos, "units")
        self.apply_scroll()

        # todo: fetch older / newer ??
        return "break"

    def apply_scroll(self):
        self._scroll_top = round(self._canvas_max_height * self.canvas.yview()[0])

    def do_motion(self, e):
        sensibility = 2
        if e.x - sensibility <= self.gutter_size <= e.x + sensibility:
            self.canvas.config(cursor="sizing")
            self._changes['cursor'] = True
            self._changes['drag'] = True
        else:
            if self._changes['cursor']:
                self.canvas.config(cursor="")
                self._changes['drag'] = False
        return "break"

    MIN_GUTTER_SIZE = 8
    MAX_GUTTER_SIZE = 500

    def do_b1_motion(self, e):
        if self._changes['drag']:
            x = e.x
            if self.MIN_GUTTER_SIZE < x <= self.MAX_GUTTER_SIZE:
                self._changes['gutter_size'] = True
                self.gutter_size = x
                self.refresh_display()
        return "break"
