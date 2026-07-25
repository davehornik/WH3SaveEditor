# -*- coding: utf-8 -*-
"""Headless test: load save into MainWindow, check tables populate + edit."""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from gui import MainWindow

app = QApplication(sys.argv[:1])
w = MainWindow()
w.load(sys.argv[1])
print("info:", w.info.text())
print("factions rows:", w.fact_table.rowCount())
print("combo current:", w.fac_combo.currentText())
print("characters rows:", w.char_table.rowCount())
print("units rows:", w.unit_table.rowCount())
assert w.fact_table.rowCount() > 500
assert w.char_table.rowCount() > 0
assert w.unit_table.rowCount() > 0

# simulate editing XP of first character through the table
it = w.char_table.item(0, 5)
before = it.data(Qt.DisplayRole)
it.setData(Qt.DisplayRole, 99999)
nodes = w._table_nodes[w.char_table]
node = nodes[it.data(Qt.UserRole)]
assert node.value == 99999, node.value
print("char XP edit: %s -> %s OK, dirty=%s" % (before, node.value, node.dirty))

# switch faction in combo (index-based, as popup selection does)
w.fac_combo.setCurrentIndex(w.fac_combo.findText("wh3_main_cth_the_western_provinces"))
print("western provinces: chars=%d units=%d" % (
    w.char_table.rowCount(), w.unit_table.rowCount()))
assert w.char_table.rowCount() not in (0, 20)
print("GUI TABLES TEST PASSED")
