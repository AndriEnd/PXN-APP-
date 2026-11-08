"""Editor LUT (Look-Up Table) respons force feedback: 5 titik, input tetap 0/25/50/75/100 %,
output dapat digeser. Garis putus-putus = respons linear 1:1 sebagai pembanding."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.ffb_advanced import LUT_INPUTS, LUT_PRESETS
from .. import theme
from .curve_chart import smooth_path

HANDLE_R = 8.0
HIT_R = 16.0


class LutChart(QWidget):
    valuesChanged = Signal(list)  # dipancarkan saat drag dilepas / setelah klik

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._vals = list(LUT_PRESETS["linear"][1])
        self._drag = -1
        self._hover = -1
        self._color = QColor(theme.ACCENT_2)

    # ---- data
    def values(self) -> list:
        return list(self._vals)

    def set_values(self, vals) -> None:
        if self._drag >= 0:
            return
        v = [int(x) for x in vals][:5]
        if len(v) == 5:
            self._vals = v
            self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    # ---- geometry
    def _plot(self) -> QRectF:
        return QRectF(44, 14, self.width() - 44 - 18, self.height() - 14 - 40)

    def _pt(self, i: int) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + r.width() * LUT_INPUTS[i] / 100, r.bottom() - r.height() * self._vals[i] / 100)

    def _value_at(self, y: float) -> int:
        r = self._plot()
        return int(round(max(0.0, min(100.0, (r.bottom() - y) / r.height() * 100))))

    def _hit(self, pos: QPointF) -> int:
        best, dist = -1, HIT_R
        for i in range(1, 5):  # titik 0 selalu (0,0)
            d = ((self._pt(i).x() - pos.x()) ** 2 + (self._pt(i).y() - pos.y()) ** 2) ** 0.5
            if d < dist:
                best, dist = i, d
        return best

    # ---- mouse
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = self._hit(e.position())
            if self._drag >= 0:
                self._move(e.position().y())

    def mouseMoveEvent(self, e) -> None:
        if self._drag >= 0:
            self._move(e.position().y())
        else:
            h = self._hit(e.position())
            if h != self._hover:
                self._hover = h
                self.setCursor(Qt.PointingHandCursor if h >= 0 else Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag >= 0:
            self._drag = -1
            self.valuesChanged.emit(self.values())
            self.update()

    def _move(self, y: float) -> None:
        i = self._drag
        lo = self._vals[i - 1]
        hi = self._vals[i + 1] if i < 4 else 100
        self._vals[i] = max(lo, min(hi, self._value_at(y)))
        self.update()

    # ---- paint
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
        for k in range(5):
            x = r.left() + r.width() * k / 4
            y = r.top() + r.height() * k / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8))
        for k in range(5):
            pct = k * 25
            p.drawText(QRectF(r.left() + r.width() * k / 4 - 20, r.bottom() + 4, 40, 14), Qt.AlignCenter, str(pct))
            p.drawText(QRectF(0, r.bottom() - r.height() * k / 4 - 8, 38, 16), Qt.AlignRight | Qt.AlignVCenter, str(pct))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(r.left(), r.bottom() + 20, r.width(), 16), Qt.AlignCenter, "GAYA DARI GAME (%)  →  OUTPUT KE MOTOR (%)")
        # linear reference
        p.setPen(QPen(QColor(theme.TEXT_MUTED), 1, Qt.DashLine))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.top()))
        # curve
        pts = [self._pt(i) for i in range(5)]
        path = smooth_path(pts)
        fill = QPainterPath(path)
        fill.lineTo(QPointF(r.right(), r.bottom()))
        fill.lineTo(QPointF(r.left(), r.bottom()))
        fill.closeSubpath()
        soft = QColor(self._color)
        soft.setAlpha(34)
        p.setPen(Qt.NoPen)
        p.setBrush(soft)
        p.drawPath(fill)
        p.setPen(QPen(self._color, 3, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        for i, q in enumerate(pts):
            active = i == self._drag or i == self._hover
            fixed = i == 0
            p.setPen(QPen(QColor(theme.BG), 2))
            p.setBrush(QColor(theme.TEXT_MUTED) if fixed else (self._color.lighter(125) if active else self._color))
            p.drawEllipse(q, HANDLE_R * (1.2 if active else 1.0), HANDLE_R * (1.2 if active else 1.0))
            if active and not fixed:
                p.setPen(QColor(theme.TEXT))
                p.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
                p.drawText(QRectF(q.x() - 30, q.y() - 30, 60, 18), Qt.AlignCenter, f"{self._vals[i]}%")
