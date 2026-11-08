"""Penerima UDP di thread latar. Tidak memakai Qt: ``on_data`` dipanggil dari thread penerima."""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable

from .models import Telemetry
from .parsers import parse

DEFAULT_PORT = 9000  # Constants.TELEMETRY_PORT pada aplikasi asli


def local_ips() -> list:
    """Alamat IPv4 lokal PC (untuk diisikan di pengaturan Data Out / UDP game)."""
    ips: list = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


class UdpTelemetryReceiver:
    def __init__(self, port: int = DEFAULT_PORT, game: str = "auto",
                 on_data: Callable[[Telemetry], None] | None = None, host: str = "0.0.0.0") -> None:
        self.port, self.game, self.on_data, self.host = port, game, on_data, host
        self.packets = 0
        self.rejected = 0
        self.last_packet_at = 0.0
        self.error = ""
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Buka soket dan mulai menerima. False + ``error`` bila port tidak bisa dipakai."""
        if self.running:
            return True
        self.error = ""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))
        except OSError as exc:
            sock.close()
            self.error = f"Port UDP {self.port} tidak dapat dipakai: {exc.strerror or exc}"
            return False
        sock.settimeout(0.25)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="udp-telemetry", daemon=True)
        self._thread.start()
        return True

    @property
    def bound_port(self) -> int:
        return self._sock.getsockname()[1] if self._sock else self.port

    def _run(self) -> None:
        sock = self._sock
        while not self._stop.is_set() and sock is not None:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            t = parse(data, self.game)
            if t is None:
                self.rejected += 1
                continue
            self.packets += 1
            self.last_packet_at = time.monotonic()
            if self.on_data is not None:
                try:
                    self.on_data(t)
                except Exception:  # noqa: BLE001 - callback tidak boleh mematikan penerima
                    pass

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    def age(self) -> float | None:
        return None if not self.last_packet_at else time.monotonic() - self.last_packet_at
