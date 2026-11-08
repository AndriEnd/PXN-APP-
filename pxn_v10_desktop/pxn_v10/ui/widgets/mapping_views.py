"""Interactive vector diagrams for button remapping / test highlighting.

Ports of WheelMappingView, PedalMappingView, LeverMappingView and BrakeMappingView: every
physical control is a 'thumb' that shows the function it is currently mapped to; clicking a
thumb emits ``selected(code)`` (the key picker then chooses the new function). In test mode the
views are read-only and light up green while a control is pressed.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core import constants as C
from ...core import keycodes as K
from .. import theme

THUMB = 54.0
PS_SYMBOLS = {8: ("△", "#3DDC97"), 9: ("○", "#FF5C6C"), 10: ("✕", "#5AA9FF"), 11: ("□", "#E58AD8")}

# silkscreen text of the physical wheel buttons (WheelMappingView.getKeyString)
WHEEL_PHYS_TEXT = {
    0: "VIEW", 1: "L3", 2: "R3", 3: "MENU", 4: "▲", 5: "▶", 6: "▼", 7: "◀", 8: "Y", 9: "B", 10: "A", 11: "X",
    12: "L1", 13: "R1", 14: "L2", 15: "R2", 16: "HOME", 17: "SHARE",
}


class MappingView(QWidget):
    selected = Signal(int)

    DESIGN = (400.0, 400.0)
    PHYSICAL: tuple = ()
    THUMB_W = THUMB  # wider thumbs for controls with long names (pedals, handbrake)

    def __init__(self, parent=None, interactive: bool = True) -> None:
        super().__init__(parent)
        self.mode = C.MODE_PC_DINPUT
        self.keymap: dict = {}
        self.pressed: dict = {}
        self.selected_code = -1
        self.interactive = interactive
        self._hover = -1
        self._press_pos: QPointF | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        w, h = self.design_size()
        self.setMinimumSize(int(w * 0.62), int(h * 0.62))

    # ---------------------------------------------------------------- state
    def set_mode(self, mode: int) -> None:
        self.mode = mode
        w, h = self.design_size()
        self.setMinimumSize(int(w * 0.62), int(h * 0.62))
        self.update()

    def set_keymap(self, keymap: dict) -> None:
        self.keymap = keymap
        self.update()

    def set_pressed(self, pressed: dict) -> None:
        self.pressed = pressed
        self.update()

    def set_selected(self, code: int) -> None:
        self.selected_code = code
        self.update()

    # ---------------------------------------------------------- to override
    def design_size(self) -> tuple:
        return self.DESIGN

    def positions(self) -> dict:
        return {}

    def physical_text(self, code: int) -> str:
        return K.key_label(code, self.mode)

    def paint_art(self, p: QPainter) -> None:
        pass

    # -------------------------------------------------------------- geometry
    def _xform(self) -> tuple:
        dw, dh = self.design_size()
        s = min(self.width() / dw, self.height() / dh)
        ox, oy = (self.width() - dw * s) / 2, (self.height() - dh * s) / 2
        return s, ox, oy

    def _to_design(self, pos: QPointF) -> QPointF:
        s, ox, oy = self._xform()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _hit(self, pos: QPointF) -> int:
        d = self._to_design(pos)
        for code, c in self.positions().items():
            if abs(d.x() - c[0]) <= self.THUMB_W / 2 + 4 and abs(d.y() - c[1]) <= THUMB / 2 + 4:
                return code
        return -1

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s, ox, oy = self._xform()
        p.translate(ox, oy)
        p.scale(s, s)
        self.paint_art(p)
        for code, (cx, cy) in self.positions().items():
            self._paint_thumb(p, code, cx, cy)

    def _paint_thumb(self, p: QPainter, code: int, cx: float, cy: float) -> None:
        tw = self.THUMB_W
        rect = QRectF(cx - tw / 2, cy - THUMB / 2, tw, THUMB)
        func = self.keymap.get(code, code)
        remapped = func != code
        down = bool(self.pressed.get(code))
        sel = code == self.selected_code
        hov = code == self._hover and self.interactive

        if down:
            glow = QRadialGradient(rect.center(), THUMB * 0.95)
            glow.setColorAt(0, QColor(47, 210, 122, 120))
            glow.setColorAt(1, QColor(47, 210, 122, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(rect.center(), tw * 0.8, THUMB * 0.95)
            fill, border = QColor("#163D2A"), QColor(theme.GREEN)
        elif sel:
            fill, border = QColor(theme.ACCENT_SOFT), QColor(theme.ACCENT)
        elif hov:
            fill, border = QColor("#2B3240"), QColor("#4A5568")
        else:
            fill, border = QColor(theme.SURFACE_3), QColor(theme.BORDER)
        p.setPen(QPen(border, 2.2 if (down or sel) else 1.4))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 15, 15)

        # function label (what the button does now)
        if self.mode == C.MODE_PS4_WHEEL and func in PS_SYMBOLS:
            sym, col = PS_SYMBOLS[func]
            p.setPen(QColor(col))
            p.setFont(QFont(theme.FONT_FAMILY, 17, QFont.Bold))
            p.drawText(rect, Qt.AlignCenter, sym)
        else:
            text = K.key_label(func, self.mode)
            size = 11.5 if len(text) <= 3 else (9.0 if len(text) <= 6 else 7.5)
            f = QFont(theme.FONT_FAMILY, size, QFont.Bold)
            p.setFont(f)
            while p.fontMetrics().horizontalAdvance(text) > tw - 8 and f.pointSizeF() > 5.5:
                f.setPointSizeF(f.pointSizeF() - 0.5)
                p.setFont(f)
            p.setPen(QColor(theme.GREEN if down else (theme.ACCENT_2 if remapped else theme.TEXT)))
            p.drawText(rect.adjusted(2, 0, -2, 0), Qt.AlignCenter, text)
        if remapped:  # small accent dot: this button was remapped
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(QPointF(rect.right() - 7, rect.top() + 7), 3.4, 3.4)

        # physical label under the thumb
        p.setPen(QColor(theme.TEXT_MUTED if not down else theme.GREEN))
        p.setFont(QFont(theme.FONT_FAMILY, 7.5, QFont.DemiBold))
        label_rect = QRectF(cx - max(40, tw / 2 + 6), rect.bottom() + 2, max(80, tw + 12), 14)
        p.drawText(label_rect, Qt.AlignCenter, self.physical_text(code))

    # ----------------------------------------------------------------- mouse
    def mousePressEvent(self, e) -> None:
        if self.interactive and e.button() == Qt.LeftButton:
            self._press_pos = e.position()

    def mouseMoveEvent(self, e) -> None:
        if not self.interactive:
            return
        h = self._hit(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.PointingHandCursor if h >= 0 else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if not self.interactive or e.button() != Qt.LeftButton or self._press_pos is None:
            return
        moved = (e.position() - self._press_pos).manhattanLength() > 12
        self._press_pos = None
        if moved:
            return
        code = self._hit(e.position())
        if code >= 0:
            self.selected_code = code
            self.update()
            self.selected.emit(code)

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()


def _soft_panel(p: QPainter, rect: QRectF, radius: float = 22) -> None:
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor(theme.SURFACE_2))
    g.setColorAt(1, QColor(theme.SURFACE))
    p.setPen(QPen(QColor(theme.BORDER_SOFT), 1))
    p.setBrush(g)
    p.drawRoundedRect(rect, radius, radius)


# =========================================================================== wheel
class WheelMappingView(MappingView):
    PHYSICAL = K.WHEEL_PHYSICAL
    COL_L, COL_R = 48.0, 352.0
    ROWS = (130.0, 206.0, 282.0, 358.0)

    def design_size(self) -> tuple:
        return (400.0, 572.0 if self.mode == C.MODE_PC_DINPUT else 480.0)

    def physical_text(self, code: int) -> str:
        return WHEEL_PHYS_TEXT.get(code, "")

    def positions(self) -> dict:
        d_input = self.mode == C.MODE_PC_DINPUT
        top = 44.0
        pos = {
            14: (self.COL_L, top), 12: (156.0, top), 13: (244.0, top), 15: (self.COL_R, top),
            4: (self.COL_L, self.ROWS[0]), 6: (self.COL_L, self.ROWS[1]),
            7: (self.COL_L, self.ROWS[2]), 5: (self.COL_L, self.ROWS[3]),
            10: (self.COL_R, self.ROWS[0]), 9: (self.COL_R, self.ROWS[1]),
            11: (self.COL_R, self.ROWS[2]), 8: (self.COL_R, self.ROWS[3]),
        }
        low = self.ROWS[3] + 78
        pos[1] = (self.COL_L, low)
        pos[2] = (self.COL_R, low)
        if d_input:
            pos[16] = (200.0, low)
            pos[0] = (self.COL_L, low + 82)
            pos[17] = (200.0, low + 82)
            pos[3] = (self.COL_R, low + 82)
        return pos

    def paint_art(self, p: QPainter) -> None:
        cx, cy = 200.0, (self.ROWS[0] + self.ROWS[3]) / 2
        r = 104.0
        # soft backdrop
        glow = QRadialGradient(QPointF(cx, cy), r * 1.5)
        glow.setColorAt(0, QColor(255, 82, 48, 22))
        glow.setColorAt(1, QColor(255, 82, 48, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), r * 1.5, r * 1.5)
        # rim
        rim = QPen(QColor("#2C3440"), 22)
        p.setPen(rim)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r - 8, r - 8)
        p.setPen(QPen(QColor("#394352"), 2))
        p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)
        p.drawEllipse(QPointF(cx, cy), r - 20, r - 20)
        # spokes + hub
        spoke = QPen(QColor("#2C3440"), 16)
        spoke.setCapStyle(Qt.FlatCap)
        p.setPen(spoke)
        p.drawLine(QPointF(cx - r + 12, cy + 4), QPointF(cx - 22, cy + 4))
        p.drawLine(QPointF(cx + r - 12, cy + 4), QPointF(cx + 22, cy + 4))
        p.drawLine(QPointF(cx, cy + 22), QPointF(cx, cy + r - 12))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2C3440"))
        p.drawEllipse(QPointF(cx, cy), 28, 28)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(cx - 3, cy - r - 3, 6, 18), 3, 3)  # 12 o'clock marker
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(QFont(theme.FONT_FAMILY, 8, QFont.Bold))
        p.drawText(QRectF(cx - 24, cy - 8, 48, 16), Qt.AlignCenter, "PXN")


# =========================================================================== pedals
class PedalMappingView(MappingView):
    PHYSICAL = K.PEDAL_PHYSICAL
    DESIGN = (420.0, 330.0)
    THUMB_W = 92.0

    def positions(self) -> dict:
        return {22: (80.0, 50.0), 21: (210.0, 50.0), 20: (340.0, 50.0)}

    def physical_text(self, code: int) -> str:
        return {22: "CLUTCH", 21: "BRAKE", 20: "ACCELERATOR"}.get(code, "")

    def paint_art(self, p: QPainter) -> None:
        specs = {22: (84.0, 54.0, 118.0, "#3B9EFF"), 21: (210.0, 74.0, 126.0, "#FF4B55"), 20: (336.0, 50.0, 150.0, "#2FD27A")}
        base = 250.0
        _soft_panel(p, QRectF(18, 124, 384, 186), 20)
        for code, (cx, w, h, color) in specs.items():
            down = bool(self.pressed.get(code))
            top = base - h - (8 if down else 0)
            rect = QRectF(cx - w / 2, top, w, h)
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor("#38414F"))
            g.setColorAt(1, QColor("#252B36"))
            p.setPen(QPen(QColor(color) if down else QColor("#465063"), 2))
            p.setBrush(g)
            p.drawRoundedRect(rect, 9, 9)
            p.setPen(QPen(QColor("#4A5568"), 2))
            for i in range(1, 6):  # anti-slip ribs
                y = top + 14 + i * (h - 28) / 6
                p.drawLine(QPointF(rect.left() + 10, y), QPointF(rect.right() - 10, y))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(cx - 11, base + 14, 22, 5), 2.5, 2.5)
        p.setPen(QPen(QColor("#2A313D"), 3))
        p.drawLine(QPointF(40, base + 30), QPointF(380, base + 30))


# =========================================================================== shifter
class LeverMappingView(MappingView):
    PHYSICAL = K.LEVER_PHYSICAL
    DESIGN = (450.0, 350.0)
    COLS = (74.0, 174.0, 274.0, 374.0)
    TOP_GEAR, BOT_GEAR = 150.0, 266.0

    def positions(self) -> dict:
        c = self.COLS
        return {
            25: (150.0, 48.0), 26: (300.0, 48.0),
            27: (c[0], self.TOP_GEAR), 28: (c[0], self.BOT_GEAR),
            29: (c[1], self.TOP_GEAR), 30: (c[1], self.BOT_GEAR),
            31: (c[2], self.TOP_GEAR), 32: (c[2], self.BOT_GEAR),
            33: (c[3], self.BOT_GEAR),
        }

    def physical_text(self, code: int) -> str:
        return {25: "LEVER R", 26: "LEVER L", 33: "R"}.get(code, f"GEAR {code - 26}" if 27 <= code <= 32 else "")

    def paint_art(self, p: QPainter) -> None:
        c = self.COLS
        _soft_panel(p, QRectF(18, 102, 414, 228), 22)
        gate = QPen(QColor("#303846"), 12)
        gate.setCapStyle(Qt.RoundCap)
        p.setPen(gate)
        mid = (self.TOP_GEAR + self.BOT_GEAR) / 2
        for x in c[:3]:
            p.drawLine(QPointF(x, self.TOP_GEAR), QPointF(x, self.BOT_GEAR))
        p.drawLine(QPointF(c[0], mid), QPointF(c[2], mid))
        p.drawLine(QPointF(c[2], mid), QPointF(c[3], self.BOT_GEAR))


# ========================================================================== handbrake
class BrakeMappingView(MappingView):
    PHYSICAL = K.BRAKE_PHYSICAL
    DESIGN = (360.0, 330.0)
    THUMB_W = 92.0

    def positions(self) -> dict:
        return {23: (180.0, 56.0)}

    def physical_text(self, code: int) -> str:
        return "HANDBRAKE"

    def paint_art(self, p: QPainter) -> None:
        _soft_panel(p, QRectF(18, 120, 324, 190), 22)
        down = bool(self.pressed.get(23))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2C3440"))
        p.drawRoundedRect(QRectF(90, 270, 180, 22), 8, 8)
        lever = QPen(QColor(theme.GREEN if down else "#465063"), 16)
        lever.setCapStyle(Qt.RoundCap)
        p.setPen(lever)
        tip = QPointF(238, 168) if down else QPointF(200, 150)
        p.drawLine(QPointF(160, 272), tip)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(tip, 15, 15)
