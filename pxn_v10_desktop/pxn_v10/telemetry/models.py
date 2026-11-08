"""Model data telemetri yang sama untuk semua game."""

from __future__ import annotations

import math
from dataclasses import dataclass

KMH_TO_MPH = 0.621371


def _finite(v: float, default: float = 0.0) -> float:
    return v if isinstance(v, (int, float)) and math.isfinite(v) else default


@dataclass
class Telemetry:
    source: str = ""
    speed_kmh: float = 0.0
    rpm: float = 0.0
    max_rpm: float = 0.0
    gear: int | None = None  # -1 = R, 0 = N, 1.. = gigi; None = tidak diketahui
    lap: int | None = None  # nomor lap yang sedang berjalan (mulai 1)
    lap_time: float | None = None  # detik
    best_lap: float | None = None  # detik
    rpm_exact: bool = True  # False: satuan RPM game tidak pasti, hanya rasio yang bermakna

    def sanitized(self) -> "Telemetry":
        self.speed_kmh = max(0.0, _finite(self.speed_kmh))
        self.rpm = max(0.0, _finite(self.rpm))
        self.max_rpm = max(0.0, _finite(self.max_rpm))
        return self

    @property
    def rpm_fraction(self) -> float:
        return 0.0 if self.max_rpm <= 0 else max(0.0, min(1.0, self.rpm / self.max_rpm))

    def speed(self, unit: str = "kmh") -> float:
        return self.speed_kmh * (KMH_TO_MPH if unit == "mph" else 1.0)

    @property
    def gear_text(self) -> str:
        if self.gear is None:
            return "–"
        return "R" if self.gear < 0 else ("N" if self.gear == 0 else str(self.gear))


def format_lap_time(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return "--:--.---"
    return f"{int(seconds // 60):02d}:{seconds % 60:06.3f}"
