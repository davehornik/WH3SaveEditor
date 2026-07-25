# -*- coding: utf-8 -*-
"""Čitelná jména z herních lokalizačních packů (local_XX.pack).

PFH5 pack -> text\\localisation__.loc (zstd) -> {loc_klíč: text}.
Načítá se ve stejném jazyce, jaký má hráč ve hře (data/language.txt).
Filtrovaná podmnožina se cachuje na disk, takže start je rychlý.
Bez nalezené hry modul tiše degraduje — get() vrací None a tabulky
zůstanou u dosavadních klíčů/pretty() náhrad.
"""
import json
import os
import struct
import threading

from i18n import app_dir

APP_ID = "1142710"
GAME_DIR_NAME = os.path.join("steamapps", "common", "Total War WARHAMMER III")

# rodiny klíčů, které si držíme v cache (vše ostatní zahodíme)
PREFIXES = (
    "names_name_",
    "factions_screen_name_",
    "regions_onscreen_",
    "provinces_onscreen_",
    "land_units_onscreen_name_",
    "agent_subtypes_onscreen_name_override_",
)

_table = {}
_loaded = False
_lock = threading.Lock()


# -- nalezení hry ------------------------------------------------------------

def _steam_roots():
    """Kandidáti na kořeny Steam knihoven (registry + libraryfolders.vdf)."""
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        pass
    roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    out = []
    for r in roots:
        r = os.path.normpath(r)
        if r not in out and os.path.isdir(r):
            out.append(r)
    # libraryfolders.vdf odkazuje na další knihovny (jiné disky)
    for r in list(out):
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('"path"'):
                        p = line.split('"')[3].replace("\\\\", "\\")
                        p = os.path.normpath(p)
                        if p not in out and os.path.isdir(p):
                            out.append(p)
        except OSError:
            pass
    return out


def find_game_dir(cfg=None):
    """Složka s WH3. Přednost má settings.ini [paths] game_dir."""
    if cfg is not None:
        p = cfg.get("paths", "game_dir", fallback="")
        if p and os.path.isdir(os.path.join(p, "data")):
            return p
    for root in _steam_roots():
        p = os.path.join(root, GAME_DIR_NAME)
        if os.path.isdir(os.path.join(p, "data")):
            return p
    return None


# -- PFH5 + LOC parsování ----------------------------------------------------

def _pack_entries(data):
    """[(path, size, offset)] z indexu PFH5 packu."""
    magic, _mask, _refs, _ref_idx, nfiles, idx_size = struct.unpack_from(
        "<4sIIIII", data, 0)
    if magic != b"PFH5":
        raise ValueError("není PFH5 pack: %r" % magic)
    off = 28
    entries = []
    for _ in range(nfiles):
        size, = struct.unpack_from("<I", data, off)
        off += 5                      # u32 size + u8 compressed flag
        end = data.index(b"\x00", off)
        entries.append([data[off:end].decode("latin1"), size, 0])
        off = end + 1
    pos = 28 + idx_size
    for e in entries:
        e[2] = pos
        pos += e[1]
    return entries


def _read_loc(pack_path):
    """{loc_klíč: text} z text\\localisation__.loc uvnitř packu."""
    import zstandard
    with open(pack_path, "rb") as f:
        data = f.read()
    entry = next((e for e in _pack_entries(data)
                  if e[0].lower().endswith(".loc")), None)
    if entry is None:
        raise ValueError("pack neobsahuje .loc soubor")
    _path, size, pos = entry
    raw = data[pos:pos + size]
    usize, = struct.unpack_from("<I", raw, 0)
    out = zstandard.ZstdDecompressor().decompress(raw[4:], max_output_size=usize)
    # FFFE 'LOC' 00, u32 verze, u32 počet; entry = utf16 klíč + utf16 text + u8
    count, = struct.unpack_from("<I", out, 10)
    off = 14
    full = {}
    for _ in range(count):
        kl, = struct.unpack_from("<H", out, off)
        off += 2
        key = out[off:off + 2 * kl].decode("utf-16-le")
        off += 2 * kl
        vl, = struct.unpack_from("<H", out, off)
        off += 2
        full[key] = out[off:off + 2 * vl].decode("utf-16-le")
        off += 2 * vl + 1
    # hodnoty umí odkazovat jinam ({{tr:jiný_klíč}}) — rozpusť před filtrací
    table = {}
    for key, val in full.items():
        if not key.startswith(PREFIXES):
            continue
        for _ in range(4):                       # max hloubka řetězení
            if val.startswith("{{tr:") and val.endswith("}}"):
                val = full.get(val[5:-2], "")
            else:
                break
        if val and not val.startswith("{{tr:"):
            table[key] = val
    return table


# -- načtení s diskovou cache ------------------------------------------------

def _cache_path():
    return os.path.join(app_dir(), "loc_cache.json")


def load(cfg=None):
    """Načti lokalizace (cache -> pack). Bezpečné volat opakovaně i z vlákna."""
    global _table, _loaded
    with _lock:
        if _loaded:
            return bool(_table)
        _loaded = True
        game = find_game_dir(cfg)
        if not game:
            return False
        lang = "en"
        try:
            with open(os.path.join(game, "data", "language.txt")) as f:
                lang = f.read().strip().lower() or "en"
        except OSError:
            pass
        pack = os.path.join(game, "data", "local_%s.pack" % lang)
        if not os.path.isfile(pack):
            pack = os.path.join(game, "data", "local_en.pack")
            if not os.path.isfile(pack):
                return False
        try:
            mtime = int(os.path.getmtime(pack))
            try:
                with open(_cache_path(), encoding="utf-8") as f:
                    c = json.load(f)
                if c.get("pack") == pack and c.get("mtime") == mtime:
                    _table = c["table"]
                    return True
            except (OSError, ValueError, KeyError):
                pass
            _table = _read_loc(pack)
            try:
                with open(_cache_path(), "w", encoding="utf-8") as f:
                    json.dump({"pack": pack, "mtime": mtime, "table": _table},
                              f, ensure_ascii=False)
            except OSError:
                pass
            return True
        except Exception:
            _table = {}
            return False


def preload(cfg=None):
    """Odstartuj načítání na pozadí (při startu aplikace)."""
    threading.Thread(target=load, args=(cfg,), daemon=True).start()


def ready():
    return _loaded


# -- dotazy ------------------------------------------------------------------

def get(key):
    v = _table.get(key)
    return v if v else None


def faction(key):
    return get("factions_screen_name_" + str(key))


def region(key):
    return get("regions_onscreen_" + str(key))


def province(key):
    return get("provinces_onscreen_" + str(key))


def unit(key):
    return get("land_units_onscreen_name_" + str(key))


def subtype(key):
    return get("agent_subtypes_onscreen_name_override_" + str(key))


def char_name(parts):
    """Přelož části jména postavy (names_name_XXX ...). None = neumíme."""
    out = [v for v in (get(p) for p in parts) if v]
    return " ".join(out) if out else None
