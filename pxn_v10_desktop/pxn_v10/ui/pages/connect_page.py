"""Device selection / scanning screen (DeviceV10Fragment + Task 5.2 radar, RSSI cards, quick connect)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...core.events import ConnEvent, ConnState, DeviceFound
from .. import theme
from ..context import LINK_TITLES, LINKS, AppContext
from ..widgets.common import SegmentedBar, StatusDot, button, card, label
from ..widgets.gauges import Radar, SignalBars, rssi_bars

STATUS_TEXT = {
    ConnState.DISCONNECTED: "Nyalakan setir PXN-V10 dan pastikan Bluetooth PC aktif, lalu tekan GO.",
    ConnState.SCANNING: "Memindai perangkat bernama “PXN-V10”…",
    ConnState.CONNECTING: "Menyambung ke setir…",
    ConnState.DISCOVERING_SERVICES: "Mencari layanan GATT FFE0…",
    ConnState.INITIALIZING_NOTIFY: "Mengaktifkan notifikasi FFE2…",
    ConnState.READY: "Terhubung. Sinkronisasi profil selesai.",
    ConnState.DISCONNECTING: "Memutus koneksi…",
    ConnState.RECONNECTING: "Koneksi terputus — mencoba menyambung ulang…",
}


USB_STATUS = {
    ConnState.DISCONNECTED: "Hubungkan setir dengan kabel USB lalu tekan GO. Fitur eksperimental: aplikasi hanya "
                            "menyambung bila setir menjawab protokol PXN lewat USB.",
    ConnState.SCANNING: "Mencari antarmuka konfigurasi USB (HID)…",
}
LINK_NOTES = {
    "ble": "",
    "usb": "Konfigurasi lewat USB bersifat eksperimental: protokol USB firmware PXN V10 tidak terdokumentasi. "
           "Sebelum menulis apa pun, aplikasi mengirim satu permintaan baca dan menunggu balasan. Test dan kalibrasi "
           "perangkat USB tersedia di halaman Perangkat USB tanpa koneksi ini.",
    "sim": "Setir virtual: mencoba seluruh aplikasi tanpa perangkat fisik.",
}


def status_text(state: ConnState, link: str) -> str:
    if link == "usb" and state in USB_STATUS:
        return USB_STATUS[state]
    return STATUS_TEXT.get(state, "")


class DeviceCard(QWidget):
    def __init__(self, dev: DeviceFound, on_connect, parent=None) -> None:
        super().__init__(parent)
        f = card(inner=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(f)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(14)
        lay.addWidget(StatusDot(theme.GREEN, 9))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(dev.name, "h3"))
        col.addWidget(label(dev.address, "muted"))
        lay.addLayout(col, 1)
        self.bars = SignalBars(rssi_bars(dev.rssi))
        self.rssi = label("" if dev.rssi is None else f"{dev.rssi} dBm", "muted")
        lay.addWidget(self.rssi)
        lay.addWidget(self.bars)
        b = button("Hubungkan", "primary")
        b.clicked.connect(lambda: on_connect(dev.address))
        lay.addWidget(b)
        self.address = dev.address

    def update_signal(self, dev: DeviceFound) -> None:
        self.bars.bars = rssi_bars(dev.rssi)
        self.bars.update()
        self.rssi.setText("" if dev.rssi is None else f"{dev.rssi} dBm")


class ConnectPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.cards: dict[str, DeviceCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 32)
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(14)
        col.setAlignment(Qt.AlignHCenter)
        outer.addLayout(col)
        outer.addStretch(2)

        self.radar = Radar()
        col.addWidget(self.radar, 0, Qt.AlignHCenter)
        t = label("Hubungkan PXN-V10", "h1", align=Qt.AlignCenter)
        col.addWidget(t)
        self.status = label(STATUS_TEXT[ConnState.DISCONNECTED], "dim", wrap=True, align=Qt.AlignCenter)
        self.status.setFixedWidth(520)
        col.addWidget(self.status, 0, Qt.AlignHCenter)
        self.error = label("", wrap=True, align=Qt.AlignCenter)
        self.error.setStyleSheet(f"color: {theme.RED};")
        self.error.setFixedWidth(520)
        self.error.hide()
        col.addWidget(self.error, 0, Qt.AlignHCenter)

        self.links = SegmentedBar()
        self.links.set_items([(k, LINK_TITLES[k].upper()) for k in LINKS])
        self.links.set_current(ctx.link)
        self.links.currentChanged.connect(self._link_changed)
        col.addWidget(self.links, 0, Qt.AlignHCenter)
        self.link_note = label("", "muted", wrap=True, align=Qt.AlignCenter)
        self.link_note.setFixedWidth(520)
        col.addWidget(self.link_note, 0, Qt.AlignHCenter)

        self.go = button("GO", "primary")
        self.go.setMinimumWidth(220)
        self.go.setMinimumHeight(46)
        self.go.clicked.connect(self._go_clicked)
        col.addWidget(self.go, 0, Qt.AlignHCenter)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignHCenter)
        self.quick = button("Sambungkan cepat", "ghost")
        self.quick.clicked.connect(self._quick)
        row.addWidget(self.quick)
        col.addLayout(row)

        self.list_host = QWidget()
        self.list_host.setMaximumWidth(620)
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 8, 0, 0)
        self.list_lay.setSpacing(10)
        col.addWidget(self.list_host, 0, Qt.AlignHCenter)

        ctx.bridge.connChanged.connect(self._conn_changed)
        ctx.bridge.deviceFound.connect(self._device_found)
        ctx.clientReplaced.connect(lambda: (self._sync_link(), self._refresh_quick(),
                                            self._conn_changed(ConnEvent(ConnState.DISCONNECTED))))
        self._sync_link()
        self._refresh_quick()
        self._conn_changed(ConnEvent(ctx.client.state))

    # ----------------------------------------------------------------- state
    def _refresh_quick(self) -> None:
        addr = self.ctx.settings.get("last_address", "")
        self.quick.setEnabled(bool(addr) and self.ctx.link == "ble")
        self.quick.setToolTip(f"Terakhir terhubung: {addr}" if addr else "Belum ada perangkat yang tersimpan")

    def _conn_changed(self, ev: ConnEvent) -> None:
        st = ev.state
        self.radar.set_active(st == ConnState.SCANNING)
        self.radar.set_connected(st == ConnState.READY)
        self.status.setText(status_text(st, self.ctx.link))
        busy = st in (ConnState.CONNECTING, ConnState.DISCOVERING_SERVICES, ConnState.INITIALIZING_NOTIFY,
                      ConnState.DISCONNECTING, ConnState.RECONNECTING)
        self.go.setEnabled(not busy)
        self.go.setText({ConnState.SCANNING: "BATAL", ConnState.READY: "BUKA DASHBOARD"}.get(
            st, "MENYAMBUNG…" if busy else "GO"))
        self.links.setEnabled(st == ConnState.DISCONNECTED)
        msg = self.ctx.client.last_error if st == ConnState.DISCONNECTED else ""
        self.error.setText(msg)
        self.error.setVisible(bool(msg))
        if st == ConnState.READY and self.ctx.client.last_address and self.ctx.link == "ble":
            self.ctx.settings.set("last_address", self.ctx.client.last_address)
        if st in (ConnState.DISCONNECTED,):
            self._refresh_quick()
        if st != ConnState.SCANNING and st != ConnState.DISCONNECTED:
            self._clear_cards()
        elif st == ConnState.SCANNING:
            self._clear_cards()

    def _clear_cards(self) -> None:
        for c in self.cards.values():
            c.setParent(None)
            c.deleteLater()
        self.cards.clear()

    def _device_found(self, dev: DeviceFound) -> None:
        if dev.address in self.cards:
            self.cards[dev.address].update_signal(dev)
            return
        c = DeviceCard(dev, self.ctx.client.connect)
        self.cards[dev.address] = c
        self.list_lay.addWidget(c)

    # --------------------------------------------------------------- actions
    def _go_clicked(self) -> None:
        st = self.ctx.client.state
        if st == ConnState.DISCONNECTED:
            self.ctx.client.last_error = ""
            # USB: tampilkan kandidat dulu, jangan menyambung otomatis ke antarmuka yang belum terverifikasi
            auto = bool(self.ctx.settings.get("auto_connect", True)) and self.ctx.link != "usb"
            self.ctx.client.scan(auto_connect=auto)
        elif st == ConnState.SCANNING:
            self.ctx.client.stop_scan()
            self.ctx.client.disconnect()
        elif st == ConnState.READY:
            self.ctx.navigate("dashboard")

    def _quick(self) -> None:
        addr = self.ctx.settings.get("last_address", "")
        if addr:
            self.ctx.client.last_error = ""
            self.ctx.client.connect(addr)

    def _sync_link(self) -> None:
        self.links.blockSignals(True)
        self.links.set_current(self.ctx.link)
        self.links.blockSignals(False)
        self.link_note.setText(LINK_NOTES[self.ctx.link])
        self.link_note.setVisible(bool(LINK_NOTES[self.ctx.link]))

    def _link_changed(self, link: str) -> None:
        if link == self.ctx.link:
            return
        self.ctx.use_link(link)
        self._sync_link()
        self._refresh_quick()
        self._clear_cards()
        self.ctx.toast(f"Jalur koneksi: {LINK_TITLES[link]}", "info")
