import string
import tkinter as tk
from binascii import unhexlify
from tkinter import ttk

from ruk.gui.window import BaseWindow, ModalWindow
from ruk.jcore.cpu import CPU


# root.attributes("-toolwindow", 1)

class EditBytesDialog(ModalWindow):
    def __init__(self, root: tk.Tk, address: int, cpu: CPU):
        super().__init__(parent=root, title=f"Edit {hex(address)}")

        self.root.resizable(False, False)

        self._cpu = cpu
        self.address = address

        self.asm_preview = tk.StringVar()
        self.hex_data = tk.StringVar()
        self._ret_data = tk.StringVar()

        self._valid_flag = True

        try:
            self._setup()
        except Exception as e:
            # TODO: real error message
            print(f"Invalid addr provided {hex(self.address)} !")
            raise e

    def disasm(self, chunk: bytes) -> str:
        try:
            val = int.from_bytes(chunk, "big")
            self._valid_flag = True
            try:
                op_str, args = self._cpu.disassembler.disasm(val, trace_only=True)
                return op_str.format(**args) + ";"  #op_str % args + ";"  #
            except IndexError:
                return f".word 0x{val:04x}"

        except Exception as e:
            print(e)
            self._valid_flag = False
            return "Unknown Instruction"

    VALID_CHARS = string.hexdigits + ' ' + '\t'

    def update_preview(self, *_):
        try:
            raw_data = self.hex_data.get()
            filtered_data = ''.join([
                c for c in raw_data if c in string.hexdigits
            ])

            hex_data = ''.join(filtered_data.strip().split())

            if len(hex_data) != len(raw_data):
                self.hex_data.set(filtered_data)

            if len(hex_data) > 4:
                if len(raw_data) == len(hex_data):
                    self.hex_data.set(self.hex_data.get()[:4])
                else:
                    self.hex_data.set(hex_data[:4])
                return False

            if len(hex_data) % 2 != 0:
                return True


            # self.hex_data.set(raw_data)
            self._ret_data.set(hex_data)
            data = unhexlify(hex_data)
            asm = self.disasm(data)

            self.asm_preview.set(asm)

        except Exception as e:
            print(e)

        return True

    def to_clip(self, event=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.hex_data.get())
        return "break"

    def _setup(self):
        self.root.bind('<Control-c>', func=self.to_clip)

        self.frame = ttk.Frame(self.root)
        self.frame.pack(ipadx=2, ipady=2, padx=8, pady=2)

        self.mem = self._cpu.mem.read16(self.address)
        self.asm_preview.set(self.disasm(self.mem))

        self.hex_data.set(self.mem.hex())

        self.entry = ttk.Entry(self.frame, textvariable=self.hex_data,
                               validatecommand=self.update_preview, validate='all')
        self.entry.bind("<KeyRelease>", self.update_preview)
        self.entry.bind("<Return>", self.do_ok)
        self.entry.bind("<Escape>", self.do_cancel)
        self.entry.pack(padx=8, pady=8)
        self.entry.focus_set()

        self.message = ttk.Label(self.frame, textvariable=self.asm_preview)
        self.message.pack(padx=8, pady=4)

        self.btn_frame = ttk.Frame(self.root)
        self.btn_frame.pack(padx=4, pady=4)

        btn_1 = ttk.Button(self.btn_frame, width=8,
                           text="OK",
                           style="Accent.TButton")
        btn_1['command'] = self.do_ok
        btn_1.pack(side='right', padx=4, pady=4)

        btn_2 = ttk.Button(self.btn_frame, width=8, text="Cancel")
        btn_2['command'] = self.do_cancel
        btn_2.pack(side='right', padx=4, pady=4)

        self.root.deiconify()

    def do_ok(self, *_):
        self.ret_val = self._ret_data.get()
        self.root.quit()
        self.root.destroy()

    def do_cancel(self, *_):
        self.ret_val = None
        self.root.quit()
        self.root.destroy()


class MessageBox(BaseWindow):

    def __init__(self, msg, b1, b2, frame, timeout: int = 0, entry: bool = False):

        super().__init__()

        self.msg = msg
        self.b1 = b1
        self.b2 = b2
        self.frame = frame
        self.t = timeout
        self.entry = entry

        self._setup()

    def _setup(self):
        self.root.title('Message')
        self.msg = str(self.msg)
        self.root.bind('<Control-c>', func=self.to_clip)
        if not self.frame:
            self.root.overrideredirect(True)

        self.b1_return = True
        self.b2_return = False

        if isinstance(self.b1, tuple):
            b1, self.b1_return = self.b1
        if isinstance(self.b2, tuple):
            b2, self.b2_return = self.b2

        frm_1 = ttk.Frame(self.root)
        frm_1.pack(ipadx=2, ipady=2)

        message = ttk.Label(frm_1, text=self.msg)
        message.pack(padx=8, pady=8)

        if self.entry:
            self.entry = ttk.Entry(frm_1)
            self.entry.pack()
            self.entry.focus_set()
        # button frame
        frm_2 = ttk.Frame(frm_1)
        frm_2.pack(padx=4, pady=4)
        # buttons
        btn_1 = ttk.Button(frm_2, width=8, text=self.b1)
        btn_1['command'] = self.b1_action
        btn_1.pack(side='left')
        if not self.entry:
            btn_1.focus_set()

        btn_2 = ttk.Button(frm_2, width=8, text=self.b2)
        btn_2['command'] = self.b2_action
        btn_2.pack(side='left')

        btn_1.bind('<KeyPress-Return>', func=self.b1_action)
        btn_2.bind('<KeyPress-Return>', func=self.b2_action)

        self.root.protocol("WM_DELETE_WINDOW", self.close_mod)
        # a trick to activate the window (on windows 7)
        self.root.deiconify()
        # if t is specified: call time_out after t seconds
        if self.t > 0:
            self.root.after(int(self.t * 1000), func=self.time_out)

    def b1_action(self, event=None):
        try:
            x = self.entry.get()
        except AttributeError:
            self.returning = self.b1_return
            self.root.quit()
        else:
            if x:
                self.returning = x
                self.root.quit()

    def b2_action(self, event=None):
        self.returning = self.b2_return
        self.root.quit()

    # remove this function and the call to protocol
    # then the close button will act normally
    def close_mod(self):
        pass

    def time_out(self):
        try:
            x = self.entry.get()
        except AttributeError:
            self.returning = None
        else:
            self.returning = x
        finally:
            self.root.quit()

    def to_clip(self, event=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.msg)


def mbox(msg, b1='OK', b2='Cancel', frame=True, t=False, entry=False):
    """Create an instance of MessageBox, and get data back from the user.
    msg = string to be displayed
    b1 = text for left button, or a tuple (<text for button>, <to return on press>)
    b2 = text for right button, or a tuple (<text for button>, <to return on press>)
    frame = include a standard outerframe: True or False
    t = time in seconds (int or float) until the msgbox automatically closes
    entry = include an entry widget that will have its contents returned: True or False
    """
    msgbox = MessageBox(msg, b1, b2, frame, t, entry)
    msgbox.show()
    # the function pauses here until the mainloop is quit
    msgbox.root.destroy()
    return msgbox.returning


if __name__ == '__main__':
    user = {}
    mbox('starting in 1 second...', t=1)
    user['name'] = mbox('name?', entry=True)
    if user['name']:
        user['binary'] = mbox('0 or 1?', ('False', '0'), ('True', '1'))
        mbox(user, frame=False)
