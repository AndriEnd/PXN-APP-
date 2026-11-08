"""Main configuration screen (V10MainActivity): header, mode switcher, hardware-aware tabs,
live parameter editing, factory reset."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QMenu, QPushButton, QStackedLayout, QVBoxLayout, QWidget

from ...core import constants as C
from ...core.events import Change, ConnState
from .. import theme
from ..context import AppContext
from ..widgets.common import Chip, StatusDot, StyledDialog, button, confirm, label
from ..widgets.config_editor import ConfigEditor, DeviceBackend


class DashboardPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._loading: QDialog | None = None

        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        self.stack = stack

        # ---- empty state (not connected)
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.addStretch(1)
        ev.addWidget(label("Belum terhubung", "h1", align=Qt.AlignCenter))
        ev.addWidget(label("Hubungkan setir PXN-V10 untuk mengatur parameter secara langsung.", "dim",
                           align=Qt.AlignCenter))
        go = button("Ke halaman koneksi", "primary")
        go.clicked.connect(lambda: ctx.navigate("connect"))
        ev.addSpacing(10)
        ev.addWidget(go, 0, Qt.AlignHCenter)
        ev.addStretch(2)
        stack.addWidget(empty)

        # ---- content
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(32, 26, 32, 28)
        cv.setSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.addWidget(label("DASHBOARD", "eyebrow"))
        trow = QHBoxLayout()
        trow.setSpacing(10)
        trow.addWidget(label("PXN-V10", "h1"))
        self.dot = StatusDot(theme.GREEN, 10)
        trow.addWidget(self.dot)
        self.status_text = label("Terhubung", "dim")
        trow.addWidget(self.status_text)
        self.fw_chip = Chip("FW —")
        trow.addWidget(self.fw_chip)
        trow.addStretch(1)
        title_col.addLayout(trow)
        head.addLayout(title_col, 1)

        self.mode_btn = QPushButton("D-Input")
        self.mode_btn.setObjectName("chip")
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.clicked.connect(self._mode_menu)
        head.addWidget(self.mode_btn)
        b_test = button("Uji / Test", "ghost")
        b_test.clicked.connect(lambda: ctx.navigate("test"))
        b_games = button("Game Presets", "ghost")
        b_games.clicked.connect(lambda: ctx.navigate("presets"))
        b_reset = button("Reset pabrik", "danger")
        b_reset.clicked.connect(self._factory_reset)
        for b in (b_test, b_games, b_reset):
            head.addWidget(b)
        cv.addLayout(head)

        self.editor = ConfigEditor(DeviceBackend(ctx.client))
        self.editor.notify.connect(lambda m: ctx.toast(m, "info"))
        cv.addWidget(self.editor, 1)
        stack.addWidget(content)

        b = ctx.bridge
        b.changed.connect(self._changed)
        b.connChanged.connect(lambda _e: self._sync_connection())
        ctx.clientReplaced.connect(self._client_replaced)
        self._sync_connection()
        self._apply_state()

    # ------------------------------------------------------------ connection
    def _sync_connection(self) -> None:
        ready = self.ctx.client.state == ConnState.READY
        self.stack.setCurrentIndex(1 if ready else 0)
        if ready:
            self._apply_state()
            self.editor.refresh()

    def _client_replaced(self) -> None:
        self.editor.backend = DeviceBackend(self.ctx.client)
        self._sync_connection()

    def showEvent(self, e) -> None:  # V10MainActivity.onStart -> readState()
        super().showEvent(e)
        if self.ctx.client.is_ready:
            self.ctx.client.read_state()

    # ----------------------------------------------------------------- state
    def _apply_state(self) -> None:
        ds = self.ctx.client.device_state
        self.mode_btn.setText(C.MODE_NAMES.get(ds.mode, "Unknown") + ("   ▾" if ds.is_pc_mode else ""))
        self.mode_btn.setToolTip("Ganti mode D-Input / X-Input" if ds.is_pc_mode
                                 else "Mode konsol terkunci — hanya bisa dibaca")
        self.fw_chip.setText(f"FW {ds.firmware_text}")
        self.editor.set_hardware(ds.has_pedal, ds.has_lever, ds.has_brake)
        self.editor.set_mode(ds.mode, angle_enabled=(ds.angle_mode == 1))

    def _changed(self, kind: int, _detail: int) -> None:
        if kind == Change.STATE:
            self._apply_state()
        elif kind == Change.PROFILE_READY:
            self.editor.refresh()
            self._dismiss_loading()
        elif kind in (Change.MODE, Change.ANGLE):
            self._apply_state()
        elif kind in (Change.KEYMAP, Change.FFB, Change.FORCE):
            self.editor.refresh()
        elif kind == Change.PROFILE_WRITTEN:
            self.editor.refresh()

    # ----------------------------------------------------------- mode switch
    def _mode_menu(self) -> None:
        ds = self.ctx.client.device_state
        if not ds.is_pc_mode:  # SwitchableModes: only PC mode may be changed
            self.ctx.toast("Mode konsol tidak dapat diganti dari aplikasi.", "info")
            return
        menu = QMenu(self)
        for mode in C.SWITCHABLE_MODES:
            act = menu.addAction(C.MODE_LONG_NAMES[mode])
            act.setCheckable(True)
            act.setChecked(mode == ds.mode)
            act.triggered.connect(lambda _=False, m=mode: self._switch(m))
        menu.exec(self.mode_btn.mapToGlobal(self.mode_btn.rect().bottomLeft()))

    def _switch(self, mode: int) -> None:
        if mode == self.ctx.client.device_state.mode:
            return
        self.ctx.client.switch_mode(mode)
        self.mode_btn.setText(C.MODE_NAMES[mode] + "   ▾")
        self.ctx.toast(f"Mengganti mode ke {C.MODE_LONG_NAMES[mode]}…", "info")

    # ----------------------------------------------------------- factory reset
    def _factory_reset(self) -> None:
        if not self.ctx.client.is_ready:
            return
        if not confirm(self, "Reset ke pengaturan pabrik",
                       "Profil mode saat ini (sudut, FFB, physics, kurva pedal, dan pemetaan tombol) akan "
                       "dikembalikan ke default pabrik. Lanjutkan?", ok="Reset", danger=True):
            return
        d = StyledDialog(self, "Mereset…", width=320)
        d.root.addWidget(label("Menunggu perangkat mengonfirmasi dan membaca ulang profil…", "dim", wrap=True))
        self._loading = d
        d.setWindowFlag(Qt.WindowCloseButtonHint, False)
        d.show()
        self.ctx.client.write_profile_reset()
        QTimer.singleShot(10000, self._reset_timeout)

    def _dismiss_loading(self) -> None:
        if self._loading is not None:
            self._loading.accept()
            self._loading = None
            self.ctx.toast("Profil dikembalikan ke default pabrik", "ok")

    def _reset_timeout(self) -> None:
        if self._loading is not None:
            self._loading.accept()
            self._loading = None
            self.ctx.toast("Tidak ada konfirmasi reset dari setir (timeout). Periksa koneksi.", "error")
