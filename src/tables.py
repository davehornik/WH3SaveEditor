# -*- coding: utf-8 -*-
"""Extraction of SaveParser-style tables from a WH3 save (factions,
characters, units). Rows carry references to editable Value nodes."""
from esf import Record, RecordBlock, Value, ValueArray
from i18n import t
import locdb


def world(save):
    return save.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL", "WORLD")


def faction_record(entry):
    for c in entry.children:
        if isinstance(c, Record) and c.name == "FACTION":
            return c
    return None


def factions(save):
    """[{index, key, id, money(node)}] for all factions."""
    fa = world(save).child("FACTION_ARRAY")
    rows = []
    for i, e in enumerate(fa.entries):
        f = faction_record(e)
        if f is None:
            continue
        eco = f.child("FACTION_ECONOMICS")
        aa = f.child("ARMY_ARRAY")
        ca = f.child("CHARACTER_ARRAY")
        rows.append({"index": i, "key": f.children[1].value,
                     "id": f.children[0].value,
                     "money": eco.children[1] if eco else None,
                     "armies": aa.count if aa else 0,
                     "chars": ca.count if ca else 0,
                     "record": f})
    return rows


def _loc_strings(rec):
    """Collect readable strings from CAMPAIGN_LOCALISATION-ish records."""
    out = []
    for c in rec.children:
        if isinstance(c, Value) and c.code in (0x0E, 0x0F):
            v = c.value
            if v:
                out.append(str(v))
        elif isinstance(c, Record):
            out.extend(_loc_strings(c))
        elif isinstance(c, RecordBlock):
            for e in c.entries:
                for cc in e.children:
                    if isinstance(cc, Record):
                        out.extend(_loc_strings(cc))
                    elif isinstance(cc, Value) and cc.code in (0x0E, 0x0F) and cc.value:
                        out.append(str(cc.value))
    return out


def active_characters(save, faction_key):
    """{family_member_id: force_id} for characters on the map.

    CHARACTER u32 layout: [character_id, family_member_id, force_id, unit_id, ...]
    force_id == 0 means the character commands no force (lone hero).
    """
    out = {}
    for f in factions(save):
        if f["key"] != faction_key:
            continue
        ca = f["record"].child("CHARACTER_ARRAY")
        if ca is None:
            continue
        for e in ca.entries:
            ch = next((c for c in e.children if isinstance(c, Record)
                       and c.name == "CHARACTER"), None)
            if ch is None:
                continue
            u32s = [c for c in ch.children if isinstance(c, Value)
                    and c.type_name == "u32"]
            if len(u32s) >= 3:
                out[u32s[1].value] = u32s[2].value
    return out


def forces(save, faction_key):
    """{force_id: {"type": 'ARMY'/'CARAVAN'/..., "units": n}}.

    MILITARY_FORCE u32 layout: [force_id, commander_character_id, ...]
    """
    out = {}
    for f in factions(save):
        if f["key"] != faction_key:
            continue
        aa = f["record"].child("ARMY_ARRAY")
        if aa is None:
            continue
        for e in aa.entries:
            mf = next((c for c in e.children if isinstance(c, Record)
                       and c.name == "MILITARY_FORCE"), None)
            if mf is None:
                continue
            u32s = [c for c in mf.children if isinstance(c, Value)
                    and c.type_name == "u32"]
            ftype = next((str(c.value) for c in mf.children
                          if isinstance(c, Value) and c.type_name == "ascii"
                          and c.value), "?")
            uc = mf.child("UNIT_CONTAINER")
            ua = uc.child("UNITS_ARRAY") if uc else None
            if u32s:
                n = sum(1 for x in ua.entries if not x.deleted) if ua else 0
                out[u32s[0].value] = {"type": ftype, "units": n}
    return out


_DROP = ("main", "combi", "region")


def pretty(key, drop_culture=True):
    """'wh3_main_cth_miao_ying' -> 'Miao Ying'.

    Nejdřív zkusí skutečný herní název z locdb (subtyp postavy / region),
    pak spadne na heuristiku z klíče."""
    loc = locdb.subtype(key) or locdb.region(key)
    if loc:
        return loc
    toks = [t for t in str(key).split("_") if t]
    while toks and (toks[0].startswith(("wh", "dlc", "pro", "cst", "twa", "cp"))
                    or toks[0] in _DROP):
        toks.pop(0)
    if drop_culture and len(toks) > 1 and len(toks[0]) <= 4:
        toks.pop(0)          # culture code (cth, ksl, ...)
    return " ".join(t.capitalize() for t in toks) or str(key)


def pretty_faction(key):
    """Herní název frakce, fallback na heuristiku z klíče."""
    return locdb.faction(key) or pretty(key, drop_culture=False)


def pretty_unit(key):
    """Herní název jednotky, fallback na heuristiku z klíče."""
    return locdb.unit(key) or pretty(key)


def garrisons(save):
    """{garrison_force_id: region_key} from REGION/SETTLEMENT/GARRISON_RESIDENCE."""
    out = {}
    rman = world(save).child("REGION_MANAGER")
    blk = next((c for c in rman.children if isinstance(c, RecordBlock)), None)
    if blk is None:
        return out
    for e in blk.entries:
        reg = next((c for c in e.children if isinstance(c, Record)), None)
        if reg is None:
            continue
        key = next((c.value for c in reg.children if isinstance(c, Value)
                    and c.type_name == "ascii" and c.value), "?")
        st = reg.child("SETTLEMENT")
        gr = st.child("GARRISON_RESIDENCE") if st else None
        if gr is not None and len(gr.children) > 8:
            v = gr.children[8]
            if isinstance(v, Value) and v.type_name == "u32" and v.value:
                out[v.value] = key
    return out


def characters(save, faction_key):
    """Characters of one faction from WORLD/FAMILY_TREE.

    [{id, active, role, category, subtype, name, rank(node), xp(node)}]
    """
    on_map = active_characters(save, faction_key)
    force_map = forces(save, faction_key)
    gmap = garrisons(save)
    ft = world(save).child("FAMILY_TREE")
    rows = []
    for m in ft.children:
        if not (isinstance(m, Record) and m.name == "FAMILY_MEMBER"):
            continue
        kids = m.children
        if len(kids) < 3 or not isinstance(kids[1], Value) or kids[1].value != faction_key:
            continue
        det = next((c for c in kids if isinstance(c, Record)
                    and c.name == "CHARACTER_DETAILS"), None)
        if det is None:
            continue
        dk = det.children
        skills = det.child("CAMPAIGN_SKILLS")
        idx = dk.index(skills) if skills in dk else -1
        category = dk[idx - 2].value if idx >= 2 and isinstance(dk[idx - 2], Value) else "?"
        subtype = dk[idx - 1].value if idx >= 1 and isinstance(dk[idx - 1], Value) else "?"
        rank = xp = points = None
        if skills is not None:
            u32s = [c for c in skills.children
                    if isinstance(c, Value) and c.type_name == "u32"]
            # layout: ..., bool, u32 volné skill pointy, u32 rank, u32 xp, blok skillů
            if len(u32s) >= 3:
                points, rank, xp = u32s[-3], u32s[-2], u32s[-1]
        name_rec = det.child("CHARACTER_NAME")
        name_parts = _loc_strings(name_rec) if name_rec else []
        name_parts = [p for p in name_parts
                      if p not in ("OTHER", "other", "clan_name", "forename",
                                   "family_name", "other_name")]
        name = (locdb.char_name(name_parts) or " ".join(name_parts))[:60]
        member_id = kids[0].value
        active = member_id in on_map
        if not active:
            role, kind = t("Naverbovatelný"), "pool"
        else:
            force_id = on_map[member_id]
            force = force_map.get(force_id)
            if force is None:
                role = t("Hrdina – %s (rank %s)") % (
                    pretty(subtype), rank.value if rank else "?")
                kind = "hero"
            elif force["type"] == "CARAVAN":
                role = t("%s (Karavana, %d j.)") % (pretty(subtype), force["units"])
                kind = "caravan"
            elif category == "colonel":
                reg = gmap.get(force_id)
                role = (t("Garnizona – %s (%d j.)") % (pretty(reg, drop_culture=False),
                                                       force["units"])
                        if reg else t("Armáda sídla (%d j.)") % force["units"])
                kind = "garrison"
            else:
                role = t("Armáda – %s (%d j.)") % (pretty(subtype), force["units"])
                kind = "army"
        rows.append({"id": member_id, "active": active, "role": role, "kind": kind,
                     "force_id": on_map.get(member_id, 0),
                     "category": category, "subtype": subtype,
                     "name": name, "points": points, "rank": rank, "xp": xp})
    return rows


def diplomacy(save, faction_key):
    """[{target_key, stance(node), stance2(node), score(node)}] for one faction.

    OLD_DIPLOMACY_RELATIONSHIP entry: [0]=target faction id, [1]=score i32,
    [2]=stance ascii, ..., [14]=stance ascii (duplicate).
    """
    facs = factions(save)
    by_id = {f["id"]: f for f in facs}
    me = next((f for f in facs if f["key"] == faction_key), None)
    if me is None:
        return []
    dm = me["record"].child("OLD_DIPLOMACY_MANAGER")
    blk = next((c for c in dm.children if isinstance(c, RecordBlock)), None) if dm else None
    if blk is None:
        return []
    rows = []
    for e in blk.entries:
        k = e.children
        if not k or not isinstance(k[0], Value):
            continue
        tid = k[0].value
        tgt = by_id.get(tid)
        fl = next((c for c in reversed(k) if isinstance(c, ValueArray)
                   and c.base_code == 0x0F), None)
        rows.append({"target_key": tgt["key"] if tgt else "?%s" % tid,
                     "stance": k[2] if len(k) > 2 else None,
                     "stance2": k[14] if len(k) > 14 else None,
                     "score": k[1] if len(k) > 1 else None,
                     "flags": fl})
    return rows


def reciprocal_relationship(save, faction_key, target_key):
    """{"stances": [...], "flags": node} in target's diplomacy toward faction_key."""
    facs = factions(save)
    me = next((f for f in facs if f["key"] == faction_key), None)
    tgt = next((f for f in facs if f["key"] == target_key), None)
    if me is None or tgt is None:
        return {"stances": [], "flags": None}
    dm = tgt["record"].child("OLD_DIPLOMACY_MANAGER")
    blk = next((c for c in dm.children if isinstance(c, RecordBlock)), None) if dm else None
    if blk is not None:
        for e in blk.entries:
            k = e.children
            if k and isinstance(k[0], Value) and k[0].value == me["id"]:
                fl = next((c for c in reversed(k) if isinstance(c, ValueArray)
                           and c.base_code == 0x0F), None)
                return {"stances": [n for n in (k[2] if len(k) > 2 else None,
                                                k[14] if len(k) > 14 else None)
                                    if n is not None],
                        "flags": fl}
    return {"stances": [], "flags": None}


def reciprocal_stance_nodes(save, faction_key, target_key):
    """Stance nodes in target faction's diplomacy pointing back at faction_key."""
    facs = factions(save)
    me = next((f for f in facs if f["key"] == faction_key), None)
    tgt = next((f for f in facs if f["key"] == target_key), None)
    if me is None or tgt is None:
        return []
    dm = tgt["record"].child("OLD_DIPLOMACY_MANAGER")
    blk = next((c for c in dm.children if isinstance(c, RecordBlock)), None) if dm else None
    if blk is None:
        return []
    for e in blk.entries:
        k = e.children
        if k and isinstance(k[0], Value) and k[0].value == me["id"]:
            return [n for n in (k[2] if len(k) > 2 else None,
                                k[14] if len(k) > 14 else None) if n is not None]
    return []


UNIT_CQI_TABLE = 4      # index tabulky jednotek v CAMPAIGN_COMMAND_QUEUE_INDEX_TABLES (ověřeno RE + savy)


def cqi_counter_node(save, table_index):
    """u32 uzel „další volné id" pro daný typ objektu (CQI tabulka). Hra při vzniku objektu
    vezme hodnotu a zvýší ji o 1 (Warhammer3.exe, manažer CQI `campaign+0x5bb8`, next na +0x18)."""
    tbl = save.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL",
                                  "CAMPAIGN_COMMAND_QUEUE_INDEX_TABLES")
    if tbl is None:
        raise RuntimeError("CAMPAIGN_COMMAND_QUEUE_INDEX_TABLES not found")
    vals = [c for c in tbl.children if isinstance(c, Value) and c.type_name == "u32"]
    return vals[table_index]


def allocate_unit_id(save):
    node = cqi_counter_node(save, UNIT_CQI_TABLE)
    nid = node.value
    node.value = nid + 1
    return nid


def units_block(save, force_id):
    """UNITS_ARRAY (RecordBlock) vojenské síly daného id, nebo None."""
    for f in factions(save):
        aa = f["record"].child("ARMY_ARRAY")
        if aa is None:
            continue
        for e in aa.entries:
            mf = next((c for c in e.children if isinstance(c, Record)
                       and c.name == "MILITARY_FORCE"), None)
            if mf is None:
                continue
            u32s = [c for c in mf.children if isinstance(c, Value) and c.type_name == "u32"]
            if u32s and u32s[0].value == force_id:
                uc = mf.child("UNIT_CONTAINER")
                return uc.child("UNITS_ARRAY") if uc else None
    return None


# --- AI zrcadlo jednotky (CAI_INTERFACE/CAI_WORLD) ------------------------------
# Kampaňová AI si vede vlastní kopii světa: CAI_WORLD_UNITS má přesně jeden záznam na
# jednotku ([CAI_BDI_COMPONENT_PROPERTY_SET, CAI_BDI_COMPONENT{id komponenty,…},
# CAI_UNIT{u32 0, id jednotky, id komponenty rodičovské síly}]) a každá síla má v
# CAI_WORLD_RESOURCE_MOBILES/CAI_RESOURCE_MOBILE[4] seznam id komponent svých jednotek
# (CAI_RESOURCE_MOBILE[11] = id síly). Čítač id komponent = CAI_CENTRAL_BDI_POOL[0].
# Jednotka bez zrcadla se v kampani zobrazí i pohybuje, ale při zpracování výsledku
# bitvy ji AI vrstva nenajde (hash mapa id → CAI_UNIT) → hra spadne
# (ověřeno crash dumpem 2026-10-11, FUN_14260b35c).

def _rec(entry, name):
    return next((c for c in entry.children if isinstance(c, Record) and c.name == name), None)


def _u32_array_items(arr):
    """Pole u32 id: hra ho ukládá nejmenším kódováním (0x16 = 1 B, 0x17 = 2 B LE,
    0x18 = 3 B BE, 0x08 = 4 B LE)."""
    import struct
    c = arr.base_code
    # po _set_u32_array drží nový obsah arr._new (raw jsou pořád původní bajty)
    d = bytes(arr._new) if isinstance(arr._new, (bytes, bytearray)) else bytes(arr.raw)
    if c == 0x16:
        return list(d)
    if c == 0x17:
        return list(struct.unpack("<%dH" % (len(d) // 2), d))
    if c == 0x18:
        return [(d[i] << 16) | (d[i + 1] << 8) | d[i + 2] for i in range(0, len(d) - 2, 3)]
    if c == 0x08:
        return list(struct.unpack("<%dI" % (len(d) // 4), d))
    raise ValueError("unexpected u32 array type 0x%02X" % c)


def _set_u32_array(arr, ids):
    """Přepíše pole u32 id a zvolí kódování stejně jako hra (viz _u32_array_items)."""
    import struct
    m = max(ids, default=0)
    if m < 0x100:
        code, payload = 0x16, bytes(ids)
    elif m < 0x10000:
        code, payload = 0x17, b"".join(struct.pack("<H", v) for v in ids)
    elif m < 0x1000000:
        code, payload = 0x18, b"".join(bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF]) for v in ids)
    else:
        code, payload = 0x08, b"".join(struct.pack("<I", v) for v in ids)
    arr.code = code | 0x40
    arr._new = payload
    arr.mark_dirty()


def cai_world(save):
    return save.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL", "CAI_INTERFACE", "CAI_WORLD")


def cai_next_component_node(save):
    pool = save.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL", "CAI_INTERFACE",
                                   "CAI_CENTRAL_BDI_POOL")
    if pool is None or not pool.children or not isinstance(pool.children[0], Value):
        return None
    return pool.children[0]


def cai_unit_entry(cw, unit_id):
    blk = cw.child("CAI_WORLD_UNITS")
    if blk is None:
        return None
    for e in blk.entries:
        if e.deleted:
            continue
        u = _rec(e, "CAI_UNIT")
        if u is not None and len(u.children) > 2 and u.children[1].value == unit_id:
            return e
    return None


def cai_force_entry(cw, force_id):
    blk = cw.child("CAI_WORLD_RESOURCE_MOBILES")
    if blk is None:
        return None
    for e in blk.entries:
        rm = _rec(e, "CAI_RESOURCE_MOBILE")
        if rm is not None and len(rm.children) > 11 and rm.children[11].value == force_id:
            return e
    return None


def add_cai_unit(save, unit_id, template_unit_id, force_id):
    """Vytvoří AI zrcadlo (CAI_WORLD_UNITS entry) pro novou jednotku `unit_id` v síle
    `force_id`: klon zrcadla vzorové jednotky s novým id komponenty, zapsaným id jednotky
    a id komponenty cílové síly; id komponenty se připojí do seznamu jednotek síly."""
    cw = cai_world(save)
    counter = cai_next_component_node(save)
    if cw is None or counter is None:
        raise ValueError(t("Save nemá AI vrstvu (CAI_WORLD) — jednotku nelze přidat."))
    blk = cw.child("CAI_WORLD_UNITS")
    src = cai_unit_entry(cw, template_unit_id)
    if src is None and blk is not None and blk.entries:
        src = blk.entries[0]
    fe = cai_force_entry(cw, force_id)
    if src is None or fe is None:
        raise ValueError(t("Armáda nemá záznam v AI vrstvě savu — jednotku do ní nelze přidat."))
    cid = counter.value
    counter.value = cid + 1
    ent = save.inner.clone_entry(blk, src)
    _rec(ent, "CAI_BDI_COMPONENT").children[0].value = cid
    cu = _rec(ent, "CAI_UNIT")
    cu.children[0].value = 0
    cu.children[1].value = unit_id
    cu.children[2].value = _rec(fe, "CAI_BDI_COMPONENT").children[0].value
    arr = _rec(fe, "CAI_RESOURCE_MOBILE").children[4]
    _set_u32_array(arr, _u32_array_items(arr) + [cid])
    return ent


def force_faction_key(save, force_id):
    """Klíč frakce, které patří vojenská síla daného id (None, když není)."""
    for f in factions(save):
        aa = f["record"].child("ARMY_ARRAY")
        if aa is None:
            continue
        for e in aa.entries:
            mf = next((c for c in e.children if isinstance(c, Record)
                       and c.name == "MILITARY_FORCE"), None)
            if mf is None:
                continue
            u32s = [c for c in mf.children if isinstance(c, Value) and c.type_name == "u32"]
            if u32s and u32s[0].value == force_id:
                return f["key"]
    return None


def world_unit_templates(save):
    """{klíč jednotky: řádek units()} — první řadový výskyt každého typu kdekoli na světě
    (vzor pro přidání jednotky, kterou vlastní frakce v savu nemá)."""
    out = {}
    for f in factions(save):
        for r in units(save, f["key"]):
            if not is_character_unit(r):
                out.setdefault(str(r["unit_key"]), r)
    return out


def remove_unit(save, row):
    """Odebere jednotku (řádek z units()) i její AI zrcadlo a položku v seznamu jednotek síly.
    Jednotky lordů/hrdinů odmítá."""
    if is_character_unit(row):
        raise ValueError(t("Tohle je jednotka lorda/hrdiny — tu odebrat nelze, patří k postavě."))
    uid = row["entry"].children[0].children[0].value
    row["entry"].delete()
    cw = cai_world(save)
    if cw is None:
        return
    ent = cai_unit_entry(cw, uid)
    if ent is None:
        return
    cid = _rec(ent, "CAI_BDI_COMPONENT").children[0].value
    parent = _rec(ent, "CAI_UNIT").children[2].value
    ent.delete()
    blk = cw.child("CAI_WORLD_RESOURCE_MOBILES")
    for e in (blk.entries if blk is not None else []):
        comp = _rec(e, "CAI_BDI_COMPONENT")
        if comp is not None and comp.children[0].value == parent:
            arr = _rec(e, "CAI_RESOURCE_MOBILE").children[4]
            ids = _u32_array_items(arr)
            if cid in ids:
                _set_u32_array(arr, [i for i in ids if i != cid])
            break


def set_unit_rank(row, rank):
    """Nastaví hodnost jednotky 0–9 (jednotky postav odmítá)."""
    if is_character_unit(row):
        raise ValueError(t("Tohle je jednotka lorda/hrdiny — její úroveň patří k postavě."))
    row["rank"].value = max(0, min(9, int(rank)))


def add_unit(save, template_row, force_id=None, heal=True, fresh=True, rank=None):
    """Přidá jednotku naklonováním UNITS_ARRAY entry vzorové jednotky (řádek z units()).

    UNIT layout (patch 25649450): [0] u32 id (CQI), [1] UNIT_RECORD_KEY, [2] UNIT_HISTORY,
    [3] COMMANDER_DETAILS, [4] hp, [5] hp_max, [6] char id velitele (≠0 jen u jednotek lordů/hrdinů),
    [7] u32, [8] rank u8, [9] exp f32, [10] CAMPAIGN_LOCALISATION, [11] u32 (= id − 1 u 99,9 % jednotek),
    … Nové id = čítač CQI tabulky 4 (+1). Vrací nový BlockEntry."""
    if is_character_unit(template_row):
        raise ValueError("Vzorová jednotka patří lordovi/hrdinovi — tu klonovat nelze.")
    src = template_row["entry"]
    block = src.parent
    if force_id is not None and force_id != template_row["force_id"]:
        block = units_block(save, force_id)
        if block is None:
            raise ValueError("UNITS_ARRAY of force %d not found" % force_id)
    target_force = force_id if force_id is not None else template_row["force_id"]
    template_id = next(c for c in src.children if isinstance(c, Record)
                       and c.name == "UNIT").children[0].value
    ent = save.inner.clone_entry(block, src)
    u = next(c for c in ent.children if isinstance(c, Record) and c.name == "UNIT")
    ch = u.children
    nid = allocate_unit_id(save)
    ch[0].value = nid
    if len(ch) > 11 and isinstance(ch[11], Value) and ch[11].type_name == "u32":
        ch[11].value = nid - 1
    ch[6].value = 0
    if len(ch) > 16 and isinstance(ch[16], Value) and ch[16].type_name == "u32":
        ch[16].value = 0          # vazba na postavu (vložený hrdina)
    if len(ch) > 17 and isinstance(ch[17], Value) and ch[17].type_name == "u32":
        ch[17].value = 0          # vazba na stavební slot (limit jednotek z budovy) — klon ji nesmí sdílet
    # vzor z cizí frakce: COMMANDER_DETAILS[0] = klíč frakce vlastníka
    fk = force_faction_key(save, target_force)
    cd = ch[3] if len(ch) > 3 and isinstance(ch[3], Record) and ch[3].name == "COMMANDER_DETAILS" else None
    if fk and cd is not None:
        fkey = next((c for c in cd.children if isinstance(c, Value) and c.type_name == "ascii"), None)
        if fkey is not None and str(fkey.value) != fk:
            fkey.value = fk
    if heal:
        ch[4].value = ch[5].value
    if fresh:
        ch[7].value = 0           # celkové zkušenostní body
        ch[8].value = 0
        ch[9].value = 0.0
    if rank is not None:          # naverbovat rovnou na dané hodnosti (0–9), postup v hodnosti od nuly
        ch[8].value = max(0, min(9, int(rank)))
        ch[9].value = 0.0
    # AI zrcadlo jednotky — bez něj hra spadne při první bitvě
    add_cai_unit(save, nid, template_id, target_force)
    # akční body: klon nese stav armády vzorové jednotky — převzít je od sourozence
    # v cílové armádě, aby nová jednotka nebyla „více/méně pohnutá" než zbytek
    sib = next((e for e in block.entries if e is not ent and not e.deleted), None)
    if sib is not None:
        _copy_action_points(sib, ent)
    return ent


def _unit_action_points(entry):
    u = next((c for c in entry.children if isinstance(c, Record) and c.name == "UNIT"), None)
    return u.child("UNIT_ACTION_POINTS") if u is not None else None


def _copy_action_points(src_entry, dst_entry):
    """Zkopíruje hodnoty UNIT_ACTION_POINTS (vnořený ACTION_POINTS = [aktuální, základní max,
    bonus/1024, bool] + 5 i32) z jedné jednotky na druhou."""
    a, b = _unit_action_points(src_entry), _unit_action_points(dst_entry)
    if a is None or b is None:
        return
    def copy(x, y):
        for cx, cy in zip(x.children, y.children):
            if isinstance(cx, Value) and isinstance(cy, Value):
                if cy.value != cx.value:
                    cy.value = cx.value
            elif isinstance(cx, Record) and isinstance(cy, Record):
                copy(cx, cy)
    copy(a, b)


def is_character_unit(row):
    """True pro jednotku lorda ([6] = char id velitele) nebo vloženého hrdiny
    ([16] = char id, [6] = 0) — ty patří k postavě a nelze je klonovat ani mazat."""
    return bool(row.get("commander") or row.get("char_ref")
                or "_cha_" in str(row.get("unit_key", "")))


def units(save, faction_key):
    """Units of all field armies of one faction.

    [{army, force_id, entry, commander, char_ref, unit_key,
      hp(node), hp_max(node), rank(node), exp(node)}]
    """
    rows = []
    for f in factions(save):
        if f["key"] != faction_key:
            continue
        aa = f["record"].child("ARMY_ARRAY")
        if aa is None:
            continue
        for ai, e in enumerate(aa.entries):
            mf = next((c for c in e.children if isinstance(c, Record)
                       and c.name == "MILITARY_FORCE"), None)
            if mf is None:
                continue
            uc = mf.child("UNIT_CONTAINER")
            ua = uc.child("UNITS_ARRAY") if uc else None
            if ua is None:
                continue
            mf_u32s = [c for c in mf.children if isinstance(c, Value)
                       and c.type_name == "u32"]
            force_id = mf_u32s[0].value if mf_u32s else 0
            for ue in ua.entries:
                if ue.deleted:
                    continue
                u = next((c for c in ue.children if isinstance(c, Record)
                          and c.name == "UNIT"), None)
                if u is None:
                    continue
                key_rec = u.child("UNIT_RECORD_KEY")
                key = key_rec.children[0].value if key_rec and key_rec.children else "?"
                uk = u.children
                rows.append({
                    "army": ai, "force_id": force_id, "entry": ue,
                    "unit_id": uk[0].value if uk and isinstance(uk[0], Value) else 0,
                    "commander": (uk[6].value if len(uk) > 6
                                  and isinstance(uk[6], Value) else 0),
                    "char_ref": (uk[16].value if len(uk) > 16
                                 and isinstance(uk[16], Value)
                                 and uk[16].type_name == "u32" else 0),
                    "unit_key": key,
                    "hp": uk[4] if len(uk) > 5 else None,
                    "hp_max": uk[5] if len(uk) > 5 else None,
                    "rank": uk[8] if len(uk) > 8 else None,
                    "exp": uk[9] if len(uk) > 9 else None,
                })
    return rows
