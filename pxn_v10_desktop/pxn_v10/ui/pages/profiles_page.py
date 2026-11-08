"""Game presets screen (V10GameActivity): recommended + custom presets per platform, CRUD,
send to wheel, INI import / export."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...core import constants as C
from ...ini import mapper as M
from ...core.models import DeviceProfile
from ...ini.document import IniDocument
from ...storage.database import GameProfile, load_recommended
from .. import theme
from ..context import AppContext
from ..ini_io import pick_ini_files, pick_ini_save
from ..send_dialog import send_profile
from ..widgets.common import Chip, SegmentedBar, button, card, confirm, info, label, prompt
from .profile_editor import ProfileEditorDialog

ALL_PLATFORMS = (C.PLATFORM_PC, C.PLATFORM_PS4, C.PLATFORM_XBOX_ONE, C.PLATFORM_ANDROID, C.PLATFORM_SWITCH)


def summary(gp: GameProfile) -> str:
    try:
        p = gp.profile()
    except ValueError:
        return "data tidak valid"
    parts = [C.MODE_NAMES.get(gp.mode, "?"), f"{p.angle}°", f"FFB {p.ffb}%"]
    if p.ffb_reverse:
        parts.append("Reverse")
    if p.custom_mappings():
        parts.append(f"{len(p.custom_mappings())} remap")
    return "  ·  ".join(parts)


class PresetRow(QWidget):
    def __init__(self, gp: GameProfile, page: "ProfilesPage") -> None:
        super().__init__()
        self.gp, self.page = gp, page
        f = card(inner=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(f)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(18, 12, 12, 12)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(gp.name or "(tanpa nama)", "h3"))
        col.addWidget(label(summary(gp), "muted"))
        lay.addLayout(col, 1)
        if gp.recommended:
            lay.addWidget(Chip("REKOMENDASI", theme.ACCENT_2))
        b_open = button("Buka", "ghost")
        b_open.clicked.connect(lambda: page.open_editor(gp))
        b_send = button("Kirim", "primary")
        b_send.clicked.connect(lambda: page.send(gp))
        b_send.setToolTip("Terapkan preset ini ke setir")
        more = QPushButton("•••")
        more.setObjectName("ghost")
        more.setFixedWidth(44)
        more.setStyleSheet("padding: 0px;")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda: self._menu(more))
        for w in (b_open, b_send, more):
            lay.addWidget(w)

    def _menu(self, anchor: QWidget) -> None:
        gp, page = self.gp, self.page
        m = QMenu(self)
        if gp.tutorial:
            m.addAction("Lihat tutorial", lambda: info(page, gp.name, gp.tutorial))
        if not gp.recommended:
            m.addAction("Ganti nama", lambda: page.rename(gp))
        m.addAction("Duplikat", lambda: page.duplicate(gp))
        m.addAction("Ekspor sebagai INI…", lambda: page.export_ini(gp))
        if not gp.recommended:
            m.addSeparator()
            m.addAction("Hapus", lambda: page.remove(gp))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


class Group(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        head = QHBoxLayout()
        self.title = label(title, "eyebrow")
        self.count = label("", "muted")
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch(1)
        self.lay.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        self.lay.addLayout(self.rows)
        self.empty = label("", "muted", wrap=True)
        self.lay.addWidget(self.empty)

    def clear(self) -> None:
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def set_items(self, widgets: list, empty_text: str) -> None:
        self.clear()
        for w in widgets:
            self.rows.addWidget(w)
        self.count.setText(f"({len(widgets)})")
        self.empty.setText(empty_text)
        self.empty.setVisible(not widgets)


class ProfilesPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.platform = C.PLATFORM_PC
        self.recommended = load_recommended()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("PRESET", "eyebrow"))
        col.addWidget(label("Game Presets", "h1"))
        head.addLayout(col, 1)
        b_import = button("Impor INI…", "ghost")
        b_import.clicked.connect(self.import_ini)
        b_add = button("+  Tambah preset", "primary")
        b_add.clicked.connect(self.add)
        head.addWidget(b_import, 0, Qt.AlignBottom)
        head.addWidget(b_add, 0, Qt.AlignBottom)
        root.addLayout(head)

        self.platforms = SegmentedBar()
        self.platforms.currentChanged.connect(self._platform_changed)
        root.addWidget(self.platforms, 0, Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 8, 0)
        hv.setSpacing(22)
        self.g_custom = Group("PRESET SAYA")
        self.g_rec = Group("REKOMENDASI")
        hv.addWidget(self.g_custom)
        hv.addWidget(self.g_rec)
        hv.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        ctx.bridge.changed.connect(lambda k, d: self._maybe_refresh_platforms())
        self._build_platforms()

    # ---------------------------------------------------------------- platforms
    def _platform_list(self) -> list:
        client = self.ctx.client
        if client.is_ready and client.device_state.mode:
            return C.platforms_by_mode(client.device_state.mode)
        return list(ALL_PLATFORMS)

    def _build_platforms(self) -> None:
        plats = self._platform_list()
        self.platforms.set_items([(str(p), C.PLATFORM_NAMES[p].upper()) for p in plats], keep=True)
        cur = int(self.platforms.current or plats[0])
        self.platform = cur
        self.reload()

    def _maybe_refresh_platforms(self) -> None:
        if [str(p) for p in self._platform_list()] != list(self.platforms._buttons):
            self._build_platforms()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._build_platforms()

    def _platform_changed(self, key: str) -> None:
        self.platform = int(key)
        self.reload()

    # -------------------------------------------------------------------- data
    def reload(self) -> None:
        custom = self.ctx.db.list(platform=self.platform)
        self.g_custom.set_items([PresetRow(g, self) for g in custom],
                                "Belum ada preset. Tekan “Tambah preset” atau impor file .ini.")
        rec = [g for g in self.recommended if g.platform == self.platform]
        self.g_rec.set_items([PresetRow(g, self) for g in rec], "Tidak ada preset rekomendasi untuk platform ini.")

    # ----------------------------------------------------------------- actions
    def add(self) -> None:
        mode = C.mode_by_platform(self.platform)
        client = self.ctx.client
        if client.is_ready and client.device_state.mode in C.modes_by_platform(self.platform):
            mode = client.device_state.mode
        gp = GameProfile(mode=mode, platform=self.platform)
        if self.ctx.client.is_ready:  # start from what the wheel currently has
            gp.set_profile(self.ctx.client.profile)
        self.open_editor(gp)

    def open_editor(self, gp: GameProfile) -> None:
        if gp.recommended:  # edit a copy; saving turns it into a custom preset
            gp = GameProfile(name=gp.name, mode=gp.mode, platform=gp.platform, content=gp.content,
                             tutorial=gp.tutorial, recommended=True)
        dlg = ProfileEditorDialog(self, self.ctx, gp)
        if dlg.exec() == QDialog.Accepted:
            self.reload()

    def send(self, gp: GameProfile) -> None:
        if not self.ctx.client.is_ready:
            self.ctx.toast("Hubungkan setir terlebih dahulu untuk mengirim preset.", "error")
            return
        send_profile(self, self.ctx, gp.profile(), gp.mode, gp.name, gp.tutorial, adv=gp.advanced())

    def rename(self, gp: GameProfile) -> None:
        name = prompt(self, "Ganti nama preset", "Masukkan nama baru", gp.name, ok="Ganti")
        if name:
            self.ctx.db.rename(gp.id, name)
            self.reload()

    def duplicate(self, gp: GameProfile) -> None:
        dup = gp.duplicate(" (salinan)")
        self.ctx.db.save(dup)
        self.reload()
        self.ctx.toast("Preset diduplikasi", "ok")

    def remove(self, gp: GameProfile) -> None:
        if confirm(self, "Hapus preset", f"Hapus preset “{gp.name}”? Tindakan ini tidak dapat dibatalkan.",
                   ok="Hapus", danger=True):
            self.ctx.db.delete(gp.id)
            self.reload()

    def export_ini(self, gp: GameProfile) -> None:
        path = pick_ini_save(self, self.ctx, f"{gp.name or 'preset'}.ini")
        if path:
            M.profile_to_doc(gp.profile(), gp.mode, name=gp.name, platform=gp.platform).save(path)
            self.ctx.toast(f"Diekspor ke {path}", "ok")

    def import_ini(self) -> None:
        paths = pick_ini_files(self, self.ctx, multiple=True)
        imported = 0
        for path in paths:
            try:
                doc = IniDocument.load(path)
            except OSError as exc:
                info(self, "Gagal membaca file", f"{path}\n{exc}")
                continue
            res = M.extract(doc, self.ctx.settings.bindings())
            if res.empty:
                info(self, "Tidak ada parameter setir",
                     f"“{path}” tidak berisi bagian [PXN_V10:*] dan tidak ada binding yang cocok, sehingga tidak "
                     "dapat dijadikan preset. Gunakan halaman “INI Presets” untuk membuat binding.")
                continue
            mode = res.mode or C.mode_by_platform(self.platform)
            profile = M.apply_to_profile(res, self.ctx.client.profile if self.ctx.client.is_ready else DeviceProfile())
            gp = GameProfile(name=res.name or os.path.splitext(os.path.basename(path))[0], mode=mode,
                             platform=res.platform or C.platform_by_mode(mode))
            gp.set_profile(profile)
            self.ctx.db.save(gp)
            imported += 1
        if imported:
            self.reload()
            self.ctx.toast(f"{imported} preset diimpor dari INI", "ok")

