"""Test-screen instruments: steering gauge, vertical pedal bars, gear badge, scan radar."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class SteeringGauge(QWidget):
    """Wheel graphic that rotates smoothly (interpolated at ~60 FPS) with the sensor reading."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._target = 0.0  # -1..1
        self._shown = 0.0
        self._full_lock = 900  # degrees lock-to-lock
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_range(self, degrees: int) -> None:
        self._full_lock = max(90, int(degrees))
        self.update()

    def set_fraction(self, fraction: float) -> None:
        self._target = max(-1.0, min(1.0, fraction))
        if not self._timer.isActive():
            self._timer.start()

    def reset(self) -> None:
        self._target = self._shown = 0.0
        self._timer.stop()
        self.update()

    @property
    def degrees(self) -> float:
        return self._shown * self._full_lock / 2

    def _tick(self) -> None:
        self._shown = _lerp(self._shown, self._target, 0.28)
        if abs(self._shown - self._target) < 0.0008:
            self._shown = self._target
            self._timer.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h - 70)
        c = QPointF(w / 2, size / 2 + 8)
        r = size / 2 - 10
        # arc scale
        p.setPen(QPen(QColor(theme.SURFACE_3), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(c.x() - r - 8, c.y() - r - 8, 2 * (r + 8), 2 * (r + 8)), 210 * 16, -240 * 16)
        frac = self._shown
        if abs(frac) > 0.004:
            p.setPen(QPen(QColor(theme.ACCENT), 6, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(c.x() - r - 8, c.y() - r - 8, 2 * (r + 8), 2 * (r + 8)), 90 * 16, int(-frac * 120 * 16))
        # rotating wheel
        p.save()
        p.translate(c)
        p.rotate(frac * 180)  # visual range +/-180deg regardless of the configured lock
        rim = QPen(QColor("#3A4453"), r * 0.17)
        p.setPen(rim)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r * 0.88, r * 0.88)
        p.setPen(QPen(QColor("#2C3440"), r * 0.13))
        p.drawLine(QPointF(-r * 0.8, r * 0.04), QPointF(-r * 0.22, r * 0.04))
        p.drawLine(QPointF(r * 0.8, r * 0.04), QPointF(r * 0.22, r * 0.04))
        p.drawLine(QPointF(0, r * 0.22), QPointF(0, r * 0.8))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2C3440"))
        p.drawEllipse(QPointF(0, 0), r * 0.26, r * 0.26)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(-r * 0.04, -r * 1.0, r * 0.08, r * 0.24), 3, 3)
        p.restore()
        # digital value
        deg = self.degrees
        p.setPen(QColor(theme.TEXT))
        p.setFont(QFont(theme.FONT_FAMILY, 24, QFont.Bold))
        p.drawText(QRectF(0, size + 4, w, 40), Qt.AlignCenter, f"{deg:+.0f}°".replace("+0°", "0°"))
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(0, size + 42, w, 16), Qt.AlignCenter, f"RANGE ±{self._full_lock // 2}°")
        # centered bar
        bar = QRectF(w * 0.12, size + 62, w * 0.76, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawRoundedRect(bar, 3, 3)
        mid = bar.center().x()
        half = bar.width() / 2 * frac
        fill = QRectF(min(mid, mid + half), bar.top(), abs(half), bar.height())
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(fill, 3, 3)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(mid + half, bar.center().y()), 7, 7)


class PedalBar(QWidget):
    """Vertical progress bar 0-100 % (raw sensor values are 0-255)."""

    def __init__(self, title: str, color: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self._raw = 0
        self._shown = 0.0
        self.setMinimumSize(78, 230)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_raw(self, value: int) -> None:
        self._raw = max(0, min(255, int(value)))
        if not self._timer.isActive():
            self._timer.start()

    def reset(self) -> None:
        self._raw = 0
        self._shown = 0.0
        self._timer.stop()
        self.update()

    def percent(self) -> float:
        return self._raw / 255 * 100

    def _tick(self) -> None:
        target = self._raw / 255
        self._shown = _lerp(self._shown, target, 0.35)
        if abs(self._shown - target) < 0.002:
            self._shown = target
            self._timer.stop()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(w / 2 - 17, 26, 34, h - 26 - 38)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawRoundedRect(track, 12, 12)
        fh = track.height() * self._shown
        if fh > 1:
            fill = QRectF(track.left(), track.bottom() - fh, track.width(), fh)
            g = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            g.setColorAt(0, self.color.lighter(125))
            g.setColorAt(1, self.color.darker(115))
            p.setBrush(g)
            p.drawRoundedRect(fill, 12, 12)
        p.setPen(QColor(theme.TEXT))
        p.setFont(QFont(theme.FONT_FAMILY, 11, QFont.Bold))
        p.drawText(QRectF(0, 0, w, 22), Qt.AlignCenter, f"{self._shown * 100:.0f}%")
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(0, h - 30, w, 18), Qt.AlignCenter, self.title.upper())


class GearBadge(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = "N"
        self.setMinimumSize(150, 150)
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
        neutral = self.text == "N"
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0, QColor(theme.SURFACE_3))
        g.setColorAt(1, QColor(theme.SURFACE_2))
        p.setPen(QPen(QColor(theme.BORDER if neutral else theme.ACCENT), 2))
        p.setBrush(g)
        p.drawRoundedRect(rect, 24, 24)
        p.setPen(QColor(theme.TEXT_MUTED if neutral else theme.TEXT))
        p.setFont(QFont(theme.FONT_FAMILY, int(side * 0.34), QFont.Bold))
        p.drawText(rect.adjusted(0, -side * 0.04, 0, 0), Qt.AlignCenter, self.text)
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(rect.left(), rect.bottom() - 26, rect.width(), 18), Qt.AlignCenter, "GEAR")


class Radar(QWidget):
    """Pulsing rings shown while scanning (Task 5.2)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self._phase = 0.0
        self._active = False
        self._connected = False
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and not self._timer.isActive():
            self._timer.start()
        if not active:
            self._timer.stop()
        self.update()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        maxr = min(self.width(), self.height()) / 2 - 4
        color = QColor(theme.GREEN if self._connected else theme.ACCENT)
        for i in range(3):
            base = (self._phase + i / 3) % 1.0 if self._active else (0.38 + i * 0.2)
            r = maxr * (0.3 + 0.7 * base)
            alpha = int(150 * (1 - base)) if self._active else 38
            pen = QPen(QColor(color.red(), color.green(), color.blue(), alpha), 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)
        glow = QRadialGradient(c, maxr * 0.36)
        glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 90))
        glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, maxr * 0.36, maxr * 0.36)
        # center wheel glyph
        r = maxr * 0.2
        p.setPen(QPen(color, 4))
        p.setBrush(QColor(theme.SURFACE))
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.28, r * 0.28)
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() - r * 0.28, c.y()))
        p.drawLine(QPointF(c.x() + r, c.y()), QPointF(c.x() + r * 0.28, c.y()))
        p.drawLine(QPointF(c.x(), c.y() + r * 0.28), QPointF(c.x(), c.y() + r))


def rssi_bars(rssi: int | None) -> int:
    """0..4 bars from an RSSI in dBm."""
    if rssi is None:
        return 0
    if rssi >= -55:
        return 4
    if rssi >= -67:
        return 3
    if rssi >= -78:
        return 2
    if rssi >= -90:
        return 1
    return 0


class SignalBars(QWidget):
    def __init__(self, bars: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.bars = bars
        self.setFixedSize(26, 18)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(4):
            p.setBrush(QColor(theme.GREEN if i < self.bars else theme.SURFACE_3))
            h = 5 + i * 4
            p.drawRoundedRect(QRectF(i * 6.5, 18 - h, 4.5, h), 1.5, 1.5)
