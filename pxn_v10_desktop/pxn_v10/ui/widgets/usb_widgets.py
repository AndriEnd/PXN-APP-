"""Instrumen untuk halaman Perangkat USB: grid tombol, pola shifter H, bar sumbu horizontal, baris kalibrasi."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from ...usb.config import AxisCalibration
from .. import theme
from .common import button, label


class ButtonGrid(QWidget):
    """Lampu tombol 1..N: menyala hijau saat ditekan (+ indikator POV)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._n = 0
        self._mask = 0
        self._pov = -1
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_count(self, n: int) -> None:
        self._n = max(0, min(32, int(n)))
        self.updateGeometry()
        self.update()

    def set_state(self, mask: int, pov: int = -1) -> None:
        if mask != self._mask or pov != self._pov:
            self._mask, self._pov = mask, pov
            self.update()

    def pressed(self) -> list:
        return [i for i in range(self._n) if self._mask >> i & 1]

    def _cols(self) -> int:
        return max(1, min(12, int(self.width() // 46)))

    def sizeHint(self):
        from PySide6.QtCore import QSize

        rows = max(1, -(-self._n // 12))
        return QSize(400, 30 + rows * 46)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._n == 0:
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Perangkat ini tidak melaporkan tombol")
            return
        cols = self._cols()
        cell = min(42.0, (self.width() - 4) / cols)
        for i in range(self._n):
            r, c = divmod(i, cols)
            cx, cy = 2 + c * cell + cell / 2, 6 + r * (cell + 4) + cell / 2
            on = bool(self._mask >> i & 1)
            p.setPen(QPen(QColor(theme.GREEN if on else theme.BORDER), 2))
            p.setBrush(QColor(theme.GREEN) if on else QColor(theme.SURFACE_3))
            p.drawEllipse(QPointF(cx, cy), cell * 0.38, cell * 0.38)
            p.setPen(QColor("#06210F" if on else theme.TEXT_DIM))
            p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
            p.drawText(QRectF(cx - cell / 2, cy - 9, cell, 18), Qt.AlignCenter, str(i + 1))
        if self._pov >= 0:
            p.setPen(QColor(theme.AMBER))
            p.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
            p.drawText(QRectF(0, self.height() - 20, self.width(), 18), Qt.AlignRight, f"POV {self._pov}°")


class ShifterPattern(QWidget):
    """Diagram H-pattern 6+R; gigi aktif ditandai. 'N' = tuas di tengah."""

    GEAR_POS = {"1": (0, 0), "2": (0, 1), "3": (1, 0), "4": (1, 1), "5": (2, 0), "6": (2, 1), "R": (3, 0)}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gear = "N"
        self.setMinimumSize(240, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_gear(self, gear: str) -> None:
        if gear != self._gear:
            self._gear = gear
            self.update()

    def _xy(self, gear: str) -> QPointF:
        col, row = self.GEAR_POS[gear]
        w, h = self.width(), self.height()
        x0, x1 = w * 0.14, w * 0.86
        y0, y1 = h * 0.2, h * 0.8
        return QPointF(x0 + (x1 - x0) * col / 3, y0 if row == 0 else y1)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid_y = h / 2
        p.setPen(QPen(QColor(theme.SURFACE_3), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(w * 0.14, mid_y), QPointF(w * 0.86, mid_y))
        for g, (col, _row) in self.GEAR_POS.items():
            q = self._xy(g)
            p.drawLine(QPointF(q.x(), mid_y), q)
        for g in self.GEAR_POS:
            q = self._xy(g)
            on = g == self._gear
            p.setPen(QPen(QColor(theme.ACCENT if on else theme.BORDER), 2))
            p.setBrush(QColor(theme.ACCENT) if on else QColor(theme.SURFACE_2))
            p.drawEllipse(q, 19, 19)
            p.setPen(QColor("#FFFFFF" if on else theme.TEXT_DIM))
            p.setFont(QFont(theme.FONT_FAMILY, 11, QFont.Bold))
            p.drawText(QRectF(q.x() - 19, q.y() - 12, 38, 24), Qt.AlignCenter, g)
        if self._gear == "N":
            p.setPen(QColor(theme.TEXT_MUTED))
            p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
            p.drawText(QRectF(0, mid_y + 8, w, 16), Qt.AlignCenter, "NETRAL")


class AxisBar(QWidget):
    """Bar horizontal 0..1 dengan judul dan nilai; ``bipolar`` menampilkan titik tengah (kemudi)."""

    def __init__(self, title: str, color: str = theme.ACCENT, bipolar: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.title, self.color, self.bipolar = title, QColor(color), bipolar
        self._v = 0.0
        self._text = ""
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, v: float, text: str | None = None) -> None:
        v = max(-1.0, min(1.0, v)) if self.bipolar else max(0.0, min(1.0, v))
        t = f"{v * 100:+.0f}%" if self.bipolar else f"{v * 100:.0f}%"
        t = text if text is not None else t
        if v != self._v or t != self._text:
            self._v, self._text = v, t
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(0, 0, w, 14), Qt.AlignLeft | Qt.AlignVCenter, self.title.upper())
        p.setPen(QColor(theme.TEXT))
        p.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Bold))
        p.drawText(QRectF(0, 0, w, 14), Qt.AlignRight | Qt.AlignVCenter, self._text)
        bar = QRectF(0, 20, w, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_3))
        p.drawRoundedRect(bar, 6, 6)
        p.setBrush(self.color)
        if self.bipolar:
            mid = bar.center().x()
            half = bar.width() / 2 * self._v
            p.drawRoundedRect(QRectF(min(mid, mid + half), bar.top(), abs(half), bar.height()), 6, 6)
            p.setPen(QPen(QColor(theme.TEXT_DIM), 1.5))
            p.drawLine(QPointF(mid, bar.top() - 2), QPointF(mid, bar.bottom() + 2))
        elif self._v > 0:
            p.drawRoundedRect(QRectF(0, bar.top(), max(12.0, bar.width() * self._v), bar.height()), 6, 6)


class AxisConfigRow(QWidget):
    """Baris kalibrasi satu sumbu: pilihan sumbu, deteksi, invert, min/maks, zona mati/jenuh, gamma + bar langsung."""

    changed = Signal()
    detectRequested = Signal()
    setMinRequested = Signal()
    setMaxRequested = Signal()

    def __init__(self, title: str, color: str = theme.ACCENT, optional: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.cal = AxisCalibration()
        self._n_axes = 0
        self._loading = False
        self.setObjectName("cardInner")
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 10, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(label(title.upper(), "eyebrow"))
        top.addStretch(1)
        self.raw_label = label("mentah —", "muted")
        top.addWidget(self.raw_label)
        grid.addLayout(top, 0, 0, 1, 8)

        self.axis = QComboBox()
        self.axis.setMinimumWidth(84)
        self.axis.currentIndexChanged.connect(self._edited)
        self.detect = button("Deteksi", "ghost", tooltip="Gerakkan kontrolnya hingga ujung; sumbu & kalibrasi terdeteksi")
        self.detect.clicked.connect(self.detectRequested)
        self.invert = QCheckBox("Balik")
        self.invert.toggled.connect(self._edited)
        self.b_min = button("Set min", "ghost", tooltip="Pakai posisi sekarang sebagai 0%")
        self.b_max = button("Set maks", "ghost", tooltip="Pakai posisi sekarang sebagai 100%")
        self.b_min.clicked.connect(self.setMinRequested)
        self.b_max.clicked.connect(self.setMaxRequested)
        self.dead = self._spin(0, 45, 1, "%", "Zona mati di awal gerak")
        self.sat = self._spin(0, 45, 1, "%", "Zona jenuh di akhir gerak")
        self.gamma = QDoubleSpinBox()
        self.gamma.setRange(0.2, 5.0)
        self.gamma.setSingleStep(0.1)
        self.gamma.setDecimals(1)
        self.gamma.setToolTip("Kurva respons: 1.0 = linear, >1 = lembut di awal")
        self.gamma.valueChanged.connect(self._edited)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for w in (label("Sumbu", "muted"), self.axis, self.detect, self.invert, self.b_min, self.b_max):
            row1.addWidget(w)
        row1.addStretch(1)
        grid.addLayout(row1, 1, 0, 1, 8)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for cap, w in (("Zona mati", self.dead), ("Jenuh", self.sat), ("Gamma", self.gamma)):
            row2.addWidget(label(cap, "muted"))
            row2.addWidget(w)
            row2.addSpacing(10)
        row2.addStretch(1)
        grid.addLayout(row2, 2, 0, 1, 8)
        self.bar = AxisBar("Hasil kalibrasi", color)
        grid.addWidget(self.bar, 3, 0, 1, 8)
        self.optional = optional

    def _spin(self, lo, hi, step, suffix, tip) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setToolTip(tip)
        s.valueChanged.connect(self._edited)
        return s

    # ---- binding
    def set_axes(self, labels: list) -> None:
        """``labels``: nama tiap sumbu perangkat, sesuai urutan indeks ``AxisCalibration.axis``."""
        self._loading = True
        self.axis.clear()
        self.axis.addItems(["—"] + list(labels))
        self._n_axes = len(labels)
        self._loading = False
        self.set_calibration(self.cal)

    def set_calibration(self, cal: AxisCalibration) -> None:
        self.cal = cal
        self._loading = True
        idx = cal.axis + 1 if 0 <= cal.axis < self._n_axes else 0
        self.axis.setCurrentIndex(idx)
        self.invert.setChecked(cal.invert)
        self.dead.setValue(int(round(cal.deadzone * 100)))
        self.sat.setValue(int(round(cal.saturation * 100)))
        self.gamma.setValue(cal.gamma)
        self._loading = False

    def _edited(self, *_a) -> None:
        if self._loading:
            return
        c = self.cal
        c.axis = self.axis.currentIndex() - 1
        c.invert = self.invert.isChecked()
        c.deadzone = self.dead.value() / 100
        c.saturation = self.sat.value() / 100
        c.gamma = round(self.gamma.value(), 2)
        self.changed.emit()

    def show_live(self, raw: float | None, value: float | None) -> None:
        self.raw_label.setText("mentah —" if raw is None else f"mentah {int(raw)}  ·  rentang {self.cal.raw_min}–{self.cal.raw_max}")
        self.bar.set_value(0.0 if value is None else value)

    def set_detecting(self, active: bool, text: str = "") -> None:
        self.detect.setText(text if active else "Deteksi")
        self.detect.setEnabled(not active)
