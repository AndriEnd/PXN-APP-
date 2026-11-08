"""Penguraian paket UDP game. Offset diambil dari aplikasi Android asli (MeterForzaActivity / MeterDirtActivity):

* Forza Horizon 4/5 "Dash" (paket 324 byte, little-endian): kecepatan float@256 (m/s), RPM float@16,
  RPM maks float@8, gigi byte@319 (0 = R), lap short@312, waktu lap float@304, lap terbaik float@296.
* DiRT Rally 2.0 (UDP lama, extradata=3, 264 byte = 66 float): kecepatan float@28 (m/s), gigi float@132 (-1 = R),
  RPM float@148, RPM maks float@252.
"""

from __future__ import annotations

import struct

from .models import Telemetry

GAMES = {"forza": "Forza Horizon 4 / 5", "dirt": "DiRT Rally 2.0"}
FORZA_LEN = 324
DIRT_LEN = 264
FORZA_MIN = 320  # byte terakhir yang dibaca (gigi) ada di indeks 319
DIRT_MIN = 256  # float terakhir yang dibaca ada di offset 252..255


def detect(packet: bytes) -> str | None:
    """Tebak game dari panjang paket (mode Otomatis)."""
    if len(packet) == FORZA_LEN:
        return "forza"
    if len(packet) == DIRT_LEN:
        return "dirt"
    return None


def parse_forza(packet: bytes) -> Telemetry | None:
    if len(packet) < FORZA_MIN:
        return None
    f = struct.unpack_from
    gear = packet[319]
    return Telemetry(
        source="forza",
        speed_kmh=f("<f", packet, 256)[0] * 3.6,
        rpm=f("<f", packet, 16)[0],
        max_rpm=f("<f", packet, 8)[0],
        gear=-1 if gear == 0 else gear,
        lap=f("<h", packet, 312)[0] + 1,
        lap_time=f("<f", packet, 304)[0],
        best_lap=f("<f", packet, 296)[0],
        rpm_exact=True,
    ).sanitized()


def parse_dirt(packet: bytes) -> Telemetry | None:
    if len(packet) < DIRT_MIN:
        return None
    f = struct.unpack_from
    gear = f("<f", packet, 132)[0]
    gear_i = int(gear) if gear == gear and abs(gear) < 100 else 0
    return Telemetry(
        source="dirt",
        speed_kmh=f("<f", packet, 28)[0] * 3.6,
        rpm=f("<f", packet, 148)[0],
        max_rpm=f("<f", packet, 252)[0],
        gear=gear_i,
        rpm_exact=False,  # Codemasters memakai skala RPM/10; aplikasi asli hanya memakai rasio
    ).sanitized()


def parse(packet: bytes, game: str = "auto") -> Telemetry | None:
    if game == "auto":
        game = detect(packet) or ""
    if game == "forza":
        return parse_forza(packet)
    if game == "dirt":
        return parse_dirt(packet)
    return None
