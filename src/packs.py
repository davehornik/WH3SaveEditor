# -*- coding: utf-8 -*-
"""Čtení souborů z herních packů (PFH5) — index cest a ikony jednotek.

Index: pro každý `data/*.pack` se přečte jen hlavička (28 B) a tabulka souborů, ne obsah.
Cesta → (pack, offset, velikost, komprimováno). Komprimované položky = u32 nekomprimovaná
velikost + zstd proud (stejně jako lokalizace v locdb). Ikony jednotek: `ui/units/icons/<klíč>.png`
(PNG 60×130, karty z herního panelu armády), v ui.pack jich je ~1 070.
"""
import glob
import os
import struct
import threading

import locdb

_index = None
_lock = threading.Lock()
_game_dir = None

# indexujeme jen to, co editor používá (celý index má 740 k cest a stovky MB)
KEEP_PREFIXES = ("ui/units/icons/", "ui/portraits/", "ui/flags/", "db/")


def _pack_index(path):
    """[(cesta, offset, velikost, flag)] z hlavičky a tabulky souborů jednoho PFH5 packu."""
    with open(path, "rb") as fh:
        head = fh.read(28)
        if len(head) < 28 or head[:4] != b"PFH5":
            return []
        # 4s magic, u32 typ, u32 počet závislostí, u32 velikost jejich indexu, u32 počet souborů,
        # u32 velikost indexu souborů, u32 časové razítko → index začíná na 28 (+ index závislostí)
        _magic, _mask, _refs, ref_idx, nfiles, idx_size = struct.unpack_from("<4sIIIII", head, 0)
        fh.seek(28 + ref_idx)
        data = fh.read(idx_size)
    off = 0
    entries = []
    for _ in range(nfiles):
        if off + 5 > len(data):
            break
        size, flag = struct.unpack_from("<IB", data, off)
        off += 5
        end = data.find(b"\x00", off)
        if end < 0:
            break
        entries.append([data[off:end].decode("latin1").lower().replace("\\", "/"), size, flag])
        off = end + 1
    pos = 28 + ref_idx + idx_size
    out = []
    for name, size, flag in entries:
        if name.startswith(KEEP_PREFIXES):
            out.append((name, pos, size, flag))
        pos += size
    return out


def warm_up():
    """Připraví vše pro okamžité kreslení karet (index packů, mapa karet, index portrétů).
    Volat na pozadí po startu aplikace."""
    build_index()
    unit_card_map()
    _portrait_index()
    faction_flag_map()
    portrait_chain()
    return True


def build_index(game_dir=None, force=False):
    """Index všech packů ve složce hry (pozdější pack v abecedním pořadí přepisuje dřívější)."""
    global _index, _game_dir
    with _lock:
        if _index is not None and not force:
            return _index
        game = game_dir or locdb.find_game_dir()
        idx = {}
        if game:
            for p in sorted(glob.glob(os.path.join(game, "data", "*.pack"))):
                try:
                    for name, pos, size, flag in _pack_index(p):
                        idx[name] = (p, pos, size, flag)
                except OSError:
                    continue
        _index = idx
        _game_dir = game
        return idx


def ready():
    return _index is not None


def has(path):
    return path.lower().replace("\\", "/") in build_index()


def read(path):
    """Obsah souboru z packu (bytes) nebo None."""
    ent = build_index().get(path.lower().replace("\\", "/"))
    if ent is None:
        return None
    p, pos, size, flag = ent
    with open(p, "rb") as fh:
        fh.seek(pos)
        raw = fh.read(size)
    if flag:
        try:
            import zstandard
        except ImportError:
            return None
        usize = struct.unpack_from("<I", raw, 0)[0]
        return zstandard.ZstdDecompressor().decompress(raw[4:], max_output_size=max(usize, 1))
    return raw


def _db_strings(data):
    """Řetězce z binární DB tabulky v pořadí (heuristika: u16 délka + ASCII), bez schématu."""
    out = []
    i, n = 0, len(data)
    while i < n - 2:
        ln = data[i] | (data[i + 1] << 8)
        if 3 <= ln <= 120 and i + 2 + ln <= n:
            chunk = data[i + 2:i + 2 + ln]
            if all(32 <= b < 127 for b in chunk):
                out.append(chunk.decode())
                i += 2 + ln
                continue
        i += 1
    return out


_card_map = None


def unit_card_map():
    """{klíč jednotky: název karty} z tabulky unit_variants (řádek = název, klíč, varianta, karta):
    karta = první řetězec do tří pozic za klíčem, který existuje jako ui/units/icons/<x>.png."""
    global _card_map
    if _card_map is not None:
        return _card_map
    idx = build_index()
    icons = {p[len("ui/units/icons/"):-4] for p in idx if p.startswith("ui/units/icons/")}
    cmap = {}
    for tbl in sorted(p for p in idx if p.startswith("db/unit_variants_tables/")):
        data = read(tbl)
        if not data:
            continue
        ss = _db_strings(data)
        for k, s in enumerate(ss):
            if s in icons or s in cmap:
                continue
            for j in range(k + 1, min(k + 4, len(ss))):
                if ss[j] in icons:
                    cmap[s] = ss[j]
                    break
    _card_map = cmap
    return cmap


def unit_icon(key):
    """PNG ikony jednotky (bytes) nebo None: přímý název, mapování z DB, varianty názvu."""
    key = str(key).lower()
    idx = build_index()
    cands = [key]
    card = unit_card_map().get(key)
    if card and "placeholder" not in card:
        cands.append(card)
    if key.endswith(("_0", "_1", "_2", "_3")):
        cands.append(key[:-2])
    else:
        cands.append(key + "_0")
    for c in cands:
        p = "ui/units/icons/%s.png" % c
        if p in idx:
            return read(p)
    return None


_portraits = None


def _portrait_index():
    """{název souboru bez .png: cesta} pro ui/portraits/units (karty 60×130 postav)."""
    global _portraits
    if _portraits is None:
        _portraits = {}
        for p in build_index():
            if p.startswith("ui/portraits/units/") and p.endswith(".png") and "_mask" not in p:
                _portraits.setdefault(p.rsplit("/", 1)[-1][:-4], p)
    return _portraits


_portrait_chain = None


def portrait_chain():
    """Mapy z DB pro portrét postavy podle klíče jednotky (řetězec hry):
    agent_subtypes [podtyp, klíč jednotky, …] → campaign_character_art_sets [art set, podtyp, …]
    → campaign_character_arts [art set, x, art set pro portrét, …] → agent_uniforms
    […, art set, varianta, …] → variants [varianta, název karty]. Díky tomu má portrét i postava
    bez vlastního artu (správce konvoje používá art správce)."""
    global _portrait_chain
    if _portrait_chain is not None:
        return _portrait_chain
    idx = build_index()
    pidx = _portrait_index()

    def strings(prefix):
        out = []
        for tbl in sorted(p for p in idx if p.startswith(prefix)):
            data = read(tbl)
            if data:
                out.extend(_db_strings(data))
        return out

    subtype_of_unit, artsets_of_subtype, uniform_of_set, variant_of_uniform, stem_of_variant = {}, {}, {}, {}, {}
    # agent_subtypes: [podtyp, klíč jednotky (…_cha_…), vo actor, …]
    ss = strings("db/agent_subtypes_tables/")
    for i in range(1, len(ss)):
        if "_cha_" in ss[i] and ss[i] not in subtype_of_unit:
            j = i - 1          # mezi podtypem a klíčem může být cesta k ikoně nebo příznak
            while j > 0 and (ss[j].startswith(("ui/", "ui\\")) or "_be_saved_loaded" in ss[j]):
                j -= 1
            subtype_of_unit[ss[i]] = ss[j]
    # campaign_character_art_sets: [art set, podtyp, 'general'/…] — podtyp má víc art setů (varianty)
    ss = strings("db/campaign_character_art_sets_tables/")
    for i in range(len(ss) - 1):
        if "_art_set_" in ss[i]:
            artsets_of_subtype.setdefault(ss[i + 1], []).append(ss[i])
    # campaign_character_arts: [art set, porthole override|'none', uniforma, loď, loď, animace, …]
    ss = strings("db/campaign_character_arts_tables/")
    for i in range(len(ss) - 2):
        if "_art_set_" in ss[i] and ss[i] not in uniform_of_set:
            uniform_of_set[ss[i]] = ss[i + 2]
    uniforms = set(uniform_of_set.values())
    # agent_uniforms: [varianta předchozího řádku, uniforma, varianta kampaň, varianta bitva]
    ss = strings("db/agent_uniforms_tables/")
    for i in range(len(ss) - 1):
        if ss[i] in uniforms and ss[i] not in variant_of_uniform:
            variant_of_uniform[ss[i]] = ss[i + 1]
    variants = set(variant_of_uniform.values())
    # variants: [varianta, název karty/portrétu, …]
    ss = strings("db/variants_tables/")
    for i in range(len(ss) - 1):
        if ss[i] in variants and ss[i] not in stem_of_variant:
            stem_of_variant[ss[i]] = ss[i + 1]
    _portrait_chain = (subtype_of_unit, artsets_of_subtype, uniform_of_set, variant_of_uniform, stem_of_variant)
    return _portrait_chain


def _portrait_via_db(unit_key):
    subtype_of_unit, artsets_of_subtype, uniform_of_set, variant_of_uniform, stem_of_variant = portrait_chain()
    pidx = _portrait_index()
    key = str(unit_key).lower()
    sub = subtype_of_unit.get(key)
    if sub is None:                 # varianty s jezdeckým zvířetem: klíč_1/_2 → základní klíč_0 / bez přípony
        import re
        base = re.sub(r"_\d+$", "", key)
        sub = subtype_of_unit.get(base + "_0") or subtype_of_unit.get(base)
    stem = None
    for aset in (artsets_of_subtype.get(sub, []) if sub else []):
        uni = uniform_of_set.get(aset)
        var = variant_of_uniform.get(uni) if uni else None
        stem = stem_of_variant.get(var) if var else None
        if stem and (stem + "_0" in pidx or stem in pidx):
            break
        stem = None
    for cand in ((stem + "_0", stem) if stem else ()):
        p = pidx.get(cand)
        if p and "placeholder" not in p:
            return read(p)
    return None


def character_portrait_for_unit(unit_key):
    """Portrét postavy podle klíče její jednotky: nejdřív řetězcem z DB (portrait_chain),
    pak odhadem: `wh3_dlc23_chd_cha_zhatan_the_black_lammasu` → prefixy verze/DLC a „cha_" pryč,
    od nejdelšího kmene `<kmen>_0`, `<kmen>`, `<kmen>_campaign_01_0`."""
    png = _portrait_via_db(unit_key)
    if png:
        return png
    toks = [x for x in str(unit_key).lower().split("_") if x]
    while toks and (toks[0].startswith(("wh", "dlc", "pro", "twa", "cp")) or toks[0] in ("main", "combi")):
        toks.pop(0)
    toks = [x for x in toks if x != "cha"]
    pidx = _portrait_index()
    for n in range(len(toks), 1, -1):
        stem = "_".join(toks[:n])
        for cand in (stem + "_0", stem, stem + "_campaign_01_0", stem + "_campaign_01"):
            p = pidx.get(cand)
            if p and "placeholder" not in p:
                return read(p)
    return None


PLACEHOLDER = "ui/portraits/units/0_placeholder_unit_icon.png"


def placeholder():
    return read(PLACEHOLDER)


def character_portrait(subtype_or_key):
    """PNG portrétu postavy podle názvu souboru (bez .png, s/bez `_0`) nebo None."""
    key = str(subtype_or_key).lower()
    pidx = _portrait_index()
    for cand in (key, key + "_0"):
        p = pidx.get(cand)
        if p:
            return read(p)
    return None


_flag_map = None


def faction_flag_map():
    """{klíč frakce: složka vlajky} z DB tabulky factions (sloupec flags_path, např.
    `ui\\flags\\wh3_dlc27_nor_sayl_the_faithless` — složka se často jmenuje jinak než frakce).
    Řádek = …, klíč, subkultura, …, cesta k vlajce; bereme první cestu do 10 řetězců za klíčem."""
    global _flag_map
    if _flag_map is not None:
        return _flag_map
    idx = build_index()
    fmap = {}
    for tbl in sorted(p for p in idx if p.startswith("db/factions_tables/")):
        data = read(tbl)
        if not data:
            continue
        ss = _db_strings(data)
        for k, s in enumerate(ss):
            if s in fmap or s.startswith("ui"):
                continue
            for j in range(k + 1, min(k + 11, len(ss))):
                if ss[j].lower().startswith(("ui\\flags\\", "ui/flags/")):
                    fmap[s] = ss[j].lower().replace("\\", "/").rstrip("/")
                    break
    _flag_map = fmap
    return fmap


def faction_flag(key, size=24):
    """PNG vlajky frakce (`mon_<size>.png`: 24, 64, 256) nebo None: nejdřív složka podle klíče,
    pak složka z DB tabulky factions."""
    key = str(key).lower()
    idx = build_index()
    cands = ["ui/flags/%s" % key]
    folder = faction_flag_map().get(key)
    if folder:
        cands.append(folder)
    for c in cands:
        p = "%s/mon_%d.png" % (c, size)
        if p in idx:
            return read(p)
    return None
