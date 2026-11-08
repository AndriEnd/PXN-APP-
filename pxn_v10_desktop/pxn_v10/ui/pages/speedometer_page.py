"""Speedometer: gauge kecepatan, RPM dan gigi dari telemetri UDP game (Forza Horizon 4/5, DiRT Rally 2.0).

Sama seperti tab "Meter" pada aplikasi asli: game mengirim data ke ``IP:Port`` komputer ini (UDP 9000 secara
bawaan). Data TIDAK berasal dari setir - firmware V10 tidak punya sensor atau jalur kecepatan."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QVBoxLayout, QWidget

from ...telemetry import simulator
from ...telemetry.models import Telemetry, format_lap_time
from ...telemetry.receiver import DEFAULT_PORT, UdpTelemetryReceiver, local_ips
from .. import theme
from ..context import AppContext
from ..widgets.common import CardPanel, Chip, SegmentedBar, button, label
from ..widgets.speedo import GearDisplay, RpmLeds, SpeedoGauge, nice_scale

SOURCES = (("auto", "AUTO"), ("forza", "FORZA"), ("dirt", "DIRT"), ("demo", "DEMO"))  # DIRT = DiRT Rally 2.0
UNITS = (("kmh", "KM/H"), ("mph", "MPH"))
SCALES = (("auto", "AUTO"), ("200", "200"), ("260", "260"), ("340", "340"))
STALE_AFTER_S = 1.5


class TelemetryBridge(QObject):
    data = Signal(object)  # Telemetry, dipancarkan dari thread penerima UDP -> antrean Qt


class SpeedometerPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.bridge = TelemetryBridge()
        self.receiver: UdpTelemetryReceiver | None = None
        self.last: Telemetry | None = None
        self._peak = 0.0
        self._demo_t0 = time.monotonic()
        self._rate_mark = (time.monotonic(), 0)
        self._rate = 0.0
        self.game = ctx.settings.get("telemetry_game", "auto")
        self.unit = ctx.settings.get("telemetry_unit", "kmh")
        self.scale = ctx.settings.get("telemetry_scale", "auto")
        self.port = int(ctx.settings.get("telemetry_port", DEFAULT_PORT))

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("TELEMETRI GAME", "eyebrow"))
        col.addWidget(label("Speedometer", "h1"))
        head.addLayout(col, 1)
        self.chip = Chip("MENUNGGU DATA", theme.TEXT_DIM)
        head.addWidget(self.chip, 0, Qt.AlignBottom)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # ------------------------------------------------------------ gauge
        main = CardPanel("Instrumen")
        self.gauge = SpeedoGauge()
        main.body.addWidget(self.gauge, 1)
        self.leds = RpmLeds()
        main.body.addWidget(self.leds)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.gear = GearDisplay()
        row.addWidget(self.gear, 1)
        info = QVBoxLayout()
        info.setSpacing(6)
        self.rpm_label = label("RPM —", "h3")
        self.lap_label = label("Lap —", "h3")
        self.lap_time = label("Waktu lap  --:--.---", "dim")
        self.best_lap = label("Terbaik     --:--.---", "dim")
        for w in (self.rpm_label, self.lap_label, self.lap_time, self.best_lap):
            info.addWidget(w)
        info.addStretch(1)
        row.addLayout(info, 2)
        main.body.addLayout(row)
        body.addWidget(main, 6)

        # ------------------------------------------------------------ pengaturan
        side = QVBoxLayout()
        side.setSpacing(16)
        cfg = CardPanel("Sumber data", "Pilih game atau Demo; data dikirim game ke komputer ini lewat UDP.")
        self.src_bar = SegmentedBar()
        self.src_bar.set_items(list(SOURCES))
        self.src_bar.set_current(self.game)
        self.src_bar.currentChanged.connect(self._source_changed)
        cfg.body.addWidget(self.src_bar, 0, Qt.AlignLeft)
        prow = QHBoxLayout()
        prow.addWidget(label("Port UDP", "muted"))
        prow.addStretch(1)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.port)
        self.port_spin.setKeyboardTracking(False)
        self.port_spin.valueChanged.connect(self._port_changed)
        prow.addWidget(self.port_spin)
        cfg.body.addLayout(prow)
        urow = QHBoxLayout()
        urow.addWidget(label("Satuan", "muted"))
        urow.addStretch(1)
        self.unit_bar = SegmentedBar()
        self.unit_bar.set_items(list(UNITS))
        self.unit_bar.set_current(self.unit)
        self.unit_bar.currentChanged.connect(self._unit_changed)
        urow.addWidget(self.unit_bar)
        cfg.body.addLayout(urow)
        srow = QHBoxLayout()
        srow.addWidget(label("Skala maks", "muted"))
        srow.addStretch(1)
        self.scale_bar = SegmentedBar()
        self.scale_bar.set_items(list(SCALES))
        self.scale_bar.set_current(self.scale)
        self.scale_bar.currentChanged.connect(self._scale_changed)
        srow.addWidget(self.scale_bar)
        cfg.body.addLayout(srow)
        self.status = label("", "dim", wrap=True)
        cfg.body.addWidget(self.status)
        self.b_toggle = button("Berhenti mendengarkan", "ghost")
        self.b_toggle.clicked.connect(self._toggle_listen)
        cfg.body.addWidget(self.b_toggle)
        side.addWidget(cfg)

        how = CardPanel("Cara menghubungkan")
        self.how = label("", "dim", wrap=True)
        how.body.addWidget(self.how)
        side.addWidget(how)
        side.addStretch(1)
        side_host = QWidget()
        side_host.setFixedWidth(400)
        side_host.setLayout(side)
        body.addWidget(side_host)

        self.bridge.data.connect(self._on_data)
        self.watch = QTimer(self)
        self.watch.setInterval(250)
        self.watch.timeout.connect(self._tick)
        self.demo_timer = QTimer(self)
        self.demo_timer.setInterval(33)
        self.demo_timer.timeout.connect(self._demo_tick)
        self._listening = True
        self._refresh_scale()
        self._refresh_how()

    # ============================================================ lifecycle
    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._listening:
            self._start()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._stop()

    def closeEvent(self, e) -> None:  # pragma: no cover
        self._stop()
        super().closeEvent(e)

    def _start(self) -> None:
        self._stop()
        self.watch.start()
        if self.game == "demo":
            self._demo_t0 = time.monotonic()
            self.demo_timer.start()
            self._set_status("Mode Demo: data simulasi, tidak memerlukan game.")
            return
        self.receiver = UdpTelemetryReceiver(self.port, self.game, on_data=self.bridge.data.emit)
        if not self.receiver.start():
            self._set_status(self.receiver.error, error=True)
            self.receiver = None
            return
        self._rate_mark = (time.monotonic(), 0)
        self._refresh_status()

    def _stop(self) -> None:
        self.watch.stop()
        self.demo_timer.stop()
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver = None

    # ================================================================ data
    def _demo_tick(self) -> None:
        self._on_data(simulator.demo(time.monotonic() - self._demo_t0))

    def _on_data(self, t: Telemetry) -> None:
        self.last = t
        speed = t.speed(self.unit)
        self._peak = max(self._peak, speed)
        if self.scale == "auto":
            top = nice_scale(max(self._peak * 1.08, 125 if self.unit == "mph" else 200))[0]
            if top != self.gauge._max:
                self.gauge.set_scale(top, self._unit_text())
        self.gauge.set_state(speed, t.rpm_fraction, True)
        self.leds.set_value(t.rpm_fraction)
        self.gear.set_gear(t.gear_text)
        self.rpm_label.setText(f"RPM {t.rpm:.0f} / {t.max_rpm:.0f}" if t.rpm_exact and t.max_rpm > 0
                               else f"RPM {t.rpm_fraction * 100:.0f}%")
        self.lap_label.setText("Lap —" if t.lap is None else f"Lap {t.lap}")
        self.lap_time.setText(f"Waktu lap  {format_lap_time(t.lap_time)}")
        self.best_lap.setText(f"Terbaik     {format_lap_time(t.best_lap)}")

    def _tick(self) -> None:
        r = self.receiver
        if r is not None:
            now, count = self._rate_mark
            dt = time.monotonic() - now
            if dt >= 1.0:
                self._rate = (r.packets - count) / dt
                self._rate_mark = (time.monotonic(), r.packets)
            age = r.age()
            if age is not None and age > STALE_AFTER_S:
                self.gauge.set_state(0, 0, False)
                self.leds.set_value(0)
                self.gear.set_gear("–")
            self._refresh_status()

    # ========================================================== pengaturan
    def _unit_text(self) -> str:
        return "mph" if self.unit == "mph" else "km/h"

    def _refresh_scale(self) -> None:
        if self.scale == "auto":
            self.gauge.set_scale(125 if self.unit == "mph" else 240, self._unit_text())
        else:
            self.gauge.set_scale(float(self.scale), self._unit_text())

    def _source_changed(self, key: str) -> None:
        self.game = key
        self.ctx.settings.set("telemetry_game", key)
        self.port_spin.setEnabled(key != "demo")
        self._refresh_how()
        if self.isVisible() and self._listening:
            self._start()

    def _port_changed(self, v: int) -> None:
        self.port = int(v)
        self.ctx.settings.set("telemetry_port", self.port)
        self._refresh_how()
        if self.isVisible() and self._listening:
            self._start()

    def _unit_changed(self, key: str) -> None:
        self.unit = key
        self.ctx.settings.set("telemetry_unit", key)
        self._peak = 0.0
        self._refresh_scale()
        if self.last is not None:
            self._on_data(self.last)

    def _scale_changed(self, key: str) -> None:
        self.scale = key
        self.ctx.settings.set("telemetry_scale", key)
        self._peak = 0.0
        self._refresh_scale()

    def _toggle_listen(self) -> None:
        self._listening = not self._listening
        self.b_toggle.setText("Berhenti mendengarkan" if self._listening else "Mulai mendengarkan")
        if self._listening:
            self._start()
        else:
            self._stop()
            self._set_status("Berhenti. Tekan “Mulai mendengarkan” untuk menerima data.")
            self.gauge.set_state(0, 0, False)

    def _refresh_status(self) -> None:
        r = self.receiver
        if r is None:
            return
        age = r.age()
        if age is None:
            self._set_status(f"Mendengarkan UDP port {r.bound_port}… belum ada paket."
                             + (f" ({r.rejected} paket ditolak: format tidak cocok)" if r.rejected else ""))
        elif age > STALE_AFTER_S:
            self._set_status(f"Data berhenti ({age:.0f} dtk lalu). Total {r.packets} paket.")
        else:
            self._set_status(f"Data masuk {self._rate:.0f} paket/dtk · total {r.packets}", live=True)

    def _set_status(self, text: str, error: bool = False, live: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.RED if error else theme.GREEN if live else theme.TEXT_DIM};")
        self.chip.setText("ERROR" if error else "LIVE" if live else ("DEMO" if self.game == "demo" else "MENUNGGU DATA"))
        self.chip.set_style(theme.RED if error else theme.GREEN if live else
                            (theme.BLUE if self.game == "demo" else theme.TEXT_DIM))

    def _refresh_how(self) -> None:
        ips = local_ips()
        ip = ips[0] if ips else "IP komputer ini"
        addr = f"{ip}:{self.port}"
        forza = (f"Forza Horizon 4 / 5: Settings → HUD and Gameplay → Data Out = ON, Data Out IP Address = {ip}, "
                 f"Data Out IP Port = {self.port}, Packet Format = Dash.")
        dirt = (f"DiRT Rally 2.0: pada hardware_settings_config.xml (Dokumen\\My Games\\DiRT Rally 2.0\\hardwaresettings) "
                f'set <udp enabled="true" extradata="3" ip="{ip}" port="{self.port}" delay="1" />.')
        tip = ("Jika game berjalan di PC yang sama dan tidak ada data, pakai IP LAN PC (bukan 127.0.0.1): game dari "
               "Microsoft Store tidak bisa mengirim ke loopback.")
        pick = {"forza": forza, "dirt": dirt, "demo": "Mode Demo menampilkan data simulasi tanpa game."}
        text = pick.get(self.game, forza + "\n\n" + dirt)
        if self.game != "demo":
            text += f"\n\nAlamat tujuan: {addr}" + (f" (IP lain: {', '.join(ips[1:])})" if len(ips) > 1 else "")
            text += f"\n\n{tip}\n\nUntuk game di konsol atau PC lain, tujuan datanya tetap IP PC ini."
        text += "\n\nFormat paket mengikuti aplikasi PXN asli; belum diuji dengan game sungguhan."
        self.how.setText(text)
