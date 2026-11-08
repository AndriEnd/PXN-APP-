"""Binary packet codec: encoders for requests (App -> Wheel) and decoder for notifications."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from . import constants as C


# ------------------------------------------------------------------ encoders
def read_state() -> bytes:
    return bytes([C.REPORT_ID_READ_STATE_REQ, 0x01])


def read_profile_page(mode: int, page: int) -> bytes:
    return bytes([C.REPORT_ID_READ_PROFILE_REQ, mode & 0xFF, page & 0xFF])


def switch_mode(mode: int) -> bytes:
    return bytes([C.REPORT_ID_EDIT_PARAMS_REQ, C.CMD_SWITCH_MODE, mode & 0xFF])


def key_mapping(mode: int, original: int, mapped: int) -> bytes:
    return bytes([C.REPORT_ID_EDIT_PARAMS_REQ, C.CMD_UPDATE_KEYMAP, mode & 0xFF, original & 0xFF, mapped & 0xFF])


def force_feedback(mode: int, ffb: int, reverse: int) -> bytes:
    return bytes([C.REPORT_ID_EDIT_PARAMS_REQ, C.CMD_UPDATE_FFB, mode & 0xFF, ffb & 0xFF, reverse & 0xFF])


def steering_angle(mode: int, angle: int) -> bytes:
    return bytes(
        [C.REPORT_ID_EDIT_PARAMS_REQ, C.CMD_UPDATE_ANGLE, mode & 0xFF, 0x01, angle & 0xFF, (angle >> 8) & 0xFF]
    )


def profile_reset(mode: int) -> bytes:
    return bytes([C.REPORT_ID_EDIT_PARAMS_REQ, C.CMD_RESET_PROFILE, mode & 0xFF])


def physics_forces(spring: int, damping: int, friction: int, inertia: int) -> bytes:
    return bytes(
        [
            C.REPORT_ID_EDIT_PARAMS_REQ,
            C.CMD_UPDATE_FORCE,
            0x01,
            spring & 0xFF,
            damping & 0xFF,
            friction & 0xFF,
            inertia & 0xFF,
        ]
    )


def test_mode(enter: bool) -> bytes:
    return bytes([C.REPORT_ID_TESTING_REQ, C.CMD_TESTING_ENTER if enter else C.CMD_TESTING_EXIT])


def dedup_key(packet: bytes) -> tuple | None:
    """Identity of a packet for write-queue replacement (a newer packet of the same kind replaces
    the queued one - e.g. a slider dragged quickly). ``None`` = never replace."""
    if not packet:
        return None
    op = packet[0]
    if op == C.REPORT_ID_EDIT_PARAMS_REQ and len(packet) > 1:
        sub = packet[1]
        if sub == C.CMD_UPDATE_KEYMAP and len(packet) > 3:
            return ("edit", sub, packet[3])  # per physical key
        if sub in (C.CMD_SWITCH_MODE, C.CMD_UPDATE_FFB, C.CMD_UPDATE_ANGLE, C.CMD_UPDATE_FORCE):
            return ("edit", sub)
        return None
    if op == C.REPORT_ID_WRITE_PROFILE_REQ and len(packet) > 2:
        return ("write_page", packet[2])
    if op == C.REPORT_ID_READ_PROFILE_REQ and len(packet) > 2:
        return ("read_page", packet[2])
    if op == C.REPORT_ID_READ_STATE_REQ:
        return ("read_state",)
    return None


# ------------------------------------------------------------------ decoder
@dataclass
class Inbound:
    """A decoded notification."""

    kind: str  # state | profile_page | write_ack | edit_ack | telemetry | test_ack | unknown
    raw: bytes
    data: dict[str, Any]


def decode(packet: bytes) -> Inbound:
    """Route a raw notification by its opcode (Wheel_V10.handleNotifyData)."""
    raw = bytes(packet)
    b = raw + bytes(max(0, C.PACKET_SIZE - len(raw)))  # tolerate short frames
    if not raw:
        return Inbound("unknown", raw, {})
    op = b[0]
    if op == C.REPORT_ID_READ_STATE_RESP:
        return Inbound("state", raw, {})
    if op == C.REPORT_ID_READ_PROFILE_RESP:
        return Inbound("profile_page", raw, {"page": b[2], "mode": b[1]})
    if op == C.REPORT_ID_WRITE_PROFILE_RESP:
        return Inbound("write_ack", raw, {"page": b[2], "value": struct.unpack_from("<H", b, 3)[0]})
    if op in (C.REPORT_ID_EDIT_PARAMS_RESP, C.REPORT_ID_EDIT_PARAMS_REQ):
        return Inbound("edit_ack", raw, _decode_edit_ack(b))
    if op == C.REPORT_ID_TESTING_RESP:
        if b[1] == C.CMD_TESTING_DATA:
            return Inbound("telemetry", raw, {})
        return Inbound("test_ack", raw, {"cmd": b[1]})
    return Inbound("unknown", raw, {"opcode": op})


def _decode_edit_ack(b: bytes) -> dict[str, Any]:
    sub = b[1]
    d: dict[str, Any] = {"sub": sub}
    if sub == C.CMD_SWITCH_MODE:
        d["mode"] = b[2]
    elif sub == C.CMD_UPDATE_KEYMAP:
        d["key"], d["mapped"] = b[3], b[4]
    elif sub == C.CMD_UPDATE_FFB:
        d["ffb"], d["reverse"] = b[3], b[4]
    elif sub == C.CMD_UPDATE_ANGLE:
        d["angle_mode"] = b[3]
        d["angle"] = struct.unpack_from("<H", b, 4)[0]
    elif sub in (C.CMD_UPDATE_PEDAL, C.CMD_UPDATE_LEVER, C.CMD_UPDATE_BRAKE):
        d["state"] = b[3]
    elif sub == C.CMD_UPDATE_FORCE:
        d["spring"], d["damping"], d["friction"], d["inertia"] = b[3], b[4], b[5], b[6]
    return d
