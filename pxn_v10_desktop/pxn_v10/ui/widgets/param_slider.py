"""Labelled slider with exact-value spin box, help button and optional extra header widget."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import theme


class _WheelGuardSlider(QSlider):
    """Ignore the mouse wheel unless focused so scrolling a page never changes a setting."""

    def __init__(self, *a) -> None:
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e) -> None:
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class _WheelGuardSpin(QSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e) -> None:
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class ToggleSwitch(QAbstractButton):
    """iOS-like switch used for FFB reverse."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

    def sizeHint(self) -> QSize:
        return QSize(46, 26)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QColor(theme.ACCENT if on else theme.SURFACE_3)
        if not self.isEnabled():
            track = QColor(theme.SURFACE_2)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 2, 46, 22), 11, 11)
        x = 24.0 if on else 2.0
        p.setBrush(QColor("#FFFFFF" if self.isEnabled() else theme.TEXT_MUTED))
        p.drawEllipse(QRectF(x, 3, 20, 20))


class ParamSlider(QFrame):
    """``committed`` fires with the real value (e.g. 540 for the angle slider, 70 for 70 %)."""

    committed = Signal(int)
    hintClicked = Signal()

    def __init__(self, title: str, lo: int, hi: int, step: int = 10, suffix: str = "", hint: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cardInner")
        self._lo, self._hi, self._step = lo, hi, step
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(title.upper())
        self.title.setObjectName("eyebrow")
        head.addWidget(self.title)
        self.help = QPushButton("?")
        self.help.setObjectName("icon")
        self.help.setCursor(Qt.PointingHandCursor)
        self.help.setToolTip("Penjelasan parameter")
        self.help.setVisible(hint)
        self.help.clicked.connect(self.hintClicked)
        head.addWidget(self.help)
        head.addStretch(1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(8)
        head.addLayout(self.extra)
        self.spin = _WheelGuardSpin()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setFixedWidth(84)
        self.spin.setToolTip("Nilai tepat — ketik angka lalu Enter")
        head.addWidget(self.spin)
        root.addLayout(head)

        self.slider = _WheelGuardSlider(Qt.Horizontal)
        self.slider.setRange(self._unit(lo), self._unit(hi))
        self.slider.setPageStep(1)
        self.slider.setMinimumHeight(30)  # room for the 20 px handle (otherwise it is clipped)
        root.addWidget(self.slider)

        ticks = QHBoxLayout()
        a, b = QLabel(f"{lo}{suffix}"), QLabel(f"{hi}{suffix}")
        for t in (a, b):
            t.setObjectName("muted")
        ticks.addWidget(a)
        ticks.addStretch(1)
        ticks.addWidget(b)
        root.addLayout(ticks)

        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(self._commit)
        self.spin.valueChanged.connect(self._spin_changed)

    # slider unit <-> real value
    def _unit(self, real: int) -> int:
        return int(round(real / self._step))

    def add_extra(self, w: QWidget) -> None:
        self.extra.addWidget(w)

    def value(self) -> int:
        return self.spin.value()

    def is_dragging(self) -> bool:
        return self.slider.isSliderDown()

    def set_value(self, real: int) -> None:
        real = max(self._lo, min(self._hi, int(real)))
        self._updating = True
        try:
            self.spin.setValue(real)
            self.slider.setValue(self._unit(real))
        finally:
            self._updating = False

    def set_enabled_state(self, enabled: bool) -> None:
        self.slider.setEnabled(enabled)
        self.spin.setEnabled(enabled)

    # -- user interaction
    def _slider_changed(self, unit: int) -> None:
        if self._updating:
            return
        real = max(self._lo, min(self._hi, unit * self._step))
        self._updating = True
        self.spin.setValue(real)
        self._updating = False
        if not self.slider.isSliderDown():  # keyboard / click on groove
            self.committed.emit(real)

    def _spin_changed(self, real: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(self._unit(real))
        self._updating = False
        self.committed.emit(real)

    def _commit(self) -> None:
        self.committed.emit(self.spin.value())
