"""Virtual keyboard dialog (V10PopupKeyboard): choose the function a physical button should trigger.

* D-Input: tabs GAMEPAD (rim + pedals + shifter functions) and KEYBOARD (letters / numpad).
* Other modes: the compact gamepad keyboard.
* ``Reset`` maps the button back to itself (code 46 in the original app).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ...core import constants as C
from ...core import keycodes as K
from .. import theme
from .common import SegmentedBar, button, label

RESET = K.KEYCODE_RESET


class KeyPickerDialog(QDialog):
    def __init__(self, parent, mode: int, physical: int, current: int) -> None:
        super().__init__(parent)
        self.mode = mode
        self.physical = physical
        self.current = current
        self.result_code: int | None = None
        self.setModal(True)
        self.setWindowTitle("Pilih fungsi tombol")
        self.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        phys_name = K.key_label(physical, mode)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("REMAP TOMBOL", "eyebrow"))
        titles.addWidget(label(f"{phys_name}  →  {K.key_label(current, mode)}", "h2"))
        head.addLayout(titles, 1)
        close = button("Tutup", "ghost")
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignTop)
        root.addLayout(head)

        if mode == C.MODE_PC_DINPUT:
            self.tabs = SegmentedBar()
            self.tabs.set_items([("pad", "GAMEPAD"), ("kbd", "KEYBOARD")])
            root.addWidget(self.tabs, 0, Qt.AlignLeft)
            self.pad = self._rows_widget(K.WHEEL_ROWS)
            self.kbd = QWidget()
            kv = QVBoxLayout(self.kbd)
            kv.setContentsMargins(0, 0, 0, 0)
            kv.setSpacing(12)
            kv.addWidget(self._rows_widget(K.LETTER_ROWS))
            kv.addWidget(label("TANDA BACA, PANAH & NUMPAD", "eyebrow"))
            kv.addWidget(self._rows_widget(K.NUM_ROWS))
            root.addWidget(self.pad)
            root.addWidget(self.kbd)
            self.kbd.hide()
            self.tabs.currentChanged.connect(self._tab_changed)
        else:
            root.addWidget(self._rows_widget(K.GAMEPAD_ROWS))

    def _tab_changed(self, key: str) -> None:
        self.pad.setVisible(key == "pad")
        self.kbd.setVisible(key == "kbd")
        self.adjustSize()

    def _rows_widget(self, rows) -> QWidget:
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        for row in rows:
            h = QHBoxLayout()
            h.setSpacing(8)
            h.addStretch(1)
            for code in row:
                h.addWidget(self._key(code))
            h.addStretch(1)
            v.addLayout(h)
        return host

    def _key(self, code: int) -> QPushButton:
        text = "Reset" if code == RESET else K.key_label(code, self.mode)
        b = QPushButton(text)
        wide = len(text) > 3
        b.setFixedSize(76 if wide else 56, 46)
        b.setCursor(Qt.PointingHandCursor)
        is_current = (code == self.current) or (code == RESET and self.current == self.physical)
        if code == RESET:
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: 1px dashed {theme.ACCENT}; color: {theme.ACCENT_2};"
                f" border-radius: 9px; padding: 0; font-weight: 700; }}"
                f"QPushButton:hover {{ background: {theme.ACCENT_SOFT}; }}"
            )
        elif is_current:
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT_SOFT}; border: 1px solid {theme.ACCENT}; color: {theme.ACCENT_2};"
                f" border-radius: 9px; padding: 0; font-weight: 700; }}"
            )
        else:
            b.setStyleSheet("QPushButton { padding: 0; border-radius: 9px; }")
        b.clicked.connect(lambda _=False, c=code: self._choose(c))
        return b

    def _choose(self, code: int) -> None:
        # Reset restores the physical function (V10MainActivity: i == 46 -> selectedCode)
        self.result_code = self.physical if code == RESET else code
        self.accept()


def pick_key(parent, mode: int, physical: int, current: int) -> int | None:
    d = KeyPickerDialog(parent, mode, physical, current)
    if d.exec() == QDialog.Accepted:
        return d.result_code
    return None
