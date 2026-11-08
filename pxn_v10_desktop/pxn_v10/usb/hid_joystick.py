"""Pembacaan game controller langsung lewat deskriptor HID (``HidP_*``), pengganti ``winmm``.

Kenapa: ``winmm`` hanya mengenal 6 sumbu standar dan salah menguraikan field yang tidak sejajar byte
(mis. sumbu 10-bit handbrake yang menyebar di dua byte) atau sumbu Rx/Ry/slider/simulation-controls
(mis. posisi analog tuas shifter). Dengan ``HidP_GetUsageValue`` setiap field dibaca sesuai deskriptor
perangkat, berapa pun bit-nya dan di mana pun letaknya.

Setiap perangkat dibuka *hanya-baca* (tanpa akses tulis), report input dibaca di thread latar dan
diurai ke ``JoyState`` (nilai sumbu diskalakan ke 0..65535 agar kompatibel dengan kalibrasi).
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes as w

from .hid import HidInfo, enumerate_hid
from .joystick import JoyInfo, JoystickBackend, JoyState, WinMMBackend

RAW_MAX = 65535
NAMES = {
    (1, 0x30): "X", (1, 0x31): "Y", (1, 0x32): "Z", (1, 0x33): "Rx", (1, 0x34): "Ry", (1, 0x35): "Rz",
    (1, 0x36): "Slider", (1, 0x37): "Dial", (1, 0x38): "Wheel",
    (2, 0xBA): "Rudder", (2, 0xBB): "Throttle", (2, 0xC4): "Accelerator", (2, 0xC5): "Brake",
    (2, 0xC6): "Clutch", (2, 0xC8): "Steering",
}
HAT = (1, 0x39)
SUCCESS = 0x110000


def axis_name(page: int, usage: int) -> str:
    return NAMES.get((page, usage), f"{page:X}:{usage:X}")


def unique_names(names) -> list:
    """Nama sumbu yang kembar diberi nomor ("Slider", "Slider 2") agar bisa dibedakan di UI."""
    seen: dict = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} {seen[n]}")
    return out


def scale_to_raw(value: int, lo: int, hi: int) -> int:
    """Nilai logis [lo, hi] -> 0..65535 (dibatasi)."""
    if hi <= lo:
        return 0
    return int(round(max(0, min(1, (value - lo) / (hi - lo))) * RAW_MAX))


def sign_extend(value: int, bits: int, logical_min: int) -> int:
    if logical_min < 0 and bits > 0 and value >= 1 << (bits - 1):
        return value - (1 << bits)
    return value


def hat_to_degrees(value: int, lo: int, hi: int) -> int:
    """Hat switch: lo..hi = 8 arah mulai dari atas searah jarum jam; di luar rentang = netral (-1)."""
    if value < lo or value > hi:
        return -1
    steps = hi - lo + 1
    return int(round((value - lo) * 360 / steps)) % 360


class _Api:
    """Fungsi hid.dll + kernel32 dengan tipe argumen (64-bit aman)."""

    def __init__(self) -> None:
        class VALUE_CAPS(ctypes.Structure):
            _fields_ = [("UsagePage", w.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                        ("BitField", w.USHORT), ("LinkCollection", w.USHORT), ("LinkUsage", w.USHORT),
                        ("LinkUsagePage", w.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                        ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte),
                        ("HasNull", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte), ("BitSize", w.USHORT),
                        ("ReportCount", w.USHORT), ("Reserved2", w.USHORT * 5), ("UnitsExp", w.ULONG),
                        ("Units", w.ULONG), ("LogicalMin", w.LONG), ("LogicalMax", w.LONG),
                        ("PhysicalMin", w.LONG), ("PhysicalMax", w.LONG),
                        ("u0", w.USHORT), ("u1", w.USHORT), ("u2", w.USHORT), ("u3", w.USHORT),
                        ("u4", w.USHORT), ("u5", w.USHORT), ("u6", w.USHORT), ("u7", w.USHORT)]

        class HIDP_CAPS(ctypes.Structure):
            _fields_ = [("Usage", w.USHORT), ("UsagePage", w.USHORT), ("InputReportByteLength", w.USHORT),
                        ("OutputReportByteLength", w.USHORT), ("FeatureReportByteLength", w.USHORT),
                        ("Reserved", w.USHORT * 17), ("NumberLinkCollectionNodes", w.USHORT),
                        ("NumberInputButtonCaps", w.USHORT), ("NumberInputValueCaps", w.USHORT),
                        ("NumberInputDataIndices", w.USHORT), ("NumberOutputButtonCaps", w.USHORT),
                        ("NumberOutputValueCaps", w.USHORT), ("NumberOutputDataIndices", w.USHORT),
                        ("NumberFeatureButtonCaps", w.USHORT), ("NumberFeatureValueCaps", w.USHORT),
                        ("NumberFeatureDataIndices", w.USHORT)]

        self.VALUE_CAPS, self.CAPS = VALUE_CAPS, HIDP_CAPS
        self.hid = hid = ctypes.WinDLL("hid", use_last_error=True)
        self.k32 = k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        H = ctypes.c_void_p
        k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, H]
        k32.CreateFileW.restype = H
        k32.CloseHandle.argtypes = [H]
        hid.HidD_GetPreparsedData.argtypes = [H, ctypes.POINTER(H)]
        hid.HidD_GetPreparsedData.restype = w.BOOLEAN
        hid.HidD_FreePreparsedData.argtypes = [H]
        hid.HidD_GetInputReport.argtypes = [H, ctypes.c_void_p, w.ULONG]
        hid.HidD_GetInputReport.restype = w.BOOLEAN
        hid.HidP_GetCaps.argtypes = [H, ctypes.POINTER(HIDP_CAPS)]
        hid.HidP_GetCaps.restype = ctypes.c_long
        hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.POINTER(VALUE_CAPS), ctypes.POINTER(w.USHORT), H]
        hid.HidP_GetValueCaps.restype = ctypes.c_long
        hid.HidP_GetUsageValue.argtypes = [ctypes.c_int, w.USHORT, w.USHORT, w.USHORT, ctypes.POINTER(w.ULONG), H,
                                           ctypes.c_void_p, w.ULONG]
        hid.HidP_GetUsageValue.restype = ctypes.c_long
        hid.HidP_GetUsages.argtypes = [ctypes.c_int, w.USHORT, w.USHORT, ctypes.POINTER(w.USHORT),
                                       ctypes.POINTER(w.ULONG), H, ctypes.c_void_p, w.ULONG]
        hid.HidP_GetUsages.restype = ctypes.c_long
        hid.HidP_MaxUsageListLength.argtypes = [ctypes.c_int, w.USHORT, H]
        hid.HidP_MaxUsageListLength.restype = w.ULONG


_api: _Api | None = None


def api() -> _Api:
    global _api
    if _api is None:
        _api = _Api()
    return _api


class _Axis:
    def __init__(self, report_id: int, page: int, usage: int, lo: int, hi: int, bits: int) -> None:
        self.report_id, self.page, self.usage, self.lo, self.hi, self.bits = report_id, page, usage, lo, hi, bits
        self.name = axis_name(page, usage)


class _Device:
    """Satu game controller HID yang dibuka hanya-baca."""

    def __init__(self, info: HidInfo) -> None:
        from .hid_transport import WinHidIO

        a = api()
        self.info = info
        self.axes: list = []
        self.hat: _Axis | None = None
        self.n_buttons = 0
        self.report_ids: set = set()
        self.values: list = []
        self.buttons = 0
        self.pov = -1
        self.dead = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pre = ctypes.c_void_p()
        h = a.k32.CreateFileW(info.path, 0, 3, None, 3, 0, None)  # akses 0: hanya untuk membaca deskriptor
        if h in (None, ctypes.c_void_p(-1).value):
            raise OSError("tidak dapat membaca deskriptor HID")
        try:
            if not a.hid.HidD_GetPreparsedData(h, ctypes.byref(self._pre)):
                raise OSError("HidD_GetPreparsedData gagal")
        finally:
            a.k32.CloseHandle(h)
        caps = a.CAPS()
        if a.hid.HidP_GetCaps(self._pre, ctypes.byref(caps)) != SUCCESS:
            raise OSError("HidP_GetCaps gagal")
        self.in_len = caps.InputReportByteLength
        n = caps.NumberInputValueCaps
        if n:
            arr = (a.VALUE_CAPS * n)()
            count = w.USHORT(n)
            if a.hid.HidP_GetValueCaps(0, arr, ctypes.byref(count), self._pre) != SUCCESS:
                raise OSError("HidP_GetValueCaps gagal")
            for vc in arr[: count.value]:
                lo, hi = vc.LogicalMin, vc.LogicalMax
                usages = range(vc.u0, vc.u1 + 1) if vc.IsRange else [vc.u0]
                for u in usages:
                    ax = _Axis(vc.ReportID, vc.UsagePage, u, lo, hi, vc.BitSize)
                    if (vc.UsagePage, u) == HAT:
                        self.hat = ax
                    elif vc.UsagePage in (1, 2) and not (vc.UsagePage == 1 and u > 0x38):
                        self.axes.append(ax)
                    self.report_ids.add(vc.ReportID)
        self.n_buttons = int(a.hid.HidP_MaxUsageListLength(0, 9, self._pre))
        # Perangkat HID hanya mengirim report saat berubah; sebelum report pertama Windows pun menganggap sumbu di
        # titik tengah. GetInputReport tidak andal (setir membalas payload vendor, shifter nol), jadi tidak dipakai.
        self.values = [RAW_MAX // 2] * len(self.axes)
        self._io_cls = WinHidIO

    # ---- info
    def joyinfo(self, slot: int) -> JoyInfo:
        n = len(self.axes)
        return JoyInfo(slot, self.info.vid, self.info.pid, self.info.product or "USB Game Controller",
                       tuple(range(n)), ((0, RAW_MAX),) * n, min(self.n_buttons, 32), self.hat is not None,
                       tuple(unique_names(ax.name for ax in self.axes)))

    # ---- parsing
    def parse(self, report: bytes) -> None:
        a = api()
        buf = ctypes.create_string_buffer(bytes(report), len(report))
        val = w.ULONG()
        with self._lock:
            for i, ax in enumerate(self.axes):
                if a.hid.HidP_GetUsageValue(0, ax.page, 0, ax.usage, ctypes.byref(val), self._pre, buf,
                                            len(report)) == SUCCESS:
                    v = sign_extend(int(val.value), ax.bits, ax.lo)
                    self.values[i] = scale_to_raw(v, ax.lo, ax.hi)
            if self.hat is not None and a.hid.HidP_GetUsageValue(
                    0, self.hat.page, 0, self.hat.usage, ctypes.byref(val), self._pre, buf, len(report)) == SUCCESS:
                self.pov = hat_to_degrees(int(val.value), self.hat.lo, self.hat.hi)
            if self.n_buttons:
                usages = (w.USHORT * max(1, self.n_buttons))()
                length = w.ULONG(self.n_buttons)
                if a.hid.HidP_GetUsages(0, 9, 0, usages, ctypes.byref(length), self._pre, buf,
                                        len(report)) == SUCCESS:
                    mask = 0
                    for u in usages[: length.value]:
                        if 1 <= u <= 64:
                            mask |= 1 << (u - 1)
                    self.buttons = mask

    def state(self) -> JoyState:
        with self._lock:
            return JoyState(list(self.values), self.buttons & 0xFFFFFFFF, self.pov)

    # ---- reader thread
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"hid-joy-{self.info.id_text}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        io = self._io_cls(self.info, readonly=True)
        try:
            io.open()
        except Exception:  # noqa: BLE001
            self.dead = True
            return
        try:
            while not self._stop.is_set():
                report = io.read(0.25)
                if report:
                    self.parse(report)
        except OSError:
            self.dead = True
        finally:
            io.close()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._pre:
            api().hid.HidD_FreePreparsedData(self._pre)
            self._pre = ctypes.c_void_p()


class HidJoystickBackend(JoystickBackend):
    """Semua HID game controller (Usage Page 1 / Joystick, Gamepad, Multi-axis) dengan parsing deskriptor."""

    SLOT_BASE = 200

    def __init__(self, enumerator=enumerate_hid) -> None:
        if sys.platform != "win32":
            raise OSError("hanya Windows")
        api()  # gagal cepat bila hid.dll tidak ada
        self._enum = enumerator
        self._devs: dict = {}  # path -> _Device
        self._slots: dict = {}  # slot -> path

    def enumerate(self) -> list:
        infos = sorted((i for i in self._enum() if i.is_game_controller), key=lambda i: i.path)
        live = {i.path for i in infos}
        for path in [p for p in self._devs if p not in live or self._devs[p].dead]:
            self._devs.pop(path).close()
        out, self._slots = [], {}
        for n, info in enumerate(infos):
            dev = self._devs.get(info.path)
            if dev is None:
                try:
                    dev = _Device(info)
                except Exception:  # noqa: BLE001 - perangkat tak terbaca: lewati
                    continue
                if not dev.axes and not dev.n_buttons:
                    dev.close()
                    continue
                self._devs[info.path] = dev
            slot = self.SLOT_BASE + n
            self._slots[slot] = info.path
            out.append(dev.joyinfo(slot))
        return out

    def read(self, slot: int) -> JoyState | None:
        path = self._slots.get(slot)
        dev = self._devs.get(path) if path else None
        if dev is None or dev.dead:
            return None
        dev.start()
        return dev.state()

    def close(self) -> None:
        for d in self._devs.values():
            d.close()
        self._devs.clear()


class CombinedBackend(JoystickBackend):
    """HID (utama) + winmm untuk perangkat yang tidak terlihat sebagai HID (mis. driver virtual)."""

    WINMM_BASE = 100

    def __init__(self, hid: JoystickBackend, winmm: JoystickBackend | None) -> None:
        self.hid, self.winmm = hid, winmm

    def enumerate(self) -> list:
        infos = list(self.hid.enumerate())
        seen = {(i.vid, i.pid) for i in infos}
        if self.winmm is not None:
            for j in self.winmm.enumerate():
                if (j.vid, j.pid) not in seen:
                    infos.append(JoyInfo(self.WINMM_BASE + j.slot, j.vid, j.pid, j.name, j.axes, j.ranges,
                                         j.n_buttons, j.has_pov, j.axis_names))
        return infos

    def read(self, slot: int) -> JoyState | None:
        if self.WINMM_BASE <= slot < HidJoystickBackend.SLOT_BASE:
            return self.winmm.read(slot - self.WINMM_BASE) if self.winmm is not None else None
        return self.hid.read(slot)


def best_backend() -> JoystickBackend | None:
    """Backend terbaik untuk Windows: HID berbasis deskriptor, ditambah winmm bila tersedia."""
    if sys.platform != "win32":
        return None
    try:
        hid = HidJoystickBackend()
    except Exception:  # noqa: BLE001
        from .joystick import default_backend

        return default_backend()
    try:
        winmm = WinMMBackend()
    except Exception:  # noqa: BLE001
        winmm = None
    return CombinedBackend(hid, winmm)
