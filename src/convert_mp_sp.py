# -*- coding: utf-8 -*-
"""MP -> SP save conversion (experimental).

usage: python convert_mp_sp.py <mp_save> <player_index 0|1> <out_path> <save_name>
"""
import lzma
import struct
import sys

from esf import (SaveFile, EsfFile, Record, RecordBlock, Value, ValueArray,
                 write_varint, LZMA_FILTER)
import tables


def name_idx(esf, name):
    if name in esf.names:
        return esf.names.index(name)
    esf.names.append(name)
    return len(esf.names) - 1


def enc_ascii(esf, s):
    return b"\x0f" + struct.pack("<I", esf.intern_ascii(s))


def enc_utf16(esf, s):
    return b"\x0e" + struct.pack("<I", esf.intern_utf16(s))


def enc_u32(v):
    return b"\x08" + struct.pack("<I", v)


def rec_header(nidx, version, content_len):
    return (bytes([0xA0]) + struct.pack("<H", nidx) + bytes([version])
            + write_varint(content_len))


def copy_node(esf, node):
    return esf.data[node.start:node.cend]


PROFILE = None      # utf16 profilový string vlastníka (z jeho SP savu)


PLAYER_BASE = 17        # první hráčský blok v MP hlavičce
PLAYER_SIZE = 10        # polí na hráče


def player_count(mp_hdr):
    return mp_hdr.children[16].value


def player_block(mp_hdr, i):
    """(name, faction_key, flags_path, faction_name, u64) hráče i."""
    k = mp_hdr.children
    b = PLAYER_BASE + PLAYER_SIZE * i
    return (str(k[b].value), str(k[b + 1].value), str(k[b + 2].value),
            str(k[b + 3].value), k[b + 4].value)


def build_gpsi(esf, mp_hdr, keep):
    """SP-style GAME_PERSISTENT_SESSION_ID: only the kept player's identity."""
    g = mp_hdr.child("GAME_PERSISTENT_SESSION_ID")
    kids = g.children                       # [utf16, u64[], TIMESTAMP]
    u64_keep = player_block(mp_hdr, keep)[4]
    ident = (enc_utf16(esf, PROFILE) if PROFILE
             else copy_node(esf, kids[0]))
    content = (ident
               + b"\x49" + write_varint(8) + struct.pack("<Q", u64_keep)
               + copy_node(esf, kids[2]))
    return rec_header(name_idx(esf, "GAME_PERSISTENT_SESSION_ID"),
                      g.version, len(content)) + content


def build_sp_header(esf, mp_hdr, keep, save_name):
    """Assemble SAVE_GAME_HEADER (v3) bytes from MP header data."""
    k = mp_hdr.children
    _, faction_key, flags_path, faction_name, _ = player_block(mp_hdr, keep)
    turn_a, turn_b = k[3].value, k[4].value
    season = str(k[5].value)
    parts = [
        enc_ascii(esf, faction_key),        # 0 faction key
        enc_ascii(esf, ""),                 # 1 portrait (cosmetic, empty)
        enc_u32(turn_a),                    # 2
        enc_u32(turn_b),                    # 3
        enc_utf16(esf, season),             # 4
        enc_ascii(esf, flags_path),         # 5
        copy_node(esf, k[7]),               # 6 DATE
        enc_utf16(esf, faction_name),       # 7 faction screen name
        build_gpsi(esf, mp_hdr, keep),      # 8 GPSI (jen náš u64)
        copy_node(esf, k[9]),               # 9 unk25
        copy_node(esf, k[10]),              # 10 TIMESTAMP
        enc_utf16(esf, save_name),          # 11 save name
        copy_node(esf, k[12]),              # 12 campaign key
        copy_node(esf, k[13]),              # 13 ''
        copy_node(esf, k[14]),              # 14 build version
        copy_node(esf, mp_hdr.child("MAPS")),           # 15 MAPS
        b"\x4f\x00",                        # 16 ascii[] empty
        b"\x48\x00",                        # 17 u32[] empty
        b"\x4c\x00",                        # 18 coord2d[] empty
        copy_node(esf, mp_hdr.child("mod_history_block_name")),  # 19 mod_history
    ]
    content = b"".join(parts)
    return rec_header(name_idx(esf, "SAVE_GAME_HEADER"), 3, len(content)) + content


def esf_file_bytes(esf, body):
    out = bytearray()
    out += struct.pack("<IIII", esf.magic, esf.unknown, esf.timestamp,
                       16 + len(body))
    out += body
    out += struct.pack("<H", len(esf.names))
    for nm in esf.names:
        b = nm.encode("ascii")
        out += struct.pack("<H", len(b)) + b
    wide = esf._wide            # ABCB: u32 délky stringů, ABCA: u16
    out += struct.pack("<I", len(esf.utf16))
    for idx, s in esf.utf16.items():
        b = s.encode("utf-16-le")
        out += (struct.pack("<I", len(b) // 2) if wide
                else struct.pack("<H", len(b) // 2)) + b + struct.pack("<I", idx)
    out += struct.pack("<I", len(esf.ascii))
    for idx, s in esf.ascii.items():
        b = s.encode("latin-1")
        out += (struct.pack("<I", len(b)) if wide
                else struct.pack("<H", len(b))) + b + struct.pack("<I", idx)
    return bytes(out)


def convert(mp_path, keep, out_path, save_name):
    s = SaveFile(mp_path)
    drop_key = None

    # --- 1) campaign body: switch all OTHER players' factions to AI ---------
    hdr_in = s.inner.root.child("SAVE_GAME_HEADER_MULTIPLAYER")
    n_players = player_count(hdr_in)
    keep_key = player_block(hdr_in, keep)[1]
    drop_keys = [player_block(hdr_in, i)[1] for i in range(n_players)
                 if i != keep]
    facs = {f["key"]: f["record"] for f in tables.factions(s)}
    for dk in drop_keys:
        cps = facs[dk].child("CAMPAIGN_PLAYER_SETUP")
        human_node = next(c for c in cps.children
                          if isinstance(c, Value) and c.type_name == "ascii"
                          and str(c.value) in ("FULL_HUMAN", "NON_HUMAN"))
        human_node.value = "NON_HUMAN"

    # CAMPAIGN_SETUP_LOCAL: faction of the LOCAL player = the kept one
    env = s.inner.root.child("CAMPAIGN_ENV")
    env.child("CAMPAIGN_SETUP_LOCAL").children[0].value = keep_key
    # CAMPAIGN_SETUP children[9]: v SP savech je 1
    cnt = env.child("CAMPAIGN_SETUP").children[9]
    if cnt.value != 1:
        cnt.value = 1

    # CAMPAIGN_SETUP_OPTIONS: režim kampaně MP_NORMAL -> SP_NORMAL.
    # Tohle je HLAVNÍ přepínač — s MP_* hra po načtení nahodí síťovou
    # vrstvu, nenajde klienty a kopne "Klient opustil hru".
    opts = env.child("CAMPAIGN_SETUP").child("CAMPAIGN_SETUP_OPTIONS")
    mode = opts.children[0]
    if str(mode.value).startswith("MP"):
        mode.value = "SP" + str(mode.value)[2:]
    if opts.children[4].type_name == "unk23" and opts.children[4].value:
        opts.children[4].value = 0              # v SP 0
    ing = opts.child("CAMPAIGN_SETUP_INGAME_MODIFIABLES")
    for idx in (5, 6, 9):                       # MP-only bool volby (SP: False)
        b = ing.children[idx]
        if isinstance(b, Value) and b.type_name == "bool" and b.value:
            b.value = False

    # --- 1c) turn control: jediný člověk --------------------------------
    # HUMAN_FACTIONS + lidská TURN_GROUP jinak drží OBA hráče a hra na
    # konci kola čeká na tah druhého "klienta" -> timeout -> kick.
    fac_ids = {f["key"]: f["id"] for f in tables.factions(s)}
    keep_id = fac_ids[keep_key]
    drop_ids = [fac_ids[k] for k in drop_keys]
    assert keep_id < 256 and all(d < 65536 for d in drop_ids)
    model = env.child("CAMPAIGN_MODEL")
    hf_arr = next(c for c in model.child("HUMAN_FACTIONS").children
                  if isinstance(c, ValueArray))
    hf_arr._new = bytes([keep_id])          # arr16: 1 B na frakci
    hf_arr.mark_dirty()
    tc = model.child("WORLD").child("TURN_CONTROL")
    tg_blk = next(c for c in tc.children if isinstance(c, RecordBlock))
    for e in tg_blk.entries:
        arrs = [c for c in e.children if isinstance(c, ValueArray)]
        if not arrs:
            continue
        head = arrs[0]
        if head.base_code == 0x16:          # lidská skupina (arr16)
            head._new = bytes([keep_id])
            head.mark_dirty()
            for c in e.children:            # leader id + unk23 jako v SP
                if isinstance(c, Value) and c.type_name == "u32":
                    c.value = keep_id
                    break
            for c in e.children:
                if isinstance(c, Value) and c.type_name == "unk23" and c.value:
                    c.value = 0
                    break
        elif head.base_code == 0x17:        # AI skupina (arr17, u16 LE)
            payload = s.inner.data[head.cstart:head.cend]
            head._new = payload + b"".join(struct.pack("<H", d)
                                           for d in drop_ids)
            head.mark_dirty()

    # ENV-level GAME_PERSISTENT_SESSION_ID: keep only the owner's identity
    u64_keep = player_block(hdr_in, keep)[4]
    env_gpsi = s.inner.root.child("CAMPAIGN_ENV").child("GAME_PERSISTENT_SESSION_ID")
    if PROFILE:
        env_gpsi.children[0].value = PROFILE
    arr = next(c for c in env_gpsi.children if isinstance(c, ValueArray))
    arr._new = struct.pack("<Q", u64_keep)
    arr.mark_dirty()

    # multiplayer flag in CAMPAIGN_MODEL (child 14: True in MP, False in SP)
    model = s.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL")
    flag = model.children[14]
    assert isinstance(flag, Value) and flag.type_name == "bool" and flag.value
    flag.value = False

    # --- 2) inner file: rebuild root as CAMPAIGN_SAVE_GAME ------------------
    inner = s.inner
    build = inner.root.child("BUILD")
    env = inner.root.child("CAMPAIGN_ENV")
    parts = [copy_node(inner, build),
             build_sp_header(inner, hdr_in, keep, save_name),
             inner._serialize(env)]                    # env is dirty (AI flag)
    content = b"".join(parts)
    root_idx = name_idx(inner, "CAMPAIGN_SAVE_GAME")
    body = (bytes([0x80]) + struct.pack("<H", root_idx)
            + bytes([inner.root.version]) + write_varint(len(content))
            + content)
    inner_bytes = esf_file_bytes(inner, body)

    # --- 3) compress + rebuild outer ----------------------------------------
    comp = lzma.compress(inner_bytes, format=lzma.FORMAT_ALONE,
                         filters=LZMA_FILTER)
    props, stream = comp[:5], comp[13:]
    outer = s.outer
    hdr_out = outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER")
    info_content = (enc_u32(len(inner_bytes))
                    + b"\x46" + write_varint(5) + props)
    info_bytes = rec_header(name_idx(outer, "COMPRESSED_DATA_INFO"), 0,
                            len(info_content)) + info_content
    cd_content = (b"\x46" + write_varint(len(stream)) + stream + info_bytes)
    cd_bytes = rec_header(name_idx(outer, "COMPRESSED_DATA"), 0,
                          len(cd_content)) + cd_content
    parts = [copy_node(outer, outer.root.child("BUILD")),
             build_sp_header(outer, hdr_out, keep, save_name),
             cd_bytes]
    content = b"".join(parts)
    root_idx = name_idx(outer, "CAMPAIGN_SAVE_GAME")
    body = (bytes([0x80]) + struct.pack("<H", root_idx)
            + bytes([outer.root.version]) + write_varint(len(content))
            + content)
    with open(out_path, "wb") as f:
        f.write(esf_file_bytes(outer, body))
    return keep_key, drop_keys


if __name__ == "__main__":
    mp, keep, out, name = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    if len(sys.argv) > 5:
        PROFILE = sys.argv[5]
    keep_key, drop_keys = convert(mp, keep, out, name)
    print("kept %s (human), demoted %s -> %s" % (keep_key, drop_keys, out))
    # verify
    v = SaveFile(out)
    hdr = v.outer.root.child("SAVE_GAME_HEADER")
    env = v.campaign_root.child("CAMPAIGN_ENV")
    print("verify: root=%s, mp=%s, faction=%s, local=%s" % (
        v.outer.root.name, v.is_multiplayer, hdr.children[0].value,
        env.child("CAMPAIGN_SETUP_LOCAL").children[0].value))
    facs = {f["key"]: f["record"] for f in tables.factions(v)}
    get = lambda r: next(str(c.value) for c in r.children
                         if isinstance(c, Value) and c.type_name == "ascii"
                         and str(c.value) in ("FULL_HUMAN", "NON_HUMAN"))
    for key in [keep_key] + drop_keys:
        print("verify: %s = %s" % (
            key, get(facs[key].child("CAMPAIGN_PLAYER_SETUP"))))
