"""Instrumen speedometer: gauge kecepatan melingkar (jarum + busur), deretan LED RPM, lencana gigi."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme

START_DEG = 225.0  # titik awal skala (kiri-bawah), derajat berlawanan arah jarum jam dari jam 3
SWEEP_DEG = 270.0


def nice_scale(max_value: float) -> tuple:
    """(skala_maks, langkah_mayor) yang rapi untuk ``max_value``: contoh 237 -> (240, 20)."""
    if max_value <= 0:
        return 100.0, 10.0
    steps = (10, 20, 25, 50, 100)
    for step in steps:
        top = math.ceil(max_value / step) * step
        if top / step <= 14:
            return float(top), float(step)
    return float(math.ceil(max_value / 100) * 100), 100.0


class SpeedoGauge(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(340, 340)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._speed = 0.0
        self._max = 240.0
        self._unit = "km/h"
        self._rpm = 0.0
        self._active = False

    # ---- data
    def set_scale(self, top: float, unit: str) -> None:
        self._max, self._unit = float(top), unit
        self.update()

    def set_state(self, speed: float, rpm_fraction: float, active: bool = True) -> None:
        speed = max(0.0, float(speed))
        rpm_fraction = max(0.0, min(1.0, float(rpm_fraction)))
        if (speed, rpm_fraction, active) != (self._speed, self._rpm, self._active):
            self._speed, self._rpm, self._active = speed, rpm_fraction, active
            self.update()

    @property
    def speed(self) -> float:
        return self._speed

    # ---- geometry
    def _angle(self, value: float) -> float:
        frac = max(0.0, min(1.0, value / self._max)) if self._max else 0.0
        return START_DEG - SWEEP_DEG * frac

    @staticmethod
    def _pt(c: QPointF, r: float, deg: float) -> QPointF:
        a = math.radians(deg)
        return QPointF(c.x() + r * math.cos(a), c.y() - r * math.sin(a))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        r = side / 2 - 14
        top, step = nice_scale(self._max)
        # bezel
        p.setPen(QPen(QColor(theme.BORDER), 2))
        p.setBrush(QColor(theme.SURFACE))
        p.drawEllipse(c, r + 8, r + 8)
        # alur skala
        arc = QRectF(c.x() - r + 8, c.y() - r + 8, 2 * (r - 8), 2 * (r - 8))
        p.setPen(QPen(QColor(theme.SURFACE_3), 10, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(arc, int(START_DEG * 16), int(-SWEEP_DEG * 16))
        # busur nilai (gradasi hijau -> oranye -> merah mengikuti posisi)
        frac = max(0.0, min(1.0, self._speed / self._max)) if self._max else 0.0
        if frac > 0.002:
            g = QColor(theme.GREEN if frac < 0.55 else theme.AMBER if frac < 0.82 else theme.RED)
            p.setPen(QPen(g, 10, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(arc, int(START_DEG * 16), int(-SWEEP_DEG * frac * 16))
        # tik dan label
        n = int(round(self._max / step))
        label_every = 1 if n <= 12 else 2
        p.setFont(QFont(theme.FONT_FAMILY, max(8, int(side / 42)), QFont.Bold))
        for i in range(n + 1):
            v = i * step
            deg = self._angle(v)
            p.setPen(QPen(QColor(theme.TEXT_DIM), 2.2))
            p.drawLine(self._pt(c, r - 22, deg), self._pt(c, r - 34, deg))
            if i % label_every == 0:
                tp = self._pt(c, r - 54, deg)
                p.setPen(QColor(theme.TEXT_DIM))
                p.drawText(QRectF(tp.x() - 24, tp.y() - 11, 48, 22), Qt.AlignCenter, f"{v:.0f}")
            if i < n:  # tik minor di antara dua tik mayor
                p.setPen(QPen(QColor(theme.TEXT_MUTED), 1.2))
                mid = self._angle(v + step / 2)
                p.drawLine(self._pt(c, r - 22, mid), self._pt(c, r - 28, mid))
        # jarum
        deg = self._angle(self._speed)
        p.setPen(QPen(QColor(theme.ACCENT), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(self._pt(c, 14, deg), self._pt(c, r - 38, deg))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawEllipse(c, 13, 13)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(c, 6, 6)
        # angka digital
        p.setPen(QColor(theme.TEXT if self._active else theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, max(20, int(side / 8)), QFont.Bold))
        p.drawText(QRectF(c.x() - r / 2, c.y() + r * 0.22, r, r * 0.34), Qt.AlignCenter, f"{self._speed:.0f}")
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, max(8, int(side / 38)), QFont.Bold))
        p.drawText(QRectF(c.x() - r / 2, c.y() + r * 0.55, r, 20), Qt.AlignCenter, self._unit.upper())


class RpmLeds(QWidget):
    """Deretan LED RPM seperti vLed pada aplikasi asli: hijau, lalu kuning, 25% terakhir merah."""

    def __init__(self, count: int = 24, parent=None) -> None:
        super().__init__(parent)
        self.count = count
        self._value = 0.0
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction != self._value:
            self._value = fraction
            self.update()

    @property
    def lit(self) -> int:
        return int(round(self._value * self.count))

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        gap = 4.0
        w = (self.width() - gap * (self.count - 1)) / self.count
        lit = self.lit
        p.setPen(Qt.NoPen)
        for i in range(self.count):
            pos = i / max(1, self.count - 1)
            color = QColor(theme.GREEN if pos < 0.55 else theme.AMBER if pos < 0.78 else theme.RED)
            if i >= lit:
                color.setAlpha(46)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(i * (w + gap), 3, w, self.height() - 6), 3, 3)


class GearDisplay(QWidget):
    """Lencana gigi besar (R / N / 1..)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = "–"
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_gear(self, text: str) -> None:
        if text != self.text:
            self.text = text
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 8
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        idle = self.text in ("–", "N")
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0, QColor(theme.SURFACE_3))
        g.setColorAt(1, QColor(theme.SURFACE_2))
        p.setPen(QPen(QColor(theme.BORDER if idle else theme.ACCENT), 2))
        p.setBrush(g)
        p.drawRoundedRect(rect, 22, 22)
        color = theme.RED if self.text == "R" else (theme.TEXT_MUTED if idle else theme.TEXT)
        p.setPen(QColor(color))
        p.setFont(QFont(theme.FONT_FAMILY, int(side * 0.42), QFont.Bold))
        p.drawText(rect, Qt.AlignCenter, self.text)
