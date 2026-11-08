"""Sumber demo dan pembangun paket uji (dipakai test dan mode Demo di UI)."""

from __future__ import annotations

import math
import struct

from .models import Telemetry
from .parsers import DIRT_LEN, FORZA_LEN

GEAR_TOP_KMH = (0, 45, 80, 120, 165, 205, 250)  # batas atas kecepatan tiap gigi (indeks = gigi)


def demo(t: float) -> Telemetry:
    """Mobil virtual berakselerasi 0 sampai ~240 km/h lalu mengerem, berulang tiap 24 detik."""
    cycle = (t % 24.0) / 24.0
    frac = cycle / 0.7 if cycle < 0.7 else 1 - (cycle - 0.7) / 0.3
    speed = 240 * max(0.0, min(1.0, frac)) ** 1.1
    gear = next((g for g in range(1, 7) if speed <= GEAR_TOP_KMH[g]), 6)
    lo, hi = GEAR_TOP_KMH[gear - 1], GEAR_TOP_KMH[gear]
    rpm_frac = 0.3 + 0.62 * max(0.0, min(1.0, (speed - lo) / (hi - lo))) if speed > 1 else 0.18
    lap_t = t % 83.0
    return Telemetry("demo", speed, rpm_frac * 8000 + 40 * math.sin(t * 7), 8000.0, gear if speed > 1 else 0,
                     int(t // 83) + 1, lap_t, 81.234, True).sanitized()


def build_forza_packet(speed_kmh=0.0, rpm=0.0, max_rpm=0.0, gear=1, lap=0, lap_time=0.0, best_lap=0.0) -> bytes:
    b = bytearray(FORZA_LEN)
    struct.pack_into("<f", b, 256, speed_kmh / 3.6)
    struct.pack_into("<f", b, 16, rpm)
    struct.pack_into("<f", b, 8, max_rpm)
    b[319] = gear & 0xFF
    struct.pack_into("<h", b, 312, lap)
    struct.pack_into("<f", b, 304, lap_time)
    struct.pack_into("<f", b, 296, best_lap)
    return bytes(b)


def build_dirt_packet(speed_kmh=0.0, rpm=0.0, max_rpm=0.0, gear=1) -> bytes:
    b = bytearray(DIRT_LEN)
    struct.pack_into("<f", b, 28, speed_kmh / 3.6)
    struct.pack_into("<f", b, 132, float(gear))
    struct.pack_into("<f", b, 148, rpm)
    struct.pack_into("<f", b, 252, max_rpm)
    return bytes(b)
