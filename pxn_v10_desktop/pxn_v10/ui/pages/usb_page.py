"""Perangkat USB: deteksi setir / shifter / handbrake sebagai USB Game Controller, test langsung, dan
konfigurasi (kalibrasi sumbu, pemetaan gigi, mode handbrake). Konfigurasi disimpan di PC."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...usb import config as U
from ...usb.devices import UsbDevice, list_com_ports
from .. import theme
from ..context import AppContext
from ..widgets.common import CardPanel, Chip, SegmentedBar, StatusDot, button, label
from ..widgets.gauges import GearBadge, SteeringGauge
from ..widgets.usb_widgets import AxisBar, AxisConfigRow, ButtonGrid, ShifterPattern

PROBE_AXIS_SECONDS = 3.0
PROBE_BUTTON_SECONDS = 8.0
ROLE_COLORS = {U.ROLE_WHEEL: theme.ACCENT, U.ROLE_PEDALS: theme.GREEN, U.ROLE_SHIFTER: theme.BLUE,
               U.ROLE_HANDBRAKE: theme.AMBER, U.ROLE_OTHER: theme.TEXT_DIM}


class DeviceRow(QFrame):
    def __init__(self, dev: UsbDevice, role: str, selected: bool, on_click) -> None:
        super().__init__()
        self.setObjectName("cardInner")
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        self.key = dev.key
        if selected:
            self.setStyleSheet(f"QFrame#cardInner {{ border: 1px solid {theme.ACCENT}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        lay.addWidget(StatusDot(theme.GREEN if dev.readable else theme.AMBER, 9))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(dev.name, "h3"))
        col.addWidget(label(f"{dev.id_text}  ·  {dev.summary}", "muted"))
        col.addSpacing(3)
        col.addWidget(Chip(U.ROLE_TITLES[role].upper(), ROLE_COLORS[role]), 0, Qt.AlignLeft)
        lay.addLayout(col, 1)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._on_click(self.key)


class UsbPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.devices: list = []
        self.dev: UsbDevice | None = None
        self.ds = U.DeviceSettings()
        self.decoder = U.ShifterDecoder(self.ds.shifter)
        self._loading = False
        self._state = None
        self._axis_probe: dict | None = None
        self._btn_probe: dict | None = None
        self.com_labels: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(18)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("PERANGKAT USB", "eyebrow"))
        col.addWidget(label("Setir, shifter & handbrake lewat USB", "h1"))
        head.addLayout(col, 1)
        self.count_label = label("", "dim")
        head.addWidget(self.count_label, 0, Qt.AlignBottom)
        self.refresh_btn = button("Segarkan", "ghost")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn, 0, Qt.AlignBottom)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ------------------------------------------------------------- left column
        left_host = QWidget()
        left_host.setFixedWidth(372)
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(16)
        self.list_card = CardPanel("Terdeteksi", "Terpasang sebagai USB Game Controller; hot-plug otomatis.")
        self.rows_host = QVBoxLayout()
        self.rows_host.setSpacing(8)
        self.list_card.body.addLayout(self.rows_host)
        self.empty = label("Belum ada perangkat USB game controller. Hubungkan setir, shifter atau handbrake "
                           "dengan kabel USB — perangkat muncul di sini otomatis.", "dim", wrap=True)
        self.list_card.body.addWidget(self.empty)
        left.addWidget(self.list_card)

        self.com_card = CardPanel("Port COM", "Perangkat serial USB (mis. shifter/handbrake DIY berbasis Arduino).")
        self.com_host = QVBoxLayout()
        self.com_host.setSpacing(6)
        self.com_card.body.addLayout(self.com_host)
        left.addWidget(self.com_card)

        cfg = CardPanel("Konfigurasi setir lewat USB")
        self.usb_cfg_text = label("", "dim", wrap=True)
        cfg.body.addWidget(self.usb_cfg_text)
        self.usb_cfg_btn = button("Sambung lewat USB…", "primary")
        self.usb_cfg_btn.clicked.connect(self._open_usb_connect)
        cfg.body.addWidget(self.usb_cfg_btn)
        left.addWidget(cfg)
        left.addStretch(1)
        body.addWidget(left_host)

        # ------------------------------------------------------------ right column
        self.detail = CardPanel("")
        self.title = label("Pilih perangkat", "h2")
        self.sub = label("", "muted")
        t = QVBoxLayout()
        t.setSpacing(0)
        t.addWidget(self.title)
        t.addWidget(self.sub)
        self.detail.header.insertLayout(0, t)
        self.role_combo = QComboBox()
        for r in U.ROLES:
            self.role_combo.addItem(U.ROLE_TITLES[r], r)
        self.role_combo.currentIndexChanged.connect(self._role_changed)
        self.role_combo.setToolTip("Peran perangkat menentukan tampilan test dan opsi konfigurasi")
        self.detail.add_header_widget(label("Peran", "muted"))
        self.detail.add_header_widget(self.role_combo)
        self.tabs = SegmentedBar()
        self.tabs.set_items([("test", "TEST"), ("config", "KONFIGURASI")])
        self.tabs.currentChanged.connect(self._tab_changed)
        self.detail.body.addWidget(self.tabs, 0, Qt.AlignLeft)
        self.stack = QStackedWidget()
        self.detail.body.addWidget(self.stack, 1)
        self.stack.addWidget(self._scroll(self._build_test()))
        self.stack.addWidget(self._scroll(self._build_config()))
        self.placeholder = label("Pilih salah satu perangkat di sebelah kiri untuk mengetes dan mengonfigurasinya.",
                                 "dim", wrap=True, align=Qt.AlignCenter)
        self.detail.body.addWidget(self.placeholder, 1)
        body.addWidget(self.detail, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._poll)
        ctx.usbDevicesChanged.connect(self.set_devices)
        ctx.clientReplaced.connect(self._update_usb_card)
        self.set_devices(list(ctx.usb_monitor.devices))
        self._update_usb_card()
        self._show_selection()

    # =========================================================== construction
    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.NoFrame)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        s.setWidget(w)
        return s

    def _build_test(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)

        # --- setir / pedal
        self.t_wheel = QWidget()
        wl = QHBoxLayout(self.t_wheel)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(16)
        self.gauge = SteeringGauge()
        wl.addWidget(self.gauge, 3)
        pedals = QVBoxLayout()
        pedals.setSpacing(6)
        self.b_steer = AxisBar("Kemudi", theme.ACCENT, bipolar=True)
        self.b_acc = AxisBar("Gas", theme.GREEN)
        self.b_brake = AxisBar("Rem", theme.RED)
        self.b_clutch = AxisBar("Kopling", theme.BLUE)
        for b in (self.b_steer, self.b_acc, self.b_brake, self.b_clutch):
            pedals.addWidget(b)
        pedals.addStretch(1)
        wl.addLayout(pedals, 2)
        lay.addWidget(self.t_wheel)

        # --- shifter
        self.t_shifter = QWidget()
        sl = QHBoxLayout(self.t_shifter)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(16)
        self.pattern = ShifterPattern()
        self.gear = GearBadge()
        sl.addWidget(self.pattern, 3)
        sl.addWidget(self.gear, 2)
        lay.addWidget(self.t_shifter)

        # --- handbrake
        self.t_hand = QWidget()
        hl = QVBoxLayout(self.t_hand)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("TARIKAN HANDBRAKE", "eyebrow"))
        top.addStretch(1)
        self.hand_chip = Chip("DILEPAS", theme.TEXT_DIM)
        top.addWidget(self.hand_chip)
        hl.addLayout(top)
        self.b_hand = AxisBar("Posisi", theme.AMBER)
        hl.addWidget(self.b_hand)
        lay.addWidget(self.t_hand)

        # --- tombol + sumbu mentah (semua peran)
        raw = CardPanel("Sumbu mentah", "Nilai langsung dari perangkat sebelum kalibrasi.")
        self.raw_bars = [AxisBar(f"Sumbu {n + 1}", theme.TEXT_DIM) for n in range(10)]
        for b in self.raw_bars:
            raw.body.addWidget(b)
        self.raw_card = raw
        lay.addWidget(raw)
        btn = CardPanel("Tombol", "Menyala hijau saat ditekan.")
        self.grid = ButtonGrid()
        btn.body.addWidget(self.grid)
        self.btn_card = btn
        lay.addWidget(btn)
        lay.addStretch(1)
        return host

    def _build_config(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        self.cfg_note = label("", "muted", wrap=True)
        self.cfg_note.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 10px 12px;")
        lay.addWidget(self.cfg_note)

        # --- setir / pedal
        self.c_wheel = QWidget()
        cw = QVBoxLayout(self.c_wheel)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.setSpacing(10)
        self.row_steer = AxisConfigRow("Kemudi", theme.ACCENT)
        self.row_acc = AxisConfigRow("Gas", theme.GREEN)
        self.row_brake = AxisConfigRow("Rem", theme.RED)
        self.row_clutch = AxisConfigRow("Kopling", theme.BLUE, optional=True)
        self.wheel_rows = {"steer": self.row_steer, "acc": self.row_acc, "brake": self.row_brake,
                           "clutch": self.row_clutch}
        for name, row in self.wheel_rows.items():
            cw.addWidget(row)
            self._wire_axis_row(row, lambda n=name: getattr(self.ds.wheel, n))
        lock = QHBoxLayout()
        lock.addWidget(label("Rentang kunci-ke-kunci untuk tampilan derajat", "muted"))
        lock.addStretch(1)
        self.lock_spin = QSpinBox()
        self.lock_spin.setRange(90, 3600)
        self.lock_spin.setSingleStep(10)
        self.lock_spin.setSuffix("°")
        self.lock_spin.valueChanged.connect(self._lock_changed)
        lock.addWidget(self.lock_spin)
        cw.addLayout(lock)
        lay.addWidget(self.c_wheel)

        # --- handbrake
        self.c_hand = QWidget()
        ch = QVBoxLayout(self.c_hand)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(10)
        mode = QHBoxLayout()
        mode.addWidget(label("Jenis handbrake", "muted"))
        self.hand_mode = QComboBox()
        self.hand_mode.addItem("Analog (sumbu)", "analog")
        self.hand_mode.addItem("Tombol (on/off)", "button")
        self.hand_mode.currentIndexChanged.connect(self._hand_changed)
        mode.addWidget(self.hand_mode)
        mode.addStretch(1)
        mode.addWidget(label("Ambang aktif", "muted"))
        self.hand_thr = QSpinBox()
        self.hand_thr.setRange(1, 90)
        self.hand_thr.setSuffix("%")
        self.hand_thr.valueChanged.connect(self._hand_changed)
        mode.addWidget(self.hand_thr)
        ch.addLayout(mode)
        self.row_hand = AxisConfigRow("Handbrake", theme.AMBER)
        self._wire_axis_row(self.row_hand, lambda: self.ds.handbrake.cal)
        ch.addWidget(self.row_hand)
        self.hand_btn_box = QFrame()
        self.hand_btn_box.setObjectName("cardInner")
        hb = QHBoxLayout(self.hand_btn_box)
        hb.setContentsMargins(14, 10, 14, 10)
        hb.addWidget(label("TOMBOL HANDBRAKE", "eyebrow"))
        hb.addStretch(1)
        self.hand_btn_label = label("—", "h3")
        hb.addWidget(self.hand_btn_label)
        self.hand_learn = button("Pelajari", "ghost")
        self.hand_learn.clicked.connect(lambda: self._learn_button(self.hand_learn, self._set_hand_button))
        hb.addWidget(self.hand_learn)
        ch.addWidget(self.hand_btn_box)
        lay.addWidget(self.c_hand)

        # --- shifter
        self.c_shift = QWidget()
        cs = QVBoxLayout(self.c_shift)
        cs.setContentsMargins(0, 0, 0, 0)
        cs.setSpacing(10)
        kind = QHBoxLayout()
        kind.addWidget(label("Jenis shifter", "muted"))
        self.shift_kind = QComboBox()
        self.shift_kind.addItem("H-pattern (satu tombol per gigi)", "h")
        self.shift_kind.addItem("Sekuensial (naik / turun)", "seq")
        self.shift_kind.currentIndexChanged.connect(self._shift_kind_changed)
        kind.addWidget(self.shift_kind)
        kind.addStretch(1)
        cs.addLayout(kind)
        self.h_box = QFrame()
        self.h_box.setObjectName("cardInner")
        hv = QVBoxLayout(self.h_box)
        hv.setContentsMargins(14, 12, 14, 12)
        hv.setSpacing(6)
        hv.addWidget(label("PEMETAAN GIGI → TOMBOL", "eyebrow"))
        hv.addWidget(label("Klik “Pelajari”, lalu masukkan tuas ke gigi tersebut (atau tekan tombolnya).", "muted",
                           wrap=True))
        self.gear_labels: dict = {}
        self.gear_learn: dict = {}
        for g in U.GEARS:
            row = QHBoxLayout()
            row.addWidget(label("Gigi " + ("mundur (R)" if g == "R" else g), "h3"))
            row.addStretch(1)
            lb = label("—", "dim")
            lb.setMinimumWidth(80)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.gear_labels[g] = lb
            row.addWidget(lb)
            b = button("Pelajari", "ghost")
            b.clicked.connect(lambda _=False, gg=g, bb=b: self._learn_button(bb, lambda idx, gx=gg: self._set_gear(gx, idx)))
            self.gear_learn[g] = b
            row.addWidget(b)
            hv.addLayout(row)
        cs.addWidget(self.h_box)
        self.seq_box = QFrame()
        self.seq_box.setObjectName("cardInner")
        sv = QVBoxLayout(self.seq_box)
        sv.setContentsMargins(14, 12, 14, 12)
        sv.setSpacing(6)
        sv.addWidget(label("TOMBOL SEKUENSIAL", "eyebrow"))
        self.seq_labels: dict = {}
        self.seq_learn: dict = {}
        for key, title in (("up", "Naik (upshift)"), ("down", "Turun (downshift)")):
            row = QHBoxLayout()
            row.addWidget(label(title, "h3"))
            row.addStretch(1)
            lb = label("—", "dim")
            self.seq_labels[key] = lb
            row.addWidget(lb)
            b = button("Pelajari", "ghost")
            b.clicked.connect(lambda _=False, k=key, bb=b: self._learn_button(bb, lambda idx, kk=k: self._set_seq(kk, idx)))
            self.seq_learn[key] = b
            row.addWidget(b)
            sv.addLayout(row)
        mx = QHBoxLayout()
        mx.addWidget(label("Gigi tertinggi", "h3"))
        mx.addStretch(1)
        self.seq_max = QSpinBox()
        self.seq_max.setRange(1, 10)
        self.seq_max.valueChanged.connect(self._seq_max_changed)
        mx.addWidget(self.seq_max)
        sv.addLayout(mx)
        cs.addWidget(self.seq_box)
        lay.addWidget(self.c_shift)

        foot = QHBoxLayout()
        foot.addWidget(label("Perubahan tersimpan otomatis di PC ini.", "muted"))
        foot.addStretch(1)
        reset = button("Reset ke bawaan", "ghost")
        reset.clicked.connect(self._reset_config)
        foot.addWidget(reset)
        lay.addLayout(foot)
        lay.addStretch(1)
        return host

    def _wire_axis_row(self, row: AxisConfigRow, getter) -> None:
        row.changed.connect(self._save)
        row.detectRequested.connect(lambda: self._detect_axis(row, getter))
        row.setMinRequested.connect(lambda: self._set_extent(row, getter, "min"))
        row.setMaxRequested.connect(lambda: self._set_extent(row, getter, "max"))

    # ============================================================== devices
    def refresh(self) -> None:
        self.ctx.usb_monitor.refresh_now()
        self._update_com()

    def set_devices(self, devices: list) -> None:
        self.devices = list(devices)
        keys = [d.key for d in self.devices]
        if self.dev is None or self.dev.key not in keys:
            self.dev = self.devices[0] if self.devices else None
            self._load_device()
        else:
            self.dev = next(d for d in self.devices if d.key == self.dev.key)
        self._rebuild_rows()
        n = len(self.devices)
        self.count_label.setText(f"{n} perangkat terdeteksi" if n else "Tidak ada perangkat")
        self._update_com()
        self._update_usb_card()
        self._show_selection()

    def _rebuild_rows(self) -> None:
        while self.rows_host.count():
            it = self.rows_host.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for d in self.devices:
            role = self.ctx.usb_settings(d.key, d.guessed_role).role
            self.rows_host.addWidget(DeviceRow(d, role, self.dev is not None and d.key == self.dev.key, self.select))
        self.empty.setVisible(not self.devices)

    def select(self, key: str) -> None:
        self._cancel_probes()
        self.dev = next((d for d in self.devices if d.key == key), None)
        self._load_device()
        self._rebuild_rows()
        self._show_selection()

    def _load_device(self) -> None:
        self._loading = True
        dev = self.dev
        if dev is None:
            self.ds = U.DeviceSettings()
            self._loading = False
            return
        self.ds = self.ctx.usb_settings(dev.key, dev.guessed_role)
        self.decoder = U.ShifterDecoder(self.ds.shifter)
        labels = dev.joy.axis_labels() if dev.joy else []
        for row in (*self.wheel_rows.values(), self.row_hand):
            row.set_axes(labels)
        for name, row in self.wheel_rows.items():
            row.set_calibration(getattr(self.ds.wheel, name))
        self.row_hand.set_calibration(self.ds.handbrake.cal)
        self.role_combo.setCurrentIndex(U.ROLES.index(self.ds.role))
        self.lock_spin.setValue(self.ds.wheel.lock_degrees)
        self.gauge.set_range(self.ds.wheel.lock_degrees)
        self.hand_mode.setCurrentIndex(0 if self.ds.handbrake.mode == "analog" else 1)
        self.hand_thr.setValue(int(round(self.ds.handbrake.threshold * 100)))
        self.shift_kind.setCurrentIndex(0 if self.ds.shifter.kind == "h" else 1)
        self.seq_max.setValue(self.ds.shifter.seq_max)
        self.grid.set_count(dev.joy.n_buttons if dev.joy else 0)
        for n, b in enumerate(self.raw_bars):
            b.setVisible(dev.joy is not None and n < dev.joy.n_axes)
            if dev.joy is not None and n < dev.joy.n_axes:
                b.title = f"Sumbu {dev.joy.axis_label(n)}"
                b.update()
        self._refresh_labels()
        self._loading = False
        self._apply_role()

    def _show_selection(self) -> None:
        has = self.dev is not None
        self.tabs.setVisible(has)
        self.stack.setVisible(has)
        self.placeholder.setVisible(not has)
        self.role_combo.setEnabled(has)
        if has:
            self.title.setText(self.dev.name)
            self.sub.setText(f"{self.dev.id_text}  ·  {self.dev.summary}"
                             + ("" if self.dev.readable else "  ·  tidak terbaca sebagai joystick"))
        else:
            self.title.setText("Pilih perangkat")
            self.sub.setText("")
        self._sync_timer()

    # ================================================================ roles
    def _apply_role(self) -> None:
        role = self.ds.role
        wheel_like = role in (U.ROLE_WHEEL, U.ROLE_PEDALS)
        self.t_wheel.setVisible(wheel_like)
        self.gauge.setVisible(role == U.ROLE_WHEEL)
        self.b_steer.setVisible(role == U.ROLE_WHEEL)
        self.t_shifter.setVisible(role == U.ROLE_SHIFTER)
        self.t_hand.setVisible(role == U.ROLE_HANDBRAKE)
        self.c_wheel.setVisible(wheel_like)
        self.row_steer.setVisible(role == U.ROLE_WHEEL)
        self.c_hand.setVisible(role == U.ROLE_HANDBRAKE)
        self.c_shift.setVisible(role == U.ROLE_SHIFTER)
        self.raw_card.setVisible(True)
        notes = {
            U.ROLE_WHEEL: "Kalibrasi sisi-aplikasi untuk membaca setir lewat USB (tidak menulis ke firmware). "
                          "Untuk menulis konfigurasi ke firmware gunakan koneksi di kartu “Konfigurasi setir lewat USB”.",
            U.ROLE_PEDALS: "Tetapkan sumbu untuk Gas, Rem, dan Kopling; atur zona mati dan kurva.",
            U.ROLE_SHIFTER: "Pemetaan gigi disimpan di PC dan dipakai untuk menampilkan gigi aktif. "
                            "Firmware shifter USB tidak diubah.",
            U.ROLE_HANDBRAKE: "Kalibrasi tarikan handbrake: lepas penuh → Set min, tarik penuh → Set maks "
                              "(atau tekan Deteksi lalu tarik handbrake sampai habis).",
            U.ROLE_OTHER: "Peran belum ditentukan. Pilih peran di kanan atas untuk membuka opsi konfigurasi.",
        }
        self.cfg_note.setText(notes[role])
        self._refresh_labels()

    def _role_changed(self) -> None:
        if self._loading or self.dev is None:
            return
        self.ds.role = self.role_combo.currentData()
        self._save()
        self._apply_role()
        self._rebuild_rows()

    def _tab_changed(self, key: str) -> None:
        self.stack.setCurrentIndex(0 if key == "test" else 1)

    # ============================================================== saving
    def _save(self) -> None:
        if self._loading or self.dev is None:
            return
        self.ctx.save_usb_settings(self.dev.key, self.ds)
        self.decoder.cfg = self.ds.shifter

    def _lock_changed(self, v: int) -> None:
        if self._loading:
            return
        self.ds.wheel.lock_degrees = int(v)
        self.gauge.set_range(int(v))
        self._save()

    def _hand_changed(self) -> None:
        if self._loading:
            return
        self.ds.handbrake.mode = self.hand_mode.currentData()
        self.ds.handbrake.threshold = self.hand_thr.value() / 100
        self.row_hand.setVisible(self.ds.handbrake.mode == "analog")
        self.hand_btn_box.setVisible(self.ds.handbrake.mode == "button")
        self._save()

    def _shift_kind_changed(self) -> None:
        if self._loading:
            return
        self.ds.shifter.kind = self.shift_kind.currentData()
        self.decoder.reset()
        self._refresh_labels()
        self._save()

    def _seq_max_changed(self, v: int) -> None:
        if self._loading:
            return
        self.ds.shifter.seq_max = int(v)
        self._save()

    def _reset_config(self) -> None:
        if self.dev is None:
            return
        keep = self.ds.role
        self.ds = U.DeviceSettings(role=keep)
        self.ctx.save_usb_settings(self.dev.key, self.ds)
        self._load_device()
        self.ctx.toast("Konfigurasi perangkat dikembalikan ke bawaan", "info")

    def _refresh_labels(self) -> None:
        h = self.ds.handbrake
        self.row_hand.setVisible(h.mode == "analog")
        self.hand_btn_box.setVisible(h.mode == "button")
        self.hand_btn_label.setText("—" if h.button < 0 else f"Tombol {h.button + 1}")
        s = self.ds.shifter
        for g, lb in self.gear_labels.items():
            idx = s.gears.get(g)
            lb.setText("—" if idx is None or idx < 0 else f"Tombol {idx + 1}")
        self.seq_labels["up"].setText("—" if s.seq_up < 0 else f"Tombol {s.seq_up + 1}")
        self.seq_labels["down"].setText("—" if s.seq_down < 0 else f"Tombol {s.seq_down + 1}")
        self.h_box.setVisible(s.kind == "h")
        self.seq_box.setVisible(s.kind == "seq")

    # ============================================================ wizards
    def _read(self):
        dev = self.dev
        if dev is None or dev.joy is None or self.ctx.usb_backend is None:
            return None
        return self.ctx.usb_backend.read(dev.joy.slot)

    def _detect_axis(self, row: AxisConfigRow, getter) -> None:
        st = self._read()
        if st is None or not st.axes:
            self.ctx.toast("Perangkat ini tidak memiliki sumbu yang bisa dibaca", "error")
            return
        self._cancel_probes()
        probe = U.AxisProbe()
        probe.start(st, self.dev.joy.ranges)
        self._axis_probe = {"row": row, "get": getter, "probe": probe, "end": time.monotonic() + PROBE_AXIS_SECONDS}
        row.set_detecting(True, "Gerakkan…")

    def _finish_axis_probe(self) -> None:
        info, self._axis_probe = self._axis_probe, None
        row, probe = info["row"], info["probe"]
        row.set_detecting(False)
        idx = probe.result()
        if idx is None:
            self.ctx.toast("Tidak ada sumbu yang bergerak — coba lagi dan gerakkan kontrolnya hingga ujung", "error")
            return
        cal = info["get"]()
        cal.axis = idx
        lo, hi = probe.extent(idx)
        rng = self.dev.joy.ranges[idx]
        if (hi - lo) >= 0.5 * (rng[1] - rng[0]):  # gerakan penuh → sekalian kalibrasi min/maks
            cal.raw_min, cal.raw_max = lo, hi
        row.set_calibration(cal)
        self._save()
        self.ctx.toast(f"Sumbu {self.dev.joy.axis_label(idx)} terdeteksi", "ok")

    def _set_extent(self, row: AxisConfigRow, getter, which: str) -> None:
        st = self._read()
        cal = getter()
        if st is None or cal.axis < 0 or cal.axis >= len(st.axes):
            self.ctx.toast("Pilih sumbu terlebih dahulu", "error")
            return
        raw = int(st.axes[cal.axis])
        if which == "min":
            cal.raw_min = raw
        else:
            cal.raw_max = raw
        self._save()

    def _learn_button(self, btn, callback) -> None:
        st = self._read()
        if st is None:
            self.ctx.toast("Perangkat tidak terbaca", "error")
            return
        self._cancel_probes()
        probe = U.ButtonProbe()
        probe.start(st)
        btn.setText("Tekan tombol…")
        btn.setEnabled(False)
        self._btn_probe = {"btn": btn, "cb": callback, "probe": probe, "end": time.monotonic() + PROBE_BUTTON_SECONDS}

    def _finish_button_probe(self, found: int | None) -> None:
        info, self._btn_probe = self._btn_probe, None
        info["btn"].setText("Pelajari")
        info["btn"].setEnabled(True)
        if found is None:
            self.ctx.toast("Tidak ada tombol yang ditekan", "error")
            return
        info["cb"](found)
        self._refresh_labels()
        self._save()
        self.ctx.toast(f"Tombol {found + 1} terdeteksi", "ok")

    def _cancel_probes(self) -> None:
        if self._axis_probe is not None:
            self._axis_probe["row"].set_detecting(False)
            self._axis_probe = None
        if self._btn_probe is not None:
            self._btn_probe["btn"].setText("Pelajari")
            self._btn_probe["btn"].setEnabled(True)
            self._btn_probe = None

    def _set_hand_button(self, idx: int) -> None:
        self.ds.handbrake.button = idx

    def _set_gear(self, gear: str, idx: int) -> None:
        for g, v in list(self.ds.shifter.gears.items()):
            if v == idx and g != gear:  # satu tombol hanya untuk satu gigi
                del self.ds.shifter.gears[g]
        self.ds.shifter.gears[gear] = idx

    def _set_seq(self, key: str, idx: int) -> None:
        if key == "up":
            self.ds.shifter.seq_up = idx
        else:
            self.ds.shifter.seq_down = idx

    # =============================================================== polling
    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._cancel_probes()
        self._sync_timer()

    def _sync_timer(self) -> None:
        want = self.isVisible() and self.dev is not None and self.dev.readable
        if want and not self.timer.isActive():
            self.timer.start()
        elif not want and self.timer.isActive():
            self.timer.stop()

    def _poll(self) -> None:
        st = self._read()
        if st is None:
            return
        self._state = st
        dev, ds = self.dev, self.ds
        # wizards
        if self._axis_probe is not None:
            self._axis_probe["probe"].feed(st)
            left = self._axis_probe["end"] - time.monotonic()
            self._axis_probe["row"].set_detecting(True, f"Gerakkan… {max(0, int(left) + 1)}")
            if left <= 0:
                self._finish_axis_probe()
        if self._btn_probe is not None:
            found = self._btn_probe["probe"].feed(st)
            if found is not None or time.monotonic() >= self._btn_probe["end"]:
                self._finish_button_probe(found)
        role = ds.role
        self.grid.set_state(st.buttons, st.pov)
        for i, bar in enumerate(self.raw_bars):
            if i < len(st.axes) and dev.joy is not None:
                lo, hi = dev.joy.ranges[i]
                bar.set_value((st.axes[i] - lo) / (hi - lo) if hi > lo else 0.0, f"{st.axes[i]}")
        if role in (U.ROLE_WHEEL, U.ROLE_PEDALS):
            w = ds.wheel
            steer = None
            if role == U.ROLE_WHEEL and 0 <= w.steer.axis < len(st.axes):
                steer = w.steer.bipolar(st.axes[w.steer.axis])
                self.gauge.set_fraction(steer)
                self.b_steer.set_value(steer, f"{steer * w.lock_degrees / 2:+.0f}°")
            for bar, cal in ((self.b_acc, w.acc), (self.b_brake, w.brake), (self.b_clutch, w.clutch)):
                v = cal.read(st)
                bar.setVisible(cal.axis >= 0)
                bar.set_value(0.0 if v is None else v)
            for name, row in self.wheel_rows.items():
                cal = getattr(w, name)
                raw = st.axes[cal.axis] if 0 <= cal.axis < len(st.axes) else None
                row.show_live(raw, None if raw is None else cal.normalize(raw))
        elif role == U.ROLE_SHIFTER:
            gear = self.decoder.update(st)
            self.pattern.set_gear(gear)
            self.gear.set_gear(gear)
        elif role == U.ROLE_HANDBRAKE:
            value, on = ds.handbrake.decode(st)
            self.b_hand.set_value(value)
            self.hand_chip.setText("DITARIK" if on else "DILEPAS")
            self.hand_chip.set_style(theme.AMBER if on else theme.TEXT_DIM)
            cal = ds.handbrake.cal
            raw = st.axes[cal.axis] if 0 <= cal.axis < len(st.axes) else None
            self.row_hand.show_live(raw, None if raw is None else cal.normalize(raw))

    # ============================================================== USB wheel card
    def _update_com(self) -> None:
        for lb in self.com_labels:
            lb.setParent(None)
            lb.deleteLater()
        self.com_labels = []
        ports = list_com_ports() if not self.ctx.simulator else []
        if not ports:
            lbs = [label("Tidak ada port COM terdeteksi.", "dim")]
        else:
            lbs = [label(f"{p.name}  ·  {'USB serial' if p.is_usb else p.device}", "h3") for p in ports]
            lbs.append(label("Port COM terdeteksi dan dicantumkan. Protokol serial perangkat DIY berbeda-beda dan "
                             "tidak diketahui aplikasi, jadi data port tidak dibaca.", "muted", wrap=True))
        for lb in lbs:
            self.com_host.addWidget(lb)
        self.com_labels = lbs

    def _update_usb_card(self) -> None:
        cands = [(d, h) for d in self.devices for h in d.config_interfaces]
        using = self.ctx.link == "usb"
        if cands:
            d, h = cands[0]
            self.usb_cfg_text.setText(
                f"Antarmuka konfigurasi HID ditemukan pada {d.name} (Usage Page 0x{h.usage_page:04X}). "
                "Eksperimental: protokol USB firmware PXN V10 tidak terdokumentasi. Aplikasi hanya mengirim satu "
                "permintaan baca; bila setir tidak menjawab, koneksi dibatalkan tanpa menulis apa pun.")
            self.usb_cfg_btn.setText("Sudah memakai USB — buka koneksi" if using else "Sambung lewat USB…")
            self.usb_cfg_btn.setEnabled(True)
        else:
            self.usb_cfg_text.setText(
                "Tidak ada antarmuka konfigurasi (HID vendor-defined) pada perangkat yang terdeteksi. Test dan "
                "kalibrasi tetap berfungsi lewat USB di halaman ini; konfigurasi firmware setir memakai Bluetooth.")
            self.usb_cfg_btn.setText("Coba sambung lewat USB…")
            self.usb_cfg_btn.setEnabled(True)

    def _open_usb_connect(self) -> None:
        self.ctx.use_link("usb")
        self.ctx.navigate("connect")

    def closeEvent(self, e) -> None:  # pragma: no cover
        self.timer.stop()
        super().closeEvent(e)

