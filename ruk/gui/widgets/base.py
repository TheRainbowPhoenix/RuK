import tkinter as tk


class BaseWrapper(object):
    def set_widget(self, frame: tk.Frame):
        raise NotImplementedError

    def update_values(self):
        raise NotImplementedError


class BaseFrame(object):
    def refresh(self):
        raise NotImplementedError

    def hook(self, root: tk.Frame):
        raise NotImplementedError
