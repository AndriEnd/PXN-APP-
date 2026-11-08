"""Generic editor for any INI document: Group -> [SECTION:SUB] -> KEY = value.

Every key of the file is editable (that is how "all parameters of the shader preset" can be
configured); values that hold a base64-encoded nested INI (``POSTPROCESSING_SCRIPT_SETTINGS`` ...)
open in a nested editor.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
)

from ...ini.document import Entry, IniDocument, decode_embedded, encode_embedded, infer_type
from ...ini.schema import GROUP
from .. import theme
from .common import StyledDialog, button, label

ROLE_ENTRY = Qt.UserRole + 1
ROLE_SECTION = Qt.UserRole + 2
ROLE_KIND = Qt.UserRole + 3

TYPE_COLORS = {
    "bool": theme.BLUE, "int": theme.GREEN, "float": theme.GREEN, "embedded": theme.AMBER,
    "text": theme.TEXT_DIM, "empty": theme.TEXT_MUTED,
}


class _ValueOnlyDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index: QModelIndex):  # noqa: N802
        if index.column() != 1 or index.data(ROLE_KIND) != "key":
            return None
        editor = QLineEdit(parent)
        return editor


class IniTreeWidget(QTreeWidget):
    edited = Signal()
    keySelected = Signal(str, str)  # section, key (for "bind this key")
    bindRequested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc: IniDocument | None = None
        self._entries: dict[int, tuple] = {}
        self._bound: dict = {}  # (section.lower(), key.lower()) -> target label
        self._loading = False
        self.setColumnCount(4)
        self.setHeaderLabels(["Parameter", "Nilai", "Tipe", "Ke setir"])
        self.setAlternatingRowColors(False)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setItemDelegate(_ValueOnlyDelegate(self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemChanged.connect(self._item_changed)
        self.currentItemChanged.connect(self._current_changed)
        self.itemActivated.connect(self._activated)
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, h.ResizeMode.Interactive)
        h.setSectionResizeMode(1, h.ResizeMode.Stretch)
        h.setSectionResizeMode(2, h.ResizeMode.Fixed)
        h.setSectionResizeMode(3, h.ResizeMode.Interactive)
        self.setColumnWidth(0, 300)
        self.setColumnWidth(2, 84)
        self.setColumnWidth(3, 130)

    # ----------------------------------------------------------------- model
    def set_document(self, doc: IniDocument | None, bound: dict | None = None) -> None:
        self.doc = doc
        self._bound = bound or {}
        self.rebuild()

    def set_bound(self, bound: dict) -> None:
        self._bound = bound
        self.rebuild()

    def rebuild(self) -> None:
        expanded = self._expanded_paths()
        self._loading = True
        self.clear()
        self._entries.clear()
        if self.doc is not None:
            groups: dict[str, QTreeWidgetItem] = {}
            for sec in self.doc.sections:
                prefix, _, sub = sec.name.partition(":")
                g = groups.get(prefix)
                if g is None:
                    g = self._node(prefix or "(global)", is_group=True)
                    g.setData(0, ROLE_SECTION, prefix)
                    groups[prefix] = g
                    self.addTopLevelItem(g)
                parent = g
                if sub:
                    parent = self._node(sub, is_group=False)
                    parent.setData(0, ROLE_SECTION, sec.name)
                    g.addChild(parent)
                for entry in sec.items():
                    parent.addChild(self._key_item(sec.name, entry))
            for g in groups.values():
                total = sum(1 for _ in self._iter_keys(g))
                g.setText(1, f"{total} key")
                for i in range(g.childCount()):
                    c = g.child(i)
                    if c.data(0, ROLE_KIND) == "section":
                        c.setText(1, f"{c.childCount()} key")
        self._loading = False
        self._restore_expanded(expanded)

    def _iter_keys(self, item: QTreeWidgetItem):
        for i in range(item.childCount()):
            c = item.child(i)
            if c.data(0, ROLE_KIND) == "key":
                yield c
            else:
                yield from self._iter_keys(c)

    def _node(self, text: str, is_group: bool) -> QTreeWidgetItem:
        it = QTreeWidgetItem([text])
        it.setData(0, ROLE_KIND, "group" if is_group else "section")
        f = QFont(self.font())
        f.setBold(True)
        it.setFont(0, f)
        it.setForeground(0, QBrush(QColor(theme.ACCENT_2 if text.upper().startswith(GROUP) else theme.TEXT)))
        it.setForeground(1, QBrush(QColor(theme.TEXT_MUTED)))
        return it

    def _key_item(self, section: str, entry: Entry) -> QTreeWidgetItem:
        t = infer_type(entry.value)
        it = QTreeWidgetItem([entry.key, entry.value, t if t != "empty" else "—", ""])
        it.setData(0, ROLE_KIND, "key")
        it.setData(0, ROLE_ENTRY, id(entry))
        it.setData(0, ROLE_SECTION, section)
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        self._entries[id(entry)] = (section, entry)
        it.setForeground(2, QBrush(QColor(TYPE_COLORS.get(t, theme.TEXT_DIM))))
        native = section.upper().startswith(GROUP + ":")
        if native:
            it.setForeground(0, QBrush(QColor(theme.ACCENT_2)))
        bound = self._bound.get((section.lower(), entry.key.lower()))
        if bound:
            it.setText(3, f"→ {bound}")
            it.setForeground(3, QBrush(QColor(theme.GREEN)))
        elif native:
            it.setText(3, "native")
            it.setForeground(3, QBrush(QColor(theme.ACCENT_2)))
        if t == "embedded":
            it.setToolTip(1, "Berisi INI bersarang (base64). Klik ganda untuk mengedit isinya.")
        return it

    # --------------------------------------------------------------- editing
    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 1 or item.data(0, ROLE_KIND) != "key":
            return
        _section, entry = self._entries.get(item.data(0, ROLE_ENTRY), (None, None))
        if entry is None:
            return
        entry.value = item.text(1).strip()
        t = infer_type(entry.value)
        self._loading = True
        item.setText(2, t if t != "empty" else "—")
        item.setForeground(2, QBrush(QColor(TYPE_COLORS.get(t, theme.TEXT_DIM))))
        self._loading = False
        self.edited.emit()

    def _activated(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, ROLE_KIND) == "key" and item.text(2) == "embedded":
            self.edit_embedded(item)

    def edit_embedded(self, item: QTreeWidgetItem) -> None:
        _section, entry = self._entries[item.data(0, ROLE_ENTRY)]
        nested = decode_embedded(entry.value)
        if nested is None:
            return
        dlg = StyledDialog(self.window(), f"Isi bersarang — {entry.key}", width=640)
        dlg.resize(680, 520)
        tree = IniTreeWidget()
        tree.set_document(nested)
        dlg.root.addWidget(label("Nilai ini adalah file INI yang disandikan base64. Ubah isinya di sini; "
                                 "saat disimpan akan disandikan ulang.", "dim", wrap=True))
        dlg.root.addWidget(tree, 1)
        b_cancel, b_ok = button("Batal", "ghost"), button("Terapkan", "primary")
        b_cancel.clicked.connect(dlg.reject)
        b_ok.clicked.connect(dlg.accept)
        dlg.buttons.addWidget(b_cancel)
        dlg.buttons.addWidget(b_ok)
        dlg.finish()
        tree.expandAll()
        if dlg.exec() == QDialog.Accepted:
            entry.value = encode_embedded(nested, like=entry.value)
            item.setText(1, entry.value)
            self.edited.emit()

    def _current_changed(self, cur: QTreeWidgetItem | None, _prev) -> None:
        if cur is not None and cur.data(0, ROLE_KIND) == "key":
            self.keySelected.emit(cur.data(0, ROLE_SECTION), cur.text(0))

    def current_key(self) -> tuple | None:
        it = self.currentItem()
        if it is not None and it.data(0, ROLE_KIND) == "key":
            return it.data(0, ROLE_SECTION), it.text(0)
        return None

    # ------------------------------------------------------------- operations
    def add_key(self, section: str, key: str, value: str) -> None:
        if self.doc is None:
            return
        self.doc.set(section, key, value)
        self.rebuild()
        self.edited.emit()

    def delete_current(self) -> None:
        it = self.currentItem()
        if it is None or self.doc is None:
            return
        kind = it.data(0, ROLE_KIND)
        if kind == "key":
            sec = self.doc.section(it.data(0, ROLE_SECTION))
            _s, entry = self._entries[it.data(0, ROLE_ENTRY)]
            sec.entries = [e for e in sec.entries if e is not entry]
        elif kind == "section":
            self.doc.delete(it.data(0, ROLE_SECTION))
        else:
            prefix = it.data(0, ROLE_SECTION)
            for name in [s for s in self.doc.section_names() if s.partition(":")[0] == prefix]:
                self.doc.delete(name)
        self.rebuild()
        self.edited.emit()

    def apply_filter(self, text: str) -> None:
        t = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            kind = item.data(0, ROLE_KIND)
            if kind == "key":
                hit = not t or t in item.text(0).lower() or t in item.text(1).lower() or t in item.text(3).lower() \
                    or t in str(item.data(0, ROLE_SECTION)).lower()
                item.setHidden(not hit)
                return hit
            any_child = False
            for i in range(item.childCount()):
                any_child |= visit(item.child(i))
            own = not t or t in item.text(0).lower()
            if own and t and not any_child:  # section name matched -> show all of its keys
                for i in range(item.childCount()):
                    self._unhide(item.child(i))
                any_child = True
            item.setHidden(not (any_child or own and not t))
            if t and any_child:
                item.setExpanded(True)
            return any_child

        for i in range(self.topLevelItemCount()):
            visit(self.topLevelItem(i))

    def _unhide(self, item: QTreeWidgetItem) -> None:
        item.setHidden(False)
        for i in range(item.childCount()):
            self._unhide(item.child(i))

    # ----------------------------------------------------------- expansion keep
    def _expanded_paths(self) -> set:
        out = set()

        def walk(it: QTreeWidgetItem, path: str) -> None:
            p = path + "/" + it.text(0)
            if it.isExpanded():
                out.add(p)
            for i in range(it.childCount()):
                walk(it.child(i), p)

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i), "")
        return out

    def _restore_expanded(self, paths: set) -> None:
        def walk(it: QTreeWidgetItem, path: str) -> None:
            p = path + "/" + it.text(0)
            if p in paths:
                it.setExpanded(True)
            for i in range(it.childCount()):
                walk(it.child(i), p)

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i), "")

    # ------------------------------------------------------------ context menu
    def _menu(self, pos) -> None:
        it = self.itemAt(pos)
        if it is None:
            return
        kind = it.data(0, ROLE_KIND)
        m = QMenu(self)
        if kind == "key":
            m.addAction("Edit nilai", lambda: self.editItem(it, 1))
            if it.text(2) == "embedded":
                m.addAction("Edit isi bersarang…", lambda: self.edit_embedded(it))
            m.addAction("Ikat ke parameter setir…", lambda: self.bindRequested.emit(it.data(0, ROLE_SECTION), it.text(0)))
            m.addSeparator()
            m.addAction("Hapus key", self.delete_current)
        else:
            m.addAction("Hapus " + ("section" if kind == "section" else "grup"), self.delete_current)
        m.exec(self.viewport().mapToGlobal(pos))
