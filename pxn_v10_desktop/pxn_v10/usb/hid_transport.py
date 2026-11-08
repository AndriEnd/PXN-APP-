"""Konfigurasi setir lewat USB: transport HID yang membawa frame protokol PXN (20 byte) yang sama dengan BLE.

PERHATIAN - status verifikasi: dokumentasi PXN V10 yang tersedia tidak menjelaskan protokol konfigurasi USB.
Transport ini mengasumsikan firmware menerima frame ``50..54`` yang sama lewat antarmuka HID
*vendor-defined* (Usage Page >= 0xFF00) yang punya report input dan output. Asumsi itu belum diuji pada
perangkat fisik. Karena itu:

* hanya antarmuka yang benar-benar memenuhi syarat itu yang ditawarkan;
* saat menyambung, transport mengirim SATU permintaan baca ``50 01`` dan menunggu balasan ``D0``;
  tanpa balasan yang valid koneksi dibatalkan dan tidak ada perintah tulis yang pernah dikirim;
* setelah itu pun, perintah tulis ditolak sampai balasan ``D0`` pertama diterima.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import sys
import threading
from abc import ABC, abstractmethod

from ..ble.transport import DisconnectCallback, FoundCallback, NotifyCallback, Transport, TransportError
from ..core import codec
from ..core import constants as C
from ..core.events import DeviceFound
from .hid import HidInfo, enumerate_hid

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 2.5


# ----------------------------------------------------------------------------------- I/O layer
class HidIO(ABC):
    """Satu handle HID terbuka. ``read`` mengembalikan report utuh (byte pertama = report ID)."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self, timeout: float) -> bytes | None:
        """Blokir sampai ``timeout`` detik. None = tidak ada data; raise OSError bila perangkat hilang."""

    @abstractmethod
    def write(self, report_id: int, payload: bytes) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class WinHidIO(HidIO):
    """HID Windows dengan overlapped I/O (agar ``read`` bisa timeout dan dibatalkan dengan bersih)."""

    def __init__(self, info: HidInfo, readonly: bool = False) -> None:
        self.readonly = readonly  # hanya membaca report input (diagnostik); tidak pernah menulis
        if sys.platform != "win32":
            raise TransportError("Transport USB HID hanya tersedia di Windows")
        self.info = info
        self._h = None
        self._closed = False

    def open(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32, self._ct, self._w = k32, ctypes, w
        k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
        k32.CreateEventW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, w.DWORD]
        k32.WaitForSingleObject.restype = w.DWORD
        k32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        k32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(w.DWORD), w.BOOL]

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", w.DWORD),
                        ("OffsetHigh", w.DWORD), ("hEvent", ctypes.c_void_p)]

        self._ov_t = OVERLAPPED
        GENERIC_RW, SHARE_RW, OPEN_EXISTING, OVERLAPPED_FLAG = (0x80000000 if self.readonly else 0xC0000000), 0x3, 3, 0x40000000
        h = k32.CreateFileW(self.info.path, GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, OVERLAPPED_FLAG, None)
        if h in (None, ctypes.c_void_p(-1).value):
            raise TransportError(f"Tidak dapat membuka perangkat USB (kode {ctypes.get_last_error()}). "
                                 "Tutup aplikasi lain yang memakai perangkat ini.")
        self._h = h

    def _transfer(self, fn, buf, length: int, timeout_ms: int) -> int | None:
        ct, w, k32 = self._ct, self._w, self._k32
        ov = self._ov_t()
        ov.hEvent = k32.CreateEventW(None, True, False, None)
        try:
            if not fn(self._h, buf, length, None, ct.byref(ov)):
                if ct.get_last_error() != 997:  # ERROR_IO_PENDING
                    raise OSError(f"HID I/O gagal ({ct.get_last_error()})")
            if k32.WaitForSingleObject(ov.hEvent, timeout_ms) == 0x102:  # WAIT_TIMEOUT
                k32.CancelIoEx(self._h, ct.byref(ov))
                n = w.DWORD(0)
                k32.GetOverlappedResult(self._h, ct.byref(ov), ct.byref(n), True)
                return None
            n = w.DWORD(0)
            if not k32.GetOverlappedResult(self._h, ct.byref(ov), ct.byref(n), False):
                raise OSError(f"HID I/O gagal ({ct.get_last_error()})")
            return int(n.value)
        finally:
            k32.CloseHandle(ov.hEvent)

    def read(self, timeout: float) -> bytes | None:
        if self._h is None or self._closed:
            raise OSError("closed")
        size = max(self.info.input_len, 2)
        buf = self._ct.create_string_buffer(size)
        n = self._transfer(self._k32.ReadFile, buf, size, int(timeout * 1000))
        return None if n is None else buf.raw[:n]

    def write(self, report_id: int, payload: bytes) -> None:
        if self.readonly:
            raise OSError("handle read-only")
        if self._h is None or self._closed:
            raise OSError("closed")
        total = self.info.output_len
        if len(payload) + 1 > total:
            raise TransportError(f"Payload {len(payload)} byte melebihi report output ({total - 1} byte)")
        data = bytes([report_id]) + payload + bytes(total - 1 - len(payload))
        buf = self._ct.create_string_buffer(data, total)
        if self._transfer(self._k32.WriteFile, buf, total, 1000) is None:
            raise OSError("Penulisan HID timeout")

    def close(self) -> None:
        if self._h is None:
            return
        self._closed = True
        self._k32.CancelIoEx(self._h, None)
        self._k32.CloseHandle(self._h)
        self._h = None


class FakeHidIO(HidIO):
    """HID virtual yang dijawab ``MockV10Device`` - untuk test dan simulator."""

    def __init__(self, device=None, respond: bool = True) -> None:
        from ..ble.mock_device import MockV10Device

        self.device = device or MockV10Device()
        self.respond = respond
        self.written: list = []
        self._q: queue.Queue = queue.Queue()
        self._open = False
        self._unplugged = False

    def open(self) -> None:
        self._open = True

    def read(self, timeout: float) -> bytes | None:
        if self._unplugged or not self._open:
            raise OSError("device removed")
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            raise OSError("device removed")
        return item

    def write(self, report_id: int, payload: bytes) -> None:
        if self._unplugged or not self._open:
            raise OSError("device removed")
        self.written.append((report_id, bytes(payload)))
        if self.respond:
            for r in self.device.handle(bytes(payload[: C.PACKET_SIZE])):
                self._q.put(bytes([report_id]) + r + bytes(44))  # report USB biasanya dipadatkan

    def close(self) -> None:
        self._open = False
        self._q.put(None)

    def unplug(self) -> None:
        self._unplugged = True
        self._q.put(None)


# ------------------------------------------------------------------------------------ transport
class HidTransport(Transport):
    label = "USB (HID, eksperimental)"

    def __init__(self, enumerator=enumerate_hid, io_factory=None, report_id: int = 0, include_all: bool = False,
                 probe_timeout: float = PROBE_TIMEOUT_S) -> None:
        self._enumerator = enumerator
        self._io_factory = io_factory or (lambda info: WinHidIO(info))
        self.report_id = report_id
        self.include_all = include_all
        self.probe_timeout = probe_timeout
        self._known: dict = {}
        self._io: HidIO | None = None
        self._reader: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_notify: NotifyCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._probe: asyncio.Future | None = None
        self.verified = False
        self._connected = False

    # ---- discovery
    def candidates(self, infos: list) -> list:
        controllers = {(i.vid, i.pid) for i in infos if i.is_game_controller}
        out = []
        for i in infos:
            if not (i.is_vendor and i.can_exchange_reports):
                continue
            is_pxn = "pxn" in (i.product + i.manufacturer).lower()
            if self.include_all or is_pxn or (i.vid, i.pid) in controllers:
                out.append(i)
        return out

    async def scan(self, timeout: float, on_found: FoundCallback) -> None:
        loop = asyncio.get_running_loop()
        infos = await loop.run_in_executor(None, self._enumerator)
        cands = self.candidates(list(infos))
        if not cands:
            gamepads = [i for i in infos if i.is_game_controller]
            hint = (" Perangkat USB game controller terdeteksi, tetapi tidak ada antarmuka konfigurasi (HID "
                    "vendor-defined dengan report input dan output) - firmware ini kemungkinan hanya "
                    "dikonfigurasi lewat Bluetooth." if gamepads else
                    " Tidak ada perangkat USB game controller yang terdeteksi. Hubungkan setir dengan kabel USB.")
            raise TransportError("Konfigurasi lewat USB tidak tersedia." + hint)
        for info in cands:
            self._known[info.path] = info
            name = f"{info.product or 'USB HID'} · USB {info.id_text} · UP 0x{info.usage_page:04X}"
            on_found(DeviceFound(name, info.path, None))

    async def stop_scan(self) -> None:
        return None

    # ---- connection
    async def connect(self, address: str, on_notify: NotifyCallback, on_disconnect: DisconnectCallback) -> None:
        loop = asyncio.get_running_loop()
        info = self._known.get(address)
        if info is None:
            infos = await loop.run_in_executor(None, self._enumerator)
            info = next((i for i in infos if i.path == address), None)
            if info is None:
                raise TransportError("Perangkat USB tidak ditemukan (dicabut?)")
        io = self._io_factory(info)
        try:
            await loop.run_in_executor(None, io.open)
        except TransportError:
            raise
        except OSError as exc:
            raise TransportError(f"Tidak dapat membuka perangkat USB: {exc}") from exc
        self._io, self._loop = io, loop
        self._on_notify, self._on_disconnect = on_notify, on_disconnect
        self.verified = False
        self._probe = loop.create_future()
        self._stop_reader.clear()
        self._connected = True
        self._reader = threading.Thread(target=self._read_loop, args=(io,), name="hid-reader", daemon=True)
        self._reader.start()
        try:  # satu-satunya paket yang boleh keluar sebelum perangkat terbukti menjawab: baca state
            await self._send(codec.read_state())
            await asyncio.wait_for(self._probe, self.probe_timeout)
        except (asyncio.TimeoutError, OSError, TransportError) as exc:
            await self.disconnect()
            raise TransportError(
                "Perangkat tidak menjawab protokol konfigurasi PXN lewat USB (tidak ada balasan D0). "
                "Tidak ada perintah tulis yang dikirim. Gunakan Bluetooth untuk konfigurasi, atau coba antarmuka "
                "USB lain.") from exc
        self.verified = True

    def _read_loop(self, io: HidIO) -> None:
        loop = self._loop
        while not self._stop_reader.is_set():
            try:
                report = io.read(0.2)
            except OSError:
                if not self._stop_reader.is_set() and loop is not None:
                    loop.call_soon_threadsafe(self._lost)
                return
            if not report or len(report) < 2:
                continue
            frame = bytes(report[1 : 1 + C.PACKET_SIZE])  # byte 0 = report ID
            if loop is not None:
                loop.call_soon_threadsafe(self._deliver, frame)

    def _deliver(self, frame: bytes) -> None:
        if not self._connected:
            return
        if not self.verified:
            if frame and frame[0] == C.REPORT_ID_READ_STATE_RESP and self._probe is not None and not self._probe.done():
                self._probe.set_result(True)  # tidak diteruskan: klien belum siap, ia akan meminta ulang state
            return  # selain balasan probe diabaikan sebelum terverifikasi
        if self._on_notify is not None:
            self._on_notify(frame)

    def _lost(self) -> None:
        was = self._connected
        self._connected = False
        if was and self._on_disconnect is not None:
            self._on_disconnect()

    async def _send(self, data: bytes) -> None:
        io = self._io
        if io is None or not self._connected:
            raise TransportError("Tidak terhubung")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, io.write, self.report_id, bytes(data))
        except OSError as exc:
            raise TransportError(f"Penulisan USB gagal: {exc}") from exc

    async def write(self, data: bytes) -> None:
        if not self.verified and not (data and data[0] == C.REPORT_ID_READ_STATE_REQ):
            raise TransportError("Perangkat USB belum terbukti memakai protokol PXN - perintah tulis ditolak")
        await self._send(data)

    async def disconnect(self) -> None:
        self._connected = False
        self.verified = False
        self._stop_reader.set()
        io, self._io = self._io, None
        if io is not None:
            try:
                io.close()
            except Exception:  # noqa: BLE001
                log.debug("hid close failed", exc_info=True)
        reader, self._reader = self._reader, None
        if reader is not None and reader is not threading.current_thread():
            await asyncio.get_running_loop().run_in_executor(None, reader.join, 1.0)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._io is not None
