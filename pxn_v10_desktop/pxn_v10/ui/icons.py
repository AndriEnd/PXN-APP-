"""Small vector icons drawn with QPainter (no image assets needed, crisp at any DPI)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _canvas(size: int, ratio: float = 2.0):
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.setDevicePixelRatio(ratio)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    return px, p


def _pen(color: str, width: float = 1.8) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def draw_icon(name: str, color: str = theme.TEXT_DIM, size: int = 20) -> QPixmap:
    px, p = _canvas(size)
    s = float(size)
    p.setPen(_pen(color, 1.7))
    p.setBrush(Qt.NoBrush)
    c = QPointF(s / 2, s / 2)
    if name == "connect":  # signal waves
        p.setBrush(QColor(color))
        p.drawEllipse(c, 1.8, 1.8)
        p.setBrush(Qt.NoBrush)
        for r in (5.0, 8.0):
            p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 45 * 16, 90 * 16)
            p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 225 * 16, 90 * 16)
    elif name == "dashboard":  # steering wheel
        p.drawEllipse(c, 8.2, 8.2)
        p.drawEllipse(c, 2.2, 2.2)
        p.drawLine(QPointF(c.x() - 8.2, c.y()), QPointF(c.x() - 2.2, c.y()))
        p.drawLine(QPointF(c.x() + 2.2, c.y()), QPointF(c.x() + 8.2, c.y()))
        p.drawLine(QPointF(c.x(), c.y() + 2.2), QPointF(c.x(), c.y() + 8.2))
    elif name == "test":  # gauge
        r = 8.2
        p.drawArc(QRectF(c.x() - r, c.y() - r + 1.5, 2 * r, 2 * r), 20 * 16, 140 * 16)
        a = math.radians(55)
        p.drawLine(QPointF(c.x(), c.y() + 1.5), QPointF(c.x() + 6 * math.cos(a), c.y() + 1.5 - 6 * math.sin(a)))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(c.x(), c.y() + 1.5), 1.4, 1.4)
    elif name == "presets":  # stacked cards
        p.drawRoundedRect(QRectF(3.5, 3, 13, 5), 1.8, 1.8)
        p.drawRoundedRect(QRectF(3.5, 9.5, 13, 3.5), 1.8, 1.8)
        p.drawRoundedRect(QRectF(3.5, 14.5, 13, 3), 1.5, 1.5)
    elif name == "ini":  # document
        path = QPainterPath()
        path.moveTo(5, 2.5)
        path.lineTo(11.5, 2.5)
        path.lineTo(15.5, 6.5)
        path.lineTo(15.5, 17.5)
        path.lineTo(5, 17.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(11.5, 2.5), QPointF(11.5, 6.5))
        p.drawLine(QPointF(11.5, 6.5), QPointF(15.5, 6.5))
        for y in (10, 13):
            p.drawLine(QPointF(7.5, y), QPointF(13, y))
    elif name == "info":
        p.drawEllipse(c, 8.2, 8.2)
        p.drawLine(QPointF(c.x(), c.y() - 0.5), QPointF(c.x(), c.y() + 3.8))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(c.x(), c.y() - 3.4), 0.9, 0.9)
    elif name == "speed":  # speedometer: busur + jarum + tik
        r = 8.4
        p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), -40 * 16, 260 * 16)
        for deg in (215, 150, 90, 30, -35):
            a = math.radians(deg)
            p.drawLine(QPointF(c.x() + (r - 1.2) * math.cos(a), c.y() - (r - 1.2) * math.sin(a)),
                       QPointF(c.x() + (r - 3.2) * math.cos(a), c.y() - (r - 3.2) * math.sin(a)))
        a = math.radians(55)
        p.drawLine(c, QPointF(c.x() + 6 * math.cos(a), c.y() - 6 * math.sin(a)))
        p.setBrush(QColor(color))
        p.drawEllipse(c, 1.5, 1.5)
        p.setBrush(Qt.NoBrush)
    elif name == "template":  # three faders
        for x, y in ((5.5, 7.0), (10, 12.5), (14.5, 8.5)):
            p.drawLine(QPointF(x, 3.5), QPointF(x, 16.5))
            p.setBrush(QColor(theme.SURFACE))
            p.drawRoundedRect(QRectF(x - 2.2, y - 1.6, 4.4, 3.2), 1.2, 1.2)
        p.setBrush(Qt.NoBrush)
    elif name == "usb":  # trident
        p.drawLine(QPointF(10, 3.5), QPointF(10, 16))
        p.drawLine(QPointF(10, 11.5), QPointF(5.5, 8.5))
        p.drawLine(QPointF(10, 9.5), QPointF(14.5, 6.5))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(10, 16.5), 1.9, 1.9)
        p.drawEllipse(QPointF(5.5, 7.4), 1.4, 1.4)
        p.drawRect(QRectF(13.1, 4.2, 2.8, 2.8))
        p.drawPolygon([QPointF(10, 1.6), QPointF(8.4, 4.2), QPointF(11.6, 4.2)])
    elif name == "chevron":
        p.drawLine(QPointF(6, 8), QPointF(10, 12))
        p.drawLine(QPointF(10, 12), QPointF(14, 8))
    elif name == "plus":
        p.drawLine(QPointF(10, 4.5), QPointF(10, 15.5))
        p.drawLine(QPointF(4.5, 10), QPointF(15.5, 10))
    elif name == "check":
        p.drawLine(QPointF(4.5, 10.5), QPointF(8.5, 14.5))
        p.drawLine(QPointF(8.5, 14.5), QPointF(15.5, 6))
    p.end()
    return px


def icon(name: str, color: str = theme.TEXT_DIM, size: int = 20) -> QIcon:
    return QIcon(draw_icon(name, color, size))


def nav_icon(name: str) -> QIcon:
    """Icon with a dim normal state and an accent 'checked' state."""
    ic = QIcon()
    ic.addPixmap(draw_icon(name, theme.TEXT_DIM), QIcon.Normal, QIcon.Off)
    ic.addPixmap(draw_icon(name, theme.ACCENT_2), QIcon.Normal, QIcon.On)
    ic.addPixmap(draw_icon(name, theme.TEXT_MUTED), QIcon.Disabled, QIcon.Off)
    return ic
