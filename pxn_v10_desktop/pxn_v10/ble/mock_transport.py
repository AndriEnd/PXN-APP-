"""Simulator transport: lets the full stack run without a physical PXN-V10."""

from __future__ import annotations

import asyncio
import time

from ..core import constants as C
from ..core.events import DeviceFound
from .mock_device import MockV10Device
from .transport import DisconnectCallback, FoundCallback, NotifyCallback, Transport, TransportError

SIM_ADDRESS = "SI:MU:LA:TO:R0:10"


class MockTransport(Transport):
    label = "Simulator"

    def __init__(self, device: MockV10Device | None = None, latency: float = 0.02, telemetry_hz: float = 60.0) -> None:
        self.device = device or MockV10Device()
        self.latency = latency
        self.telemetry_hz = telemetry_hz
        self._connected = False
        self._on_notify: NotifyCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._stop: asyncio.Event | None = None
        self._telemetry_task: asyncio.Task | None = None
        self.fail_next_connect = False

    # ---------------------------------------------------------------- scanning
    async def scan(self, timeout: float, on_found: FoundCallback) -> None:
        self._stop = asyncio.Event()
        await asyncio.sleep(min(0.6, timeout))
        if not self._stop.is_set():
            on_found(DeviceFound(f"{C.DEVICE_NAME} (Simulator)", SIM_ADDRESS, -48))
        try:
            await asyncio.wait_for(self._stop.wait(), max(0.0, timeout - 0.6))
        except asyncio.TimeoutError:
            pass

    async def stop_scan(self) -> None:
        if self._stop is not None:
            self._stop.set()

    # -------------------------------------------------------------- connection
    async def connect(self, address: str, on_notify: NotifyCallback, on_disconnect: DisconnectCallback) -> None:
        await asyncio.sleep(self.latency * 5)
        if self.fail_next_connect:
            self.fail_next_connect = False
            raise TransportError("Simulasi: koneksi gagal (GATT 133)")
        self._on_notify, self._on_disconnect = on_notify, on_disconnect
        self._connected = True

    async def write(self, data: bytes) -> None:
        if not self._connected:
            raise TransportError("Tidak terhubung")
        responses = self.device.handle(data)
        loop = asyncio.get_running_loop()
        for r in responses:
            loop.call_later(self.latency, self._deliver, r)
        # start / stop the telemetry stream together with test mode
        if self.device.testing and self._telemetry_task is None:
            self._telemetry_task = loop.create_task(self._telemetry_loop())
        elif not self.device.testing and self._telemetry_task is not None:
            self._telemetry_task.cancel()
            self._telemetry_task = None

    def _deliver(self, frame: bytes) -> None:
        if self._connected and self._on_notify is not None:
            self._on_notify(frame)

    async def _telemetry_loop(self) -> None:
        t0 = time.monotonic()
        try:
            while self._connected and self.device.testing:
                self._deliver(self.device.telemetry_frame(time.monotonic() - t0))
                await asyncio.sleep(1.0 / self.telemetry_hz)
        except asyncio.CancelledError:
            pass
        finally:
            self._telemetry_task = None

    async def disconnect(self) -> None:
        self._connected = False
        if self._telemetry_task is not None:
            self._telemetry_task.cancel()
            self._telemetry_task = None
        self.device.testing = False

    def simulate_link_loss(self) -> None:
        """Test hook: behave like the wheel being switched off."""
        self._connected = False
        self.device.testing = False
        if self._on_disconnect is not None:
            self._on_disconnect()

    @property
    def is_connected(self) -> bool:
        return self._connected
