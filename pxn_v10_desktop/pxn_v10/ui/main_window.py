"""Main window: sidebar navigation, stacked pages, toast host, connection footer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.events import ConnState
from . import icons, theme
from .context import AppContext
from .pages.connect_page import ConnectPage
from .pages.dashboard_page import DashboardPage
from .pages.info_page import InfoPage
from .pages.ini_page import IniPage
from .pages.profiles_page import ProfilesPage
from .pages.speedometer_page import SpeedometerPage
from .pages.templates_page import TemplatesPage
from .pages.test_page import TestPage
from .pages.usb_page import UsbPage
from .widgets.common import StatusDot, Toast, button, label

NAV = (
    ("connect", "Koneksi", "connect", False),
    ("dashboard", "Dashboard", "dashboard", True),
    ("test", "Test sensor", "test", True),
    ("speedo", "Speedometer", "speed", False),
    ("template", "Template && FFB", "template", False),
    ("usb", "Perangkat USB", "usb", False),
    ("presets", "Game Presets", "presets", False),
    ("ini", "INI Presets", "ini", False),
    ("info", "Info && Pengaturan", "info", False),
)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("PXN V10 Desktop")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 720)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ----------------------------------------------------------- sidebar
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 22, 16, 18)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        mark = QFrame()
        mark.setFixedSize(34, 34)
        mark.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {theme.ACCENT}, stop:1 {theme.ACCENT_2});"
            "border-radius: 10px;")
        brand.addWidget(mark)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(label("PXN V10", "h2"))
        bt.addWidget(label("DESKTOP CONFIGURATOR", "muted"))
        brand.addLayout(bt, 1)
        sv.addLayout(brand)
        sv.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: dict[str, QPushButton] = {}
        self.needs_connection: dict[str, bool] = {}
        for key, text, icon, needs in NAV:
            b = QPushButton("  " + text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setIcon(icons.nav_icon(icon))
            b.setIconSize(b.iconSize() * 1.0)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(b)
            sv.addWidget(b)
            self.nav[key] = b
            self.needs_connection[key] = needs
        sv.addStretch(1)

        foot = QFrame()
        foot.setObjectName("cardInner")
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(14, 12, 14, 12)
        fv.setSpacing(8)
        row = QHBoxLayout()
        self.dot = StatusDot(theme.TEXT_MUTED, 9)
        row.addWidget(self.dot)
        self.foot_status = label("Tidak terhubung", "h3")
        row.addWidget(self.foot_status, 1)
        fv.addLayout(row)
        self.foot_detail = label("PXN-V10", "muted")
        fv.addWidget(self.foot_detail)
        self.foot_btn = button("Putuskan", "ghost")
        self.foot_btn.clicked.connect(self._foot_clicked)
        fv.addWidget(self.foot_btn)
        sv.addWidget(foot)
        lay.addWidget(side)

        # ------------------------------------------------------------ pages
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {
            "connect": ConnectPage(ctx),
            "dashboard": DashboardPage(ctx),
            "test": TestPage(ctx),
            "speedo": SpeedometerPage(ctx),
            "template": TemplatesPage(ctx),
            "usb": UsbPage(ctx),
            "presets": ProfilesPage(ctx),
            "ini": IniPage(ctx),
            "info": InfoPage(ctx),
        }
        for w in self.pages.values():
            self.stack.addWidget(w)

        self.toast = Toast(central)
        ctx.toastRequested.connect(self.toast.show_message)
        ctx.navigateRequested.connect(self.show_page)
        ctx.bridge.connChanged.connect(self._conn_changed)
        ctx.bridge.changed.connect(lambda _k, _d: self._conn_changed(None))
        ctx.bridge.errorRaised.connect(lambda m: ctx.toast(m, "error"))
        ctx.clientReplaced.connect(lambda: self._conn_changed(None))

        self._current = ""
        self.show_page("connect")
        self._conn_changed(None)

    # ------------------------------------------------------------ navigation
    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        if self.needs_connection.get(key) and not self.ctx.connected:
            self.ctx.toast("Hubungkan setir terlebih dahulu.", "info")
            key = "connect"
        if self._current == "test" and key != "test":
            self.pages["test"].deactivate()  # type: ignore[attr-defined]
        self._current = key
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)
        if key == "test":
            self.pages["test"].activate()  # type: ignore[attr-defined]

    def _conn_changed(self, _ev) -> None:
        client = self.ctx.client
        st = client.state
        ready = st == ConnState.READY
        for key, needs in self.needs_connection.items():
            if needs:
                self.nav[key].setEnabled(ready)
        names = {
            ConnState.DISCONNECTED: ("Tidak terhubung", theme.TEXT_MUTED),
            ConnState.SCANNING: ("Memindai…", theme.AMBER),
            ConnState.READY: ("Terhubung", theme.GREEN),
            ConnState.RECONNECTING: ("Menyambung ulang…", theme.AMBER),
        }
        text, color = names.get(st, ("Menyambung…", theme.AMBER))
        self.foot_status.setText(text)
        self.dot.set_color(color)
        sim = " (Simulator)" if self.ctx.simulator else ""
        ds = client.device_state
        self.foot_detail.setText(f"{'Simulator · ' if sim else ''}FW {ds.major_ver}.{ds.minor_ver}" if ready
                                 else ("Simulator" if sim else "PXN-V10"))
        self.foot_btn.setText("Putuskan" if ready else "Ke halaman koneksi")
        self.foot_btn.setVisible(st != ConnState.SCANNING)
        if ready and self._current == "connect":
            self.show_page("dashboard")
        elif not ready and self.needs_connection.get(self._current):
            self.show_page("connect")

    def _foot_clicked(self) -> None:
        if self.ctx.connected:
            self.ctx.client.disconnect()
        else:
            self.show_page("connect")

    # ---------------------------------------------------------------- events
    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.reposition()

    def changeEvent(self, e) -> None:  # leaving the foreground = onPause for the test screen
        super().changeEvent(e)
        if e.type().name == "WindowStateChange" and self._current == "test":
            test = self.pages["test"]
            if self.isMinimized():
                test.deactivate()  # type: ignore[attr-defined]
            else:
                test.activate()  # type: ignore[attr-defined]

    def closeEvent(self, e: QCloseEvent) -> None:
        try:
            self.pages["test"].deactivate()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        self.ctx.shutdown()
        super().closeEvent(e)
