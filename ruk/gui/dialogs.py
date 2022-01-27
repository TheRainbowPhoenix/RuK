import tkinter as tk
from tkinter import ttk

from ruk.gui.window import BaseWindow


class EditBytesDialog(BaseWindow):
    def __init__(self, address: int):
        super().__init__(f"Edit Bytes at {hex(address)}")

        self._setup()

    def _setup(self):
        self.frame = ttk.Frame(self.root)
        self.frame.pack(ipadx=2, ipady=2)

        self.entry = ttk.Entry(self.frame)
        self.entry.pack()
        self.entry.focus_set()

        self.message = ttk.Label(self.frame, text="bf 0x0800006a;")
        self.message.pack(padx=8, pady=8)

        self.btn_frame = ttk.Frame(self.root)
        self.btn_frame.pack(padx=4, pady=4)


        btn_2 = ttk.Button(self.btn_frame, width=8, text="Cancel")
        # btn_1['command'] = self.b1_action
        btn_2.pack(side='right')

        btn_1 = ttk.Button(self.btn_frame, width=8, text="OK")
        # btn_1['command'] = self.b1_action
        btn_1.pack(side='right')


        self.root.deiconify()



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
        user['sex'] = mbox('male or female?', ('male', 'm'), ('female', 'f'))
        mbox(user, frame=False)
