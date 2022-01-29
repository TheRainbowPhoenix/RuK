import sys
import os
import ctypes
import tkinter as tk
from tkinter import ttk

import typing

from ruk.gui.controls import ControlsFrame
from ruk.gui.cpu_wrap import RegisterFrame
from ruk.gui.disasm_wrap import DisasmFrame
from ruk.gui.preferences import preferences, Preferences
from ruk.gui.resources import ResourceManager

if typing.TYPE_CHECKING:  # pragma: no cover
    from ruk.classpad import Classpad
    from ruk.gui.widgets.base import BaseFrame

PLATFORM = sys.platform


class BaseWindow(object):
    def __init__(self, title: str = "Unnamed window", root=None):
        if root is None:
            self.root = tk.Tk()
        else:
            self.root = root

        if "win" in PLATFORM:
            app_id = u'local.konshin.phoebe.RuK'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

        self.root.title(title)
        self.root.resizable(True, True)

        self.preferences: Preferences = preferences

        self.resources: ResourceManager = ResourceManager(self.root)

        self.screensize = (800, 600)

        if root is None:
            self.set_theme()

    def win32_fixes(self):
        if "win" in PLATFORM:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # if your windows version >= 8.1
            except:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()  # Before Windows 8.1
                except:
                    pass  # Windows 7 or before

            try:
                self.screensize = [ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)]
            except:
                pass

    def set_theme(self):
        """
        Set the cute Sun Valley theme
        """
        # TODO: user-configured them
        scheme = self.preferences.get("theme_scheme", "light")
        self.root.tk.call("source", "./ruk/gui/theme/sun-valley.tcl")
        self.root.tk.call("set_theme", scheme)

        self.resources.load()

    def show(self):
        self.root.update_idletasks()

        if "win" in PLATFORM:
            self.root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)), "res/RuK.ico"))
            self.win32_fixes()
        else:
            self.screensize = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())

        xp = (self.screensize[0] // 2) - (self.root.winfo_width() // 2)
        yp = (self.screensize[1] // 2) - (self.root.winfo_height() // 2)
        geom = (self.root.winfo_width(), self.root.winfo_height(), xp, yp)
        self.root.geometry('{0}x{1}+{2}+{3}'.format(*geom))

        self.root.mainloop()


class ModalWindow(BaseWindow):
    def __init__(self, title: str = "Unnamed window", parent: tk.Tk = None):
        if parent is None:
            parent = tk.Tk()

        root = tk.Toplevel(parent)

        self.ret_val: typing.Any = None

        super().__init__(title, root=root)


        self.root.transient(parent)
        self.root.grab_set()
        # self.root = root
        self.root.title(title)


class DebuggerWindow(BaseWindow):
    def __init__(self, **kw):
        super().__init__(title="RuK - Debugger")

        self.frames: typing.List[BaseFrame] = []

        self._cp: Classpad = None

    def setup_workspace(self):
        """
        Control frames: debugger
        """
        control_frame = tk.Frame(master=self.root, width=50, bd=0)

        self.control_ctrl: ControlsFrame = ControlsFrame(self._cp.cpu, self.resources)
        self.control_ctrl.hook(control_frame)
        self.control_ctrl.set_refresh_callback(self.refresh_all)

        control_frame.pack(fill=tk.X, side=tk.TOP, expand=False, anchor=tk.N)

        """
        ASM Frame: disasm view
        """
        asm_frame = tk.Frame(master=self.root, width=600, height=650, bd=0)
        self.asm_view = DisasmFrame(self._cp.cpu, self.resources)
        self.asm_view.hook(asm_frame)
        self.asm_view.set_refresh_callback(self.refresh_all)
        asm_frame.pack(fill=tk.BOTH, side=tk.LEFT, expand=True, anchor=tk.CENTER)

        """
        Regs frame: register view
        """
        regs_frame = tk.Frame(master=self.root, width=200, height=100)

        self.reg_ctrl_frame: RegisterFrame = RegisterFrame(self._cp.cpu)
        self.reg_ctrl_frame.hook(regs_frame)
        self.frames.append(self.reg_ctrl_frame)

        regs_frame.pack(fill=tk.BOTH, side=tk.RIGHT, expand=False, anchor=tk.SE)

    def refresh_all(self):
        for frame in self.frames:
            frame.refresh()

    def setup_callbacks(self):
        def on_step():
            self.reg_ctrl_frame.do_step()
            self.asm_view.do_step()

        self.control_ctrl.on_step_callback = on_step

        def on_reset():
            self.reg_ctrl_frame.refresh()
            self.asm_view.refresh()

        self.control_ctrl.on_stop_callback = on_reset

    def attach(self, cp):
        self._cp = cp

        self.setup_workspace()
        self.refresh_all()

        self.setup_callbacks()
