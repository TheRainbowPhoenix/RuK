"""
LCD Display Viewer window for RuK.

Shows the R61523 LCD framebuffer (396x224 RGB565) in a Tkinter window.
Can be toggled from the "LCD" button in the toolbar.
"""

import tkinter as tk
from tkinter import ttk

from ruk.gui.window import BaseWindow


class LCDViewerWindow(BaseWindow):
    """A window that displays the LCD framebuffer."""

    def __init__(self, root: tk.Tk, display):
        super().__init__(title="LCD Display :: RuK")
        self.display = display
        self._scale = 2   # 2x scaling (792x448)
        self._auto_refresh = False
        self._refresh_interval = 100   # ms
        self._after_id = None
        self._setup()

    def _setup(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        # Toolbar
        toolbar = ttk.Frame(self.root)
        toolbar.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)

        refresh_btn = ttk.Button(toolbar, text="Refresh", command=self._refresh, width=10)
        refresh_btn.pack(side=tk.LEFT, padx=2)

        self._auto_var = tk.IntVar(value=0)
        auto_check = ttk.Checkbutton(toolbar, text="Auto", variable=self._auto_var,
                                     command=self._toggle_auto)
        auto_check.pack(side=tk.LEFT, padx=2)

        # Canvas for the LCD
        canvas_w = 396 * self._scale
        canvas_h = 224 * self._scale
        self.canvas = tk.Canvas(self.root, width=canvas_w, height=canvas_h,
                                bg='black', highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Scrollbars (in case window is smaller than canvas)
        h_scroll = ttk.Scrollbar(self.root, orient=tk.HORIZONTAL, command=self.canvas.xview)
        v_scroll = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        h_scroll.grid(row=2, column=0, sticky='ew')
        v_scroll.grid(row=1, column=1, sticky='ns')

        # Set scroll region
        self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))

        # Create the PhotoImage for rendering
        self._image = tk.PhotoImage(width=396, height=224)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._image)

        # Initial render
        self._refresh()

        self.root.deiconify()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _rgb565_to_rgb(self, val):
        """Convert a 16-bit RGB565 value to an (r, g, b) tuple."""
        r = (val >> 11) & 0x1F
        g = (val >> 5) & 0x3F
        b = val & 0x1F
        # Scale to 0-255
        r = (r << 3) | (r >> 2)
        g = (g << 2) | (g >> 4)
        b = (b << 3) | (b >> 2)
        return r, g, b

    def _refresh(self):
        """Render the current framebuffer to the canvas."""
        if self.display is None:
            return

        fb = self.display.get_framebuffer()
        # Build pixel data as a hex string for PhotoImage.put()
        # PhotoImage.put() expects a list of strings like "#RRGGBB ..."
        pixel_rows = []
        for y in range(224):
            row_pixels = []
            for x in range(396):
                val = fb[y][x] & 0xFFFF
                r, g, b = self._rgb565_to_rgb(val)
                row_pixels.append(f"#{r:02X}{g:02X}{b:02X}")
            pixel_rows.append(' '.join(row_pixels))

        self._image.put(pixel_rows)

        # Scale up by zooming (PhotoImage zoom)
        self._image_zoomed = self._image.zoom(self._scale, self._scale)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._image_zoomed)

    def _toggle_auto(self):
        if self._auto_var.get():
            self._auto_refresh = True
            self._schedule_refresh()
        else:
            self._auto_refresh = False
            if self._after_id:
                self.root.after_cancel(self._after_id)
                self._after_id = None

    def _schedule_refresh(self):
        if self._auto_refresh:
            self._refresh()
            self._after_id = self.root.after(self._refresh_interval, self._schedule_refresh)

    def _on_close(self):
        self._auto_refresh = False
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.root.withdraw()

    def setup_callbacks(self):
        pass

    def attach(self, cp):
        pass
