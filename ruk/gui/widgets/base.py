import tkinter as tk
from typing import Callable


class BaseWrapper(object):
    def set_widget(self, frame: tk.Frame):
        raise NotImplementedError

    def update_values(self):
        raise NotImplementedError


class BaseFrame(object):
    def __init__(self):
        def noop():
            pass
        self._refresh_callback = noop()

    def refresh(self):
        raise NotImplementedError

    def hook(self, root: tk.Frame):
        raise NotImplementedError

    def set_refresh_callback(self, call: Callable):
        self._refresh_callback = call
