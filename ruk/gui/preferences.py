import json
from typing import Union

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
    }
}

class Preferences(object):
    def __init__(self, default=None):
        if default is None:
            default = _default_conf
        self._config = default

    def __setitem__(self, key: Union[str, int], value):
        self._config[key] = value

    def __getitem__(self, item: Union[str, int]):
        return self._config[item]

    def get(self, item: Union[str, int], default=""):
        try:
            return self._config[item]
        except (IndexError, KeyError):
            return default

    def __len__(self):
        return len(self._config)

    def __iter__(self):
        for x in self._config.__iter__():
            yield x

    def __str__(self):
        return str(self._config)

    def __repr__(self):
        return repr(self._config)


preferences = Preferences()
