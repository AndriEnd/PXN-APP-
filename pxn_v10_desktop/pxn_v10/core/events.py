"""Events emitted by the wheel client (V10ChangeEvent / V10ConnEvent / V10TestEvent)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class ConnState(str, Enum):
    """Connection FSM: DISCONNECTED -> SCANNING -> CONNECTING -> DISCOVERING_SERVICES
    -> INITIALIZING_NOTIFY -> READY (-> RECONNECTING on link loss)."""

    DISCONNECTED = "disconnected"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    DISCOVERING_SERVICES = "discovering_services"
    INITIALIZING_NOTIFY = "initializing_notify"
    READY = "ready"
    DISCONNECTING = "disconnecting"
    RECONNECTING = "reconnecting"


class Change(IntEnum):
    """Same numbering as the type field of V10ChangeEvent in the Android code."""

    STATE = 1
    PROFILE_READY = 2
    MODE = 3
    KEYMAP = 4
    FFB = 5
    ANGLE = 6
    PEDAL_STATE = 8
    LEVER_STATE = 9
    RESET_DONE = 10
    FORCE = 11
    PROFILE_WRITTEN = 12
    BRAKE_STATE = 13
    PROFILE_PAGE = 20  # extra: every received page (progress indication)


@dataclass(frozen=True)
class ConnEvent:
    state: ConnState
    message: str = ""


@dataclass(frozen=True)
class ChangeEvent:
    type: Change
    detail: int = 0


@dataclass(frozen=True)
class TestEvent:
    __test__ = False
    snapshot: object  # TestSnapshot


@dataclass(frozen=True)
class DeviceFound:
    name: str
    address: str
    rssi: int | None = None


@dataclass(frozen=True)
class ErrorEvent:
    message: str


@dataclass(frozen=True)
class LogEvent:
    direction: str  # "TX" | "RX"
    data: bytes
