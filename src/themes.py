# -*- coding: utf-8 -*-
"""Tématovací systém: 5 témat dle design handoffu (misc/HANDOFF.md).

Tokeny se do BASE_QSS dosazují přes %-formátování; každé téma může přidat
vlastní QSS blok v `extra_qss`. Vše je podmnožina Qt QSS (barvy, border,
border-radius, qlineargradient) — žádný blur/animace.
"""

# pořadí = pořadí v combu Nastavení
ORDER = ("obsidian", "forge", "parchment", "parchment_dark", "bloodthrone")

LABELS = {"obsidian": "Obsidian & Amber",
          "forge": "Kovárna",
          "parchment": "Pergamen & pečeť",
          "parchment_dark": "Tmavý pergamen",
          "bloodthrone": "Krevní trůn"}

DEFAULT = "obsidian"

BASE_QSS = """
QMainWindow, QWidget { background: %(win)s; color: %(text)s; font-size: 12px; }
QLabel { background: transparent; }
QWidget[class="row"] { background: transparent; }
QToolBar { background: %(chrome)s; border: none; border-bottom: 1px solid %(border)s; padding: 4px; spacing: 6px; }
QToolBar QToolButton { background: transparent; border: 1px solid %(border)s;
    border-radius: %(r)spx; padding: 5px 12px; color: %(text)s; }
QToolBar QToolButton:hover { border-color: %(acc)s; }
QToolBar QToolButton[role="primary"] { background: %(accGrad)s; color: %(accText)s;
    font-weight: bold; border: 1px solid %(acc)s; }
QToolBar QToolButton[role="primary"]:hover { border-color: %(text)s; }
QStatusBar { background: %(chrome)s; color: %(faint)s; border-top: 1px solid %(border)s; }
QStatusBar QLabel { color: %(faint)s; }
QLabel#title { font-size: 19px; font-weight: bold; color: %(text)s; }
QLabel#muted { color: %(muted)s; }
QLabel[class="badge-exp"] { color: %(warn)s; border: 1px solid %(warn)s; border-radius: 2px;
    padding: 1px 5px; font-size: 9px; font-weight: bold; background: transparent; }
QLabel[class="unsaved"] { color: %(acc)s; font-weight: bold; }
QLabel[class="micro"] { color: %(faint)s; font-size: 9px; font-weight: bold; }
QLabel[class="warn-box"] { color: %(danger)s; border: 1px solid %(dangerBorder)s;
    border-radius: %(r)spx; padding: 6px 8px; background: transparent; }

QWidget#sidebarBox { background: %(chrome)s; }
QListWidget#sidebar { background: %(chrome)s; border: none; font-size: 13px; outline: none; }
QListWidget#sidebar::item { padding: 10px 14px; margin: 1px 8px; border-radius: %(r)spx;
    color: %(muted)s; border-left: 3px solid transparent; }
QListWidget#sidebar::item:hover:!selected { background: %(hovRow)s; color: %(text)s; }
/* ::item:selected je per-téma v extra_qss */

QTableWidget, QTreeView { background: %(panel)s; alternate-background-color: %(panel)s;
    gridline-color: transparent; border: 1px solid %(border)s; color: %(text)s; }
QTableWidget::item, QTreeView::item { border-bottom: 1px solid %(hair)s; padding: 4px 6px; }
QTableWidget::item:hover, QTreeView::item:hover { background: %(hovRow)s; }
QTableWidget::item:selected, QTreeView::item:selected { background: %(selBg)s; color: %(selText)s; }
QHeaderView::section { background: %(panel2)s; color: %(muted)s; padding: 6px;
    border: none; border-bottom: 1px solid %(border)s;
    border-right: 1px solid %(headSep)s; font-weight: bold; font-size: 10px; }
QHeaderView::section:last { border-right: none; }
QTableCornerButton::section { background: %(panel2)s; border: none; }

QLineEdit, QComboBox { background: %(input)s; border: 1px solid %(border)s;
    border-radius: %(r)spx; padding: 5px 7px; color: %(text)s; selection-background-color: %(acc)s;
    selection-color: %(accText)s; }
QLineEdit:focus, QComboBox:focus { border-color: %(acc)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox { combobox-popup: 0; }
QComboBox QAbstractItemView { background: %(panel)s; border: 1px solid %(border)s;
    color: %(text)s; selection-background-color: %(selBg)s; selection-color: %(selText)s; }

QPushButton { background: %(panel)s; border: 1px solid %(border)s; border-radius: %(r)spx;
    padding: 7px 16px; color: %(text)s; }
QPushButton:hover { border-color: %(acc)s; }
QPushButton:disabled { color: %(faint)s; }
QPushButton[role="primary"] { background: %(accGrad)s; color: %(accText)s;
    font-weight: bold; border: 1px solid %(acc)s; }
QPushButton[role="primary"]:hover { border-color: %(text)s; }
QPushButton[role="danger"] { background: transparent; color: %(danger)s;
    border: 1px solid %(dangerBorder)s; font-weight: bold; }
QPushButton[role="danger"]:hover { background: %(hovRow)s; }
QPushButton[role="seg"] { padding: 5px 14px; }
QPushButton[role="seg"]:checked { background: %(accGrad)s; color: %(accText)s;
    font-weight: bold; border-color: %(acc)s; }

QTabWidget::pane { border: 1px solid %(border)s; top: -1px; }
QTabBar::tab { background: %(win)s; color: %(muted)s; padding: 7px 16px; border: 1px solid %(border)s;
    border-bottom: none; border-top-left-radius: %(r)spx; border-top-right-radius: %(r)spx; }
QTabBar::tab:selected { background: %(accGrad)s; color: %(accText)s; font-weight: bold; }

QFrame#panel { border: 1px solid %(border)s; border-radius: %(r)spx; background: %(panel)s; }
QWidget#sectionHead { background: %(secBandBg)s; border-bottom: 1px solid %(secBandLine)s;
    border-top-left-radius: %(r)spx; border-top-right-radius: %(r)spx; }
QLabel#sectionTitle { color: %(secTitle)s; font-size: 10px; font-weight: bold;
    background: transparent; }
QFrame#sectionLine { background: %(hair)s; border: none; }
QWidget#sectionBody { background: transparent; }

QWidget#segBox { border: 1px solid %(border)s; border-radius: %(r)spx; background: %(input)s; }
QWidget#segBox QPushButton[role="seg"] { border: none; border-radius: 0;
    padding: 5px 14px; background: transparent; }
QWidget#segBox QPushButton[role="seg"]:checked { background: %(accGrad)s;
    color: %(accText)s; font-weight: bold; }

QLineEdit[class="money"] { font-weight: bold; font-size: 13px; color: %(moneyColor)s; }

QWidget#updateBox { border: 1px solid %(acc)s; border-radius: %(r)spx;
    background: transparent; }

QCheckBox, QRadioButton { color: %(text)s; background: transparent; spacing: 7px; }
QRadioButton:disabled { color: %(faint)s; }
QRadioButton::indicator { width: 12px; height: 12px; border-radius: 7px;
    border: 1px solid %(border)s; background: %(input)s; }
QRadioButton::indicator:hover { border-color: %(acc)s; }
QRadioButton::indicator:checked { border: 4px solid %(acc)s; background: %(input)s;
    width: 6px; height: 6px; }
QCheckBox::indicator { width: 13px; height: 13px; border-radius: 3px;
    border: 1px solid %(border)s; background: %(input)s; }
QCheckBox::indicator:hover { border-color: %(acc)s; }
QCheckBox::indicator:checked { background: %(acc)s; border: 1px solid %(acc)s; }

QScrollBar:vertical { background: %(panel)s; width: 12px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(acc)s; }
QScrollBar:horizontal { background: %(panel)s; height: 12px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: %(acc)s; }

QDialog { background: %(panel)s; border: 1px solid %(border)s; }
QMessageBox { background: %(panel)s; }
QProgressDialog { background: %(panel)s; }
"""

THEMES = {
 "obsidian": dict(r=5, navSel="#e08a2e", headSep="#22262c", secBandBg="transparent", secBandLine="transparent",
   moneyColor="#e6e8ec", numColor="", microFmt="%s", titleAlign="left",
   win="#17191d", chrome="#121417", panel="#1d2025", panel2="#1a1d21", input="#131518",
   border="#2e3238", hair="#22262c", text="#e6e8ec", muted="#949aa5", faint="#676d78",
   acc="#e08a2e", accText="#17191d", accGrad="#e08a2e", secTitle="#e08a2e",
   selBg="rgba(224,138,46,0.13)", selText="#e6e8ec", hovRow="#22262c",
   danger="#d05b4e", dangerBorder="#6e3630", ok="#7fb069", warn="#d05b4e",
   link="#e08a2e",
   extra_qss="""
QListWidget#sidebar::item:selected { background: #1d2126; color: #e08a2e;
    font-weight: bold; border-left: 3px solid #e08a2e; border-radius: 0; }
"""),

 "forge": dict(r=2, navSel="#211a10", titleFmt="◆ %s ◆", titleAlign="center", headSep="#4f4433",
   secBandBg="qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2e2820, stop:1 #241f19)",
   secBandLine="#4a3f30", moneyColor="#d9ad52", numColor="#d9ad52", microFmt="— %s —",
   win="#1b1713", chrome="#221c15", panel="#241e17", panel2="#2a241d", input="#16120e",
   border="#3d3427", hair="#29231b", text="#eae2d2", muted="#a2967f", faint="#7a6f5c",
   acc="#cfa042", accText="#211a10",
   accGrad="qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #d9ad52, stop:1 #b58530)",
   secTitle="#cfa042", selBg="#4a3a1f", selText="#f0e3c0", hovRow="#2a241d",
   danger="#d8766a", dangerBorder="#6e352c", ok="#8ba05e", warn="#d8766a",
   link="#cfa042",
   extra_qss="""
QListWidget#sidebar::item:selected { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #d9ad52, stop:1 #b58530); color: #211a10; font-weight: bold; }
QHeaderView::section { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #2e2820, stop:1 #241f19); color: #cfa042; border-bottom: 1px solid #8c6a26; }
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #332c23, stop:1 #282219); }
QToolBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #26201a, stop:1 #211b15); }
"""),

 "parchment": dict(r=3, navSel="#2c2418", headSep="#d3c4a2", secBandBg="transparent", secBandLine="transparent",
   moneyColor="#2c2418", numColor="", microFmt="%s", titleAlign="left",
   # POZOR: dvouzónové téma — rám tmavý, obsah světlý (viz extra_qss)
   win="#e8dcc2", chrome="#24211d", panel="#f0e7d2", panel2="#dfd2b4", input="#faf3e3",
   border="#b9a888", hair="#d3c4a2", text="#2c2418", muted="#6f6250", faint="#a89d87",
   acc="#8e2f2b", accText="#f0e7d2", accGrad="#8e2f2b", secTitle="#8e2f2b",
   selBg="#8e2f2b", selText="#f0e7d2", hovRow="#e0d3b6",
   danger="#8e2f2b", dangerBorder="#8e2f2b", ok="#5d6e46", warn="#8e2f2b",
   link="#9a742e",
   extra_qss="""
QToolBar { background: #24211d; border-bottom: 2px solid #8e2f2b; }
QToolBar QLabel { color: #8d8471; }
QToolBar QToolButton { color: #d9d0bd; }
QToolBar QLineEdit, QToolBar QComboBox { background: #1d1a17; border-color: #4a4238; color: #d9d0bd; }
QToolBar QPushButton { background: transparent; border-color: #4a4238; color: #d9d0bd; }
QStatusBar { background: #24211d; color: #8d8471; }
QStatusBar QLabel { color: #a89d87; }
QWidget#sidebarBox { background: #24211d; }
QLabel[class="micro"] { color: #8d8471; }
QListWidget#sidebar { background: #24211d; }
QListWidget#sidebar::item { color: #a89d87; margin: 1px 0 1px 6px; border-left: none;
    border-top-left-radius: 4px; border-bottom-left-radius: 4px; }
QListWidget#sidebar::item:hover:!selected { background: #2e2a25; color: #d9d0bd; }
QListWidget#sidebar::item:selected { background: #e8dcc2; color: #2c2418; font-weight: bold; }
QHeaderView::section { border-bottom: 2px solid #b9a888; }
"""),

 "parchment_dark": dict(r=3, navSel="#e8dcc2", headSep="#5a5142", secBandBg="transparent", secBandLine="transparent",
   moneyColor="#c8a35a", numColor="", microFmt="%s", titleAlign="left",
   win="#2e2921", chrome="#26211b", panel="#37312a", panel2="#3e372e", input="#211d17",
   border="#4a4234", hair="#3e372e", text="#d6c9ad", muted="#9c8f77", faint="#8d8168",
   acc="#c05a4a", accText="#211d17", accGrad="#c05a4a", secTitle="#c05a4a",
   selBg="#c05a4a", selText="#211d17", hovRow="#3e372e",
   danger="#c05a4a", dangerBorder="#c05a4a", ok="#95a865", warn="#c8a35a",
   link="#c8a35a",
   extra_qss="""
QToolBar { border-bottom: 2px solid #c05a4a; }
QListWidget#sidebar::item:selected { background: #2e2921; color: #e8dcc2; font-weight: bold;
    border-left: 3px solid #c05a4a; border-radius: 0; }
"""),

 "bloodthrone": dict(r=2, navSel="#f5e6da", titleFmt="▼ %s", titleAlign="left", headSep="#66302a",
   secBandBg="qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2a1414, stop:1 #1f0e0e)",
   secBandLine="#8f1f18", moneyColor="#d8a648", numColor="#d8a648", microFmt="▼ %s",
   win="#170d0d", chrome="#100808", panel="#211011", panel2="#1f0e0e", input="#0f0707",
   border="#47201d", hair="#2a1313", text="#eddcd2", muted="#a58a80", faint="#74584f",
   acc="#c93a2b", accText="#f5e6da",
   accGrad="qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #c93a2b, stop:1 #8f1f18)",
   secTitle="#c93a2b",
   selBg="qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #8f1f18, stop:1 #6e1712)",
   selText="#f5e6da", hovRow="#2e1715",
   # v tomto tématu jsou varování MOSAZNÁ (červená je všude):
   danger="#d8a648", dangerBorder="#a3742a", ok="#93a05a", warn="#d8a648",
   link="#d8a648",
   extra_qss="""
QListWidget#sidebar::item:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
    stop:0 #c93a2b, stop:1 #8f1f18); color: #f5e6da; font-weight: bold;
    border-left: 3px solid #d8a648; border-radius: 0; }
QHeaderView::section { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #2a1414, stop:1 #1f0e0e); color: #c93a2b; border-bottom: 1px solid #8f1f18; }
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2c1715, stop:1 #211010); }
QToolBar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1d0f0f, stop:1 #150a0a); }
QLabel[class="unsaved"] { color: #d8a648; }
"""),
}


def theme(key):
    return THEMES.get(key, THEMES[DEFAULT])


def build_style(theme_key):
    t = theme(theme_key)
    return (BASE_QSS + t.get("extra_qss", "")) % t


def stance_colors(theme_key):
    """Barvy diplomatických postojů odvozené z tématu (HANDOFF §3)."""
    t = theme(theme_key)
    return {"war": t["danger"], "neutral": t["muted"],
            "defensive_allies": t["ok"], "military_allies": t["ok"],
            "master": t["warn"], "vassal": t["warn"]}


def build_palette(theme_key):
    """QPalette pro nativní prvky mimo QSS (menu, tooltips, ...)."""
    from PySide6.QtGui import QPalette, QColor
    t = theme(theme_key)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["win"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["panel"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["panel"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["faint"]))
    pal.setColor(QPalette.Button, QColor(t["panel"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["panel2"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["acc"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["accText"]))
    pal.setColor(QPalette.Link, QColor(t["link"]))
    return pal
