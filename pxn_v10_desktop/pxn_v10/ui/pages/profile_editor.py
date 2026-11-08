"""Preset editor (V10ProfileActivity): edit a stored game profile offline, save it, or send it to
the wheel. Can also import an INI over the current values or export the preset as INI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QMenu, QPushButton, QVBoxLayout

from ...core import constants as C
from ...core.models import DeviceProfile
from ...ini import mapper as M
from ...storage.database import GameProfile
from .. import theme
from ..context import AppContext
from ..ini_io import load_into_profile, pick_ini_files, pick_ini_save
from ..send_dialog import send_profile
from ..widgets.common import button, confirm, hline, info, label, prompt
from ..widgets.config_editor import ConfigEditor, LocalBackend


class ProfileEditorDialog(QDialog):
    def __init__(self, parent, ctx: AppContext, gp: GameProfile, tutorial: str = "") -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.gp = gp
        self.tutorial = tutorial or gp.tutorial
        self.profile: DeviceProfile = gp.profile()
        self.mode = gp.mode or C.mode_by_platform(gp.platform)
        self.dirty = False
        self.saved: GameProfile | None = None

        self.setWindowTitle("Editor preset")
        self.setModal(True)
        self.resize(1180, 800)
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label("EDITOR PRESET" + ("  ·  REKOMENDASI" if gp.recommended else ""), "eyebrow"))
        self.name = QLineEdit(gp.name)
        self.name.setPlaceholderText("Nama preset (mis. “Forza Horizon 5 — Drift”)")
        self.name.setMinimumWidth(340)
        self.name.setStyleSheet("font-size: 14pt; font-weight: 700; padding: 8px 12px;")
        self.name.textEdited.connect(lambda _t: self._mark_dirty())
        col.addWidget(self.name)
        head.addLayout(col, 1)

        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("chip")
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.clicked.connect(self._mode_menu)
        head.addWidget(self.mode_btn, 0, Qt.AlignBottom)
        b_import = button("Impor INI", "ghost")
        b_import.clicked.connect(self._import_ini)
        b_export = button("Ekspor INI", "ghost")
        b_export.clicked.connect(self._export_ini)
        self.b_send = button("Kirim ke setir", "ghost")
        self.b_send.clicked.connect(self._send)
        b_save = button("Simpan", "primary")
        b_save.clicked.connect(self._save)
        close = button("Tutup", "ghost")
        close.clicked.connect(self.reject)
        for b in (b_import, b_export, self.b_send, b_save, close):
            head.addWidget(b, 0, Qt.AlignBottom)
        root.addLayout(head)
        root.addWidget(hline())

        self.editor = ConfigEditor(LocalBackend(self.profile))
        self.editor.changed.connect(self._mark_dirty)
        self.editor.set_hardware(True, True, True)
        root.addWidget(self.editor, 1)
        self._apply_mode()
        ctx.bridge.connChanged.connect(self._conn)
        self._conn(None)

    # ------------------------------------------------------------------ state
    def _conn(self, _ev) -> None:
        ready = self.ctx.client.is_ready
        self.b_send.setEnabled(True)
        self.b_send.setToolTip("" if ready else "Setir belum terhubung — Anda akan diminta menyimpan preset.")

    def _mark_dirty(self) -> None:
        self.dirty = True

    def _apply_mode(self) -> None:
        pc = self.gp.platform == C.PLATFORM_PC
        self.mode_btn.setText(C.MODE_NAMES.get(self.mode, "?") + ("   ▾" if pc else ""))
        self.mode_btn.setToolTip("Pilih D-Input / X-Input" if pc else "Mode ditentukan oleh platform preset")
        self.editor.set_mode(self.mode)

    def _mode_menu(self) -> None:
        if self.gp.platform != C.PLATFORM_PC:
            return
        menu = QMenu(self)
        for mode in C.modes_by_platform(self.gp.platform):
            act = menu.addAction(C.MODE_LONG_NAMES[mode])
            act.setCheckable(True)
            act.setChecked(mode == self.mode)
            act.triggered.connect(lambda _=False, m=mode: self._set_mode(m))
        menu.exec(self.mode_btn.mapToGlobal(self.mode_btn.rect().bottomLeft()))

    def _set_mode(self, mode: int) -> None:
        self.mode = mode
        self.gp.mode = mode
        self._mark_dirty()
        self._apply_mode()

    # ---------------------------------------------------------------- actions
    def _commit(self) -> bool:
        name = self.name.text().strip()
        if not name:
            name = prompt(self, "Nama preset", "Masukkan nama preset") or ""
            if not name:
                self.ctx.toast("Nama preset wajib diisi", "error")
                return False
            self.name.setText(name)
        self.gp.name = name
        self.gp.mode = self.mode
        self.gp.set_profile(self.profile.copy().clamp())
        self.gp.recommended = False  # a saved copy of a recommended preset becomes a custom one
        self.ctx.db.save(self.gp)
        self.saved = self.gp
        self.dirty = False
        return True

    def _save(self) -> None:
        if self._commit():
            self.ctx.toast("Preset tersimpan", "ok")
            self.accept()

    def _send(self) -> None:
        if not self.ctx.client.is_ready:
            if confirm(self, "Setir tidak terhubung", "Simpan perubahan preset saat ini agar dapat dikirim nanti?",
                       ok="Simpan"):
                self._save()
            return
        send_profile(self, self.ctx, self.profile.copy().clamp(), self.mode, self.name.text().strip(), self.tutorial,
                     adv=self.gp.advanced())

    def _import_ini(self) -> None:
        paths = pick_ini_files(self, self.ctx, multiple=False)
        if not paths:
            return
        try:
            profile, res = load_into_profile(self.ctx, paths[0], self.profile)
        except OSError as exc:
            info(self, "Gagal membaca file", str(exc))
            return
        if res.empty:
            info(self, "Tidak ada parameter setir",
                 "File INI ini tidak memuat bagian [PXN_V10:*] dan tidak ada binding yang cocok, sehingga tidak ada "
                 "yang diubah. Buka halaman “INI Presets” untuk membuat binding ke parameter setir.")
            return
        self.profile.__dict__.update(profile.__dict__)
        self.editor.backend = LocalBackend(self.profile)
        if res.mode and (res.mode in C.modes_by_platform(self.gp.platform)):
            self.mode = res.mode
            self.gp.mode = res.mode
        if res.name and not self.name.text().strip():
            self.name.setText(res.name)
        self._apply_mode()
        self._mark_dirty()
        msg = f"{len(res.items)} parameter diterapkan dari INI"
        if res.warnings:
            msg += f" ({len(res.warnings)} peringatan)"
        self.ctx.toast(msg, "ok")

    def _export_ini(self) -> None:
        name = self.name.text().strip() or "preset"
        path = pick_ini_save(self, self.ctx, f"{name}.ini")
        if not path:
            return
        doc = M.profile_to_doc(self.profile, self.mode, name=name, platform=self.gp.platform)
        doc.save(path)
        self.ctx.toast(f"Diekspor ke {path}", "ok")

    # ------------------------------------------------------------------ close
    def reject(self) -> None:
        if self.dirty and not confirm(self, "Perubahan belum disimpan", "Tutup editor tanpa menyimpan perubahan?",
                                      ok="Tutup tanpa simpan", danger=True):
            return
        super().reject()
