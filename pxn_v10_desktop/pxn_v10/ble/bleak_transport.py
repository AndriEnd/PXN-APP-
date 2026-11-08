"""Real Bluetooth Low Energy transport for Windows / macOS / Linux using ``bleak``.

GATT layout (see PRD §3.2): service FFE0, write FFE1, notify FFE2 (CCCD written by bleak's
``start_notify``).
"""

from __future__ import annotations

import asyncio
import logging

from ..core import constants as C
from ..core.events import DeviceFound
from .transport import DisconnectCallback, FoundCallback, NotifyCallback, Transport, TransportError

log = logging.getLogger(__name__)


class BleakTransport(Transport):
    label = "Bluetooth LE"

    def __init__(self, device_name: str = C.DEVICE_NAME) -> None:
        self._name = device_name.lower()
        self._client = None
        self._stop: asyncio.Event | None = None  # created inside the running loop in scan()
        self._seen: dict = {}
        self._write_response = True

    # ---------------------------------------------------------------- scanning
    async def scan(self, timeout: float, on_found: FoundCallback) -> None:
        from bleak import BleakScanner  # imported lazily: the simulator works without bleak

        self._stop = asyncio.Event()
        reported: set = set()

        def detection(device, adv) -> None:
            name = (getattr(adv, "local_name", None) or device.name or "").strip()
            if not name or name.lower() != self._name:  # Case-insensitive equals, like the Android scan filter
                return
            self._seen[device.address] = device
            rssi = getattr(adv, "rssi", None)
            # report every sighting once, then only when RSSI changes noticeably
            key = (device.address, None if rssi is None else rssi // 5)
            if key in reported:
                return
            reported.add(key)
            on_found(DeviceFound(name, device.address, rssi))

        try:
            async with BleakScanner(detection_callback=detection):
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
        except Exception as exc:  # Bluetooth radio off, no adapter, permission denied, ...
            raise TransportError(_friendly(exc)) from exc

    async def stop_scan(self) -> None:
        if self._stop is not None:
            self._stop.set()

    # -------------------------------------------------------------- connection
    async def connect(self, address: str, on_notify: NotifyCallback, on_disconnect: DisconnectCallback) -> None:
        from bleak import BleakClient

        target = self._seen.get(address, address)  # a BLEDevice connects faster than a bare address

        def _disconnected(_client) -> None:
            on_disconnect()

        client = BleakClient(target, disconnected_callback=_disconnected, timeout=15.0)
        try:
            await client.connect()  # autoConnect=false equivalent: a direct connection
            service = client.services.get_service(C.SERVICE_UUID)
            if service is None:
                raise TransportError("Layanan FFE0 tidak ditemukan - ini bukan PXN-V10?")
            write_char = service.get_characteristic(C.WRITE_CHAR_UUID)
            notify_char = service.get_characteristic(C.NOTIFY_CHAR_UUID)
            if write_char is None or notify_char is None:
                raise TransportError("Karakteristik FFE1/FFE2 tidak lengkap")
            # Android's writeCharacteristic() uses the default (with-response) write type
            self._write_response = "write" in write_char.properties
            await client.start_notify(notify_char, lambda _c, data: on_notify(bytes(data)))
        except TransportError:
            await _safe_disconnect(client)
            raise
        except Exception as exc:
            await _safe_disconnect(client)
            raise TransportError(_friendly(exc)) from exc
        self._client = client

    async def write(self, data: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise TransportError("Tidak terhubung")
        try:
            await client.write_gatt_char(C.WRITE_CHAR_UUID, data, response=self._write_response)
        except Exception as exc:
            raise TransportError(_friendly(exc)) from exc

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await _safe_disconnect(client)

    @property
    def is_connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected)


async def _safe_disconnect(client) -> None:
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001 - already gone
        log.debug("disconnect failed", exc_info=True)


def _friendly(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    low = text.lower()
    if "bluetooth" in low and ("off" in low or "disabled" in low or "turned" in low):
        return "Bluetooth pada PC dalam keadaan mati. Aktifkan Bluetooth lalu coba lagi."
    if "no bluetooth adapter" in low or "adapter" in low and "not" in low:
        return "Adapter Bluetooth tidak ditemukan pada PC ini."
    if "access" in low and "denied" in low:
        return "Akses Bluetooth ditolak oleh Windows (Settings > Privacy > Bluetooth)."
    return text
