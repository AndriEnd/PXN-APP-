"""Application context shared by all pages: BLE client, Qt bridge, storage, helpers."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..ble.client import AsyncRunner, WheelClient
from ..ble.mock_transport import MockTransport
from ..core.events import (
    ChangeEvent,
    ConnEvent,
    ConnState,
    DeviceFound,
    ErrorEvent,
    LogEvent,
    TestEvent,
)
from ..storage.database import ProfileDatabase
from ..storage.settings import Settings
from ..usb.config import DeviceSettings, apply_known_defaults
from ..usb.devices import UsbMonitor, UsbScanner
from ..usb.hid import enumerate_hid
from ..usb.hid_joystick import best_backend
from ..usb.joystick import FakeJoystickBackend

LINKS = ("ble", "usb", "sim")
LINK_TITLES = {"ble": "Bluetooth", "usb": "USB (eksperimental)", "sim": "Simulator"}


class ClientBridge(QObject):
    """Turns the thread-agnostic WheelClient callbacks into (queued) Qt signals."""

    connChanged = Signal(object)  # ConnEvent
    changed = Signal(int, int)  # Change type, detail
    testFrame = Signal(object)  # TestSnapshot
    deviceFound = Signal(object)  # DeviceFound
    errorRaised = Signal(str)
    logLine = Signal(str, bytes)  # direction, data

    def __init__(self) -> None:
        super().__init__()
        self._client: WheelClient | None = None

    def attach(self, client: WheelClient) -> None:
        if self._client is not None:
            self._client.remove_listener(self._on_event)
        self._client = client
        client.add_listener(self._on_event)

    def _on_event(self, event: object) -> None:
        if isinstance(event, ConnEvent):
            self.connChanged.emit(event)
        elif isinstance(event, ChangeEvent):
            self.changed.emit(int(event.type), event.detail)
        elif isinstance(event, TestEvent):
            self.testFrame.emit(event.snapshot)
        elif isinstance(event, DeviceFound):
            self.deviceFound.emit(event)
        elif isinstance(event, ErrorEvent):
            self.errorRaised.emit(event.message)
        elif isinstance(event, LogEvent):
            self.logLine.emit(event.direction, event.data)


class AppContext(QObject):
    toastRequested = Signal(str, str)  # message, kind (info | ok | error)
    clientReplaced = Signal()
    navigateRequested = Signal(str)  # page key
    usbDevicesChanged = Signal(object)  # list[UsbDevice] (dipancarkan dari thread pemindai -> antrean Qt)

    def __init__(self, settings: Settings | None = None, db: ProfileDatabase | None = None,
                 simulator: bool = False) -> None:
        super().__init__()
        self.settings = settings or Settings()
        self.db = db or ProfileDatabase()
        self.runner = AsyncRunner()
        self.bridge = ClientBridge()
        self.link = "sim" if simulator else "ble"
        self.client = self._make_client(self.link)
        # ---- perangkat USB (shifter / handbrake / setir sebagai game controller)
        self.usb_backend = FakeJoystickBackend.demo() if simulator else best_backend()
        self.usb_scanner = UsbScanner(self.usb_backend, (lambda: []) if simulator else enumerate_hid)
        self.usb_monitor = UsbMonitor(self.usb_scanner, interval=2.0, on_change=self.usbDevicesChanged.emit)
        self.usb_monitor.start()

    # ------------------------------------------------------------------ client
    @property
    def simulator(self) -> bool:
        return self.link == "sim"

    def _make_client(self, link: str) -> WheelClient:
        if link == "sim":
            transport = MockTransport()
        elif link == "usb":
            from ..usb.hid_transport import HidTransport

            transport = HidTransport()
        else:
            from ..ble.bleak_transport import BleakTransport

            transport = BleakTransport()
        client = WheelClient(
            transport,
            self.runner,
            auto_reconnect=bool(self.settings.get("auto_reconnect", True)),
        )
        self.bridge.attach(client)
        return client

    def use_simulator(self, enabled: bool) -> None:
        """Swap the transport (real BLE <-> simulator). Disconnects first."""
        self.use_link("sim" if enabled else "ble")

    def use_link(self, link: str) -> None:
        """Pilih jalur konfigurasi setir: ``ble`` | ``usb`` | ``sim``. Memutus koneksi yang ada lebih dulu."""
        if link not in LINKS or link == self.link:
            return
        try:
            self.client.disconnect().result(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        was_sim = self.simulator
        self.link = link
        if was_sim != self.simulator:  # perangkat USB demo hanya ada di simulator
            self.usb_backend = FakeJoystickBackend.demo() if self.simulator else best_backend()
            self.usb_scanner.backend = self.usb_backend
            self.usb_scanner.hid_enumerator = (lambda: []) if self.simulator else enumerate_hid
            self.usb_monitor.refresh_now()
        self.client = self._make_client(link)
        self.clientReplaced.emit()

    # ------------------------------------------------------------------ USB settings
    def usb_settings(self, key: str, guessed_role: str = "other") -> DeviceSettings:
        raw = (self.settings.get("usb_devices", {}) or {}).get(key)
        if raw is None:
            ds = DeviceSettings(role=guessed_role)
            if guessed_role == "handbrake":
                ds.handbrake.cal.axis = 0
            apply_known_defaults(ds, key, migrate=False)  # shifter dikenal: pemetaan gigi yang benar sejak awal
            return ds
        ds = DeviceSettings.from_dict(raw)
        if apply_known_defaults(ds, key, migrate=True):  # setelan lama yang belum diubah pengguna -> perbaiki & simpan
            self.save_usb_settings(key, ds)
        return ds

    def save_usb_settings(self, key: str, ds: DeviceSettings) -> None:
        data = dict(self.settings.get("usb_devices", {}) or {})
        data[key] = ds.to_dict()
        self.settings.set("usb_devices", data)

    # --------------------------------------------------------------------- ui
    def toast(self, message: str, kind: str = "info") -> None:
        self.toastRequested.emit(message, kind)

    def navigate(self, page: str) -> None:
        self.navigateRequested.emit(page)

    @property
    def connected(self) -> bool:
        return self.client.state == ConnState.READY

    def shutdown(self) -> None:
        if getattr(self, "_closed", False):  # closeEvent + pemanggil lain: jangan menunggu loop yang sudah berhenti
            return
        self._closed = True
        self.usb_monitor.stop()
        try:
            self.client.disconnect().result(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        self.runner.stop()
        self.db.close()
