from tkinter import ttk
import tkinter as tk

from ruk.gui.widgets.base import BaseWrapper


class FlexGrid(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.text = tk.Text(self, wrap="char", borderwidth=0, highlightthickness=0,
                            state="disabled")
        self.text.pack(fill="both", expand=True)
        self.boxes = []

    def add_box(self, elem: BaseWrapper):
        frame = tk.Frame(self.text, bd=1, relief="sunken", background="blue",
                       width=224, height=40)
        elem.set_widget(frame)
        self.boxes.append(frame)

        self.text.configure(state="normal")
        self.text.window_create("end", window=frame)
        self.text.configure(state="disabled")