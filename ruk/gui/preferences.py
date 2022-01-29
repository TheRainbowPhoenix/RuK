import json
from typing import Union, Dict

# Dark mode
_default_conf = {
    "theme_scheme": "dark",
    "tooltip_light": {
        "bg": "#E7E7E7",
        "background": "#FAFAFA",
    },
    "tooltip_dark": {
        "bg": "#1D1D1D",
        "background": "#272727",
    },
    "lines_width": 1,
    "arrow_spacing": 3,
    "arrow_spacing_start": 8,
    "gutter_size": 54,
}

_default_theme = {
    # Ayu
    "#~gui.background": "#202020",  # default is #25282b but I like darker
    "ec comment": '#95e6cb',
    "ec cmp": '#50d0e0',
    "ec input": '#808080',
    "ec jmp": '#c2d94c',
    "ec math": '#50d0e0',
    "ec mov": '#d9d8d7',
    "ec nop": '#a37acc',
    "ec num": '#f28779',
    "ec offset": '#ed9366',
    "ec other": '#808080',
    "ec pop": '#50d0e0',
    "ec push": '#50d0e0',
    "ec reg": '#e6e1cf',
    "ec ret": '#d06060',
    "ec swi": '#d06060',
    "ec trap": '#d06060',
    "ec call": '#ff7733',
    "ec ucall": '#5ccfe6',
    "ec ujmp": '#c2d94c',
    "ec usrcmt": '#fa6e32',
    "ec flow": '#c2d94c',
    "#~highlightPC": '#571a07',
    "#~lineHighlight": '#2B2B2B',  # '#1B1B1B', if you want darker
}


class DictWrapper(object):
    def __init__(self, default):
        self._values = default

    def __setitem__(self, key: Union[str, int], value):
        self._values[key] = value

    def __getitem__(self, item: Union[str, int]):
        return self._values[item]

    def get(self, item: Union[str, int], default=""):
        try:
            return self._values[item]
        except (IndexError, KeyError):
            return default

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        for x in self._values.__iter__():
            yield x

    def __str__(self):
        return str(self._values)

    def __repr__(self):
        return repr(self._values)


class ColorTheme(DictWrapper):
    def __init__(self, name: str, colors: Dict[str, str]):
        self.name = name
        super().__init__(colors)

    @property
    def offset(self):
        return self._values["ec offset"]

    @property
    def mov(self):
        return self._values["ec mov"]

    @property
    def jmp(self):
        return self._values["ec jmp"]

    @property
    def ret(self):
        return self._values["ec ret"]

    @property
    def cmp(self):
        return self._values["ec cmp"]

    @property
    def num(self):
        return self._values["ec num"]

    @property
    def math(self):
        return self._values["ec math"]

    @property
    def comment(self):
        return self._values["ec comment"]

    @property
    def trap(self):
        return self._values["ec trap"]

    @property
    def flow(self):
        return self._values["ec flow"]

    @property
    def call(self):
        return self._values["ec call"]

    @property
    def gui_background(self):
        return self._values["#~gui.background"]

    @property
    def highlight_PC(self):
        return self._values["#~highlightPC"]

    @property
    def line_highlight(self):
        return self._values["#~lineHighlight"]


class FontTheme(DictWrapper):
    def __init__(self, name='Consolas', size: int = 14):  # 14
        default = {
            'name': name,
            'size': size
        }
        super().__init__(default)

    @property
    def string(self) -> str:
        return f'{self._values["name"]} {self._values["size"]}'

    @property
    def name(self) -> int:
        return self._values["name"]

    @property
    def size(self) -> int:
        return self._values["size"]


class Preferences(DictWrapper):
    def __init__(self, default=None):
        if default is None:
            default = _default_conf

        super().__init__(default)

        self._current_theme = ColorTheme("Ayu", _default_theme)
        self._current_font = FontTheme()

    @property
    def current_theme(self) -> ColorTheme:
        return self._current_theme

    @property
    def current_font(self) -> FontTheme:
        return self._current_font


preferences = Preferences()
