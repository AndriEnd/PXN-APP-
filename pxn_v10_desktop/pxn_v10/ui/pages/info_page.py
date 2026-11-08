"""Settings & info (V10SettingActivity / V10BookActivity / V10SupportActivity)."""

from __future__ import annotations

import platform

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QPlainTextEdit, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from ... import __app_name__, __version__
from ...core.events import ConnState
from .. import theme
from ..context import AppContext
from ..widgets.common import CardPanel, button, label

MANUAL_HTML = f"""
<style>
 h3 {{ color:{theme.ACCENT_2}; margin-top:16px; margin-bottom:4px; }}
 p, li {{ color:{theme.TEXT_DIM}; line-height:150%; }}
 b {{ color:{theme.TEXT}; }}
</style>
<h3>1. Menyambungkan setir</h3>
<p>Nyalakan PXN-V10, aktifkan Bluetooth di PC, lalu buka <b>Koneksi → GO</b>. Aplikasi memindai perangkat bernama
<b>PXN-V10</b> dan tersambung otomatis. Setelah itu status dan seluruh profil (6 halaman) dibaca dari setir.
<b>Sambungkan cepat</b> memakai alamat setir terakhir. <b>Mode simulator</b> memakai setir virtual untuk mencoba
aplikasi tanpa perangkat.</p>
<h3>2. Mode D-Input / X-Input</h3>
<p>Klik badge mode di Dashboard untuk beralih antara <b>PC DirectInput</b> dan <b>PC XInput</b>. Mode konsol
(PS4, Xbox One, Android, Switch) bersifat baca-saja. Slider Spring/Damping/Friction/Inertia hanya tersedia di
D-Input dan PS4.</p>
<h3>3. Parameter kemudi</h3>
<ul>
<li><b>ANGLE</b> 90°–900°: sudut putar efektif kemudi.</li>
<li><b>FORCE FEEDBACK</b> 0–100 %, dengan saklar <b>REVERSE</b> untuk membalik arah gaya.</li>
<li><b>SPRING / DAMPING / FRICTION / INERTIA</b>: empat gaya fisika. Tombol <b>?</b> menjelaskan masing-masing.</li>
</ul>
<p>Perubahan dikirim saat slider dilepas; paket dikirim berjarak 100 ms dan perubahan beruntun dari jenis yang sama
digabung agar antrean tidak menumpuk. Anda juga bisa mengetik nilai tepat pada kotak angka.</p>
<h3>4. Kurva pedal</h3>
<p>Tab <b>PEDAL</b> menampilkan kurva Gas / Rem / Kopling dengan empat titik yang dapat digeser. <b>Reset kurva</b>
mengembalikan ke garis linear bawaan.</p>
<h3>5. Pemetaan tombol</h3>
<p>Klik sebuah tombol pada diagram setir, pedal, shifter atau handbrake, lalu pilih fungsi baru pada keyboard virtual
(Gamepad / Keyboard di mode D-Input). <b>Reset</b> mengembalikan tombol ke fungsi aslinya.</p>
<h3>6. Test sensor</h3>
<p>Halaman <b>Test</b> mengaktifkan mode uji pada setir dan menampilkan sudut, pedal, gigi, dan tombol yang ditekan
secara real-time. Mode uji dimatikan otomatis saat Anda meninggalkan halaman.</p>
<h3>7. Game Presets & INI</h3>
<p>Preset menyimpan seluruh konfigurasi (tombol, sudut, FFB, 4 gaya, 3 kurva) dan dapat dikirim ke setir.
Halaman <b>INI Presets</b> mengimpor file <b>.ini</b> apa pun, mengedit semua parameternya, lalu mengirim bagian
<b>[PXN_V10:*]</b> (atau key yang di-binding) ke setir.</p>
<h3>8. Reset pabrik</h3>
<p>Tombol <b>Reset pabrik</b> di Dashboard mengembalikan profil mode saat ini ke default (900°, FFB 100 %, kurva linear,
pemetaan tombol asli).</p>
<h3>Pemecahan masalah</h3>
<ul>
<li>Setir tidak ditemukan: pastikan tidak sedang tersambung ke perangkat lain dan Bluetooth PC aktif.</li>
<li>Koneksi terputus saat bekerja: aplikasi mencoba menyambung ulang 3 kali secara otomatis.</li>
<li>Perubahan tidak terasa di game: cek mode (D-Input/X-Input) dan pengaturan sudut/FFB di dalam game.</li>
</ul>
"""

SUPPORTED_GAMES = [
    ("Assetto Corsa", "Assetto Corsa · Assetto Corsa Competizione"),
    ("DIRT Rally", "DIRT Rally 2.0 · DIRT 4 · DIRT 5"),
    ("Forza Horizon 5", "Forza Horizon 4 (Microsoft Store) · Forza Horizon 5"),
    ("F1 2021", "F1 2018 – F1 2022"),
    ("Project CARS 3", "Project CARS 2 · Project CARS 3"),
    ("Euro Truck Simulator 2", ""),
    ("American Truck Simulator", ""),
    ("WRC 10", "WRC 8 · WRC 9 · WRC 10"),
    ("BeamNG", ""),
    ("iRacing", ""),
    ("Need For Speed", "Payback · Heat"),
    ("Snow Runner", ""),
    ("GT 7", "PlayStation 4"),
]


class InfoPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("PENGATURAN", "eyebrow"))
        col.addWidget(label("Info & Pengaturan", "h1"))
        root.addLayout(col)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(16)
        info_card = CardPanel("Informasi")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self._vals: dict[str, object] = {}
        rows = [
            ("APP NAME", __app_name__),
            ("APP VERSION", f"v{__version__}"),
            ("SYSTEM", f"{platform.system()} {platform.release()}"),
            ("RUNTIME", f"Python {platform.python_version()} · PySide6 {pyside_version}"),
            ("STATUS", ""),
            ("FIRMWARE VERSION", ""),
        ]
        for i, (k, v) in enumerate(rows):
            grid.addWidget(label(k, "eyebrow"), i, 0)
            lb = label(v, "value" if k in ("STATUS", "FIRMWARE VERSION") else "dim")
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(lb, i, 1)
            self._vals[k] = lb
        grid.setColumnStretch(1, 1)
        info_card.body.addLayout(grid)
        left.addWidget(info_card)

        set_card = CardPanel("Pengaturan")
        self.c_reconnect = QCheckBox("Sambung ulang otomatis saat koneksi terputus")
        self.c_reconnect.setChecked(bool(ctx.settings.get("auto_reconnect", True)))
        self.c_reconnect.toggled.connect(self._reconnect_toggled)
        self.c_auto = QCheckBox("Langsung tersambung saat PXN-V10 ditemukan")
        self.c_auto.setChecked(bool(ctx.settings.get("auto_connect", True)))
        self.c_auto.toggled.connect(lambda v: ctx.settings.set("auto_connect", bool(v)))
        set_card.body.addWidget(self.c_reconnect)
        set_card.body.addWidget(self.c_auto)
        left.addWidget(set_card)
        left.addStretch(1)
        body.addLayout(left, 4)

        tabs = QTabWidget()
        manual = QTextBrowser()
        manual.setHtml(MANUAL_HTML)
        manual.setOpenExternalLinks(True)
        manual.setStyleSheet(f"QTextBrowser {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER_SOFT};"
                             f" border-radius: 12px; padding: 14px; }}")
        tabs.addTab(manual, "PANDUAN")
        games = QTextBrowser()
        html = "<table cellpadding='9' width='100%'>" + "".join(
            f"<tr><td><b>{n}</b></td><td style='color:{theme.TEXT_DIM}'>{c}</td></tr>" for n, c in SUPPORTED_GAMES) + "</table>"
        games.setHtml(html)
        games.setStyleSheet(manual.styleSheet())
        tabs.addTab(games, "GAME DIDUKUNG")
        logw = QWidget()
        lv = QVBoxLayout(logw)
        lv.setContentsMargins(0, 10, 0, 0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(600)
        self.log.setStyleSheet("font-family: 'Cascadia Mono', Consolas, monospace; font-size: 9pt;")
        lv.addWidget(self.log, 1)
        clear = button("Bersihkan log", "ghost")
        clear.clicked.connect(self.log.clear)
        lv.addWidget(clear, 0, Qt.AlignRight)
        tabs.addTab(logw, "LOG BLE")
        body.addWidget(tabs, 7)

        ctx.bridge.connChanged.connect(lambda _e: self._refresh())
        ctx.bridge.changed.connect(lambda k, d: self._refresh())
        ctx.bridge.logLine.connect(self._log_line)
        self._refresh()

    def _reconnect_toggled(self, value: bool) -> None:
        self.ctx.settings.set("auto_reconnect", bool(value))
        self.ctx.client.auto_reconnect = bool(value)

    def _refresh(self) -> None:
        c = self.ctx.client
        ready = c.state == ConnState.READY
        self._vals["STATUS"].setText("Terhubung" if ready else "Tidak terhubung")  # type: ignore[attr-defined]
        self._vals["STATUS"].setStyleSheet(f"color: {theme.GREEN if ready else theme.TEXT_MUTED};")  # type: ignore[attr-defined]
        self._vals["FIRMWARE VERSION"].setText(c.device_state.firmware_text if ready else "—")  # type: ignore[attr-defined]

    def _log_line(self, direction: str, data: bytes) -> None:
        self.log.appendPlainText(f"{direction}  {data.hex(' ').upper()}")
