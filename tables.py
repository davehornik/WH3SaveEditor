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
                out[u32s[0].value] = {"type": ftype,
                                      "units": ua.count if ua else 0}
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


def units(save, faction_key):
    """Units of all field armies of one faction.

    [{army, unit_key, hp(node), hp_max(node), rank(node), exp(node)}]
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
                u = next((c for c in ue.children if isinstance(c, Record)
                          and c.name == "UNIT"), None)
                if u is None:
                    continue
                key_rec = u.child("UNIT_RECORD_KEY")
                key = key_rec.children[0].value if key_rec and key_rec.children else "?"
                uk = u.children
                rows.append({
                    "army": ai, "force_id": force_id, "entry": ue,
                    "commander": (uk[6].value if len(uk) > 6
                                  and isinstance(uk[6], Value) else 0),
                    "unit_key": key,
                    "hp": uk[4] if len(uk) > 5 else None,
                    "hp_max": uk[5] if len(uk) > 5 else None,
                    "rank": uk[8] if len(uk) > 8 else None,
                    "exp": uk[9] if len(uk) > 9 else None,
                })
    return rows
