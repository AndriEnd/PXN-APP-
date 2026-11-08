"""Interactive pedal response curve (4 draggable control points).

X = pedal input (12-bit ADC, 0..4095), Y = output (16-bit, 0..65535). As in the Android
``LinearChartView`` the curve starts at (0,0), passes the four control points and ends at the
top-right corner; each point can only move between its neighbours so the curve stays monotonic.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core import constants as C
from .. import theme

HANDLE_R = 8.5
HIT_R = 18.0


def smooth_path(pts: list) -> QPainterPath:
    """Monotone cubic (Fritsch-Carlson) through ``pts`` (pixel coords, x non-decreasing).
    Falls back to straight segments when two points share the same x."""
    path = QPainterPath()
    clean = [pts[0]]
    for q in pts[1:]:
        if abs(q.x() - clean[-1].x()) < 1e-6 and abs(q.y() - clean[-1].y()) < 1e-6:
            continue
        clean.append(q)
    path.moveTo(clean[0])
    n = len(clean)
    if n < 2:
        return path
    dx = [clean[i + 1].x() - clean[i].x() for i in range(n - 1)]
    if n == 2 or any(d <= 1e-6 for d in dx):
        for q in clean[1:]:
            path.lineTo(q)
        return path
    dy = [clean[i + 1].y() - clean[i].y() for i in range(n - 1)]
    m = [dy[i] / dx[i] for i in range(n - 1)]
    t = [m[0]] + [0.0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2 for i in range(1, n - 1)] + [m[-1]]
    for i in range(n - 1):  # limit slopes so the curve cannot overshoot
        if m[i] == 0:
            t[i] = t[i + 1] = 0.0
            continue
        a, b = t[i] / m[i], t[i + 1] / m[i]
        s = a * a + b * b
        if s > 9:
            k = 3 / s ** 0.5
            t[i], t[i + 1] = k * a * m[i], k * b * m[i]
    for i in range(n - 1):
        h = dx[i] / 3
        path.cubicTo(
            QPointF(clean[i].x() + h, clean[i].y() + t[i] * h),
            QPointF(clean[i + 1].x() - h, clean[i + 1].y() - t[i + 1] * h),
            clean[i + 1],
        )
    return path


class CurveChart(QWidget):
    pointMoving = Signal(int, int, int)  # index, x, y (live while dragging)
    pointCommitted = Signal(int, int, int)  # on mouse release

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(380, 330)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._values = [list(p) for p in C.DEFAULT_CURVE]
        self._color = QColor(theme.ACCENT)
        self._drag = -1
        self._hover = -1
        self._enabled = True

    # ------------------------------------------------------------------ API
    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_points(self, pts) -> None:
        if self._drag >= 0:
            return
        self._values = [[int(x), int(y)] for x, y in pts]
        self.update()

    def points(self) -> list:
        return [list(p) for p in self._values]

    # ------------------------------------------------------------- geometry
    def _plot(self) -> QRectF:
        return QRectF(52, 18, self.width() - 52 - 22, self.height() - 18 - 44)

    def _to_px(self, x: float, y: float) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + x / C.CURVE_X_MAX * r.width(), r.bottom() - y / C.CURVE_Y_MAX * r.height())

    def _to_val(self, pt: QPointF) -> tuple:
        r = self._plot()
        x = (pt.x() - r.left()) / r.width() * C.CURVE_X_MAX
        y = (r.bottom() - pt.y()) / r.height() * C.CURVE_Y_MAX
        return x, y

    def _bounds(self, i: int) -> tuple:
        lo_x, lo_y = (0, 0) if i == 0 else self._values[i - 1]
        hi_x, hi_y = (C.CURVE_X_MAX, C.CURVE_Y_MAX) if i == 3 else self._values[i + 1]
        return lo_x, hi_x, lo_y, hi_y

    # --------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        # background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 10, 10)
        # grid
        p.setClipRect(r)
        grid = QPen(QColor(theme.BORDER_SOFT), 1)
        p.setPen(grid)
        for i in range(1, 4):
            x = r.left() + r.width() * i / 4
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        # linear reference
        ref = QPen(QColor(theme.TEXT_MUTED), 1.2, Qt.DashLine)
        p.setPen(ref)
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.top()))
        p.setClipping(False)

        # curve
        pts = [self._to_px(0, 0)] + [self._to_px(x, y) for x, y in self._values] + [self._to_px(C.CURVE_X_MAX, C.CURVE_Y_MAX)]
        path = smooth_path(pts)
        fill = QPainterPath(path)
        fill.lineTo(r.right(), r.bottom())
        fill.lineTo(r.left(), r.bottom())
        fill.closeSubpath()
        area = QColor(self._color)
        area.setAlpha(34)
        p.setPen(Qt.NoPen)
        p.setBrush(area)
        p.setClipRect(r)
        p.drawPath(fill)
        p.setClipping(False)
        pen = QPen(self._color, 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # handles
        for i, (x, y) in enumerate(self._values):
            c = self._to_px(x, y)
            active = i in (self._drag, self._hover)
            halo = QColor(self._color)
            halo.setAlpha(70 if active else 0)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, HANDLE_R + 6, HANDLE_R + 6)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(c, HANDLE_R, HANDLE_R)
            p.setBrush(self._color)
            p.drawEllipse(c, HANDLE_R - 3.5, HANDLE_R - 3.5)

        # axes labels
        p.setFont(QFont(theme.FONT_FAMILY, 8))
        p.setPen(QColor(theme.TEXT_MUTED))
        for i in range(5):
            frac = i / 4
            p.drawText(QRectF(0, r.bottom() - r.height() * frac - 9, 46, 18), Qt.AlignRight | Qt.AlignVCenter, f"{int(frac * 100)}%")
            if i:
                p.drawText(QRectF(r.left() + r.width() * frac - 24, r.bottom() + 6, 48, 16), Qt.AlignCenter, f"{int(frac * 100)}%")
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(r.left(), r.bottom() + 22, r.width(), 18), Qt.AlignCenter, "Input pedal (ADC 0–4095)  →  Output (0–65535)")

        # live readout bubble
        idx = self._drag if self._drag >= 0 else self._hover
        if idx >= 0:
            x, y = self._values[idx]
            text = f"P{idx}   x {x} ({x / C.CURVE_X_MAX:.0%})   y {y} ({y / C.CURVE_Y_MAX:.0%})"
            p.setFont(QFont(theme.FONT_FAMILY, 8.5, QFont.DemiBold))
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 20
            rect = QRectF(r.left() + 10, r.top() + 10, w, 26)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.SURFACE_3))
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(QColor(theme.TEXT))
            p.drawText(rect, Qt.AlignCenter, text)

    # --------------------------------------------------------------- mouse
    def _hit(self, pos: QPointF) -> int:
        for i in range(3, -1, -1):
            d = self._to_px(*self._values[i]) - pos
            if d.x() * d.x() + d.y() * d.y() <= HIT_R * HIT_R:
                return i
        return -1

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._enabled = enabled
        super().setEnabled(enabled)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag = self._hit(e.position())
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._drag >= 0:
            x, y = self._to_val(e.position())
            lo_x, hi_x, lo_y, hi_y = self._bounds(self._drag)
            nx = int(round(max(lo_x, min(hi_x, x))))
            ny = int(round(max(lo_y, min(hi_y, y))))
            self._values[self._drag] = [nx, ny]
            self.pointMoving.emit(self._drag, nx, ny)
            self.update()
        else:
            h = self._hit(e.position())
            if h != self._hover:
                self._hover = h
                self.setCursor(Qt.OpenHandCursor if h >= 0 else Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._drag >= 0:
            i = self._drag
            self._drag = -1
            x, y = self._values[i]
            self.pointCommitted.emit(i, x, y)
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()
