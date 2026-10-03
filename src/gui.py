# -*- coding: utf-8 -*-
"""WH3 Save Editor - GUI v0.2: sidebar navigation, dark theme."""
import os
import sys

from PySide6.QtCore import (Qt, QAbstractItemModel, QModelIndex, QThread,
                            Signal, QSize)
from PySide6.QtGui import QAction, QKeySequence, QColor, QBrush, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QTreeView, QFrame,
                               QFileDialog, QMessageBox, QTableWidget,
                               QTableWidgetItem, QLabel, QProgressDialog,
                               QStyleFactory, QHeaderView, QComboBox,
                               QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QListWidgetItem, QStackedWidget,
                               QLineEdit, QFormLayout, QPushButton, QGroupBox,
                               QStyledItemDelegate, QDialog, QDialogButtonBox)

from esf import (SaveFile, Record, RecordBlock, BlockEntry, Value, ValueArray,
                 UTF16, ASCII)
import tables
import i18n
import locdb
import themes
from i18n import t

APP_VERSION = "1.2.3"

# aktivní téma (slovník tokenů) — nastavuje set_theme(); výchozí dle themes.DEFAULT
THEME = themes.theme(themes.DEFAULT)
THEME_KEY = themes.DEFAULT
STANCE_COLORS = themes.stance_colors(themes.DEFAULT)


def set_theme(key):
    """Přepne globální tokeny; QSS/paletu aplikuje volající (apply_theme)."""
    global THEME, THEME_KEY, STANCE_COLORS
    THEME_KEY = key
    THEME = themes.theme(key)
    STANCE_COLORS.clear()
    STANCE_COLORS.update(themes.stance_colors(key))


# --- lazy tree model -------------------------------------------------------

class TreeItem:
    __slots__ = ("node", "parent", "row", "_children", "label")

    def __init__(self, node, parent, row, label=None):
        self.node = node
        self.parent = parent
        self.row = row
        self._children = None
        self.label = label

    def children(self, save):
        if self._children is None:
            kids = []
            n = self.node
            if isinstance(n, (Record, BlockEntry)):
                for i, c in enumerate(n.children):
                    if (isinstance(c, Record) and c.name == "COMPRESSED_DATA"
                            and save.inner is not None and n.parent is None):
                        kids.append(TreeItem(save.inner.root, self, i,
                                             label="COMPRESSED_DATA (%s)" % t("dekomprimováno")))
                    else:
                        kids.append(TreeItem(c, self, i))
            elif isinstance(n, RecordBlock):
                for i, e in enumerate(n.entries):
                    kids.append(TreeItem(e, self, i, label="%s – %d" % (n.name, i)))
            self._children = kids
        return self._children

    def has_children(self):
        n = self.node
        if isinstance(n, (Record, BlockEntry)):
            return n.size > 0
        if isinstance(n, RecordBlock):
            return n.count > 0
        return False


def value_summary(node):
    if isinstance(node, Record):
        return ""
    if isinstance(node, RecordBlock):
        return t("%d záznamů") % node.count
    if isinstance(node, BlockEntry):
        return ""
    if isinstance(node, ValueArray):
        items = node.items(limit=6)
        if items is None:
            return "%d B" % node.size
        n_total = node.items()
        n = len(n_total) if n_total is not None else 0
        s = ", ".join(repr(x) for x in items)
        if n > 6:
            s += ", …"
        return "[%s] (%d)" % (s, n)
    v = node.value
    if isinstance(v, float):
        return ("%.6f" % v).rstrip("0").rstrip(".")
    return str(v)


class EsfTreeModel(QAbstractItemModel):
    edited = Signal()
    HEADERS = ("Uzel", "Hodnota", "Typ")

    def __init__(self, save):
        super().__init__()
        self.save = save
        self.root_item = TreeItem(save.outer.root, None, 0)

    def index(self, row, col, parent=QModelIndex()):
        if parent.isValid():
            kids = parent.internalPointer().children(self.save)
        else:
            kids = [self.root_item]
        if 0 <= row < len(kids):
            return self.createIndex(row, col, kids[row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        p = index.internalPointer().parent
        if p is None:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return 1
        if parent.column() != 0:
            return 0
        return len(parent.internalPointer().children(self.save))

    def hasChildren(self, parent=QModelIndex()):
        if not parent.isValid():
            return True
        return parent.internalPointer().has_children()

    def columnCount(self, parent=QModelIndex()):
        return 3

    def headerData(self, sec, orient, role):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return t(self.HEADERS[sec])
        return None

    def data(self, index, role):
        item = index.internalPointer()
        n = item.node
        col = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == 0:
                if item.label:
                    return item.label
                if isinstance(n, (Record, RecordBlock)):
                    return n.name
                if isinstance(n, BlockEntry):
                    return "…"
                return "•"
            if col == 1:
                if role == Qt.EditRole and isinstance(n, Value):
                    v = n.value
                    return str(v) if not isinstance(v, bool) else ("true" if v else "false")
                return value_summary(n)
            if col == 2:
                if isinstance(n, Record):
                    return "record v%d" % n.version
                if isinstance(n, RecordBlock):
                    return "block v%d" % n.version
                if isinstance(n, BlockEntry):
                    return ""
                return n.type_name
        if role == Qt.ForegroundRole:
            if isinstance(n, Value) and n.dirty:
                return QBrush(QColor(THEME["acc"]))
            if col == 2:
                return QBrush(QColor(THEME["faint"]))
        return None

    def flags(self, index):
        fl = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        n = index.internalPointer().node
        if index.column() == 1 and isinstance(n, Value) and n.editable:
            fl |= Qt.ItemIsEditable
        return fl

    def setData(self, index, text, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        n = index.internalPointer().node
        if not isinstance(n, Value):
            return False
        try:
            n.value = self._parse(n, str(text).strip())
        except (ValueError, OverflowError):
            return False
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    @staticmethod
    def _parse(node, text):
        tn = node.type_name
        if tn == "bool":
            if text.lower() in ("true", "1", "ano", "yes"):
                return True
            if text.lower() in ("false", "0", "ne", "no"):
                return False
            raise ValueError(text)
        if tn in ("f32", "f64"):
            return float(text.replace(",", "."))
        if tn in ("utf16", "ascii"):
            return text
        v = int(text, 0)
        if tn.startswith("u") and v < 0:
            raise ValueError("unsigned")
        return v


_MONO_FAMILY = None


def _mono_family():
    """JetBrains Mono: přibalené TTF -> systém -> Consolas. Vrací název rodiny."""
    global _MONO_FAMILY
    if _MONO_FAMILY is not None:
        return _MONO_FAMILY
    from PySide6.QtGui import QFontDatabase
    fam = None
    base = os.path.join(i18n.res_dir(), "fonts")
    if os.path.isdir(base):
        for fn in sorted(os.listdir(base)):
            if fn.lower().endswith(".ttf"):
                fid = QFontDatabase.addApplicationFont(os.path.join(base, fn))
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                if fams and fam is None:
                    fam = fams[0]
    if fam is None and "JetBrains Mono" in QFontDatabase.families():
        fam = "JetBrains Mono"
    _MONO_FAMILY = fam or "Consolas"
    return _MONO_FAMILY


def _mono_font(size=9, bold=True):
    from PySide6.QtGui import QFont
    # pozn.: pojmenované rodiny "… SemiBold/Medium" Qt renderuje jako Regular;
    # jediné, co reálně přitlačí, je Bold váha na základní rodině
    f = QFont(_mono_family(), size, QFont.Bold if bold else QFont.Normal)
    f.setStyleHint(QFont.Monospace)
    return f


# asymetrické vztahy: druhá strana dostane zrcadlovou hodnotu
STANCE_RECIPROCAL = {"vassal": "master", "master": "vassal"}


def _color_dot(color):
    from PySide6.QtGui import QPixmap, QPainter, QIcon
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return QIcon(pm)


class StanceDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        from PySide6.QtCore import QTimer
        cb = QComboBox(parent)
        for i, (val, col) in enumerate(STANCE_COLORS.items()):
            cb.addItem(_color_dot(col), val)
            cb.setItemData(i, QBrush(QColor(col)), Qt.ForegroundRole)
        QTimer.singleShot(0, cb.showPopup)
        return cb

    def setEditorData(self, editor, index):
        i = editor.findText(str(index.data(Qt.DisplayRole)))
        if i >= 0:
            editor.setCurrentIndex(i)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


GITHUB_REPO = "davehornik/WH3SaveEditor"


def _ver_key(s):
    """'v1.1' / '1.1-beta1' -> porovnatelná n-tice; beta/rc < finální verze."""
    import re
    s = s.strip().lstrip("vV")
    pre = 0 if any(x in s.lower() for x in ("alpha", "beta", "rc")) else 1
    nums = tuple(int(x) for x in re.findall(r"\d+", s.split("-")[0])[:3])
    return nums + (0,) * (3 - len(nums)) + (pre,)


class UpdateCheck(QThread):
    """Tichá kontrola nové verze na GitHubu (při startu, na pozadí)."""
    found = Signal(str)     # tag nové verze

    def run(self):
        try:
            import json as _json
            from urllib.request import Request, urlopen
            req = Request(
                "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
                headers={"User-Agent": "WH3SaveEditor/" + APP_VERSION,
                         "Accept": "application/vnd.github+json"})
            with urlopen(req, timeout=5) as r:
                tag = _json.load(r).get("tag_name", "")
            if tag and _ver_key(tag) > _ver_key(APP_VERSION):
                self.found.emit(tag)
        except Exception:   # noqa: BLE001 — offline/rate-limit = žádná zpráva
            pass


class SaveWorker(QThread):
    done = Signal(int, str)

    def __init__(self, save, path):
        super().__init__()
        self.save = save
        self.path = path

    def run(self):
        try:
            n = self.save.save(self.path)
            self.done.emit(n, "")
        except Exception as e:      # noqa: BLE001
            self.done.emit(-1, str(e))


# --- main window -----------------------------------------------------------

def _spaced(text):
    """'SAVE EDITOR' -> 'S A V E  E D I T O R' (mikrolabel sidebaru)."""
    return "  ".join(" ".join(w) for w in text.split())


class SectionPanel(QFrame):
    """Panel s per-téma titulkovou lištou (FIXES G4) — náhrada QGroupBox."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._raw = title.upper()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._head = QWidget()
        self._head.setObjectName("sectionHead")
        hh = QHBoxLayout(self._head)
        hh.setContentsMargins(12, 7, 12, 7)
        hh.setSpacing(10)
        self._line_l = QFrame()
        self._line_l.setObjectName("sectionLine")
        self._line_l.setFixedHeight(1)
        self._title = QLabel()
        self._title.setObjectName("sectionTitle")
        self._line_r = QFrame()
        self._line_r.setObjectName("sectionLine")
        self._line_r.setFixedHeight(1)
        hh.addWidget(self._line_l, 1)
        hh.addWidget(self._title)
        hh.addWidget(self._line_r, 1)
        outer.addWidget(self._head)
        bodyw = QWidget()
        bodyw.setObjectName("sectionBody")
        self.body = QVBoxLayout(bodyw)
        self.body.setContentsMargins(12, 8, 12, 12)
        outer.addWidget(bodyw)
        self.refresh()

    def refresh(self):
        from PySide6.QtGui import QFont
        self._title.setText(THEME.get("titleFmt", "%s") % self._raw)
        f = self._title.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)   # QSS letter-spacing neumí
        self._title.setFont(f)
        self._line_l.setVisible(THEME.get("titleAlign", "left") == "center")


# unicode glyfy (HANDOFF §5) — vykreslují se do QPixmap ikon přes
# Segoe UI Symbol (mono outline), aby Windows nesáhl po barevném emoji fontu
PAGES = [("◈", "Přehled", "overview"),
         ("⚔", "Postavy a jednotky", "tables"),
         ("⚖", "Diplomacie", "diplo"),
         ("♜", "Území a města", "territory"),
         ("⌗", "RAW data", "raw"),
         ("⚒", "Nástroje", "tools")]


def _nav_icon(glyph, color, color_sel):
    """Monochromatická ikona z unicode glyfu; Normal + Selected stav."""
    from PySide6.QtGui import QPixmap, QPainter, QIcon, QFont
    from PySide6.QtCore import QRect

    def render(col):
        pm = QPixmap(36, 36)          # 2x pro ostré škálování
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Segoe UI Symbol", 11)
        p.setFont(f)
        p.setPen(QColor(col))
        p.drawText(QRect(0, 0, 18, 18), Qt.AlignCenter, glyph)
        p.end()
        return pm

    icon = QIcon()
    icon.addPixmap(render(color), QIcon.Normal)
    icon.addPixmap(render(color_sel), QIcon.Selected)
    return icon


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.save_file = None
        self.model = None
        self.worker = None
        self.setWindowTitle("WH3 Save Editor v%s" % APP_VERSION)
        self.resize(1360, 860)

        import configparser
        self.settings_path = os.path.join(i18n.app_dir(), "settings.ini")
        self.cfg = configparser.ConfigParser()
        self.cfg.read(self.settings_path, encoding="utf-8")
        if "paths" not in self.cfg:
            self.cfg["paths"] = {}
        if "ui" not in self.cfg:
            self.cfg["ui"] = {}
        locdb.preload(self.cfg)      # čitelná jména z herních packů (na pozadí)

        tb = self.addToolBar(t("Hlavní"))
        tb.setMovable(False)
        act_open = QAction("▤ " + t("Otevřít…"), self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self.open_dialog)
        tb.addAction(act_open)
        self.save_picker = QComboBox()
        self.save_picker.setMinimumWidth(330)
        mono = _mono_font(10)
        self.save_picker.setMaxVisibleItems(22)
        self.save_picker.setFont(mono)
        self.save_picker.view().setFont(mono)
        self.save_picker.activated.connect(self._quick_open)
        tb.addWidget(self.save_picker)
        self.act_save = QAction(t("Uložit jako…"), self)
        self.act_save.setShortcut(QKeySequence.SaveAs)
        self.act_save.triggered.connect(self.save_dialog)
        self.act_save.setEnabled(False)
        tb.addAction(self.act_save)
        btn = tb.widgetForAction(self.act_save)
        if btn is not None:
            btn.setProperty("role", "primary")
        act_cfg = QAction(t("Nastavení"), self)
        act_cfg.triggered.connect(self.open_settings)
        tb.addAction(act_cfg)
        tb.addSeparator()
        lbl = QLabel(t("  Frakce: "))
        tb.addWidget(lbl)
        self.fac_combo = QComboBox()
        self.fac_combo.setEditable(True)
        self.fac_combo.setInsertPolicy(QComboBox.NoInsert)
        self.fac_combo.setMinimumWidth(340)
        comp = self.fac_combo.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        from PySide6.QtWidgets import QCompleter
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.fac_combo.currentIndexChanged.connect(self.faction_selected)
        self.fac_combo.activated.connect(self.faction_selected)
        tb.addWidget(self.fac_combo)
        self.info = QLabel("")
        self.info.setContentsMargins(16, 0, 8, 0)
        tb.addWidget(self.info)

        # sidebar (box s mikrolabelem) + stacked pages
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setIconSize(QSize(18, 18))
        self.sidebar.setSpacing(0)
        for glyph, label, _ in PAGES:
            it = QListWidgetItem(t(label), self.sidebar)
            it.setSizeHint(QSize(140, 36))
        self.sidebar.setCurrentRow(0)
        side_box = QWidget()
        side_box.setObjectName("sidebarBox")
        side_box.setFixedWidth(196)
        sv = QVBoxLayout(side_box)
        sv.setContentsMargins(0, 10, 0, 0)
        sv.setSpacing(4)
        self.micro = QLabel(_spaced(t("EDITOR SAVU")))
        self.micro.setProperty("class", "micro")
        self.micro.setContentsMargins(16, 0, 0, 0)
        sv.addWidget(self.micro)
        sv.addWidget(self.sidebar, 1)
        self.stack = QStackedWidget()
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.stack.addWidget(self._page_overview())
        self.stack.addWidget(self._page_tables())
        self.stack.addWidget(self._page_diplo())
        self.stack.addWidget(self._placeholder("♜", t("Území a města"),
                                               t("Regiony, budovy a garnizony – v přípravě.")))
        self.stack.addWidget(self._page_raw())
        self.stack.addWidget(self._page_tools())

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(side_box)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage(t("Otevři .save nebo .save_multiplayer soubor"))
        self.unsaved_lbl = QLabel("")
        self.unsaved_lbl.setProperty("class", "unsaved")
        self.unsaved_lbl.setVisible(False)
        self.statusBar().insertPermanentWidget(0, self.unsaved_lbl)
        self.sig_lbl = QLabel()
        self.sig_lbl.setTextFormat(Qt.RichText)
        self.sig_lbl.setOpenExternalLinks(True)
        self.statusBar().addPermanentWidget(self.sig_lbl)
        ver = QLabel("v%s " % APP_VERSION)
        ver.setObjectName("muted")
        self.statusBar().addPermanentWidget(ver)
        self._table_nodes = {}
        self._loading = False
        self._player_factions = []
        self._edit_count = 0
        self.apply_theme(self.cfg["ui"].get("theme", themes.DEFAULT),
                         self.cfg["ui"].get("density", "compact"),
                         startup=True)
        self._first_run_check()
        self._refresh_save_list()
        self._refresh_recent()
        self.update_lbl = QLabel("")
        self.update_lbl.setTextFormat(Qt.RichText)
        self.update_lbl.setOpenExternalLinks(True)
        self.update_lbl.setVisible(False)
        self.statusBar().insertPermanentWidget(1, self.update_lbl)
        self._upd = UpdateCheck()
        self._upd.found.connect(self._update_available)
        self._upd.start()

    def _update_available(self, tag):
        self._update_tag = tag
        self.update_lbl.setText(
            '<a style="color:%s;font-weight:bold;text-decoration:none" '
            'href="https://github.com/%s/releases/latest">▲ %s</a>&nbsp; '
            % (THEME["link"], GITHUB_REPO,
               t("Nová verze %s ke stažení") % tag))
        self.update_lbl.setVisible(True)
        self.update_box_lbl.setText(
            '<span style="color:%s;font-weight:bold;font-size:13px">%s</span><br>'
            '<span style="color:%s">%s</span>'
            % (THEME["text"], t("Nová verze %s ke stažení") % tag,
               THEME["muted"], t("Aktuálně máš verzi %s.") % APP_VERSION))
        self.update_box.setVisible(True)

    # -- téma / hustota -------------------------------------------------------

    def _all_tables(self):
        return [x for x in (getattr(self, n, None) for n in
                            ("fact_table", "char_table", "unit_table",
                             "diplo_table")) if x is not None]

    def apply_theme(self, key, density=None, startup=False):
        if key not in themes.THEMES:
            key = themes.DEFAULT
        set_theme(key)
        app = QApplication.instance()
        app.setPalette(themes.build_palette(key))
        app.setStyleSheet(themes.build_style(key))
        if density is None:
            density = self.cfg["ui"].get("density", "compact")
        self.apply_density(density)
        self._retheme_dynamic()
        if not startup and self.save_file is not None:
            # překreslit tabulky (foregroundy nastavené přes setForeground)
            self._last_key = None
            self.faction_selected()

    def apply_density(self, density):
        h = 34 if density == "airy" else 26
        for tab in self._all_tables():
            tab.verticalHeader().setDefaultSectionSize(h)

    def _retheme_dynamic(self):
        """Prvky s barvou zapečenou v rich-textu / stylesheetu."""
        for sp in self.findChildren(SectionPanel):
            sp.refresh()
        self.micro.setText(THEME.get("microFmt", "%s") % _spaced(t("EDITOR SAVU")))
        self.welcome_glyph.setStyleSheet(
            "font-size: 34px; color: %s; background: transparent;" % THEME["acc"])
        self.btn_delunit.setText(
            ("⚠ " if THEME_KEY == "bloodthrone" else "✕ ") + t("Odebrat jednotku"))
        for i, (glyph, _, _) in enumerate(PAGES):
            self.sidebar.item(i).setIcon(
                _nav_icon(glyph, THEME["muted"], THEME.get("navSel", THEME["acc"])))
        self.sig_lbl.setText(
            '%s <a style="color:%s;text-decoration:none" '
            'href="https://github.com/davehornik">davehornik</a>&nbsp;'
            % (t("Vytvořeno s ♥ od"), THEME["link"]))
        for val, rb in getattr(self, "dip_radios", {}).items():
            rb.setStyleSheet("color: %s" % STANCE_COLORS.get(val, THEME["text"]))
        if getattr(self, "welcome_steps", None) is not None:
            self.welcome_steps.setText(self._welcome_steps_html())
        if self.save_file is not None:
            self._set_overview_sub()
            self._set_mods_label()

    # -- nastavení složek ----------------------------------------------------

    def _save_cfg(self):
        with open(self.settings_path, "w", encoding="utf-8") as f:
            self.cfg.write(f)

    def _find_save_root(self):
        """Najdi ...\\The Creative Assembly\\Warhammer3 na běžných místech."""
        cands = []
        for env in ("APPDATA", "USERPROFILE"):
            b = os.environ.get(env)
            if b:
                cands.append(os.path.join(b, "The Creative Assembly", "Warhammer3"))
                cands.append(os.path.join(b, "AppData", "Roaming",
                                          "The Creative Assembly", "Warhammer3"))
        for c in cands:
            if os.path.isdir(os.path.join(c, "save_games")) or \
                    os.path.isdir(os.path.join(c, "save_games_multiplayer")):
                return c
        return cands[0] if cands else ""

    def _first_run_check(self):
        p = self.cfg["paths"]
        if "sp_dir" in p or "mp_dir" in p:
            return
        base = self._find_save_root()
        sp = os.path.join(base, "save_games")
        mp = os.path.join(base, "save_games_multiplayer")
        if os.path.isdir(sp):
            p["sp_dir"] = sp
        if os.path.isdir(mp):
            p["mp_dir"] = mp
        # nag jen když se NENAŠLA ani jedna složka (jinak MP-only nag zbytečně)
        if not os.path.isdir(sp) and not os.path.isdir(mp):
            QMessageBox.information(
                self, t("Nastavení složek"),
                t("Nenašel jsem výchozí složky se savy.\n\nBěžně bývají v:\n"
                  "%s\n(save_games a save_games_multiplayer)\n\n"
                  "Nastav je prosím v Nastavení, nebo je vyber při "
                  "otevírání savu.") % base)
        self._save_cfg()

    def _set_dir(self, key, ask=True):
        title = t("Složka singleplayer savů") if key == "sp_dir" else t("Složka multiplayer savů")
        d = QFileDialog.getExistingDirectory(self, title,
                                             self.cfg["paths"].get(key, ""))
        if d:
            self.cfg["paths"][key] = d
            self._save_cfg()
            self._refresh_save_list()

    def _refresh_save_list(self):
        self.save_picker.clear()
        self.save_picker.addItem("⌕ " + t("Rychlé otevření savu…"), None)
        for label, key, pat in (("SP", "sp_dir", ".save"),
                                ("MP", "mp_dir", ".save_multiplayer")):
            d = self.cfg["paths"].get(key)
            if not d or not os.path.isdir(d):
                continue
            files = [f for f in os.listdir(d) if f.lower().endswith(pat)]
            files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)),
                       reverse=True)
            from datetime import datetime
            for f in files[:25]:
                full = os.path.join(d, f)
                stamp = datetime.fromtimestamp(
                    os.path.getmtime(full)).strftime("%d.%m.%Y %H:%M")
                self.save_picker.addItem("%s  ·  %s  ·  %s" % (label, stamp, f),
                                         full)

    def _quick_open(self, index):
        path = self.save_picker.itemData(index)
        if path:
            self.load(path)
        self.save_picker.setCurrentIndex(0)

    # -- pages --------------------------------------------------------------

    def _welcome_steps_html(self):
        acc, mut = THEME["acc"], THEME["muted"]
        steps = ((1, t("Otevři save")), (2, t("Uprav hodnoty")),
                 (3, t("Ulož jako kopii")))
        arrow = ' &nbsp;<span style="color:%s">→</span>&nbsp; ' % THEME["faint"]
        return arrow.join(
            '<span style="color:%s;font-weight:bold">%d</span> '
            '<span style="color:%s">%s</span>' % (acc, n, mut, s)
            for n, s in steps)

    def _page_welcome(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(3)
        self.welcome_glyph = QLabel("◈")
        self.welcome_glyph.setAlignment(Qt.AlignCenter)
        v.addWidget(self.welcome_glyph)
        title = QLabel(t("Žádný save není načtený"))
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)
        sub = QLabel(t("Otevři soubor .save nebo .save_multiplayer — najdeš je "
                       "ve složce") + "\n"
                     + r"AppData\Roaming\The Creative Assembly\Warhammer3\save_games…")
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        v.addSpacing(10)
        b = QPushButton("▤ " + t("Otevřít save…"))
        b.setProperty("role", "primary")
        b.clicked.connect(self.open_dialog)
        v.addWidget(b, alignment=Qt.AlignCenter)
        v.addSpacing(14)
        g = SectionPanel(t("Poslední savy"))
        g.setMaximumWidth(520)
        g.setMinimumWidth(440)
        self.recent_box = QVBoxLayout()
        g.body.addLayout(self.recent_box)
        v.addWidget(g, alignment=Qt.AlignCenter)
        v.addSpacing(10)
        self.welcome_steps = QLabel(self._welcome_steps_html())
        self.welcome_steps.setTextFormat(Qt.RichText)
        self.welcome_steps.setAlignment(Qt.AlignCenter)
        v.addWidget(self.welcome_steps)
        v.addSpacing(18)
        # banner nové verze — viditelný kompromis mezi pop-upem a status barem
        self.update_box = QWidget()
        self.update_box.setObjectName("updateBox")
        self.update_box.setMaximumWidth(520)
        self.update_box.setMinimumWidth(440)
        ub = QHBoxLayout(self.update_box)
        ub.setContentsMargins(14, 10, 14, 10)
        self.update_box_lbl = QLabel("")
        self.update_box_lbl.setTextFormat(Qt.RichText)
        ub.addWidget(self.update_box_lbl, 1)
        b_upd = QPushButton(t("Stáhnout"))
        b_upd.setProperty("role", "primary")

        def open_releases():
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(
                "https://github.com/%s/releases/latest" % GITHUB_REPO))

        b_upd.clicked.connect(open_releases)
        ub.addWidget(b_upd)
        self.update_box.setVisible(False)
        v.addWidget(self.update_box, alignment=Qt.AlignCenter)
        v.addStretch(4)
        return w

    def _refresh_recent(self):
        if getattr(self, "recent_box", None) is None:
            return
        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        from datetime import datetime
        found = []
        for key, pat in (("sp_dir", ".save"), ("mp_dir", ".save_multiplayer")):
            d = self.cfg["paths"].get(key)
            if not d or not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.lower().endswith(pat):
                    full = os.path.join(d, f)
                    found.append((os.path.getmtime(full), f, full))
        found.sort(reverse=True)
        if not found:
            lbl = QLabel(t("žádné"))
            lbl.setObjectName("muted")
            self.recent_box.addWidget(lbl)
            return
        for mtime, name, full in found[:4]:
            stamp = datetime.fromtimestamp(mtime).strftime("%d.%m. %H:%M")
            lbl = QLabel('<a style="color:%s;text-decoration:none" href="#">%s</a>'
                         '&nbsp;&nbsp;<span style="color:%s">· %s</span>'
                         % (THEME["link"], name, THEME["faint"], stamp))
            lbl.setTextFormat(Qt.RichText)
            lbl.linkActivated.connect(lambda _, p=full: self.load(p))
            self.recent_box.addWidget(lbl)

    def _page_overview(self):
        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 22, 28, 22)
        self.overview_title = QLabel("")
        self.overview_title.setObjectName("title")
        self.overview_sub = QLabel("")
        self.overview_sub.setObjectName("muted")
        self.overview_sub.setTextFormat(Qt.RichText)
        v.addWidget(self.overview_title)
        v.addWidget(self.overview_sub)

        def flabel(text):
            lbl = QLabel(text)
            lbl.setObjectName("muted")
            return lbl

        def fvalue():
            lbl = QLabel("–")
            lbl.setStyleSheet("font-weight: bold; background: transparent;")
            return lbl

        g1 = SectionPanel(t("Informace o savu"))
        form = QFormLayout()
        g1.body.addLayout(form)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText(t("název zobrazený ve hře"))
        self.ed_name.editingFinished.connect(self.apply_save_name)
        self.lbl_campaign = fvalue()
        self.lbl_players = fvalue()
        self.lbl_version = fvalue()
        form.addRow(flabel(t("Název savu:")), self.ed_name)
        form.addRow(flabel(t("Kampaň:")), self.lbl_campaign)
        form.addRow(flabel(t("Hráči:")), self.lbl_players)
        form.addRow(flabel(t("Verze hry:")), self.lbl_version)
        self.lbl_mods = QLabel("–")
        self.lbl_mods.setWordWrap(True)
        self.lbl_mods.setTextFormat(Qt.RichText)
        self.lbl_mods.setOpenExternalLinks(True)
        form.addRow(flabel(t("Mody:")), self.lbl_mods)
        v.addWidget(g1)
        v.addSpacing(6)

        g2 = SectionPanel(t("Pokladny hráčů"))
        self.money_box = QVBoxLayout()
        self.money_box.setSpacing(10)
        g2.body.addLayout(self.money_box)
        v.addWidget(g2)
        v.addSpacing(4)

        hint = QLabel("ⓘ " + t("Změny se projeví až po „Uložit jako…“ a načtení "
                               "savu ve hře. Originál si vždy nech zálohovaný."))
        hint.setObjectName("muted")
        v.addWidget(hint)
        v.addStretch(1)

        self.overview_stack = QStackedWidget()
        self.overview_stack.addWidget(self._page_welcome())   # 0 = welcome
        self.overview_stack.addWidget(content)                # 1 = data
        return self.overview_stack

    def _page_tables(self):
        self.fact_table = self._make_table(["#", "Frakce", "Klíč", "Peníze"])
        self.char_table = self._make_table(["ID", "Role", "Typ", "Subtyp", "Jméno",
                                            "Body", "Rank", "XP"], stretch=4)
        self.unit_table = self._make_table(["Armáda", "Jednotka", "Síla", "Max",
                                            "Rank", "Exp"])
        self.unit_table.setColumnWidth(0, 170)
        self.role_filter = QComboBox()
        self.role_filter.addItems([t(x) for x in
                                   ("Vše", "Hratelné", "Armády", "Hrdinové",
                                    "Karavany", "Garnizony", "Naverbovatelní")])
        self.role_filter.currentIndexChanged.connect(lambda *_: self._refresh_chars())
        self.role_filter.setVisible(False)
        self.unit_filter = QComboBox()
        self.unit_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.unit_filter.setMinimumWidth(240)
        self.unit_filter.currentIndexChanged.connect(lambda *_: self._refresh_units())
        self.unit_filter.setVisible(False)
        tabs = QTabWidget()
        tabs.addTab(self.fact_table, t("Frakce"))
        tabs.addTab(self.char_table, t("Postavy"))
        tabs.addTab(self.unit_table, t("Jednotky"))
        def on_tab(i):
            self.role_filter.setVisible(i == 1)
            self.unit_filter.setVisible(i == 2)
            self.btn_heal.setVisible(i == 2)
            self.btn_maxrank.setVisible(i == 2)
            self.btn_delunit.setVisible(i == 2)
        tabs.currentChanged.connect(on_tab)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        row.addWidget(self.role_filter)
        row.addWidget(self.unit_filter)
        self.btn_heal = QPushButton("✚ " + t("Uzdravit armádu"))
        self.btn_heal.clicked.connect(lambda: self._army_action("heal"))
        self.btn_maxrank = QPushButton("▲ " + t("Max rank armádě"))
        self.btn_maxrank.clicked.connect(lambda: self._army_action("rank"))
        self.btn_delunit = QPushButton("✕ " + t("Odebrat jednotku"))
        self.btn_delunit.setProperty("role", "danger")
        self.btn_delunit.clicked.connect(self._delete_unit)
        for b in (self.btn_heal, self.btn_maxrank, self.btn_delunit):
            b.setVisible(False)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(tabs)
        return box

    FLAG_LABELS = (("NON_AGGRESSION_PACT", "Pakt o neútočení"),
                   ("TRADE_RIGHTS", "Obchodní práva"),
                   ("SOFT_MILITARY_ACCESS", "Vojenský průchod"))

    def _page_diplo(self):
        from PySide6.QtWidgets import QRadioButton, QCheckBox, QButtonGroup
        self.diplo_table = self._make_table(["Frakce", "Klíč", "Postoj", "Vztah"],
                                            stretch=0)
        self.diplo_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.diplo_table.cellClicked.connect(self._diplo_select)
        detail = SectionPanel(t("Detail vztahu"))
        detail.setFixedWidth(420)     # fixní — ať panel neskáče podle délky jmen
        dv = detail.body
        self.dip_target = QLabel(t("← vyber frakci v tabulce"))
        self.dip_target.setObjectName("title")
        self.dip_target.setWordWrap(True)
        dv.addWidget(self.dip_target)
        self._dip_loading = True
        self.dip_group = QButtonGroup(self)
        self.dip_radios = {}
        for val, col in STANCE_COLORS.items():
            rb = QRadioButton(val)
            rb.setStyleSheet("color: %s" % col)
            self.dip_group.addButton(rb)
            self.dip_radios[val] = rb
            rb.toggled.connect(lambda on, v=val: self._diplo_set_stance(v) if on else None)
            if val in ("master", "vassal"):
                roww = QWidget()
                roww.setProperty("class", "row")
                rh = QHBoxLayout(roww)
                rh.setContentsMargins(0, 0, 0, 0)
                rh.setSpacing(8)
                rh.addWidget(rb)
                badge = QLabel(t("EXPERIMENTÁLNÍ"))
                badge.setProperty("class", "badge-exp")
                rh.addWidget(badge)
                rh.addStretch(1)
                dv.addWidget(roww)
            else:
                dv.addWidget(rb)
        # vysvětlivka master/vassal (dřív v textu radií — roztahovala panel)
        self.dip_mv_hint = QLabel("")
        self.dip_mv_hint.setObjectName("muted")
        self.dip_mv_hint.setWordWrap(True)
        dv.addWidget(self.dip_mv_hint)
        dv.addSpacing(10)
        dv.addWidget(QLabel(t("Smlouvy (mohou platit souběžně):")))
        self.dip_checks = {}
        for flag, label in self.FLAG_LABELS:
            cb = QCheckBox(t(label))
            cb.toggled.connect(lambda on, fl=flag: self._diplo_toggle_flag(fl, on))
            self.dip_checks[flag] = cb
            dv.addWidget(cb)
        self.dip_other = QLabel("")
        self.dip_other.setObjectName("muted")
        self.dip_other.setWordWrap(True)
        dv.addWidget(self.dip_other)
        dv.addStretch(1)
        warn = QLabel(t("⚠ master/vassal (vazalství) je experimentální a může save "
                        "rozbít — zkoušej jen na záloze."))
        warn.setProperty("class", "warn-box")
        warn.setWordWrap(True)
        dv.addWidget(warn)
        self._dip_loading = False
        self._dip_sel = None
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        self.diplo_info = QLabel(t("Diplomacie"))
        v.addWidget(self.diplo_info)
        h = QHBoxLayout()
        h.addWidget(self.diplo_table, 1)
        h.addWidget(detail)
        v.addLayout(h)
        return w

    def _diplo_select(self, row, _col):
        tk = self.diplo_table.item(row, 1).text()
        d = getattr(self, "_dip_by_key", {}).get(tk)
        if d is None:
            return
        self._dip_loading = True
        self._dip_sel = d
        self.dip_target.setText(tables.pretty_faction(tk))
        me, tgt = tables.pretty_faction(self._last_key), tables.pretty_faction(tk)
        self.dip_mv_hint.setText(
            t("master: %s bude PÁNEM, %s vazalem") % (me, tgt) + "\n"
            + t("vassal: %s se stane VAZALEM frakce %s") % (me, tgt))
        st = str(d["stance"].value) if d["stance"] else ""
        self.dip_group.setExclusive(False)
        for val, rb in self.dip_radios.items():
            rb.setChecked(val == st)
        self.dip_group.setExclusive(True)
        items = (d["flags"].items() or []) if d["flags"] is not None else []
        if d["flags"] is not None and d["flags"]._new is not None:
            items = d["flags"]._new
        known = {f for f, _ in self.FLAG_LABELS}
        for flag, cb in self.dip_checks.items():
            cb.setChecked(flag in items)
        other = [i for i in items if i not in known]
        self.dip_other.setText(t("Další příznaky: %s") % ", ".join(other) if other else "")
        self._dip_loading = False

    def _diplo_set_stance(self, val):
        if self._dip_loading or self._dip_sel is None:
            return
        d = self._dip_sel
        for n in (d["stance"], d["stance2"]):
            if n is not None:
                n.value = val
        recip = STANCE_RECIPROCAL.get(val, val)
        rr = tables.reciprocal_relationship(self.save_file, self._last_key,
                                            d["target_key"])
        for n in rr["stances"]:
            n.value = recip
        for r in range(self.diplo_table.rowCount()):
            if self.diplo_table.item(r, 1).text() == d["target_key"]:
                self._loading = True
                it = self.diplo_table.item(r, 2)
                it.setData(Qt.DisplayRole, val)
                it.setForeground(QBrush(QColor(STANCE_COLORS.get(val, "#fff"))))
                self._loading = False
        self.mark_modified()

    def _diplo_toggle_flag(self, flag, on):
        if self._dip_loading or self._dip_sel is None:
            return
        d = self._dip_sel
        rr = tables.reciprocal_relationship(self.save_file, self._last_key,
                                            d["target_key"])
        for node in (d["flags"], rr["flags"]):
            if node is None:
                continue
            items = node._new if node._new is not None else (node.items() or [])
            items = [i for i in items if i != flag]
            if on:
                items.append(flag)
            node.set_ascii_items(items)
        self.mark_modified()

    def _page_raw(self):
        self.tree = QTreeView()
        self.tree.setUniformRowHeights(True)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        warn = QLabel(t("⚠ Surová struktura savu — edituj, jen pokud víš, co děláš."))
        warn.setObjectName("muted")
        v.addWidget(warn)
        v.addWidget(self.tree)
        return w

    def _page_tools(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 22, 28, 22)
        title = QLabel(t("Nástroje"))
        title.setObjectName("title")
        v.addWidget(title)
        g = SectionPanel(t("Převod multiplayer → singleplayer"))
        gv = g.body
        badge = QLabel(t("EXPERIMENTÁLNÍ"))
        badge.setProperty("class", "badge-exp")
        gv.addWidget(badge, alignment=Qt.AlignLeft)
        desc = QLabel(t("Vezme kooperativní/multiplayer save a vytvoří z něj "
                        "singleplayer save, ve kterém pokračuješ sólo: tvoje "
                        "frakce zůstane hratelná, frakce ostatních hráčů "
                        "převezme AI. Svět kampaně zůstává beze změny."))
        desc.setWordWrap(True)
        gv.addWidget(desc)
        warn = QLabel(t("⚠ Experimentální funkce — před použitím si zálohuj "
                        "savy. Tvoje identita se načte automaticky z tvých "
                        "singleplayer savů."))
        warn.setObjectName("muted")
        warn.setWordWrap(True)
        gv.addWidget(warn)
        b = QPushButton(t("Vybrat MP save a převést…"))
        b.clicked.connect(self.mp_to_sp_dialog)
        gv.addWidget(b, alignment=Qt.AlignLeft)
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _local_profile(self):
        """(utf16 string, u64) z nejnovějšího lokálního SP savu."""
        from esf import EsfFile, ValueArray, Value
        d = self.cfg["paths"].get("sp_dir")
        if not d or not os.path.isdir(d):
            return None, None
        files = sorted((f for f in os.listdir(d) if f.lower().endswith(".save")),
                       key=lambda f: os.path.getmtime(os.path.join(d, f)),
                       reverse=True)
        for f in files:
            try:
                e = EsfFile.from_path(os.path.join(d, f))
                g = e.root.child("SAVE_GAME_HEADER").child(
                    "GAME_PERSISTENT_SESSION_ID")
                arr = next(c for c in g.children if isinstance(c, ValueArray))
                ids = arr.items()
                return str(g.children[0].value), (ids[0] if ids else None)
            except Exception:   # noqa: BLE001
                continue
        return None, None

    def mp_to_sp_dialog(self):
        from PySide6.QtWidgets import QInputDialog
        import convert_mp_sp as conv
        from esf import EsfFile
        path, _ = QFileDialog.getOpenFileName(
            self, t("Vybrat MP save a převést…"),
            self.cfg["paths"].get("mp_dir", ""),
            "MP savegames (*.save_multiplayer)")
        if not path:
            return
        try:
            outer = EsfFile.from_path(path)
            hdr = outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER")
            n = conv.player_count(hdr)
            players = [conv.player_block(hdr, i) for i in range(n)]
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), str(e))
            return
        profile, my_u64 = self._local_profile()
        items, default = [], 0
        for i, p in enumerate(players):
            mark = t("  ← ty") if p[4] == my_u64 else ""
            items.append("%s — %s%s" % (p[0], tables.pretty_faction(p[1]), mark))
            if p[4] == my_u64:
                default = i
        if profile is None:
            QMessageBox.warning(self, t("Nástroje"),
                                t("Nenašel jsem žádný tvůj singleplayer save "
                                  "— ulož nejdřív libovolnou sólo kampaň "
                                  "(kvůli identitě hráče)."))
            return
        choice, ok = QInputDialog.getItem(
            self, t("Převod multiplayer → singleplayer"),
            t("Pokračovat sólo jako:"), items, default, False)
        if not ok:
            return
        keep = items.index(choice)
        keep_p = players[keep]
        base = os.path.splitext(os.path.basename(path))[0]
        suggested = "%s SOLO – %s" % (keep_p[0],
                                      tables.pretty_faction(keep_p[1]))
        out_name, ok = QInputDialog.getText(
            self, t("Převod multiplayer → singleplayer"),
            t("Název nového savu:"), text=suggested)
        out_name = out_name.strip()
        if not ok or not out_name:
            return
        safe = "".join(c for c in out_name if c not in '\\/:*?"<>|')
        out = os.path.join(self.cfg["paths"].get("sp_dir", ""),
                           "%s.%s.save" % (safe, base.split(".")[-1]
                                           if base.split(".")[-1].isdigit() else "0"))
        conv.PROFILE = profile
        self.progress = QProgressDialog(t("Převádím (LZMA komprese)…"), "",
                                        0, 0, self)
        self.progress.setCancelButton(None)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(300)
        self.setEnabled(False)

        class W(QThread):
            done = Signal(str, str)

            def run(w_self):
                try:
                    conv.convert(path, keep, out, out_name)
                    w_self.done.emit(out, "")
                except Exception as e:  # noqa: BLE001
                    w_self.done.emit("", str(e))

        self.worker = W()
        self.worker.done.connect(self._mp_to_sp_done)
        self.worker.start()

    def _mp_to_sp_done(self, out, err):
        self.progress.close()
        self.setEnabled(True)
        if err:
            QMessageBox.critical(self, t("Chyba"), err)
            return
        self._refresh_save_list()
        QMessageBox.information(self, t("Nástroje"),
                                t("Hotovo! Nový singleplayer save:") + "\n" + out)

    def _placeholder(self, emoji, title, text):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(1)
        for s, name in ((emoji + "  " + title, "title"), (text, "muted")):
            lbl = QLabel(s)
            lbl.setObjectName(name)
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        v.addStretch(1)
        return w

    # -- tables helpers ------------------------------------------------------

    def _make_table(self, headers, stretch=1):
        tab = QTableWidget(0, len(headers))
        tab.setHorizontalHeaderLabels([t(h).upper() for h in headers])
        hdr = tab.horizontalHeader()
        # všechny sloupce interaktivní (spolehlivé tažení oběma směry),
        # poslední dopružuje zbytek šířky — žádný "gumový" Stretch uprostřed
        hdr.setStretchLastSection(True)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setMinimumSectionSize(40)
        tab.verticalHeader().setVisible(False)
        tab.setAlternatingRowColors(False)
        tab.setSelectionBehavior(QTableWidget.SelectRows)
        tab.setSortingEnabled(True)
        tab.itemChanged.connect(self._cell_edited)
        tab.setColumnWidth(0, 46)
        tab.setColumnWidth(stretch, 280)     # hlavní textový sloupec
        return tab

    def _fill_table(self, table, rows, row_tags=None):
        self._loading = True
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        nodes = []
        self._table_nodes[table] = nodes
        for r, cells in enumerate(rows):
            for col, (val, node) in enumerate(cells):
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, val)
                if col and isinstance(val, (int, float)) and not isinstance(val, bool):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if THEME.get("numColor"):
                        it.setForeground(QBrush(QColor(THEME["numColor"])))
                if node is None:
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                else:
                    it.setData(Qt.UserRole, len(nodes))
                    nodes.append(node)
                if col == 0 and row_tags is not None:
                    it.setData(Qt.UserRole + 1, row_tags[r])
                table.setItem(r, col, it)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.AscendingOrder)
        self._loading = False

    def _cell_edited(self, item):
        if self._loading:
            return
        idx = item.data(Qt.UserRole)
        nodes = self._table_nodes.get(item.tableWidget())
        if idx is None or nodes is None:
            return
        node = nodes[idx]
        try:
            node.value = EsfTreeModel._parse(node, str(item.data(Qt.DisplayRole)))
        except (TypeError, ValueError, OverflowError):
            self._loading = True
            item.setData(Qt.DisplayRole, node.value)
            self._loading = False
            return
        # stance edits propagate to the duplicate field and the other side
        extra = getattr(self, "_stance_partners", {}).get(id(node))
        if extra is not None:
            target_key, stance2 = extra
            if stance2 is not None:
                stance2.value = node.value
            recip = STANCE_RECIPROCAL.get(node.value, node.value)
            for rn in tables.reciprocal_stance_nodes(self.save_file,
                                                     self._last_key, target_key):
                rn.value = recip
        col = THEME["acc"]
        if (item.tableWidget() is getattr(self, "diplo_table", None)
                and item.column() == 2):
            col = STANCE_COLORS.get(str(item.data(Qt.DisplayRole)), THEME["acc"])
        item.setForeground(QBrush(QColor(col)))
        self.mark_modified()

    # -- open / load ---------------------------------------------------------

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("Otevřít save"),
            self.cfg["paths"].get("sp_dir",
                                  os.path.join(os.environ.get("APPDATA", ""),
                                               "The Creative Assembly", "Warhammer3")),
            t("TW savegames (*.save *.save_multiplayer);;Všechny soubory (*)"))
        if path:
            self.load(path)

    def load(self, path):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        locdb.load(self.cfg)         # počkej na názvy (no-op, když už jsou)
        try:
            self.save_file = SaveFile(path)
        except Exception as e:      # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, t("Chyba"), t("Soubor se nepodařilo načíst:\n%s") % e)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.model = EsfTreeModel(self.save_file)
        self.model.edited.connect(self.mark_modified)
        self.tree.setModel(self.model)
        self.tree.expandToDepth(0)
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 420)
        self.act_save.setEnabled(True)
        self.setWindowTitle("WH3 Save Editor v%s – %s"
                            % (APP_VERSION, os.path.basename(path)))
        self.info.setText(self.header_summary())
        self.populate_factions()
        names = self._save_name_nodes()
        self.ed_name.setText(str(names[0].value) if names else "")
        self.lbl_campaign.setText(getattr(self, "_campaign_key", None) or "–")
        self.lbl_players.setText(", ".join(
            tables.pretty_faction(k) for k in self._player_factions) or "–")
        self.lbl_version.setText(next((p for p in self.info.text().split("   |   ")
                                       if "Build" in p), "–"))
        self._rebuild_money_rows()
        self._set_mods_label()
        self.overview_title.setText(os.path.basename(path))
        self._set_overview_sub()
        self.overview_stack.setCurrentIndex(1)
        self._edit_count = 0
        self.unsaved_lbl.setVisible(False)
        self.statusBar().showMessage(t("Načteno: %s") % path)

    def _set_mods_label(self):
        hdr = self.save_file.outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER") or \
            self.save_file.outer.root.child("SAVE_GAME_HEADER")
        mods = []
        mb = hdr.child("mod_history_block_name") if hdr else None
        if mb is not None:
            for e in mb.entries:
                vals = [c.value for c in e.children if isinstance(c, Value)]
                if len(vals) >= 2 and str(vals[1]) != "campaigns":
                    wid = str(vals[1])
                    name = str(vals[0]).lstrip("@").replace(".pack", "")
                    mods.append(
                        '<a style="color:%s" href="https://steamcommunity.com/'
                        'sharedfiles/filedetails/?id=%s">%s</a> &nbsp;%s'
                        % (THEME["link"], wid, wid, name))
        self.lbl_mods.setText("<br>".join(mods) if mods else t("žádné"))

    def _set_overview_sub(self):
        self.overview_sub.setText(
            '%s · %s %s · <span style="color:%s">✓ %s</span>' % (
                t("Multiplayer save") if self.save_file.is_multiplayer
                else t("Singleplayer save"),
                t("kampaň"), getattr(self, "_campaign_key", "?"),
                THEME["ok"], t("v pořádku načteno")))

    def header_summary(self):
        s = self.save_file
        parts = ["multiplayer" if s.is_multiplayer else "singleplayer"]
        self._player_factions = []
        self._players = []
        hdr = s.outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER") or \
            s.outer.root.child("SAVE_GAME_HEADER")
        if hdr is not None:
            kids = hdr.children
            if not s.is_multiplayer:
                if kids and isinstance(kids[0], Value) and kids[0].code == ASCII:
                    key = str(kids[0].value)
                    self._player_factions.append(key)
                    self._players.append((tables.pretty_faction(key), key))
                    parts.append(key)
            else:
                for i, c in enumerate(kids):
                    if (isinstance(c, Value) and c.code == ASCII
                            and str(c.value).startswith("ui\\")):
                        prev = kids[i - 1] if i >= 1 else None
                        if not (isinstance(prev, Value) and prev.code == ASCII):
                            continue
                        key = str(prev.value)
                        name = next((kids[j].value for j in range(i - 2, -1, -1)
                                     if isinstance(kids[j], Value)
                                     and kids[j].code == UTF16), "?")
                        self._player_factions.append(key)
                        self._players.append((str(name), key))
                        parts.append("%s (%s)" % (name, key))
            ver = next((str(c.value) for c in kids
                        if isinstance(c, Value) and c.code == ASCII
                        and "Build" in str(c.value)), None)
            if ver:
                parts.append(ver)
        return "   |   ".join(parts)

    # -- save name / quick actions ------------------------------------------

    def _save_name_nodes(self):
        s = self.save_file
        hdr = s.outer.root.child("SAVE_GAME_HEADER_MULTIPLAYER") or \
            s.outer.root.child("SAVE_GAME_HEADER")
        if hdr is None:
            return []
        kids = hdr.children
        name_val = None
        self._campaign_key = None
        for i, c in enumerate(kids):
            if (i > 0 and isinstance(c, Value) and c.code == ASCII
                    and str(c.value).startswith("wh")
                    and "\\" not in str(c.value)):
                prevs = [kids[j] for j in range(i - 1, -1, -1)
                         if isinstance(kids[j], Value) and kids[j].code == UTF16]
                if prevs:
                    name_val = prevs[0].value
                    self._campaign_key = str(c.value)
                    break
        if name_val is None:
            return []
        return [c for c in kids if isinstance(c, Value) and c.code == UTF16
                and c.value == name_val]

    def apply_save_name(self):
        if self.save_file is None:
            return
        new = self.ed_name.text()
        changed = False
        for n in self._save_name_nodes():
            if n.value != new:
                n.value = new
                changed = True
        if changed:
            self.mark_modified()
            self.statusBar().showMessage(t("Název savu změněn na: %s") % new)

    def _money_node(self, key):
        for f in tables.factions(self.save_file):
            if f["key"] == key:
                return f["money"]
        return None

    def _rebuild_money_rows(self):
        if self.save_file is None:
            return
        while self.money_box.count():
            it = self.money_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                sub = it.layout()
                while sub.count():
                    sw = sub.takeAt(0).widget()
                    if sw is not None:
                        sw.deleteLater()

        def add_row(label, key):
            node = self._money_node(key)
            if node is None:
                return
            roww = QWidget()
            roww.setProperty("class", "row")
            h = QHBoxLayout(roww)
            h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            h.addWidget(lbl, 1)          # input + tlačítko k pravému okraji
            ed = QLineEdit(str(node.value))
            ed.setProperty("class", "money")
            ed.setFixedWidth(110)
            ed.setAlignment(Qt.AlignRight)
            h.addWidget(ed)
            b = QPushButton(t("Nastavit"))
            b.setProperty("role", "primary")

            def apply():
                n = self._money_node(key)
                try:
                    n.value = int(ed.text())
                except ValueError:
                    ed.setText(str(n.value))
                    return
                self.mark_modified()
                self.statusBar().showMessage(
                    t("Pokladna %s nastavena na %s — nezapomeň Uložit jako…")
                    % (tables.pretty_faction(key), ed.text()))

            b.clicked.connect(apply)
            h.addWidget(b)
            self.money_box.addWidget(roww)

        for name, key in self._players:
            add_row("♟ %s  –  %s" % (name, tables.pretty_faction(key)), key)
        sel = getattr(self, "_last_key", None)
        if sel and sel not in self._player_factions:
            add_row("⌕ " + t("Vybraná frakce  –  %s") % tables.pretty_faction(sel), sel)

    # -- tables pages --------------------------------------------------------

    def populate_factions(self):
        facs = tables.factions(self.save_file)
        self._fill_table(self.fact_table, [
            [(f["index"], None), (tables.pretty_faction(f["key"]), None),
             (f["key"], None),
             (f["money"].value if f["money"] else "", f["money"])]
            for f in facs])
        self._loading = True
        self.fac_combo.clear()
        # jen "živé" frakce (dummy frakce pro quest battles nemají armády ani postavy)
        entries = sorted(((tables.pretty_faction(f["key"]), f["key"]) for f in facs
                          if f["armies"] or f["chars"]
                          or f["key"] in self._player_factions),
                         key=lambda x: x[0].lower())
        for label, key in entries:
            self.fac_combo.addItem("%s   (%s)" % (label, key), key)
        self._loading = False
        self._last_key = None
        default = next((k for k in self._player_factions
                        if self.fac_combo.findData(k) >= 0), None)
        if default:
            self.fac_combo.setCurrentIndex(self.fac_combo.findData(default))
        self.faction_selected()

    def faction_selected(self, *_):
        if self._loading or self.save_file is None:
            return
        key = self.fac_combo.currentData()
        if key is None:
            i = self.fac_combo.findText(self.fac_combo.currentText())
            key = self.fac_combo.itemData(i) if i >= 0 else None
        if not key or key == getattr(self, "_last_key", None):
            return
        self._last_key = key
        self._chars = tables.characters(self.save_file, key)
        self._refresh_chars()
        self._units = tables.units(self.save_file, key)
        self._unit_labels = {c["force_id"]: c["role"].split(" (")[0]
                             for c in self._chars
                             if c["active"] and c.get("force_id")}
        self._loading = True
        cur = self.unit_filter.currentText()
        self.unit_filter.clear()
        self.unit_filter.addItems([t("Všechny armády")]
                                  + sorted(set(self._unit_labels.values())))
        i = self.unit_filter.findText(cur)
        self.unit_filter.setCurrentIndex(i if i >= 0 else 0)
        self._loading = False
        self._refresh_units()
        dip = tables.diplomacy(self.save_file, key)
        self._stance_partners = {}
        self._dip_by_key = {d["target_key"]: d for d in dip}
        self._dip_sel = None
        rows = []
        for d in dip:
            rows.append([(tables.pretty_faction(d["target_key"]), None),
                         (d["target_key"], None),
                         (d["stance"].value if d["stance"] else "", None),
                         (d["score"].value if d["score"] else 0, d["score"])])
        self._fill_table(self.diplo_table, rows)
        self._loading = True
        for r in range(self.diplo_table.rowCount()):
            it = self.diplo_table.item(r, 2)
            col = STANCE_COLORS.get(it.text())
            if col:
                it.setForeground(QBrush(QColor(col)))
        self._loading = False
        self.diplo_info.setText(t("Diplomacie frakce: %s") % tables.pretty_faction(key))
        self._rebuild_money_rows()

    def _army_action(self, kind):
        """Bulk edit units of the currently filtered army (or all)."""
        if not hasattr(self, "_units"):
            return
        mode = self.unit_filter.currentText()
        allmode = self.unit_filter.currentIndex() <= 0
        changed = 0
        for u in self._units:
            label = self._unit_labels.get(u["force_id"], t("Armáda %d") % u["army"])
            if not allmode and label != mode:
                continue
            if kind == "heal" and u["hp"] and u["hp_max"]:
                if u["hp"].value != u["hp_max"].value:
                    u["hp"].value = u["hp_max"].value
                    changed += 1
            elif kind == "rank" and u["rank"] and u["rank"].value != 9:
                # jednotky lordů/hrdinů přeskočit — jejich úroveň je v postavě
                if u["commander"] or "_cha_" in u["unit_key"]:
                    continue
                u["rank"].value = 9
                changed += 1
        if changed:
            self.mark_modified()
            self._last_key = None
            self.faction_selected()      # reload tables to show new values
            self.statusBar().showMessage(
                (t("Uzdraveno jednotek: %d") if kind == "heal"
                 else t("Povýšeno jednotek: %d")) % changed)

    def _refresh_units(self):
        if self._loading or self.save_file is None or not hasattr(self, "_units"):
            return
        mode = self.unit_filter.currentText()
        allmode = self.unit_filter.currentIndex() <= 0
        rows, tags = [], []
        for i, u in enumerate(self._units):
            label = self._unit_labels.get(u["force_id"],
                                          t("Armáda %d") % u["army"])
            if not allmode and label != mode:
                continue
            rows.append([(label, None),
                         (tables.pretty_unit(u["unit_key"]), None),
                         (u["hp"].value if u["hp"] else "", u["hp"]),
                         (u["hp_max"].value if u["hp_max"] else "", u["hp_max"]),
                         (u["rank"].value if u["rank"] else 0, u["rank"]),
                         (round(u["exp"].value, 4) if u["exp"] else 0.0, u["exp"])])
            tags.append(i)
        self._fill_table(self.unit_table, rows, row_tags=tags)

    def _delete_unit(self):
        row = self.unit_table.currentRow()
        if row < 0 or not hasattr(self, "_units"):
            return
        tag = self.unit_table.item(row, 0).data(Qt.UserRole + 1)
        if tag is None:
            return
        u = self._units[tag]
        if u["commander"] or "_cha_" in u["unit_key"]:
            QMessageBox.warning(self, t("Jednotky"),
                                t("Tohle je jednotka lorda/hrdiny — tu odebrat "
                                  "nelze, patří k postavě."))
            return
        if QMessageBox.question(
                self, t("Odebrat jednotku"),
                t("Opravdu odebrat jednotku %s z armády?\n(Experimentální "
                  "funkce — měj zálohu savu.)") % tables.pretty_unit(u["unit_key"])) \
                != QMessageBox.Yes:
            return
        u["entry"].delete()
        self.mark_modified()
        self._last_key = None
        self.faction_selected()

    def _refresh_chars(self):
        if self.save_file is None or not hasattr(self, "_chars"):
            return
        mode = self.role_filter.currentIndex()

        def keep(c):
            if mode <= 0:
                return True
            if mode == 1:
                return c["active"] and c["category"] != "colonel"
            return c["kind"] == ("army", "hero", "caravan",
                                 "garrison", "pool")[mode - 2]

        chars = [c for c in self._chars if keep(c)]
        self._fill_table(self.char_table, [
            [(c["id"], None), (c["role"], None),
             (c["category"], None), (c["subtype"], None),
             (c["name"], None),
             (c["points"].value if c["points"] else "", c["points"]),
             (c["rank"].value if c["rank"] else "", c["rank"]),
             (c["xp"].value if c["xp"] else "", c["xp"])]
            for c in chars])
        self._loading = True
        grey = QBrush(QColor(THEME["faint"]))
        for r in range(self.char_table.rowCount()):
            if self.char_table.item(r, 1).text() == t("Naverbovatelný"):
                for col in range(self.char_table.columnCount()):
                    self.char_table.item(r, col).setForeground(grey)
        self._loading = False

    # -- save ----------------------------------------------------------------

    def open_settings(self):
        SettingsDialog(self).exec()

    def mark_modified(self):
        self.setWindowModified(True)
        self._edit_count += 1
        self.unsaved_lbl.setText("● " + t("Neuložené změny (%d)") % self._edit_count
                                 + "  ")
        self.unsaved_lbl.setVisible(True)
        self.statusBar().showMessage(t("Neuložené změny — nezapomeň „Uložit jako…“"))

    def save_dialog(self):
        if self.save_file is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("Uložit jako"), self.save_file.path,
            t("TW savegames (*.save *.save_multiplayer);;Všechny soubory (*)"))
        if not path:
            return
        self.progress = QProgressDialog(t("Ukládám (LZMA komprese)…"), "", 0, 0, self)
        self.progress.setCancelButton(None)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(300)
        self.setEnabled(False)
        self.worker = SaveWorker(self.save_file, path)
        self.worker.done.connect(lambda n, err, p=path: self.save_done(n, err, p))
        self.worker.start()

    def save_done(self, n, err, path):
        self.progress.close()
        self.setEnabled(True)
        if n < 0:
            QMessageBox.critical(self, t("Chyba při ukládání"), err)
            return
        self.setWindowModified(False)
        self._edit_count = 0
        self.unsaved_lbl.setVisible(False)
        self._refresh_recent()
        self.statusBar().showMessage(t("Uloženo: %s (%s B)") % (path, "{:,}".format(n)))


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.win = parent
        self.setWindowTitle(t("Nastavení"))
        self.setMinimumWidth(560)
        form = QFormLayout(self)

        # téma — combo s barevným čtverečkem akcentu
        self.theme_combo = QComboBox()
        for key in themes.ORDER:
            self.theme_combo.addItem(_accent_swatch(themes.theme(key)["acc"]),
                                     t(themes.LABELS[key]), key)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(THEME_KEY)))
        form.addRow(t("Téma:"), self.theme_combo)

        # hustota tabulek — spojený segment (FIXES O4)
        from PySide6.QtWidgets import QButtonGroup
        wrap = QWidget()
        wrap.setProperty("class", "row")
        wh = QHBoxLayout(wrap)
        wh.setContentsMargins(0, 0, 0, 0)
        seg = QWidget()
        seg.setObjectName("segBox")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(1, 1, 1, 1)
        sh.setSpacing(0)
        self.density_group = QButtonGroup(self)
        cur = parent.cfg["ui"].get("density", "compact")
        for val, label in (("compact", t("Kompaktní")), ("airy", t("Vzdušná"))):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("role", "seg")
            b.setChecked(val == cur)
            self.density_group.addButton(b)
            b.setProperty("density", val)
            sh.addWidget(b)
        wh.addWidget(seg)
        wh.addStretch(1)
        form.addRow(t("Hustota tabulek:"), wrap)

        self.lang_combo = QComboBox()
        for code in i18n.available():
            self.lang_combo.addItem({"cs": "Čeština", "en": "English"}.get(code, code),
                                    code)
        self.lang_combo.setCurrentIndex(
            max(0, self.lang_combo.findData(i18n.lang)))
        form.addRow(t("Jazyk:"), self.lang_combo)
        self.dir_edits = {}
        for key, label in (("sp_dir", t("Složka SP savů:")),
                           ("mp_dir", t("Složka MP savů:")),
                           ("game_dir", t("Složka hry (kvůli názvům):"))):
            roww = QWidget()
            roww.setProperty("class", "row")
            h = QHBoxLayout(roww)
            h.setContentsMargins(0, 0, 0, 0)
            ed = QLineEdit(parent.cfg["paths"].get(key, ""))
            self.dir_edits[key] = ed
            h.addWidget(ed, 1)
            b = QPushButton(t("Procházet…"))
            b.clicked.connect(lambda _=False, k=key, e=ed: self._browse(k, e))
            h.addWidget(b)
            form.addRow(label, roww)
        gd = self.dir_edits["game_dir"]
        if not gd.text():
            auto = locdb.find_game_dir()
            if auto:
                gd.setPlaceholderText("%s (auto)" % auto)
        note = QLabel(t("Změna jazyka nebo složky hry se projeví po restartu aplikace."))
        note.setObjectName("muted")
        form.addRow(note)
        # pořadí přesně [Zrušit][Uložit] (FIXES O3) — QDialogButtonBox by
        # ho na Windows prohodil
        btn_row = QWidget()
        btn_row.setProperty("class", "row")
        bh = QHBoxLayout(btn_row)
        bh.setContentsMargins(0, 8, 0, 0)
        bh.addStretch(1)
        btn_cancel = QPushButton(t("Zrušit"))
        btn_cancel.setDefault(True)
        btn_cancel.clicked.connect(self.reject)
        bh.addWidget(btn_cancel)
        btn_save = QPushButton(t("Uložit"))
        btn_save.setProperty("role", "primary")
        btn_save.clicked.connect(self._apply)
        bh.addWidget(btn_save)
        form.addRow(btn_row)

    def _browse(self, key, ed):
        d = QFileDialog.getExistingDirectory(self, ed.text() or "", ed.text())
        if d:
            ed.setText(d)

    def _apply(self):
        cfg = self.win.cfg
        if "ui" not in cfg:
            cfg["ui"] = {}
        cfg["ui"]["lang"] = self.lang_combo.currentData()
        theme_key = self.theme_combo.currentData()
        density = next((b.property("density")
                        for b in self.density_group.buttons() if b.isChecked()),
                       "compact")
        cfg["ui"]["theme"] = theme_key
        cfg["ui"]["density"] = density
        for key, ed in self.dir_edits.items():
            if ed.text():
                cfg["paths"][key] = ed.text()
        self.win._save_cfg()
        self.win._refresh_save_list()
        # téma + hustota se aplikují hned, bez restartu
        self.win.apply_theme(theme_key, density)
        self.accept()


def _accent_swatch(color):
    from PySide6.QtGui import QPixmap, QIcon
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


def _flag_pixmap(code):
    from PySide6.QtGui import QPixmap, QPainter, QPen, QPolygon
    from PySide6.QtCore import QPoint
    pm = QPixmap(64, 42)
    if code == "cs":
        pm.fill(QColor("#ffffff"))
        p = QPainter(pm)
        p.fillRect(0, 21, 64, 21, QColor("#d7141a"))
        p.setBrush(QColor("#11457e"))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygon([QPoint(0, 0), QPoint(32, 21), QPoint(0, 42)]))
    else:
        pm.fill(QColor("#012169"))
        p = QPainter(pm)
        p.setPen(QPen(QColor("#ffffff"), 10))
        p.drawLine(0, 0, 64, 42)
        p.drawLine(64, 0, 0, 42)
        p.setPen(QPen(QColor("#C8102E"), 5))
        p.drawLine(0, 0, 64, 42)
        p.drawLine(64, 0, 0, 42)
        p.setPen(QPen(QColor("#ffffff"), 18))
        p.drawLine(32, 0, 32, 42)
        p.drawLine(0, 21, 64, 21)
        p.setPen(QPen(QColor("#C8102E"), 10))
        p.drawLine(32, 0, 32, 42)
        p.drawLine(0, 21, 64, 21)
    p.end()
    return pm


def _ask_language():
    from PySide6.QtGui import QIcon
    dlg = QDialog()
    dlg.setWindowTitle("WH3 Save Editor")
    h = QHBoxLayout(dlg)
    h.setContentsMargins(18, 18, 18, 18)
    h.setSpacing(14)
    choice = {"lang": "en"}

    def pick(code):
        choice["lang"] = code
        dlg.accept()

    for code in ("en", "cs"):
        b = QPushButton()
        b.setIcon(QIcon(_flag_pixmap(code)))
        b.setIconSize(QSize(64, 42))
        b.setFixedSize(92, 64)
        b.clicked.connect(lambda _=False, c=code: pick(c))
        h.addWidget(b)
    dlg.exec()
    return choice["lang"]


def main():
    app = QApplication(sys.argv)
    if "Fusion" in QStyleFactory.keys():
        app.setStyle("Fusion")
    # jazyk + téma musí být vyřešené dřív, než se postaví UI
    import configparser
    spath = os.path.join(i18n.app_dir(), "settings.ini")
    cfg = configparser.ConfigParser()
    cfg.read(spath, encoding="utf-8")
    theme_key = cfg.get("ui", "theme", fallback=themes.DEFAULT)
    set_theme(theme_key)
    app.setFont(_mono_font(9, bold=False))   # JB Mono všude (design 1a–2a)
    app.setPalette(themes.build_palette(theme_key))
    app.setStyleSheet(themes.build_style(theme_key))
    lang = cfg.get("ui", "lang", fallback=None)
    if not lang:
        lang = _ask_language()
        if "ui" not in cfg:
            cfg["ui"] = {}
        cfg["ui"]["lang"] = lang
        with open(spath, "w", encoding="utf-8") as f:
            cfg.write(f)
    i18n.load(lang)
    ico = os.path.join(i18n.res_dir(), "icon.ico")
    if os.path.exists(ico):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(ico))
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
