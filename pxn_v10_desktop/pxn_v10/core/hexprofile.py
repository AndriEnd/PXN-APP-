"""Hex-string profile serializer, compatible with the Android app
(``V10ProfileActivity.packProfile`` / ``unpackProfile``).

Current format (v3, little endian), 93 bytes::

    03 | 36 keymap | angle(2) | ffb | spring | damping | friction | inertia | reverse | 3 x 16 curve bytes

Legacy format (bundled recommended presets, big endian, no header), >= 41 bytes::

    34 keymap | angle(2, BE) | ffb | spring | damping | friction | inertia [| reverse | curves ...]
"""

from __future__ import annotations

import struct

from . import constants as C
from .models import DeviceProfile


class HexProfileError(ValueError):
    pass


def to_hex(data: bytes) -> str:
    return data.hex().upper()


def from_hex(text: str) -> bytes:
    cleaned = "".join(text.split())
    if len(cleaned) % 2:
        raise HexProfileError("hex string has an odd number of digits")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise HexProfileError(str(exc)) from exc


def pack_profile(profile: DeviceProfile) -> str:
    out = bytearray([C.HEX_PROFILE_VERSION])
    for code in C.KEYMAP_SEQUENCE:
        out.append(profile.mapped(code) & 0xFF)
    out += struct.pack("<H", profile.angle & 0xFFFF)
    out += bytes(
        [
            profile.ffb & 0xFF,
            profile.spring & 0xFF,
            profile.damping & 0xFF,
            profile.friction & 0xFF,
            profile.inertia & 0xFF,
            profile.ffb_reverse & 0xFF,
        ]
    )
    for curve in (profile.acc_curve, profile.brake_curve, profile.clutch_curve):
        for x, y in curve:
            out += struct.pack("<HH", x & 0xFFFF, y & 0xFFFF)
    return to_hex(bytes(out))


def unpack_profile(text: str, base: DeviceProfile | None = None) -> DeviceProfile:
    """Parse a hex profile. Missing trailing fields keep the value from ``base`` (or defaults)."""
    data = from_hex(text)
    profile = base.copy() if base is not None else DeviceProfile()
    n_hex_v2 = len(C.KEYMAP_SEQUENCE)  # 36
    if len(data) < len(C.LEGACY_KEY_SEQUENCE) + 7:
        raise HexProfileError(f"profile too short ({len(data)} bytes)")
    pos = 0

    def take(count: int) -> bytes:
        nonlocal pos
        chunk = data[pos : pos + count]
        if len(chunk) < count:
            raise HexProfileError("profile data truncated")
        pos += count
        return chunk

    if len(data) > len(C.LEGACY_KEY_SEQUENCE) + 7:  # v2/v3: header + 36 keys + LE angle
        take(1)
        for code in C.KEYMAP_SEQUENCE:
            profile.keymap[code] = take(1)[0]
        profile.angle = struct.unpack("<H", take(2))[0]
    else:  # legacy: 34 keys + BE angle
        for code in C.LEGACY_KEY_SEQUENCE:
            profile.keymap[code] = take(1)[0]
        profile.angle = struct.unpack(">H", take(2))[0]
    profile.ffb = take(1)[0]
    profile.spring = take(1)[0]
    profile.damping = take(1)[0]
    profile.friction = take(1)[0]
    profile.inertia = take(1)[0]
    if len(data) > n_hex_v2 + 8:
        profile.ffb_reverse = take(1)[0]
    if len(data) > n_hex_v2 + 9:
        for name in ("acc_curve", "brake_curve", "clutch_curve"):
            pts = []
            for _ in range(4):
                x, y = struct.unpack("<HH", take(4))
                pts.append([x, y])
            setattr(profile, name, pts)
    return profile
