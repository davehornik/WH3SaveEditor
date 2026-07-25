# -*- coding: utf-8 -*-
"""Mini i18n: klíč = český text, překlady v lang/<kód>.json (fallback = klíč)."""
import json
import os
import sys

_strings = {}
lang = "cs"


def res_dir():
    """Složka se zdroji (lang/, fonts/) — funguje i v PyInstaller .exe."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    """Složka pro zápis (settings.ini) — vedle .exe, ne do tempu."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load(code):
    global _strings, lang
    lang = code
    _strings = {}
    path = os.path.join(res_dir(), "lang", code + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            _strings = json.load(f)
    except OSError:
        pass


def t(key):
    return _strings.get(key, key)


def available():
    d = os.path.join(res_dir(), "lang")
    out = []
    if os.path.isdir(d):
        out = [f[:-5] for f in os.listdir(d) if f.endswith(".json")]
    return sorted(set(out) | {"cs"})
