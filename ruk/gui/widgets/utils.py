import tkinter as tk
from tkinter import ttk

from ruk.gui.preferences import preferences, Preferences

class HookToolTip(object):
    """
    create a tooltip for a given widget
    """

    def __init__(self, widget, text='widget info'):
        self.waittime = 500  # miliseconds
        self.wraplength = 180  # pixels
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.id = None
        self.tw = None
        self._pref = preferences

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.waittime, self.showtip)

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20

        try:
            scheme = self._pref["theme_scheme"]
            bg = self._pref[f"tooltip_{scheme}"]["bg"]
            background = self._pref[f"tooltip_{scheme}"]["background"]
        except (IndexError, KeyError):
            bg = "#000000"
            background = "#ffffff"

        self.tw = tk.Toplevel(self.widget, bg=bg, borderwidth=1)

        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background=background, borderwidth=0,
                         wraplength=self.wraplength, padx=8, pady=4)
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tw
        self.tw = None
        if tw:
            tw.destroy()

def to_clip(data: str):
    r = tk.Tk()
    r.withdraw()
    r.clipboard_clear()
    r.clipboard_append(data)
    r.update()  # now it stays on the clipboard after the window is closed
    r.destroy()

