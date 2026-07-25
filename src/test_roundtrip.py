# -*- coding: utf-8 -*-
"""Writer round-trip tests.

usage: python test_roundtrip.py <save> [--full]
  --full also force-reserializes every node of the inner file (slow, ~2 min)
"""
import os, sys, time, tempfile
from esf import SaveFile, EsfFile, Record

path = sys.argv[1]
full = "--full" in sys.argv

def treasury(save, faction_key):
    fa = save.campaign_root.walk("CAMPAIGN_ENV", "CAMPAIGN_MODEL", "WORLD", "FACTION_ARRAY")
    for e in fa.entries:
        f = next((c for c in e.children if isinstance(c, Record) and c.name == "FACTION"), None)
        if f is not None and f.children[1].value == faction_key:
            return f.child("FACTION_ECONOMICS").children[1]
    return None

# --- test 1: byte-identical serialization with no edits --------------------
save = SaveFile(path)
t0 = time.time()
assert save.inner.to_bytes() == save.inner.data, "inner to_bytes not byte-identical"
print("TEST 1a OK: inner file serializes byte-identical with no edits (%.1fs)" % (time.time() - t0))
assert save.outer.to_bytes() == save.outer.data, "outer to_bytes not byte-identical"
print("TEST 1b OK: outer file serializes byte-identical with no edits")

# --- test 2: edit treasury -> save -> reload -> verify ---------------------
sayl = treasury(save, "wh3_dlc27_nor_sayl")
astr = treasury(save, "wh3_dlc23_chd_astragoth")
print("before edit: sayl=%d astragoth=%d" % (sayl.value, astr.value))
old_astr = astr.value
sayl.value = 40000
tmp = os.path.join(tempfile.gettempdir(), "wh3edit_test.save_multiplayer")
t0 = time.time()
n = save.save(tmp)
print("saved %s bytes in %.1fs -> %s" % ("{:,}".format(n), time.time() - t0, tmp))

re = SaveFile(tmp)
sayl2 = treasury(re, "wh3_dlc27_nor_sayl")
astr2 = treasury(re, "wh3_dlc23_chd_astragoth")
assert sayl2.value == 40000, "edited value lost: %r" % sayl2.value
assert astr2.value == old_astr, "unrelated value changed: %r" % astr2.value
hdr = re.outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER")
assert re.is_multiplayer
print("TEST 2 OK: treasury edit survived save+reload (sayl=%d, astragoth=%d)" % (sayl2.value, astr2.value))

# verify rest of inner is untouched: compare against original inner bytes
orig = save.inner.data
new = re.inner.data
assert len(orig) == len(new) or abs(len(orig) - len(new)) < 64
diff = sum(1 for a, b in zip(orig, new) if a != b)
print("TEST 2b: inner differs in %d byte(s) vs original (len %d -> %d)" % (diff, len(orig), len(new)))

# --- test 3 (--full): force re-encode of every node ------------------------
if full:
    t0 = time.time()
    data2 = save.inner.to_bytes(force=True)
    print("force reserialize: %s -> %s bytes in %.1fs" % (
        "{:,}".format(len(save.inner.data)), "{:,}".format(len(data2)), time.time() - t0))
    t0 = time.time()
    inner2 = EsfFile(data2)  # constructor validates tables + root
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_deepwalk import deep_walk
    c = deep_walk(inner2.root)
    print("TEST 3 OK: force-reserialized inner reparsed, %s nodes deep-walked (%.1fs)" % (
        "{:,}".format(sum(c.values())), time.time() - t0))

print("ALL TESTS PASSED")
