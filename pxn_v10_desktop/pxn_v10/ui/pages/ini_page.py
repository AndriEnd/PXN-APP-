"""INI Presets: import any ``.ini`` (e.g. ``shader PXN V10 Ai 4 (Drift).ini``), edit *every*
parameter in it, preview how it maps to the wheel, and send the result to the PXN-V10."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QTabWidget

from ...core import constants as C
from ...core.models import DeviceProfile
from ...ini import mapper as M
from ...ini import schema as S
from ...ini.document import IniDocument
from ...storage.database import GameProfile
from ...storage.paths import ini_library_dir
from .. import theme
from ..context import AppContext
from ..ini_io import pick_ini_files, pick_ini_save
from ..send_dialog import send_profile
from ..widgets.common import CardPanel, Chip, StyledDialog, button, confirm, info, label, prompt
from ..widgets.ini_tree import IniTreeWidget
from .profile_editor import ProfileEditorDialog


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "preset"


class IniPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.doc: IniDocument | None = None
        self.path: Path | None = None
        self.dirty = False
        self.result: M.IniResult = M.IniResult()
        self.bindings: list[M.Binding] = ctx.settings.bindings()
        self._loading_bindings = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("PRESET UNIVERSAL", "eyebrow"))
        col.addWidget(label("INI Presets", "h1"))
        head.addLayout(col, 1)
        b_import = button("Impor INI…", "ghost")
        b_import.clicked.connect(self.import_files)
        b_new = button("+  Baru", "ghost")
        b_new.clicked.connect(self._new_menu)
        self._b_new = b_new
        head.addWidget(b_import, 0, Qt.AlignBottom)
        head.addWidget(b_new, 0, Qt.AlignBottom)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ---------------------------------------------------------------- library
        lib = CardPanel("Pustaka", "Salinan file yang Anda impor. File asli tidak diubah.")
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentItemChanged.connect(self._library_selected)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._library_menu)
        lib.body.addWidget(self.list, 1)
        self.lib_empty = label("Belum ada preset. Impor file .ini atau buat dari setir.", "muted", wrap=True)
        lib.body.addWidget(self.lib_empty)
        body.addWidget(lib, 3)

        # ----------------------------------------------------------------- editor
        right = QVBoxLayout()
        right.setSpacing(12)
        body.addLayout(right, 9)

        doc_head = QHBoxLayout()
        doc_head.setSpacing(10)
        self.doc_title = label("Pilih atau impor sebuah file INI", "h2")
        doc_head.addWidget(self.doc_title)
        self.kind_chip = Chip("")
        self.kind_chip.hide()
        doc_head.addWidget(self.kind_chip)
        self.count_label = label("", "muted")
        doc_head.addWidget(self.count_label)
        doc_head.addStretch(1)
        self.b_save = button("Simpan", "ghost")
        self.b_save.clicked.connect(self.save)
        self.b_save_as = button("Simpan sebagai…", "ghost")
        self.b_save_as.clicked.connect(self.save_as)
        doc_head.addWidget(self.b_save)
        doc_head.addWidget(self.b_save_as)
        right.addLayout(doc_head)

        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_params_tab(), "PARAMETER")
        self.tabs.addTab(self._build_apply_tab(), "TERAPKAN KE SETIR")
        self.tabs.addTab(self._build_binding_tab(), "BINDING")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_preview())

        ctx.bridge.changed.connect(lambda k, d: self._refresh_preview() if self.isVisible() else None)
        ctx.bridge.connChanged.connect(lambda _e: self._refresh_actions())
        self.reload_library()
        self._set_enabled(False)

    # ================================================================== tabs
    def _build_params_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cari section, key, atau nilai…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda t: self.tree.apply_filter(t))
        bar.addWidget(self.search, 1)
        b_exp = button("Buka semua", "ghost")
        b_col = button("Tutup semua", "ghost")
        b_add = button("+ Key", "ghost")
        b_del = button("Hapus", "danger")
        b_exp.clicked.connect(lambda: self.tree.expandAll())
        b_col.clicked.connect(lambda: self.tree.collapseAll())
        b_add.clicked.connect(self._add_key)
        b_del.clicked.connect(lambda: self.tree.delete_current())
        for b in (b_exp, b_col, b_add, b_del):
            bar.addWidget(b)
        v.addLayout(bar)

        self.banner_box = QWidget()
        self.banner_box.setObjectName("banner")
        self.banner_box.setStyleSheet(
            f"QWidget#banner {{ background: {theme.ACCENT_SOFT}; border: 1px solid #5A2A20; border-radius: 10px; }}")
        bl = QHBoxLayout(self.banner_box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(14)
        self.banner = label("", "dim", wrap=True)
        bl.addWidget(self.banner, 1)
        b_native = button("Tambahkan bagian PXN_V10", "primary")
        b_native.setToolTip("Menyalin nilai setir saat ini (atau default) ke file sebagai [PXN_V10:*]")
        b_native.clicked.connect(self.add_native_sections)
        bl.addWidget(b_native, 0, Qt.AlignVCenter)
        self.banner_box.hide()
        v.addWidget(self.banner_box)

        self.tree = IniTreeWidget()
        self.tree.edited.connect(self._doc_edited)
        self.tree.bindRequested.connect(self._bind_key)
        v.addWidget(self.tree, 1)
        hint = label("Klik ganda sebuah nilai untuk mengubahnya. Nilai bertanda “embedded” berisi INI bersarang "
                     "(base64) dan dapat dibuka dengan klik ganda. Klik kanan untuk mengikat key ke parameter setir.",
                     "muted", wrap=True)
        v.addWidget(hint)
        return w

    def _build_apply_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        self.apply_summary = label("", "dim", wrap=True)
        v.addWidget(self.apply_summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["PARAMETER", "SAAT INI", "DARI INI", "SUMBER", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        h = self.table.horizontalHeader()
        h.setStretchLastSection(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for c in (0, 1, 2):
            h.setSectionResizeMode(c, h.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, h.ResizeMode.Stretch)
        h.setSectionResizeMode(4, h.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 96)
        v.addWidget(self.table, 1)
        self.warnings = QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(92)
        self.warnings.setPlaceholderText("Peringatan parsing akan tampil di sini.")
        v.addWidget(self.warnings)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.b_editor = button("Buka di editor preset", "ghost")
        self.b_editor.clicked.connect(self.open_in_editor)
        self.b_store = button("Simpan sebagai Game Preset", "ghost")
        self.b_store.clicked.connect(self.store_as_preset)
        self.b_send = button("Kirim ke setir", "primary")
        self.b_send.clicked.connect(self.send_to_wheel)
        row.addStretch(1)
        for b in (self.b_editor, self.b_store, self.b_send):
            row.addWidget(b)
        v.addLayout(row)
        return w

    def _build_binding_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(10)
        v.addWidget(label(
            "Binding menghubungkan sebuah key pada file INI mana pun ke parameter setir, lengkap dengan skala nilai. "
            "Contoh: FFB_TWEAKS:CUSTOM_SOFT_LOCK / DAMPER (0–0.1) → Damping force (0–100 %). "
            "Binding berlaku untuk semua file INI.", "dim", wrap=True))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        b_add = button("+ Binding baru", "ghost")
        b_add.clicked.connect(lambda: self._add_binding(M.Binding("", "", "damping")))
        b_sel = button("Dari key terpilih", "ghost")
        b_sel.clicked.connect(self._bind_selected)
        b_del = button("Hapus terpilih", "danger")
        b_del.clicked.connect(self._delete_binding)
        bar.addWidget(b_add)
        bar.addWidget(b_sel)
        bar.addStretch(1)
        bar.addWidget(b_del)
        v.addLayout(bar)
        self.btable = QTableWidget(0, 9)
        self.btable.setHorizontalHeaderLabels(["AKTIF", "SECTION", "KEY", "PARAMETER SETIR", "IN MIN", "IN MAX",
                                               "OUT MIN", "OUT MAX", "BALIK"])
        self.btable.verticalHeader().setVisible(False)
        self.btable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.btable.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.btable.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(1, h.ResizeMode.Stretch)
        h.setSectionResizeMode(2, h.ResizeMode.Stretch)
        h.setSectionResizeMode(3, h.ResizeMode.Fixed)
        self.btable.setColumnWidth(3, 200)
        for c in (0, 4, 5, 6, 7, 8):
            h.setSectionResizeMode(c, h.ResizeMode.ResizeToContents)
        self.btable.itemChanged.connect(self._binding_cell_changed)
        v.addWidget(self.btable, 1)
        self._fill_bindings()
        return w

    # ============================================================== library
    def reload_library(self, select: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        files = sorted(ini_library_dir().glob("*.ini"), key=lambda p: p.name.lower())
        for p in files:
            it = QListWidgetItem(p.stem)
            it.setData(Qt.UserRole, str(p))
            it.setToolTip(str(p))
            self.list.addItem(it)
            if select and str(p) == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.lib_empty.setVisible(not files)
        if select:
            self._library_selected(self.list.currentItem(), None)

    def import_files(self) -> None:
        paths = pick_ini_files(self, self.ctx, multiple=True)
        last = None
        for src in paths:
            try:
                IniDocument.load(src)  # validate that it parses
            except OSError as exc:
                info(self, "Gagal membaca file", f"{src}\n{exc}")
                continue
            name = _safe_name(Path(src).stem)
            dest = ini_library_dir() / f"{name}.ini"
            n = 2
            while dest.exists():
                dest = ini_library_dir() / f"{name} ({n}).ini"
                n += 1
            shutil.copyfile(src, dest)
            last = str(dest)
        if last:
            self.reload_library(select=last)
            self.ctx.toast(f"{len(paths)} file diimpor ke pustaka", "ok")

    def _new_menu(self) -> None:
        m = QMenu(self)
        m.addAction("Dari setir yang terhubung (parameter PXN_V10)", self._new_from_wheel)
        m.addAction("Template PXN V10 kosong", self._new_template)
        m.exec(self._b_new.mapToGlobal(self._b_new.rect().bottomLeft()))

    def _new_from_wheel(self) -> None:
        client = self.ctx.client
        profile = client.profile.copy() if client.is_ready else DeviceProfile()
        mode = client.device_state.mode if client.is_ready and client.device_state.mode else C.MODE_PC_DINPUT
        name = prompt(self, "Nama preset baru", "Mis. PXN V10 Drift", "PXN V10 preset", ok="Buat")
        if name:
            doc = M.profile_to_doc(profile, mode, name=name)
            self._store_new(name, doc)

    def _new_template(self) -> None:
        name = prompt(self, "Nama preset baru", "Mis. PXN V10 Drift", "PXN V10 preset", ok="Buat")
        if name:
            doc = IniDocument.parse(S.SAMPLE_NATIVE_INI)
            doc.set(S.SEC_GENERAL, "NAME", name)
            self._store_new(name, doc)

    def _store_new(self, name: str, doc: IniDocument) -> None:
        dest = ini_library_dir() / f"{_safe_name(name)}.ini"
        n = 2
        while dest.exists():
            dest = ini_library_dir() / f"{_safe_name(name)} ({n}).ini"
            n += 1
        doc.save(str(dest))
        self.reload_library(select=str(dest))

    def _library_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        m = QMenu(self)
        m.addAction("Ganti nama", lambda: self._rename_library(it))
        m.addAction("Tampilkan di folder", lambda: os.startfile(os.path.dirname(it.data(Qt.UserRole))) if os.name == "nt" else None)
        m.addSeparator()
        m.addAction("Hapus dari pustaka", lambda: self._remove_library(it))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _rename_library(self, it: QListWidgetItem) -> None:
        old = Path(it.data(Qt.UserRole))
        name = prompt(self, "Ganti nama", "Nama baru", old.stem, ok="Ganti")
        if name:
            new = old.with_name(_safe_name(name) + ".ini")
            if new.exists() and new != old:
                info(self, "Nama sudah dipakai", "Sudah ada file dengan nama tersebut di pustaka.")
                return
            old.rename(new)
            if self.path == old:
                self.path = new
            self.reload_library(select=str(new) if self.path == new else None)

    def _remove_library(self, it: QListWidgetItem) -> None:
        p = Path(it.data(Qt.UserRole))
        if confirm(self, "Hapus dari pustaka", f"Hapus “{p.stem}” dari pustaka? File asli yang Anda impor tidak terhapus.",
                   ok="Hapus", danger=True):
            p.unlink(missing_ok=True)
            if self.path == p:
                self._clear_doc()
            self.reload_library()

    # ================================================================ document
    def _library_selected(self, cur: QListWidgetItem | None, _prev) -> None:
        if cur is None:
            return
        if self.dirty and not confirm(self, "Perubahan belum disimpan", "Buang perubahan pada file yang sedang dibuka?",
                                      ok="Buang", danger=True):
            self.list.blockSignals(True)
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole) == str(self.path):
                    self.list.setCurrentRow(i)
            self.list.blockSignals(False)
            return
        path = Path(cur.data(Qt.UserRole))
        try:
            doc = IniDocument.load(str(path))
        except OSError as exc:
            info(self, "Gagal membaca file", str(exc))
            return
        self.path, self.doc, self.dirty = path, doc, False
        self.doc_title.setText(path.stem)
        self._after_doc_change(rebuild_tree=True)
        self._set_enabled(True)

    def _clear_doc(self) -> None:
        self.doc, self.path, self.dirty = None, None, False
        self.doc_title.setText("Pilih atau impor sebuah file INI")
        self.tree.set_document(None)
        self.kind_chip.hide()
        self.count_label.setText("")
        self._set_enabled(False)
        self._refresh_preview()

    def _set_enabled(self, enabled: bool) -> None:
        for w in (self.b_save, self.b_save_as, self.tabs):
            w.setEnabled(enabled)
        self._refresh_actions()

    def _doc_edited(self) -> None:
        self.dirty = True
        self._after_doc_change(rebuild_tree=False)

    def _bound_map(self) -> dict:
        return {(b.section.lower(), b.key.lower()): S.PARAM_BY_ID[b.target].label
                for b in self.bindings if b.enabled and b.target in S.PARAM_BY_ID}

    def _after_doc_change(self, rebuild_tree: bool) -> None:
        if self.doc is None:
            return
        if rebuild_tree:
            self.tree.set_document(self.doc, self._bound_map())
            self.tree.collapseAll()
            native = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())
                      if self.tree.topLevelItem(i).text(0).upper() == S.GROUP]
            for n in native:
                n.setExpanded(True)
            self.search.clear()
        self.count_label.setText(f"{len(self.doc.sections)} section · {self.doc.count()} key"
                                 + ("  ·  belum disimpan" if self.dirty else ""))
        self._refresh_preview()

    # =================================================================== save
    def save(self) -> None:
        if self.doc is None or self.path is None:
            return
        self.doc.save(str(self.path))
        self.dirty = False
        self._after_doc_change(rebuild_tree=False)
        self.ctx.toast(f"Tersimpan ke pustaka: {self.path.name}", "ok")

    def save_as(self) -> None:
        if self.doc is None:
            return
        path = pick_ini_save(self, self.ctx, (self.path.stem if self.path else "preset") + ".ini")
        if path:
            self.doc.save(path)
            self.doc.path = str(self.path) if self.path else None
            self.ctx.toast(f"Disimpan ke {path}", "ok")

    # ================================================================ key ops
    def _add_key(self) -> None:
        if self.doc is None:
            return
        d = StyledDialog(self, "Tambah key", width=480)
        sec = QComboBox()
        sec.setEditable(True)
        sec.addItems(self.doc.section_names() or [S.SEC_WHEEL])
        cur = self.tree.current_key()
        if cur:
            sec.setCurrentText(cur[0])
        key, val = QLineEdit(), QLineEdit()
        key.setPlaceholderText("KEY")
        val.setPlaceholderText("nilai")
        for lbl, w in (("Section", sec), ("Key", key), ("Nilai", val)):
            d.root.addWidget(label(lbl.upper(), "eyebrow"))
            d.root.addWidget(w)
        b_c, b_ok = button("Batal", "ghost"), button("Tambah", "primary")
        b_c.clicked.connect(d.reject)
        b_ok.clicked.connect(d.accept)
        d.buttons.addWidget(b_c)
        d.buttons.addWidget(b_ok)
        d.finish()
        if d.exec() and key.text().strip() and sec.currentText().strip():
            self.tree.add_key(sec.currentText().strip(), key.text().strip(), val.text().strip())

    # ================================================================ preview
    def _current_profile_base(self) -> tuple:
        client = self.ctx.client
        if client.is_ready:
            mode = client.device_state.mode or C.MODE_PC_DINPUT
            return client.profile.copy(), mode, True
        return DeviceProfile(), C.MODE_PC_DINPUT, False

    def _refresh_preview(self) -> None:
        if self.doc is None:
            self.result = M.IniResult()
            self.table.setRowCount(0)
            self.apply_summary.setText("Pilih sebuah file INI untuk melihat parameter setir di dalamnya.")
            self.warnings.setPlainText("")
            self.banner_box.hide()
            self._refresh_actions()
            return
        self.result = M.extract(self.doc, self.bindings)
        r = self.result
        base, base_mode, live = self._current_profile_base()
        rows = M.diff_against(r, base, base_mode)
        self.table.setRowCount(len(rows))
        for i, (name, cur, new, src, changed) in enumerate(rows):
            vals = (name, cur if live else "—", new, src, "BERUBAH" if changed else "sama")
            for c, text in enumerate(vals):
                it = QTableWidgetItem(text)
                it.setToolTip(text)
                if c == 4:
                    it.setForeground(QColor(theme.ACCENT_2 if changed else theme.TEXT_MUTED))
                elif c == 3:
                    it.setForeground(QColor(theme.TEXT_MUTED))
                self.table.setItem(i, c, it)
            self.table.setRowHeight(i, 34)
        native_n = sum(1 for it in r.items if "binding" not in it.source)
        bound_n = len(r.items) - native_n
        kind = "NATIVE PXN" if r.native else "UNIVERSAL"
        self.kind_chip.setText(kind)
        self.kind_chip.set_style(theme.GREEN if r.native else theme.AMBER)
        self.kind_chip.show()
        if r.empty:
            self.apply_summary.setText(
                "File ini tidak memuat parameter setir. Semua key-nya tetap dapat diedit dan disimpan, tetapi untuk "
                "dikirim ke PXN-V10 tambahkan bagian [PXN_V10:*] atau buat binding.")
        else:
            self.apply_summary.setText(
                f"{len(r.items)} parameter akan diterapkan ({native_n} dari bagian PXN_V10, {bound_n} lewat binding)."
                + ("" if live else "  Setir belum terhubung — kolom “Saat ini” kosong."))
        self.warnings.setPlainText("\n".join(r.warnings))
        show_banner = not r.native and r.empty
        self.banner_box.setVisible(show_banner)
        if show_banner:
            self.banner.setText(
                "File ini adalah konfigurasi universal (bukan format PXN V10), jadi belum ada parameter yang bisa "
                "dikirim ke setir. Pilih salah satu: (1) klik kanan sebuah key → “Ikat ke parameter setir…”, "
                "(2) buka tab BINDING, atau (3) tambahkan bagian PXN_V10 dari nilai setir saat ini lewat tombol di "
                "kanan.")
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        has = self.doc is not None and not self.result.empty
        self.b_editor.setEnabled(has)
        self.b_store.setEnabled(has)
        self.b_send.setEnabled(has)
        self.b_send.setToolTip("" if self.ctx.client.is_ready else "Hubungkan setir untuk mengirim")

    # ================================================================== actions
    def _profile_from_result(self) -> tuple:
        base, base_mode, _live = self._current_profile_base()
        profile = M.apply_to_profile(self.result, base)
        mode = self.result.mode or base_mode
        return profile, mode

    def send_to_wheel(self) -> None:
        if self.doc is None or self.result.empty:
            return
        if not self.ctx.client.is_ready:
            self.ctx.toast("Hubungkan setir PXN-V10 terlebih dahulu.", "error")
            self.ctx.navigate("connect")
            return
        profile, mode = self._profile_from_result()
        name = self.result.name or (self.path.stem if self.path else "INI preset")
        send_profile(self, self.ctx, profile, mode, name, adv=self.result.ffb_adv)

    def open_in_editor(self) -> None:
        if self.doc is None or self.result.empty:
            return
        profile, mode = self._profile_from_result()
        gp = GameProfile(name=self.result.name or (self.path.stem if self.path else ""), mode=mode,
                         platform=self.result.platform or C.platform_by_mode(mode))
        gp.set_profile(profile)
        gp.set_advanced(self.result.ffb_adv)
        ProfileEditorDialog(self, self.ctx, gp).exec()

    def store_as_preset(self) -> None:
        if self.doc is None or self.result.empty:
            return
        profile, mode = self._profile_from_result()
        name = prompt(self, "Simpan sebagai Game Preset", "Nama preset",
                      self.result.name or (self.path.stem if self.path else ""), ok="Simpan")
        if not name:
            return
        gp = GameProfile(name=name, mode=mode, platform=self.result.platform or C.platform_by_mode(mode))
        gp.set_profile(profile)
        gp.set_advanced(self.result.ffb_adv)
        self.ctx.db.save(gp)
        self.ctx.toast(f"Preset “{name}” disimpan di Game Presets", "ok")

    def add_native_sections(self) -> None:
        """Merge the current wheel values (or defaults) into the open document as [PXN_V10:*]."""
        if self.doc is None:
            return
        base, mode, _ = self._current_profile_base()
        merged = M.profile_to_doc(base, mode, name=self.path.stem if self.path else "", base=self.doc)
        self.doc.sections = merged.sections
        self.dirty = True
        self._after_doc_change(rebuild_tree=True)

    # ================================================================ bindings
    def _fill_bindings(self) -> None:
        self._loading_bindings = True
        self.btable.setRowCount(0)
        for b in self.bindings:
            self._append_binding_row(b)
        self._loading_bindings = False

    def _append_binding_row(self, b: M.Binding) -> None:
        r = self.btable.rowCount()
        self.btable.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk.setCheckState(Qt.Checked if b.enabled else Qt.Unchecked)
        self.btable.setItem(r, 0, chk)
        self.btable.setItem(r, 1, QTableWidgetItem(b.section))
        self.btable.setItem(r, 2, QTableWidgetItem(b.key))
        combo = QComboBox()
        for spec in S.PARAMS:
            combo.addItem(spec.label, spec.id)
        combo.setCurrentIndex(max(0, combo.findData(b.target)))
        combo.currentIndexChanged.connect(lambda _i: self._binding_cell_changed(None))
        self.btable.setCellWidget(r, 3, combo)
        for c, v in zip((4, 5, 6, 7), (b.in_min, b.in_max, b.out_min, b.out_max)):
            it = QTableWidgetItem(f"{v:g}")
            it.setTextAlignment(Qt.AlignCenter)
            self.btable.setItem(r, c, it)
        inv = QTableWidgetItem()
        inv.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        inv.setCheckState(Qt.Checked if b.invert else Qt.Unchecked)
        self.btable.setItem(r, 8, inv)
        self.btable.setRowHeight(r, 38)

    def _add_binding(self, b: M.Binding) -> None:
        self.bindings.append(b)
        self._loading_bindings = True
        self._append_binding_row(b)
        self._loading_bindings = False
        self._persist_bindings()

    def _delete_binding(self) -> None:
        r = self.btable.currentRow()
        if r < 0:
            return
        self.btable.removeRow(r)
        del self.bindings[r]
        self._persist_bindings()

    def _bind_selected(self) -> None:
        cur = self.tree.current_key()
        if cur is None:
            info(self, "Pilih sebuah key", "Pilih dulu sebuah key pada tab PARAMETER, lalu kembali ke sini.")
            return
        self._bind_key(*cur)

    def _bind_key(self, section: str, key: str) -> None:
        raw = self.doc.get(section, key, "") if self.doc else ""
        try:
            val = float(raw)
        except ValueError:
            val = None
        lo, hi = (0.0, 1.0) if val is not None and 0 <= val <= 1 else (0.0, max(1.0, abs(val or 100) * 2))
        self._add_binding(M.Binding(section, key, "ffb", lo, hi, 0.0, 100.0))
        self.tabs.setCurrentIndex(2)
        self.btable.selectRow(self.btable.rowCount() - 1)
        self.ctx.toast("Binding dibuat — atur parameter setir dan skalanya.", "info")

    def _binding_cell_changed(self, _item) -> None:
        if self._loading_bindings:
            return
        out: list[M.Binding] = []
        for r in range(self.btable.rowCount()):
            def num(c: int, default: float) -> float:
                it = self.btable.item(r, c)
                try:
                    return float(it.text()) if it else default
                except ValueError:
                    return default

            combo: QComboBox = self.btable.cellWidget(r, 3)
            out.append(M.Binding(
                section=(self.btable.item(r, 1).text() if self.btable.item(r, 1) else "").strip(),
                key=(self.btable.item(r, 2).text() if self.btable.item(r, 2) else "").strip(),
                target=combo.currentData() if combo else "ffb",
                in_min=num(4, 0.0), in_max=num(5, 1.0), out_min=num(6, 0.0), out_max=num(7, 100.0),
                invert=self.btable.item(r, 8).checkState() == Qt.Checked,
                enabled=self.btable.item(r, 0).checkState() == Qt.Checked,
            ))
        self.bindings = out
        self._persist_bindings()

    def _persist_bindings(self) -> None:
        self.ctx.settings.set_bindings(self.bindings)
        self.tree.set_bound(self._bound_map())
        self._refresh_preview()
