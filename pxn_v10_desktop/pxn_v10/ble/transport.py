"""Transport abstraction: real BLE (bleak) and the simulator implement the same interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from ..core.events import DeviceFound

NotifyCallback = Callable[[bytes], None]
DisconnectCallback = Callable[[], None]
FoundCallback = Callable[[DeviceFound], None]


class TransportError(Exception):
    pass


class Transport(ABC):
    """Minimal GATT-like surface needed by the PXN-V10 protocol (service FFE0)."""

    label = "transport"

    @abstractmethod
    async def scan(self, timeout: float, on_found: FoundCallback) -> None:
        """Scan until ``stop_scan`` is called or ``timeout`` elapses; report matching devices."""

    @abstractmethod
    async def stop_scan(self) -> None: ...

    @abstractmethod
    async def connect(self, address: str, on_notify: NotifyCallback, on_disconnect: DisconnectCallback) -> None:
        """Connect, discover FFE0, enable notifications on FFE2. Raises TransportError."""

    @abstractmethod
    async def write(self, data: bytes) -> None:
        """Write to FFE1."""

    @abstractmethod
    async def disconnect(self) -> None: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
