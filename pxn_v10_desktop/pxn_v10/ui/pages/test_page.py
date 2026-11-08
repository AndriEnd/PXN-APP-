"""Live telemetry screen (V10TestActivity): steering gauge, pedal bars, gear badge and button
highlighting. Test mode is entered when the page is shown and left when it is hidden, the window is
minimised, or the connection drops (onResume / onPause semantics)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ...core.events import Change, ConnState
from .. import theme
from ..context import AppContext
from ..widgets.common import CardPanel, SegmentedBar, label
from ..widgets.gauges import GearBadge, PedalBar, SteeringGauge
from ..widgets.mapping_views import BrakeMappingView, LeverMappingView, PedalMappingView, WheelMappingView


class TestPage(QWidget):
    __test__ = False

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(18)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("DIAGNOSTIK", "eyebrow"))
        col.addWidget(label("Test sensor & tombol", "h1"))
        head.addLayout(col, 1)
        self.stream_label = label("● Menunggu data…", "dim")
        head.addWidget(self.stream_label, 0, Qt.AlignBottom)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # left column: steering + pedals + gear
        left = QVBoxLayout()
        left.setSpacing(16)
        steer = CardPanel("Steering angle", "Sudut sensor kemudi secara real-time.")
        self.gauge = SteeringGauge()
        steer.body.addWidget(self.gauge, 1)
        left.addWidget(steer, 5)

        row = QHBoxLayout()
        row.setSpacing(16)
        pedals = CardPanel("Pedal")
        pb = QHBoxLayout()
        pb.setSpacing(6)
        self.bar_acc = PedalBar("Gas", theme.GREEN)
        self.bar_brake = PedalBar("Rem", theme.RED)
        self.bar_clutch = PedalBar("Kopling", theme.BLUE)
        for b in (self.bar_clutch, self.bar_brake, self.bar_acc):
            pb.addWidget(b)
        pedals.body.addLayout(pb, 1)
        gear = CardPanel("Gigi aktif")
        self.gear = GearBadge()
        gear.body.addWidget(self.gear, 1)
        row.addWidget(pedals, 3)
        row.addWidget(gear, 2)
        left.addLayout(row, 4)
        body.addLayout(left, 4)

        # right column: button matrices
        right = CardPanel("Matriks tombol", "Tombol menyala hijau saat ditekan pada perangkat.")
        self.tabs = SegmentedBar()
        right.body.addWidget(self.tabs, 0, Qt.AlignLeft)
        self.views = QStackedWidget()
        self.v_wheel = WheelMappingView(interactive=False)
        self.v_pedal = PedalMappingView(interactive=False)
        self.v_lever = LeverMappingView(interactive=False)
        self.v_brake = BrakeMappingView(interactive=False)
        self._pages = {"wheel": self.v_wheel, "pedal": self.v_pedal, "lever": self.v_lever, "brake": self.v_brake}
        for v in self._pages.values():
            self.views.addWidget(v)
        right.body.addWidget(self.views, 1)
        body.addWidget(right, 5)
        self.tabs.currentChanged.connect(lambda k: self.views.setCurrentWidget(self._pages[k]))

        b = ctx.bridge
        b.testFrame.connect(self._frame)
        b.changed.connect(self._changed)
        b.connChanged.connect(self._conn)
        ctx.clientReplaced.connect(self._reset)
        self._configure_tabs()

    # --------------------------------------------------------------- lifecycle
    def activate(self) -> None:
        """Page became visible -> V10TestActivity.onResume."""
        self._active = True
        self._configure_tabs()
        client = self.ctx.client
        for v in self._pages.values():
            v.set_keymap(client.profile.keymap)
            v.set_mode(client.device_state.mode)
        self.gauge.set_range(client.profile.angle)
        if client.is_ready:
            client.toggle_test_mode(True)

    def deactivate(self) -> None:
        """Page hidden / window minimised -> onPause."""
        if not self._active:
            return
        self._active = False
        if self.ctx.client.is_ready:
            self.ctx.client.toggle_test_mode(False)
        self._reset()

    def _reset(self) -> None:
        self.gauge.reset()
        for bar in (self.bar_acc, self.bar_brake, self.bar_clutch):
            bar.reset()
        self.gear.set_gear("N")
        for v in self._pages.values():
            v.set_pressed({})
        self.stream_label.setText("● Menunggu data…")

    def _configure_tabs(self) -> None:
        ds = self.ctx.client.device_state
        items = [("wheel", "WHEEL")]
        if ds.has_pedal:
            items.append(("pedal", "PEDAL"))
        if ds.has_lever:
            items.append(("lever", "SHIFTER"))
        if ds.has_brake:
            items.append(("brake", "HANDBRAKE"))
        self.tabs.set_items(items, keep=True)

    # ------------------------------------------------------------------ events
    def _frame(self, snap) -> None:
        if not self._active:
            return
        self.gauge.set_fraction(snap.fraction)
        self.bar_acc.set_raw(snap.acc)
        self.bar_brake.set_raw(snap.brake)
        self.bar_clutch.set_raw(snap.clutch)
        self.gear.set_gear(snap.gear)
        for v in self._pages.values():
            v.set_pressed(snap.pressed)
        self.stream_label.setText("● Data langsung")
        self.stream_label.setStyleSheet(f"color: {theme.GREEN};")

    def _changed(self, kind: int, _d: int) -> None:
        if kind == Change.ANGLE:  # AngleTestView.setMax follows the configured angle
            self.gauge.set_range(self.ctx.client.profile.angle)
        elif kind == Change.STATE:
            self._configure_tabs()

    def _conn(self, ev) -> None:
        if ev.state != ConnState.READY and self._active:
            self._active = False
            self._reset()
        elif ev.state == ConnState.READY and self.isVisible():
            self.activate()
