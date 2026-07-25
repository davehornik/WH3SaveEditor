# -*- coding: utf-8 -*-
"""Deep-walk test: parse every single node of a save (outer + inner)."""
import sys, time
from esf import SaveFile, Record, RecordBlock, BlockEntry, Value, ValueArray

def deep_walk(root):
    counts = {"record": 0, "block": 0, "entry": 0, "value": 0, "array": 0}
    stack = [root]
    while stack:
        n = stack.pop()
        if isinstance(n, Record):
            counts["record"] += 1
            kids = n.children
            stack.extend(kids)
            n._children = None          # release memory
        elif isinstance(n, RecordBlock):
            counts["block"] += 1
            ents = n.entries
            stack.extend(ents)
            n._entries = None
        elif isinstance(n, BlockEntry):
            counts["entry"] += 1
            kids = n.children
            stack.extend(kids)
            n._children = None
        elif isinstance(n, ValueArray):
            counts["array"] += 1
        elif isinstance(n, Value):
            counts["value"] += 1
            n.value                     # force decode
    return counts

if __name__ == "__main__":
    path = sys.argv[1]
    t0 = time.time()
    save = SaveFile(path)
    print("loaded: multiplayer=%s, inner=%s bytes (%.1fs)" % (
        save.is_multiplayer, "{:,}".format(len(save.inner.data)) if save.inner else "-",
        time.time() - t0))
    for label, esf in (("outer", save.outer), ("inner", save.inner)):
        if esf is None:
            continue
        t0 = time.time()
        c = deep_walk(esf.root)
        total = sum(c.values())
        print("%s: %s nodes in %.1fs  %s" % (label, "{:,}".format(total), time.time() - t0, c))
    print("DEEP WALK OK")
