"""Reusable building blocks: cards, labels, segmented bars, status dots, dialogs, toasts."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import theme


def label(text: str = "", name: str = "", wrap: bool = False, align=None) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if align is not None:
        lb.setAlignment(align)
    return lb


def card(inner: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("cardInner" if inner else "card")
    return f


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.NoFrame)
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("vdivider")
    f.setFrameShape(QFrame.NoFrame)
    return f


def button(text: str, kind: str = "", icon=None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(18, 18))
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class CardPanel(QFrame):
    """A titled card with a vertical body layout."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)
        outer.setSpacing(14)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = label(title.upper(), "eyebrow")
        titles.addWidget(self.title_label)
        self.subtitle_label = label(subtitle, "muted", wrap=True)
        self.subtitle_label.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle_label)
        self.header.addLayout(titles, 1)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)
        self.title_label.setVisible(bool(title))

    def add_header_widget(self, w: QWidget) -> None:
        self.header.addWidget(w, 0, Qt.AlignRight | Qt.AlignVCenter)


class StatusDot(QWidget):
    def __init__(self, color: str = theme.TEXT_MUTED, size: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 6, size + 6)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        halo = QColor(self._color)
        halo.setAlpha(55)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(self.rect())
        p.setBrush(self._color)
        m = (self.width() - self._size) / 2
        p.drawEllipse(m, m, self._size, self._size)


class Chip(QLabel):
    """Small rounded tag."""

    def __init__(self, text: str = "", color: str = theme.TEXT_DIM, parent=None) -> None:
        super().__init__(text, parent)
        self.set_style(color)

    def set_style(self, color: str) -> None:
        c = QColor(color)
        self.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},38); color: {color};"
            f"border-radius: 9px; padding: 3px 10px; font-weight: 700; font-size: 8.5pt;"
        )


class SegmentedBar(QFrame):
    """Pill-shaped tab strip. ``set_items`` can be called repeatedly (tabs appear with hardware)."""

    currentChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("segBar")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 4, 4, 4)
        self._lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._current = ""

    def set_items(self, items: list, keep: bool = True) -> None:
        if [(k, b.text()) for k, b in self._buttons.items()] == [(k, t) for k, t in items] and items:
            return  # unchanged -> no flicker when the device state is refreshed
        previous = self._current
        for b in self._buttons.values():
            self._group.removeButton(b)
            self._lay.removeWidget(b)
            b.deleteLater()
        self._buttons.clear()
        for key, text in items:
            b = QPushButton(text)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_current(k))
            self._group.addButton(b)
            self._lay.addWidget(b)
            self._buttons[key] = b
        keys = [k for k, _ in items]
        target = previous if keep and previous in keys else (keys[0] if keys else "")
        self._current = ""
        if target:
            self.set_current(target)

    def set_current(self, key: str) -> None:
        if key not in self._buttons:
            return
        self._buttons[key].setChecked(True)
        if key != self._current:
            self._current = key
            self.currentChanged.emit(key)

    @property
    def current(self) -> str:
        return self._current


# ------------------------------------------------------------------ dialogs
class StyledDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, width: int = 440) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(26, 24, 26, 22)
        self.root.setSpacing(14)
        self.root.addWidget(label(title, "h2"))
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(10)
        self.buttons.addStretch(1)

    def finish(self) -> None:
        self.root.addSpacing(6)
        self.root.addLayout(self.buttons)


def confirm(parent, title: str, message: str, ok: str = "OK", cancel: str = "Batal", danger: bool = False) -> bool:
    d = StyledDialog(parent, title)
    d.root.addWidget(label(message, "dim", wrap=True))
    b_cancel = button(cancel, "ghost")
    b_ok = button(ok, "danger" if danger else "primary")
    b_cancel.clicked.connect(d.reject)
    b_ok.clicked.connect(d.accept)
    d.buttons.addWidget(b_cancel)
    d.buttons.addWidget(b_ok)
    d.finish()
    b_ok.setDefault(True)
    return d.exec() == QDialog.Accepted


def prompt(parent, title: str, hint: str = "", text: str = "", ok: str = "Simpan") -> str | None:
    d = StyledDialog(parent, title)
    edit = QLineEdit(text)
    edit.setPlaceholderText(hint)
    d.root.addWidget(edit)
    b_cancel = button("Batal", "ghost")
    b_ok = button(ok, "primary")
    b_cancel.clicked.connect(d.reject)
    b_ok.clicked.connect(d.accept)
    edit.returnPressed.connect(d.accept)
    d.buttons.addWidget(b_cancel)
    d.buttons.addWidget(b_ok)
    d.finish()
    edit.setFocus()
    edit.selectAll()
    if d.exec() == QDialog.Accepted:
        return edit.text().strip() or None
    return None


def info(parent, title: str, message: str, ok: str = "Mengerti") -> None:
    d = StyledDialog(parent, title, width=480)
    d.root.addWidget(label(message, "dim", wrap=True))
    b_ok = button(ok, "primary")
    b_ok.clicked.connect(d.accept)
    d.buttons.addWidget(b_ok)
    d.finish()
    d.exec()


# -------------------------------------------------------------------- toast
class Toast(QFrame):
    """Transient message in the lower-right corner of its parent window."""

    COLORS = {"info": theme.BLUE, "ok": theme.GREEN, "error": theme.RED}

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("cardInner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 18, 12)
        lay.setSpacing(10)
        self._dot = StatusDot(theme.BLUE, 9)
        self._text = QLabel()
        self._text.setWordWrap(True)
        lay.addWidget(self._dot)
        lay.addWidget(self._text, 1)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, message: str, kind: str = "info", ms: int = 3200) -> None:
        self._dot.set_color(self.COLORS.get(kind, theme.BLUE))
        self._text.setText(message)
        self.setFixedWidth(min(420, max(240, self.parent().width() // 3)))
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        self._timer.start(ms)

    def reposition(self) -> None:
        p = self.parent()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 24)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(260)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        try:
            self._anim.finished.disconnect(self._hide_once)
        except (RuntimeError, TypeError):
            pass
        if self._fx.opacity() < 0.05:
            self.hide()
