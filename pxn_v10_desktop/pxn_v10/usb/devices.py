"""Penemuan perangkat USB: menggabungkan joystick (winmm) dan antarmuka HID, plus daftar port COM."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from typing import Callable

from .config import device_key, guess_role
from .hid import enumerate_hid
from .joystick import JoyInfo, JoystickBackend


@dataclass
class UsbDevice:
    key: str
    name: str
    vid: int
    pid: int
    joy: JoyInfo | None = None  # None = hanya terlihat sebagai HID
    hid: list = field(default_factory=list)  # semua HidInfo dengan VID:PID yang sama
    guessed_role: str = "other"

    @property
    def id_text(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    @property
    def readable(self) -> bool:
        """Dapat dibaca posisinya (terlihat sebagai joystick)."""
        return self.joy is not None

    @property
    def config_interfaces(self) -> list:
        """Antarmuka HID vendor-defined dengan report input+output: kandidat konfigurasi lewat USB."""
        return [h for h in self.hid if h.is_vendor and h.can_exchange_reports]

    @property
    def summary(self) -> str:
        if self.joy is None:
            return "HID"
        return f"{self.joy.n_axes} sumbu · {self.joy.n_buttons} tombol" + (" · POV" if self.joy.has_pov else "")

    def signature(self) -> tuple:
        return (self.key, self.name, self.joy.slot if self.joy else -1, len(self.hid))


class UsbScanner:
    def __init__(self, backend: JoystickBackend | None,
                 hid_enumerator: Callable[[], list] = enumerate_hid) -> None:
        self.backend = backend
        self.hid_enumerator = hid_enumerator

    def scan(self) -> list:
        joys = self.backend.enumerate() if self.backend is not None else []
        try:
            hids = list(self.hid_enumerator())
        except Exception:  # noqa: BLE001
            hids = []
        by_id: dict = {}
        for h in hids:
            by_id.setdefault((h.vid, h.pid), []).append(h)
        seen: dict = {}
        out: list = []
        for j in joys:
            ordinal = seen.get((j.vid, j.pid), 0)
            seen[(j.vid, j.pid)] = ordinal + 1
            related = by_id.get((j.vid, j.pid), [])
            product = next((h.product for h in related if h.product), "")
            name = j.name if j.name and "game controller" not in j.name.lower() else (product or j.name)
            out.append(UsbDevice(device_key(j.vid, j.pid, ordinal), name or "USB Game Controller", j.vid, j.pid, j,
                                 related, guess_role(name, j.n_axes, j.n_buttons)))
        known = {(d.vid, d.pid) for d in out}
        # perangkat PXN yang hanya muncul sebagai HID vendor (mis. D-Input dimatikan)
        for (vid, pid), items in by_id.items():
            if (vid, pid) in known:
                continue
            if any("pxn" in (h.product + h.manufacturer).lower() for h in items):
                product = next((h.product for h in items if h.product), "PXN (USB HID)")
                out.append(UsbDevice(device_key(vid, pid), product, vid, pid, None, items, guess_role(product, 0, 0)))
        return out


class UsbMonitor:
    """Memindai berkala di thread latar dan memanggil ``on_change(devices)`` hanya jika daftar berubah."""

    def __init__(self, scanner: UsbScanner, interval: float = 2.0,
                 on_change: Callable[[list], None] | None = None) -> None:
        self.scanner = scanner
        self.interval = interval
        self.on_change = on_change
        self.devices: list = []
        self._sig: tuple | None = None
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="usb-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def refresh_now(self) -> None:
        self._sig = None  # paksa notifikasi
        self._kick.set()

    def scan_once(self) -> list:
        devices = self.scanner.scan()
        sig = tuple(d.signature() for d in devices)
        self.devices = devices
        if sig != self._sig:
            self._sig = sig
            if self.on_change is not None:
                self.on_change(devices)
        return devices

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001 - pemindaian tidak boleh mematikan thread
                pass
            self._kick.wait(self.interval)
            self._kick.clear()


# ----------------------------------------------------------------------------------- COM ports
@dataclass(frozen=True)
class ComPort:
    name: str  # COM3
    device: str  # \Device\USBSER000

    @property
    def is_usb(self) -> bool:
        d = self.device.lower()
        return any(k in d for k in ("usbser", "vcp", "silabser", "ch34", "ftdi", "prolific", "usb"))


def list_com_ports() -> list:
    """Port serial yang terdaftar Windows (HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM)."""
    if sys.platform != "win32":
        return []
    try:
        import winreg

        ports = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
            i = 0
            while True:
                try:
                    dev, name, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                ports.append(ComPort(str(name), str(dev)))
                i += 1
        return sorted(ports, key=lambda p: (len(p.name), p.name))
    except OSError:
        return []
