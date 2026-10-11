# -*- coding: utf-8 -*-
"""WH3 Save Editor - GUI v0.2: sidebar navigation, dark theme."""
import os
import sys

from PySide6.QtCore import (Qt, QAbstractItemModel, QModelIndex, QThread,
                            Signal, QSize, QRect, QPoint)
from PySide6.QtGui import (QAction, QKeySequence, QColor, QBrush, QPalette,
                           QPixmap, QIcon, QPainter, QPen, QFont, QCursor)
from PySide6.QtWidgets import (QApplication, QMainWindow, QTreeView, QFrame,
                               QFileDialog, QMessageBox, QTableWidget,
                               QTableWidgetItem, QLabel, QProgressDialog,
                               QStyleFactory, QHeaderView, QComboBox,
                               QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QListWidgetItem, QStackedWidget,
                               QLineEdit, QFormLayout, QPushButton, QGroupBox,
                               QStyledItemDelegate, QDialog, QDialogButtonBox,
                               QScrollArea, QMenu, QInputDialog, QLayout,
                               QCheckBox)

from esf import (SaveFile, Record, RecordBlock, BlockEntry, Value, ValueArray,
                 UTF16, ASCII)
import tables
import i18n
import locdb
import packs
import themes
from i18n import t


# --- roster karet (záložka Armády) -----------------------------------------

class FlowLayout(QLayout):
    """Jednoduchý flow layout: položky se skládají zleva doprava a zalamují."""

    def __init__(self, parent=None, margin=8, spacing=8):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        x, y, line_h = rect.x() + m.left(), rect.y() + m.top(), 0
        right = rect.right() - m.right()
        for it in self._items:
            sz = it.sizeHint()
            if x + sz.width() > right and line_h > 0:
                x, y, line_h = rect.x() + m.left(), y + line_h + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sz))
            x += sz.width() + self._sp
            line_h = max(line_h, sz.height())
        return y + line_h + m.bottom() - rect.y()

    def clear(self):
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w is not None:
                w.hide()               # nejdřív skrýt — widget bez rodiče by se na okamžik ukázal jako okno
                w.setParent(None)
                w.deleteLater()


class PackWarmup(QThread):
    """Na pozadí připraví index herních packů a mapu karet, aby záložka Armády nekousala."""
    done = Signal(bool)

    def run(self):
        ok = False
        try:
            ok = bool(packs.warm_up())
        except Exception:  # noqa: BLE001
            ok = False
        self.done.emit(ok)


class RosterHost(QWidget):
    """Plocha s kartami: tažení v prázdném místě = výběrový obdélník jako v Průzkumníku."""
    band_start = Signal(QPoint, bool)     # lokální pozice, ctrl
    band_move = Signal(QPoint)
    band_end = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.band_start.emit(ev.position().toPoint(), bool(ev.modifiers() & Qt.ControlModifier))
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self.band_move.emit(ev.position().toPoint())
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.band_end.emit()
        super().mouseReleaseEvent(ev)


class UnitCard(QFrame):
    """Karta jednotky jako v herním panelu armády: ikona 60×130, proužek síly, hodnost.
    Levý klik → nabídka, Ctrl+klik → přepnout výběr, tažení → výběrový obdélník,
    pravý klik → nabídka pro výběr."""
    pressed = Signal(int, int)        # idx, ctrl (0/1)
    released = Signal(int, bool)      # idx, dragged
    drag_over = Signal(QPoint)        # globální pozice při tažení
    context = Signal(int)
    W, H = 74, 158

    def __init__(self, idx, pixmap, name, hp, hp_max, rank, is_char, parent=None):
        super().__init__(parent)
        self.idx, self.pix, self.name = idx, pixmap, name
        self.hp, self.hp_max, self.rank, self.is_char = hp, hp_max, rank, is_char
        self.selected = False
        self._press = None
        self._dragged = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("%s\n%s: %s / %s\n%s: %s" % (
            name, t("Síla"), hp, hp_max,
            t("Postava") if is_char else t("Rank"), "" if is_char else rank))

    def set_selected(self, on):
        if self.selected != bool(on):
            self.selected = bool(on)
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._press = ev.globalPosition().toPoint()
            self._dragged = False
            self.pressed.emit(self.idx, 1 if (ev.modifiers() & Qt.ControlModifier) else 0)
        elif ev.button() == Qt.RightButton:
            self.context.emit(self.idx)

    def mouseMoveEvent(self, ev):
        if self._press is not None and (ev.buttons() & Qt.LeftButton):
            gp = ev.globalPosition().toPoint()
            if self._dragged or (gp - self._press).manhattanLength() > 6:
                self._dragged = True
                self.drag_over.emit(gp)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.released.emit(self.idx, self._dragged)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        frac = (self.hp / self.hp_max) if self.hp_max else 1.0
        frac = max(0.0, min(1.0, frac))
        p.fillRect(self.rect(), QColor(THEME["panel"]))
        if self.selected:
            sel = QColor(THEME["acc"])
            sel.setAlpha(60)
            p.fillRect(self.rect(), sel)
        pen = QPen(QColor(THEME["acc"]) if (self.is_char or self.selected) else QColor(THEME["border"]),
                   3 if self.selected else (2 if self.is_char else 1))
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        icon = QRect(7, 7, 60, 130)
        if self.pix is not None and not self.pix.isNull():
            scaled = self.pix.scaled(icon.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(icon.x() + (icon.width() - scaled.width()) // 2,
                         icon.y() + (icon.height() - scaled.height()) // 2, scaled)
        else:
            p.fillRect(icon, QColor(THEME["input"]))
            f = QFont()
            f.setPointSize(7)
            p.setFont(f)
            p.setPen(QColor(THEME["muted"]))
            p.drawText(icon.adjusted(2, 2, -2, -2), Qt.AlignCenter | Qt.TextWordWrap, self.name)
        bar = QRect(7, 7, 60, 5)
        p.fillRect(bar, QColor(0, 0, 0, 170))
        col = QColor("#3fbf5f") if frac > 0.66 else QColor("#e0b020") if frac > 0.33 else QColor("#d9463e")
        p.fillRect(QRect(7, 7, int(60 * frac), 5), col)
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(THEME["text"]))
        label = "%d%%" % round(frac * 100)
        if not self.is_char:
            label += "   ★%d" % self.rank
        p.drawText(QRect(0, self.H - 20, self.W, 18), Qt.AlignCenter, label)
        p.end()


class AddCard(QFrame):
    """Karta „+" na konci rosteru: otevře dialog přidání jednotky."""
    clicked = Signal()

    def __init__(self, enabled=True, parent=None):
        super().__init__(parent)
        self.setFixedSize(UnitCard.W, UnitCard.H)
        self.setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)

    def mousePressEvent(self, ev):
        if self.isEnabled():
            self.clicked.emit()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(THEME["panel"]))
        pen = QPen(QColor(THEME["acc"] if self.isEnabled() else THEME["faint"]), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        f = QFont()
        f.setPointSize(26)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "+")
        p.end()

APP_VERSION = "1.3.0"

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
    found = Signal(str, str)     # tag + release notes nové verze

    def run(self):
        try:
            import json as _json
            from urllib.request import Request, urlopen
            req = Request(
                "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
                headers={"User-Agent": "WH3SaveEditor/" + APP_VERSION,
                         "Accept": "application/vnd.github+json"})
            with urlopen(req, timeout=5) as r:
                rel = _json.load(r)
            tag = rel.get("tag_name", "")
            if tag and _ver_key(tag) > _ver_key(APP_VERSION):
                self.found.emit(tag, rel.get("body") or "")
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
        self.fac_combo.setIconSize(QSize(20, 20))
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
        self.btn_changelog = QPushButton("☰  " + t("Historie verzí"))
        self.btn_changelog.setObjectName("sidebarBtn")
        self.btn_changelog.setCheckable(True)
        self.btn_changelog.setCursor(Qt.PointingHandCursor)
        self.btn_changelog.clicked.connect(self.open_changelog)
        sv.addWidget(self.btn_changelog)
        self.stack = QStackedWidget()
        self.sidebar.currentRowChanged.connect(self._nav_changed)

        self.stack.addWidget(self._page_overview())
        self.stack.addWidget(self._page_tables())
        self.stack.addWidget(self._page_diplo())
        self.stack.addWidget(self._placeholder("♜", t("Území a města"),
                                               t("Regiony, budovy a garnizony – v přípravě.")))
        self.stack.addWidget(self._page_raw())
        self.stack.addWidget(self._page_tools())
        self.CHANGELOG_PAGE = self.stack.addWidget(self._page_changelog())

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
        self._update_tag, self._update_body = None, ""
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

    def _update_available(self, tag, body=""):
        self._update_tag = tag
        self._update_body = body
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
        if getattr(self, "stack", None) is not None                 and self.stack.currentIndex() == self.CHANGELOG_PAGE:
            self._fill_changelog()

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
        self.fact_table.setIconSize(QSize(22, 22))
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
        self.unit_filter = QComboBox()
        self.unit_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.unit_filter.setMinimumWidth(240)
        self.unit_filter.currentIndexChanged.connect(lambda *_: self._refresh_units())
        # --- záložka Armády: seznam sil vlevo, roster karet vpravo ---
        self.army_kind = QComboBox()
        self.army_kind.addItems([t("Armády"), t("Konvoje a karavany"), t("Garnizony")])
        self.army_kind.currentIndexChanged.connect(lambda *_: self._refresh_army_list())
        self.army_list = QListWidget()
        self.army_list.setIconSize(QSize(30, 65))
        self.army_list.setFixedWidth(330)
        self.army_list.currentRowChanged.connect(lambda *_: self._refresh_roster())
        self.roster_host = RosterHost()
        self.roster_host.band_start.connect(lambda pos, ctrl: self._band_begin(pos, ctrl, None))
        self.roster_host.band_move.connect(self._band_update)
        self.roster_host.band_end.connect(self._band_end)
        from PySide6.QtWidgets import QRubberBand
        self.roster_band = QRubberBand(QRubberBand.Rectangle, self.roster_host)
        self._band_origin = None
        self._band_base = set()
        self.roster_flow = FlowLayout(self.roster_host, 10, 10)
        roster_scroll = QScrollArea()
        roster_scroll.setWidgetResizable(True)
        roster_scroll.setWidget(self.roster_host)
        roster_scroll.setFrameShape(QFrame.NoFrame)
        self.roster_title = QLabel("")
        self.roster_title.setObjectName("title")
        roster_hint = QLabel("ⓘ " + t("Klik na kartu = nabídka akcí, Ctrl+klik nebo tažení myší označí víc karet, karta „+“ přidá jednotku."))
        roster_hint.setObjectName("muted")
        roster_page = QWidget()
        rpv = QVBoxLayout(roster_page)
        rpv.setContentsMargins(0, 8, 0, 0)
        rpv.setSpacing(8)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.army_kind)
        kind_row.addStretch(1)
        rpv.addLayout(kind_row)
        rh = QHBoxLayout()
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addWidget(self.army_list)
        rv = QVBoxLayout()
        rv.addWidget(self.roster_title)
        rv.addWidget(roster_scroll, 1)
        rv.addWidget(roster_hint)
        rh.addLayout(rv, 1)
        rpv.addLayout(rh, 1)
        self._pix_cache = {}
        self._roster_fid = None
        self._roster_sel_ids = set()
        self._roster_cards = []
        self._packs_progress = None
        # --- stránky s vlastní lištou filtrů/tlačítek: lišta záložek se tak nikdy nehýbe ---
        self.btn_addunit = QPushButton("+ " + t("Přidat jednotku"))
        self.btn_addunit.clicked.connect(self._add_unit_dialog)
        self.btn_heal = QPushButton("✚ " + t("Uzdravit armádu"))
        self.btn_heal.clicked.connect(lambda: self._army_action("heal"))
        self.btn_maxrank = QPushButton("▲ " + t("Max rank armádě"))
        self.btn_maxrank.clicked.connect(lambda: self._army_action("rank"))
        self.btn_delunit = QPushButton("✕ " + t("Odebrat jednotku"))
        self.btn_delunit.setProperty("role", "danger")
        self.btn_delunit.clicked.connect(self._delete_unit)

        def page(toolbar_widgets, content):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 8, 0, 0)
            v.setSpacing(8)
            if toolbar_widgets:
                row = QHBoxLayout()
                for x in toolbar_widgets:
                    row.addWidget(x)
                row.addStretch(1)
                v.addLayout(row)
            v.addWidget(content, 1)
            return w

        tabs = QTabWidget()
        tabs.addTab(page([], self.fact_table), t("Frakce"))
        tabs.addTab(page([self.role_filter], self.char_table), t("Postavy"))
        tabs.addTab(page([self.unit_filter, self.btn_addunit, self.btn_heal,
                          self.btn_maxrank, self.btn_delunit], self.unit_table), t("Jednotky"))
        tabs.addTab(roster_page, t("Armády"))
        self.tables_tabs = tabs

        def on_tab(i):
            if i == 3:
                self._refresh_army_list()
        tabs.currentChanged.connect(on_tab)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(tabs)
        return box

    FLAG_LABELS = (("NON_AGGRESSION_PACT", "Pakt o neútočení"),
                   ("TRADE_RIGHTS", "Obchodní práva"),
                   ("SOFT_MILITARY_ACCESS", "Vojenský průchod"))

    def _page_diplo(self):
        from PySide6.QtWidgets import QRadioButton, QCheckBox, QButtonGroup
        self.diplo_table = self._make_table(["Frakce", "Klíč", "Postoj", "Vztah"],
                                            stretch=0)
        self.diplo_table.setIconSize(QSize(22, 22))
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
        g2 = SectionPanel(t("Oprava převedeného savu"))
        gv2 = g2.body
        desc2 = QLabel(t("Savy převedené verzí 1.2 až 1.2.2 mají u frakcí ostatních hráčů "
                         "zaseknutý příznak hráče: hra je po načtení zařadí mezi lidské hráče "
                         "a na konci tahu čeká na jejich tah, který nikdy nepřijde. Oprava "
                         "příznak přepne a frakce vrátí mezi AI. Funguje i na rozehraném savu."))
        desc2.setWordWrap(True)
        gv2.addWidget(desc2)
        self.btn_repair = QPushButton(t("Opravit načtený save"))
        self.btn_repair.setEnabled(False)
        self.btn_repair.clicked.connect(self._repair_converted)
        gv2.addWidget(self.btn_repair, alignment=Qt.AlignLeft)
        v.addWidget(g2)
        v.addStretch(1)
        return w

    def _check_converted_save(self):
        """Po načtení SP savu: nabídne opravu zaseknutého příznaku hráče (issue #1 u verzí 1.2.x)."""
        import convert_mp_sp as conv
        if self.save_file is None or self.save_file.is_multiplayer:
            return
        try:
            stale = conv.stale_human_factions(self.save_file)
        except Exception:  # noqa: BLE001
            return
        if not stale:
            return
        names = ", ".join("%s (%d)" % (locdb.faction(k) or k, i) for i, k in stale)
        ans = QMessageBox.question(
            self, t("Oprava převedeného savu"),
            t("Tento save má zaseknutý příznak hráče u frakce: %s.\n\nJe to pozůstatek převodu "
              "multiplayer → singleplayer starší verzí editoru — hra by se při konci tahu "
              "zasekla na tahu této frakce. Opravit teď? (Potom save ulož přes „Uložit jako…“.)") % names,
            QMessageBox.Yes | QMessageBox.No)
        if ans == QMessageBox.Yes:
            self._repair_converted()

    def _repair_converted(self):
        import convert_mp_sp as conv
        if self.save_file is None:
            return
        if self.save_file.is_multiplayer:
            QMessageBox.information(self, t("Nástroje"),
                                    t("Tohle je multiplayer save — oprava se týká jen převedených singleplayer savů."))
            return
        try:
            fixed, moved = conv.repair_converted(self.save_file)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), "%s: %s" % (type(e).__name__, e))
            return
        if not fixed and not moved:
            QMessageBox.information(self, t("Nástroje"), t("Save je v pořádku, nebylo co opravit."))
            return
        self.mark_modified()
        QMessageBox.information(
            self, t("Nástroje"),
            t("Opraveno. Frakce vrácené mezi AI: %s\n\nNezapomeň save uložit přes „Uložit jako…“.")
            % ", ".join("%s (%d)" % (locdb.faction(k) or k, i) for i, k in fixed) if fixed
            else t("Opraveno: skupiny tahu srovnané.\n\nNezapomeň save uložit přes „Uložit jako…“."))

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
        self.progress.setWindowTitle(t("Převod multiplayer → singleplayer"))
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
                    # některé výjimky mají prázdnou zprávu (StopIteration, AttributeError())
                    # -> bez názvu typu by se chyba tvářila jako úspěch (GitHub issue #2)
                    w_self.done.emit("", "%s: %s" % (type(e).__name__, e) if str(e)
                                     else type(e).__name__)

        self.worker = W()
        self.worker.done.connect(self._mp_to_sp_done)
        self.worker.start()

    def _mp_to_sp_done(self, out, err):
        self.progress.close()
        self.setEnabled(True)
        if err or not out:
            QMessageBox.critical(self, t("Chyba"), err or t("Převod selhal bez chybové zprávy."))
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
            for col, cell in enumerate(cells):
                val, node = cell[0], cell[1]
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, val)
                if len(cell) > 2 and cell[2] is not None:
                    it.setIcon(cell[2])          # např. vlajka frakce
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
        if hasattr(self, "btn_repair"):
            self.btn_repair.setEnabled(not self.save_file.is_multiplayer)
        self._check_converted_save()

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
            icon = self._flag_icon(key)
            if icon is not None:
                fl = QLabel()
                fl.setPixmap(icon.pixmap(24, 24))
                fl.setFixedWidth(28)
                h.addWidget(fl)
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

    def _flag_icon(self, key):
        """QIcon vlajky frakce (24 px) z herních packů, cache; None když chybí."""
        if not hasattr(self, "_flag_cache"):
            self._flag_cache = {}
        key = str(key)
        if key in self._flag_cache:
            return self._flag_cache[key]
        icon = None
        if packs.ready():
            try:
                png = packs.faction_flag(key, 24)
                if png:
                    pm = QPixmap()
                    if pm.loadFromData(png):
                        icon = QIcon(pm)
            except Exception:  # noqa: BLE001
                icon = None
        self._flag_cache[key] = icon
        return icon

    def populate_factions(self):
        facs = tables.factions(self.save_file)
        if not packs.ready():
            packs.build_index()          # vlajky do tabulek (index je rychlý, ~1 s)
        self._fill_table(self.fact_table, [
            [(f["index"], None), (tables.pretty_faction(f["key"]), None, self._flag_icon(f["key"])),
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
            icon = self._flag_icon(key)
            if icon is not None:
                self.fac_combo.addItem(icon, "%s   (%s)" % (label, key), key)
            else:
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
        self._world_templates = None
        if getattr(self, "tables_tabs", None) is not None and self.tables_tabs.currentIndex() == 3:
            self._refresh_army_list()
        dip = tables.diplomacy(self.save_file, key)
        self._stance_partners = {}
        self._dip_by_key = {d["target_key"]: d for d in dip}
        self._dip_sel = None
        rows = []
        for d in dip:
            rows.append([(tables.pretty_faction(d["target_key"]), None, self._flag_icon(d["target_key"])),
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
                if tables.is_character_unit(u):
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
        if tables.is_character_unit(u):
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
        try:
            tables.remove_unit(self.save_file, u)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), "%s: %s" % (type(e).__name__, e))
            return
        self.mark_modified()
        self._last_key = None
        self.faction_selected()

    ARMY_UNIT_LIMIT = 20            # hra neumí víc jednotek v armádě (vč. lorda)

    # -- záložka Armády (roster karet) ---------------------------------------

    def _pixmap_for(self, key, is_char=False):
        """QPixmap ikony/portrétu jednotky z herních packů (cache; None když chybí)."""
        key = str(key)
        if key in self._pix_cache:
            return self._pix_cache[key]
        if not packs.ready():
            return None                 # index se teprve připravuje na pozadí
        pm = None
        try:
            if key == "__placeholder__":
                png = packs.placeholder()
            else:
                png = packs.character_portrait_for_unit(key) if is_char else None
            if png is None:
                png = packs.unit_icon(key)
            if png:
                pm = QPixmap()
                if not pm.loadFromData(png):
                    pm = None
        except Exception:  # noqa: BLE001
            pm = None
        if pm is None and is_char:
            pm = self._generic_leader_pixmap()
        self._pix_cache[key] = pm
        return pm

    def _generic_leader_pixmap(self):
        """Náhradní karta lorda bez artu: tmavá karta s vlajkou vybrané frakce (ať nebije do očí)."""
        key = "__generic__" + str(getattr(self, "_last_key", "") or "")
        if key in self._pix_cache:
            return self._pix_cache[key]
        pm = QPixmap(60, 130)
        pm.fill(QColor(THEME["input"]))
        p = QPainter(pm)
        p.setPen(QPen(QColor(THEME["border"]), 1))
        p.drawRect(0, 0, 59, 129)
        flag = None
        try:
            png = packs.faction_flag(self._last_key, 64) if self._last_key else None
            if png:
                flag = QPixmap()
                if not flag.loadFromData(png):
                    flag = None
        except Exception:  # noqa: BLE001
            flag = None
        if flag is not None:
            f = flag.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.setOpacity(0.85)
            p.drawPixmap((60 - f.width()) // 2, (130 - f.height()) // 2, f)
        p.end()
        self._pix_cache[key] = pm
        return pm

    def _leader_icon(self, unit_key):
        """Malá čtvercová ikona lorda (výřez obličeje z karty 60×130) pro rozbalováky."""
        if not hasattr(self, "_leader_cache"):
            self._leader_cache = {}
        key = str(unit_key)
        if key in self._leader_cache:
            return self._leader_cache[key]
        icon = None
        pm = self._pixmap_for(key, is_char=True) if key else None
        if pm is not None and not pm.isNull():
            side = min(pm.width(), pm.height())
            icon = QIcon(pm.copy(QRect(0, 6 if pm.height() > side + 6 else 0, side, side)))
        self._leader_cache[key] = icon
        return icon

    def _force_entries(self, kinds=None):
        """[(force_id, popisek, klíč jednotky velitele)] sil vybrané frakce; `kinds` = podle
        filtru druhu na záložce Armády (None = všechny druhy)."""
        if self.save_file is None or not hasattr(self, "_units"):
            return []
        want = kinds or {0: ("army",), 1: ("caravan",), 2: ("garrison",)}[self.army_kind.currentIndex()]
        ftypes = tables.forces(self.save_file, self._last_key) if self._last_key else {}
        commander_key = {}
        for u in self._units:
            if u["commander"] and u["force_id"] not in commander_key:
                commander_key[u["force_id"]] = u["unit_key"]
        counts = {}
        for u in self._units:
            counts[u["force_id"]] = counts.get(u["force_id"], 0) + 1
        out, seen = [], set()
        for c in self._chars:
            fid = c.get("force_id")
            if not c["active"] or not fid or fid in seen or fid not in counts:
                continue
            kind = c["kind"]
            if ftypes.get(fid, {}).get("type") == "CONVOY" or kind == "caravan":
                kind = "caravan"
            if kind not in want:
                continue
            seen.add(fid)
            label = self._unit_labels.get(fid, t("Armáda %d") % fid)
            if c["name"]:
                label = "%s – %s" % (label.split(" – ")[0], c["name"])
            out.append((fid, "%s  (%d/%d)" % (label, counts[fid], self.ARMY_UNIT_LIMIT),
                        commander_key.get(fid)))
        return out

    def _start_pack_warmup(self):
        """Spustí přípravu indexu packů na pozadí (jednou za běh aplikace)."""
        if getattr(self, "_warmup", None) is not None or packs.ready():
            return
        self._warmup = PackWarmup(self)
        self._warmup.done.connect(self._pack_warmup_done)
        self._warmup.start()

    def _pack_warmup_done(self, ok):
        if self._packs_progress is not None:
            self._packs_progress.close()
            self._packs_progress = None
        if getattr(self, "tables_tabs", None) is not None and self.tables_tabs.currentIndex() == 3:
            self._refresh_army_list()

    def _packs_ready_or_wait(self):
        """True, když jsou ikony k dispozici; jinak ukáže průběh a vrátí False (překreslí se po dokončení)."""
        if packs.ready() and packs._card_map is not None:
            return True
        self._start_pack_warmup()
        if self._packs_progress is None:
            dlg = QProgressDialog(t("Načítám ikony jednotek z herních packů…"), None, 0, 0, self)
            dlg.setWindowTitle(t("Armády"))
            dlg.setWindowModality(Qt.NonModal)
            dlg.setMinimumDuration(0)
            dlg.setCancelButton(None)
            dlg.show()
            self._packs_progress = dlg
        return False

    def _refresh_army_list(self):
        if self.save_file is None or not hasattr(self, "_units"):
            self.army_list.clear()
            self.roster_flow.clear()
            return
        if not self._packs_ready_or_wait():
            return
        keep = self._roster_fid
        self.army_list.blockSignals(True)
        self.army_list.clear()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for fid, label, ckey in self._force_entries():
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, fid)
                pm = self._pixmap_for(ckey, is_char=True) if ckey else None
                if pm is None:
                    pm = self._pixmap_for("__placeholder__")
                if pm is not None:
                    it.setIcon(QIcon(pm))
                self.army_list.addItem(it)
        finally:
            QApplication.restoreOverrideCursor()
        self.army_list.blockSignals(False)
        row = 0
        for i in range(self.army_list.count()):
            if self.army_list.item(i).data(Qt.UserRole) == keep:
                row = i
                break
        if self.army_list.count():
            self.army_list.setCurrentRow(row)
        self._refresh_roster()

    def _refresh_roster(self):
        self.roster_flow.clear()
        it = self.army_list.currentItem()
        if it is None or self.save_file is None:
            self.roster_title.setText("")
            self._roster_fid = None
            return
        fid = it.data(Qt.UserRole)
        if fid != self._roster_fid:
            self._roster_sel_ids = set()
        self._roster_fid = fid
        rows = [(i, u) for i, u in enumerate(self._units) if u["force_id"] == fid]
        self._roster_cards = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, u in rows:
                is_char = tables.is_character_unit(u)
                card = UnitCard(i, self._pixmap_for(u["unit_key"], is_char),
                                tables.pretty_unit(u["unit_key"]),
                                u["hp"].value if u["hp"] else 0,
                                u["hp_max"].value if u["hp_max"] else 0,
                                u["rank"].value if u["rank"] else 0, is_char)
                card.set_selected(u["unit_id"] in self._roster_sel_ids)
                card.pressed.connect(self._card_pressed)
                card.released.connect(self._card_released)
                card.drag_over.connect(self._card_drag_over)
                card.context.connect(self._card_context)
                self._roster_cards.append(card)
                self.roster_flow.addWidget(card)
        finally:
            QApplication.restoreOverrideCursor()
        self._roster_sel_ids &= {u["unit_id"] for _, u in rows}
        full = len(rows) >= self.ARMY_UNIT_LIMIT
        add = AddCard(enabled=not full)
        add.setToolTip(t("Armáda už má %d jednotek, víc hra neumí.") % self.ARMY_UNIT_LIMIT
                       if full else t("Přidat jednotku do této armády"))
        add.clicked.connect(lambda: self._add_unit_dialog(force_id=fid))
        self.roster_flow.addWidget(add)
        self.roster_title.setText(it.text())

    # -- výběr karet -----------------------------------------------------------

    def _exec_menu(self, menu):
        """Otevře kontextovou nabídku u kurzoru (testy tuhle metodu nahrazují)."""
        return menu.exec(QCursor.pos())

    def _selected_cards(self):
        return [c for c in self._roster_cards if c.selected]

    def _set_card_selected(self, card, on):
        card.set_selected(on)
        uid = self._units[card.idx]["unit_id"]
        if on:
            self._roster_sel_ids.add(uid)
        else:
            self._roster_sel_ids.discard(uid)

    def _roster_clear_selection(self):
        for c in self._roster_cards:
            c.set_selected(False)
        self._roster_sel_ids = set()

    def _card_by_idx(self, idx):
        return next((c for c in self._roster_cards if c.idx == idx), None)

    # výběrový obdélník (jako v Průzkumníku): bez Ctrl = výběr jen to, co je v rámečku,
    # s Ctrl = původní výběr + rámeček
    def _band_begin(self, local_pos, ctrl, origin_card):
        if not ctrl:
            self._roster_clear_selection()
        self._band_base = set(self._roster_sel_ids)
        if origin_card is not None:
            self._set_card_selected(origin_card, True if not ctrl else not origin_card.selected)
            self._band_base = set(self._roster_sel_ids)
        self._band_origin = local_pos
        self.roster_band.setGeometry(QRect(local_pos, QSize()))
        self.roster_band.hide()

    def _band_update(self, local_pos):
        if self._band_origin is None:
            return
        rect = QRect(self._band_origin, local_pos).normalized()
        self.roster_band.setGeometry(rect)
        if rect.width() > 3 or rect.height() > 3:
            self.roster_band.show()
        for c in self._roster_cards:
            uid = self._units[c.idx]["unit_id"]
            inside = c.geometry().intersects(rect)
            self._set_card_selected(c, inside or uid in self._band_base)

    def _band_end(self):
        self._band_origin = None
        self.roster_band.hide()

    def _card_pressed(self, idx, ctrl):
        card = self._card_by_idx(idx)
        if card is None:
            return
        self._ctrl_press = bool(ctrl)
        if not ctrl and card.selected and len(self._selected_cards()) > 1:
            # klik na už označenou skupinu: nechat výběr (na uvolnění přijde nabídka)
            self._band_origin = None
            return
        local = self.roster_host.mapFromGlobal(QCursor.pos())
        self._band_begin(local, bool(ctrl), card)

    def _card_drag_over(self, gpos):
        self._band_update(self.roster_host.mapFromGlobal(gpos))

    def _card_released(self, idx, dragged):
        self._band_end()
        if getattr(self, "_ctrl_press", False):
            self._ctrl_press = False
            return                      # Ctrl+klik jen přepíná výběr
        if dragged:
            return                      # tažení = jen výběr, nabídka až na klik
        self._open_card_menu(idx)

    def _card_context(self, idx):
        card = self._card_by_idx(idx)
        if card is not None and not card.selected:
            self._roster_clear_selection()
            self._set_card_selected(card, True)
        self._open_card_menu(idx)

    def _open_card_menu(self, idx):
        sel = self._selected_cards()
        if len(sel) > 1:
            self._multi_menu([c.idx for c in sel])
        else:
            self._card_menu(idx)

    def _multi_menu(self, idxs):
        n = len(idxs)
        regular = [i for i in idxs if not tables.is_character_unit(self._units[i])]
        m = QMenu(self)
        a_heal = m.addAction("✚ " + t("Uzdravit označené (%d)") % n)
        a_rank = m.addAction("★ " + t("Nastavit hodnost označeným…"))
        a_max = m.addAction("▲ " + t("Max hodnost označených (%d)") % len(regular))
        m.addSeparator()
        a_del = m.addAction("✕ " + t("Odebrat označené (%d)") % len(regular))
        m.addSeparator()
        a_clear = m.addAction(t("Zrušit výběr"))
        for a in (a_rank, a_max, a_del):
            a.setEnabled(bool(regular))
        act = self._exec_menu(m)
        if act is None:
            return
        if act == a_clear:
            self._roster_clear_selection()
            return
        changed = 0
        try:
            if act == a_heal:
                for i in idxs:
                    u = self._units[i]
                    if u["hp"] and u["hp_max"] and u["hp"].value != u["hp_max"].value:
                        u["hp"].value = u["hp_max"].value
                        changed += 1
            elif act in (a_rank, a_max):
                val = 9
                if act == a_rank:
                    val, ok = QInputDialog.getInt(self, t("Nastavit hodnost"), t("Hodnost (0–9):"), 9, 0, 9)
                    if not ok:
                        return
                for i in regular:
                    u = self._units[i]
                    if u["rank"] and u["rank"].value != val:
                        tables.set_unit_rank(u, val)
                        changed += 1
            elif act == a_del:
                if QMessageBox.question(
                        self, t("Odebrat jednotku"),
                        t("Opravdu odebrat %d označených jednotek z armády?\n(Experimentální "
                          "funkce — měj zálohu savu.)") % len(regular)) != QMessageBox.Yes:
                    return
                for i in regular:
                    tables.remove_unit(self.save_file, self._units[i])
                    changed += 1
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), "%s: %s" % (type(e).__name__, e))
        if changed:
            self.mark_modified()
            self._last_key = None
            self.faction_selected()
            self._refresh_army_list()
            self.statusBar().showMessage(t("Upraveno jednotek: %d") % changed)

    def _card_menu(self, idx):
        if self.save_file is None or idx >= len(self._units):
            return
        u = self._units[idx]
        is_char = tables.is_character_unit(u)
        m = QMenu(self)
        a_heal = m.addAction("✚ " + t("Uzdravit"))
        a_rank = a_max = a_dup = a_del = None
        if not is_char:
            a_rank = m.addAction("★ " + t("Nastavit hodnost…"))
            a_max = m.addAction("▲ " + t("Max hodnost"))
            a_dup = m.addAction("⧉ " + t("Duplikovat"))
            m.addSeparator()
            a_del = m.addAction("✕ " + t("Odebrat"))
        act = self._exec_menu(m)
        if act is None:
            return
        changed = False
        try:
            if act == a_heal:
                if u["hp"] and u["hp_max"] and u["hp"].value != u["hp_max"].value:
                    u["hp"].value = u["hp_max"].value
                    changed = True
            elif act == a_rank:
                val, ok = QInputDialog.getInt(self, t("Nastavit hodnost"), t("Hodnost (0–9):"),
                                              u["rank"].value if u["rank"] else 0, 0, 9)
                if ok and u["rank"] and u["rank"].value != val:
                    tables.set_unit_rank(u, val)
                    changed = True
            elif act == a_max:
                if u["rank"] and u["rank"].value != 9:
                    tables.set_unit_rank(u, 9)
                    changed = True
            elif act == a_dup:
                self._add_units(u["force_id"], u, 1, heal=False, fresh=False)
                return
            elif act == a_del:
                if QMessageBox.question(
                        self, t("Odebrat jednotku"),
                        t("Opravdu odebrat jednotku %s z armády?\n(Experimentální "
                          "funkce — měj zálohu savu.)") % tables.pretty_unit(u["unit_key"])) \
                        != QMessageBox.Yes:
                    return
                tables.remove_unit(self.save_file, u)
                changed = True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), "%s: %s" % (type(e).__name__, e))
            return
        if changed:
            self.mark_modified()
            self._last_key = None
            self.faction_selected()
            self._refresh_army_list()

    def _add_unit_dialog(self, force_id=None):
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QCheckBox
        if isinstance(force_id, bool) or not isinstance(force_id, int):
            force_id = None
        if self.save_file is None or not getattr(self, "_units", None):
            return
        counts = {}
        for u in self._units:
            counts[u["force_id"]] = counts.get(u["force_id"], 0) + 1
        armies = sorted(((fid, lbl) for fid, lbl in self._unit_labels.items() if fid in counts),
                        key=lambda kv: kv[1])
        templates = {}
        for u in self._units:
            if not tables.is_character_unit(u):
                templates.setdefault(u["unit_key"], u)
        if not armies or not templates:
            QMessageBox.information(self, t("Jednotky"),
                                    t("Frakce nemá žádnou armádu s řadovou jednotkou, "
                                      "kterou by šlo použít jako vzor."))
            return
        # předvolba armády: karta „+" / vybraný řádek / filtr armády
        pre_fid = force_id
        row = self.unit_table.currentRow()
        if pre_fid is None and row >= 0 and self.unit_table.item(row, 0) is not None:
            tag = self.unit_table.item(row, 0).data(Qt.UserRole + 1)
            if tag is not None:
                pre_fid = self._units[tag]["force_id"]
        if pre_fid is None and self.unit_filter.currentIndex() > 0:
            pre_fid = next((fid for fid, lbl in armies
                            if lbl == self.unit_filter.currentText()), None)

        dlg = QDialog(self)
        dlg.setWindowTitle(t("Přidat jednotku"))
        form = QFormLayout(dlg)
        army_cb = QComboBox()
        army_cb.setIconSize(QSize(22, 22))
        named = {fid: (label, ckey) for fid, label, ckey
                 in self._force_entries(kinds=("army", "caravan", "garrison"))}
        for fid, lbl in armies:
            label, ckey = named.get(fid, ("%s  (%d/%d)" % (lbl, counts.get(fid, 0), self.ARMY_UNIT_LIMIT), None))
            icon = self._leader_icon(ckey) if ckey else None
            if icon is not None:
                army_cb.addItem(icon, label, fid)
            else:
                army_cb.addItem(label, fid)
        if pre_fid is not None and army_cb.findData(pre_fid) >= 0:
            army_cb.setCurrentIndex(army_cb.findData(pre_fid))
        # vzorová jednotka: vyhledávací pole + seznam s kartami (filtr podle názvu i klíče)
        search = QLineEdit()
        search.setPlaceholderText(t("Hledat jednotku… (název nebo klíč)"))
        search.setClearButtonEnabled(True)
        tmpl_list = QListWidget()
        tmpl_list.setIconSize(QSize(30, 65))
        tmpl_list.setMinimumSize(560, 300)
        tmpl_list.setUniformItemSizes(True)
        world_cb = QCheckBox(t("Nabídnout i jednotky ostatních frakcí (vzor odkudkoli ze světa)"))
        own_keys = set(templates)
        lbl_count = QLabel("")
        lbl_count.setObjectName("muted")

        def fold(s):
            import unicodedata
            return "".join(c for c in unicodedata.normalize("NFKD", str(s).lower())
                           if not unicodedata.combining(c))

        def fill_templates(*_):
            cur_it = tmpl_list.currentItem()
            cur = cur_it.data(Qt.UserRole) if cur_it is not None else None
            tmpl_list.clear()
            pool = dict(templates)
            if world_cb.isChecked():
                if self._world_templates is None:
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                    try:
                        self._world_templates = tables.world_unit_templates(self.save_file)
                    finally:
                        QApplication.restoreOverrideCursor()
                for k, r in self._world_templates.items():
                    pool.setdefault(k, r)
            templates.update(pool)
            words = fold(search.text()).split()
            own = sorted(own_keys, key=lambda k: tables.pretty_unit(k).lower())
            others = sorted((k for k in pool if k not in own_keys),
                            key=lambda k: tables.pretty_unit(k).lower())
            shown = 0
            for group, foreign in ((own, False), (others, True)):
                for key in group:
                    name = tables.pretty_unit(key)
                    hay = fold(name) + " " + fold(key)
                    if words and not all(w in hay for w in words):
                        continue
                    label = "%s\n%s" % (name, key)
                    if foreign:
                        label += "   " + t("(jiná frakce)")
                    pm = self._pixmap_for(key)
                    it = QListWidgetItem(QIcon(pm), label) if pm is not None else QListWidgetItem(label)
                    it.setData(Qt.UserRole, key)
                    tmpl_list.addItem(it)
                    shown += 1
                    if key == cur:
                        tmpl_list.setCurrentItem(it)
            if tmpl_list.currentItem() is None and tmpl_list.count():
                tmpl_list.setCurrentRow(0)
            lbl_count.setText(t("Zobrazeno jednotek: %d z %d") % (shown, len(pool)))
            update_ok()

        def update_ok(*_):
            free = max(0, self.ARMY_UNIT_LIMIT - counts.get(army_cb.currentData(), 0))
            b_ok.setEnabled(free > 0 and tmpl_list.currentItem() is not None)
        world_cb.toggled.connect(fill_templates)
        search.textChanged.connect(fill_templates)
        tmpl_list.currentItemChanged.connect(update_ok)
        count = QSpinBox()
        count.setRange(1, self.ARMY_UNIT_LIMIT)
        heal = QCheckBox(t("Plná síla"))
        heal.setChecked(True)
        rank_cb = QComboBox()
        for r in range(10):
            rank_cb.addItem("★ %d" % r if r else t("0 (nová jednotka, 0 XP)"), r)
        rank_cb.addItem(t("jako vzorová jednotka (zkopírovat hodnost i XP)"), -1)
        hint = QLabel(t("Nová jednotka je kopie vzorové jednotky s novým id. "
                        "Experimentální funkce — měj zálohu savu.") + " " +
                      t("Vzorová jednotka musí v savu už někde existovat — jinak hra nemá odkud vzít její data."))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(t("Armáda:"), army_cb)
        form.addRow(t("Vzorová jednotka:"), search)
        form.addRow("", tmpl_list)
        form.addRow("", lbl_count)
        form.addRow("", world_cb)
        form.addRow(t("Počet:"), count)
        form.addRow(t("Hodnost:"), rank_cb)
        form.addRow("", heal)
        form.addRow(hint)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_cancel = QPushButton(t("Zrušit"))
        b_ok = QPushButton(t("Přidat"))
        b_ok.setProperty("role", "primary")
        b_ok.setDefault(True)
        b_cancel.clicked.connect(dlg.reject)
        b_ok.clicked.connect(dlg.accept)
        tmpl_list.itemDoubleClicked.connect(lambda *_: b_ok.isEnabled() and dlg.accept())
        btn_row.addWidget(b_cancel)
        btn_row.addWidget(b_ok)
        form.addRow(btn_row)

        def update_limit(*_):
            free = max(0, self.ARMY_UNIT_LIMIT - counts.get(army_cb.currentData(), 0))
            count.setMaximum(max(free, 1))
            count.setEnabled(free > 0)
            b_ok.setToolTip("" if free else t("Armáda už má %d jednotek, víc hra neumí.")
                            % self.ARMY_UNIT_LIMIT)
            update_ok()
        army_cb.currentIndexChanged.connect(update_limit)
        fill_templates()
        update_limit()
        search.setFocus()
        if dlg.exec() != QDialog.Accepted or tmpl_list.currentItem() is None:
            return
        rank = rank_cb.currentData()
        self._add_units(army_cb.currentData(), templates[tmpl_list.currentItem().data(Qt.UserRole)],
                        count.value(), heal.isChecked(), fresh=(rank >= 0),
                        rank=(rank if rank > 0 else None))

    def _add_units(self, force_id, template_row, count, heal=True, fresh=True, rank=None):
        added = 0
        try:
            for _ in range(count):
                tables.add_unit(self.save_file, template_row, force_id=force_id,
                                heal=heal, fresh=fresh, rank=rank)
                added += 1
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, t("Chyba"), "%s: %s" % (type(e).__name__, e))
        if added:
            for _ in range(added):
                self.mark_modified()
            self._last_key = None
            self.faction_selected()
            self.statusBar().showMessage(t("Přidáno jednotek: %d") % added)
        return added

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

    def _nav_changed(self, row):
        if row < 0:
            return                      # odznačení sidebaru (stránka Changelog)
        self.btn_changelog.setChecked(False)
        self.stack.setCurrentIndex(row)

    def open_changelog(self):
        self._fill_changelog()
        self.sidebar.setCurrentRow(-1)
        self.btn_changelog.setChecked(True)
        self.stack.setCurrentIndex(self.CHANGELOG_PAGE)

    def _page_changelog(self):
        from PySide6.QtWidgets import QTextBrowser
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 22, 28, 22)
        title = QLabel(t("Historie verzí"))
        title.setObjectName("title")
        v.addWidget(title)
        self.changelog_view = QTextBrowser()
        self.changelog_view.setOpenExternalLinks(True)
        v.addWidget(self.changelog_view, 1)
        self.changelog_link = QLabel()
        self.changelog_link.setTextFormat(Qt.RichText)
        self.changelog_link.setOpenExternalLinks(True)
        v.addWidget(self.changelog_link)
        return w

    def _fill_changelog(self):
        """Přibalený CHANGELOG.md + (je-li k dispozici) notes novější verze."""
        md = ""
        if self._update_tag and self._update_body:
            md += ("**▲ %s — %s**\n\n%s\n\n---\n\n"
                   % (t("Dostupná aktualizace"), self._update_tag,
                      self._update_body))
        try:
            with open(os.path.join(i18n.res_dir(), "CHANGELOG.md"),
                      encoding="utf-8") as f:
                md += f.read()
        except OSError:
            md += t("Changelog není k dispozici.")
        self.changelog_view.setMarkdown(md)
        self.changelog_link.setText(
            '<a style="color:%s" href="https://github.com/%s/releases">%s</a>'
            % (THEME["link"], GITHUB_REPO, t("Všechny verze na GitHubu")))

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
        self.progress.setWindowTitle(t("Uložit jako"))
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
    app.setApplicationName("WH3 Save Editor")      # titulek dialogů bez vlastního názvu (jinak "python")
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
    w._start_pack_warmup()          # ikony karet se připraví na pozadí, záložka Armády pak nekouše
    if len(sys.argv) > 1:
        w.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
