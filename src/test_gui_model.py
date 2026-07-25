# -*- coding: utf-8 -*-
"""Headless test of the Qt tree model (no window shown)."""
import sys
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QApplication
from esf import SaveFile
from gui import EsfTreeModel

app = QApplication(sys.argv[:1])
save = SaveFile(sys.argv[1])
m = EsfTreeModel(save)

root = m.index(0, 0)
assert root.isValid()
print("root:", m.data(root, Qt.DisplayRole), "|", m.data(m.index(0, 2), Qt.DisplayRole))
n = m.rowCount(root)
print("root children:", n)
assert n >= 3
for r in range(n):
    i0, i1, i2 = (m.index(r, c, root) for c in range(3))
    print("  [%d] %-45s | %-30s | %s" % (
        r, m.data(i0, Qt.DisplayRole), str(m.data(i1, Qt.DisplayRole))[:30],
        m.data(i2, Qt.DisplayRole)))

# descend into grafted campaign -> CAMPAIGN_ENV -> ... -> FACTION_ARRAY
def find_child(parent, name):
    for r in range(m.rowCount(parent)):
        i = m.index(r, 0, parent)
        if str(m.data(i, Qt.DisplayRole)).startswith(name):
            return i
    return None

camp = find_child(root, "COMPRESSED_DATA")
assert camp is not None, "grafted campaign node missing"
env = find_child(camp, "CAMPAIGN_ENV")
world = find_child(find_child(env, "CAMPAIGN_MODEL"), "WORLD")
fa = find_child(world, "FACTION_ARRAY")
print("FACTION_ARRAY:", m.data(m.index(fa.row(), 1, world), Qt.DisplayRole))
e0 = m.index(0, 0, fa)
print("entry0 label:", m.data(e0, Qt.DisplayRole), "rows:", m.rowCount(e0))
fac = find_child(e0, "FACTION")
# find an editable value child and edit it via the model
row_val = None
for r in range(m.rowCount(fac)):
    i2 = m.index(r, 2, fac)
    if m.data(i2, Qt.DisplayRole) == "i32":
        row_val = r
        break
iv = m.index(row_val, 1, fac)
before = m.data(iv, Qt.DisplayRole)
assert m.flags(iv) & Qt.ItemIsEditable
ok = m.setData(iv, "123456", Qt.EditRole)
assert ok and m.data(iv, Qt.DisplayRole) == "123456", m.data(iv, Qt.DisplayRole)
print("model edit OK: i32 %s -> 123456, dirty propagated: %s" % (
    before, save.inner.root.dirty))
# parent chain consistency
assert m.parent(iv).internalPointer() is fac.internalPointer()
assert m.parent(fac).internalPointer() is e0.internalPointer()
print("MODEL TEST PASSED")
