import os
import tkinter as tk

# os.listdir ?
resource_map = {
    'start': "res/toolbar/start.png",
    'step_over': "res/toolbar/step_over.png",
    'stop': "res/toolbar/stop.png",
    'continue_until_syscall': "res/toolbar/continue_until_syscall.png",
    'continue_until_call': "res/toolbar/continue_until_call.png",
    'step_into': "res/toolbar/step_into.png",
    'except_pause_on': "res/toolbar/except_pause_on.png",
    'except_pause_off': "res/toolbar/except_pause_off.png",
}


class ResourceManager:
    """
    Small resources manager, for easier file load...
    """
    # If any texture is missing, return this one ...
    MISSING_RES = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x03\x00\x00\x00\x03\x08\x02\x00\x00\x00\xd9J"\xe8\x00\x00\x00\tpHYs\x00\x00\x12t\x00\x00\x12t\x01\xdef\x1fx\x00\x00\x00\x18IDATx\xdac\xf8\xcf\xf0_BR\nH2@( \xc9\x00\x17\x03\x00\xa7\x14\x0b#%D\xd2\x15\x00\x00\x00\x00IEND\xaeB`\x82'

    def __init__(self, root: tk.Tk):
        self._res = {}

        self._root = root

    def load(self):
        for res in resource_map:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), resource_map[res])
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    file_format = 'png'
                    self._res[res] = tk.PhotoImage(data=f.read(), format=file_format)

    def __getitem__(self, key: str):
        try:
            return self._res[key]
        except KeyError:
            print(f"ERROR: Missing texture \"{key}\"")
            return tk.PhotoImage(data=self.MISSING_RES, format='png')
