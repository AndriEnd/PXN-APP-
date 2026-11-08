"""ConfigEditor: the wheel / pedal / shifter / handbrake editing surface.

It is shared by the live dashboard (``DeviceBackend`` -> writes go to the wheel) and the preset
editor (``LocalBackend`` -> edits only an in-memory profile), exactly like the Android app shares
``ParamsAdapter`` and the mapping views between V10MainActivity and V10ProfileActivity.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ...ble.client import WheelClient
from ...core import constants as C
from ...core.models import DeviceProfile
from .. import theme
from .common import CardPanel, SegmentedBar, button, info, label
from .curve_chart import CurveChart
from .key_picker import pick_key
from .mapping_views import BrakeMappingView, LeverMappingView, PedalMappingView, WheelMappingView
from .param_slider import ParamSlider, ToggleSwitch

HINTS = {
    "angle": ("ANGLE", "Sudut efektif putaran kemudi di dalam game (90°–900°, kelipatan 10)."),
    "ffb": ("FORCE FEEDBACK", "Kekuatan force feedback internal game; mengatur rentang output force feedback."),
    "spring": ("SPRING FORCE", "Daya pegas (pemulih) setir: seberapa kuat setir ditarik kembali ke tengah."),
    "damping": ("DAMPING FORCE", "Peredaman setir yang menahan laju putaran kemudi — membuat setir terasa lebih berat."),
    "friction": ("FRICTION FORCE", "Intensitas detail yang mewakili permukaan jalan, benturan, dan sebagainya."),
    "inertia": ("INERTIA FORCE", "Gaya kontinu yang menyesuaikan kelembaman / beban setir di dalam game."),
    "chart": ("LINEARITY", "Fungsi ini mengatur kelinearan sinyal ketika pedal diinjak. Geser keempat titik untuk "
                           "membentuk kurva respons pedal."),
}
CURVE_COLORS = {"acc": theme.GREEN, "brake": theme.RED, "clutch": theme.BLUE}
CURVE_TITLES = {"acc": "Gas", "brake": "Rem", "clutch": "Kopling"}


# ------------------------------------------------------------------ backends
class ConfigBackend:
    profile: DeviceProfile

    def set_angle(self, v: int) -> None: ...
    def set_ffb(self, v: int) -> None: ...
    def set_ffb_reverse(self, r: int) -> None: ...
    def set_force(self, name: str, v: int) -> None: ...
    def set_mapping(self, code: int, func: int) -> None: ...
    def set_curve_point(self, name: str, i: int, x: int, y: int) -> None: ...
    def reset_curve(self, name: str) -> None: ...


class DeviceBackend(ConfigBackend):
    """Edits go straight to the wheel through the paced write queue."""

    def __init__(self, client: WheelClient) -> None:
        self.client = client

    @property
    def profile(self) -> DeviceProfile:  # type: ignore[override]
        return self.client.profile

    def set_angle(self, v):
        self.client.write_angle(v)

    def set_ffb(self, v):
        self.client.write_force_feedback(v)

    def set_ffb_reverse(self, r):
        self.client.write_force_feedback_reverse(r)

    def set_force(self, name, v):
        {"spring": self.client.write_spring, "damping": self.client.write_damping,
         "friction": self.client.write_friction, "inertia": self.client.write_inertia}[name](v)

    def set_mapping(self, code, func):
        self.client.write_mapping(code, func)

    def set_curve_point(self, name, i, x, y):
        self.client.write_curve(name, i, x, y)

    def reset_curve(self, name):
        self.client.reset_curve(name)


class LocalBackend(ConfigBackend):
    """Edits an in-memory profile (preset editor)."""

    def __init__(self, profile: DeviceProfile) -> None:
        self.profile = profile

    def set_angle(self, v):
        self.profile.angle = v

    def set_ffb(self, v):
        self.profile.ffb = v

    def set_ffb_reverse(self, r):
        self.profile.ffb_reverse = r

    def set_force(self, name, v):
        setattr(self.profile, name, v)

    def set_mapping(self, code, func):
        self.profile.keymap[code] = func

    def set_curve_point(self, name, i, x, y):
        self.profile.curve(name)[i] = [x, y]

    def reset_curve(self, name):
        self.profile.reset_curve(name)


# --------------------------------------------------------------------- editor
class ConfigEditor(QWidget):
    changed = Signal()  # any user edit (the preset editor marks itself dirty)
    notify = Signal(str)

    def __init__(self, backend: ConfigBackend, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.mode = C.MODE_PC_DINPUT
        self.angle_enabled = True
        self._curve = "acc"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        self.tabs = SegmentedBar()
        root.addWidget(self.tabs, 0, Qt.AlignLeft)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_wheel()
        self._build_pedal()
        self._build_lever()
        self._build_brake()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.set_hardware(True, True, True)

    # ---------------------------------------------------------------- build
    def _build_wheel(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        params = CardPanel("Parameter kemudi", "Perubahan dikirim langsung saat slider dilepas.")
        self.params_card = params
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.sliders_lay = QVBoxLayout(host)
        self.sliders_lay.setContentsMargins(0, 0, 6, 0)
        self.sliders_lay.setSpacing(12)
        scroll.setWidget(host)
        params.body.addWidget(scroll, 1)

        self.s_angle = ParamSlider("Angle", C.ANGLE_MIN, C.ANGLE_MAX, 10, "°")
        self.s_ffb = ParamSlider("Force feedback", 0, 100, 10, "%")
        self.reverse_label = QLabel("REVERSE")
        self.reverse_label.setObjectName("eyebrow")
        self.reverse_switch = ToggleSwitch()
        self.reverse_state = QLabel("OFF")
        self.reverse_state.setObjectName("muted")
        self.reverse_state.setFixedWidth(26)
        for w in (self.reverse_label, self.reverse_switch, self.reverse_state):
            self.s_ffb.add_extra(w)
        self.physics_label = label("PHYSICS FORCES", "eyebrow")
        self.physics_note = label("", "muted", wrap=True)
        self.s_force = {
            "spring": ParamSlider("Spring force", 0, 100, 10, "%"),
            "damping": ParamSlider("Damping force", 0, 100, 10, "%"),
            "friction": ParamSlider("Friction force", 0, 100, 10, "%"),
            "inertia": ParamSlider("Inertia force", 0, 100, 10, "%"),
        }
        self.empty_label = label("Tidak ada parameter kemudi yang dapat diatur pada mode ini.", "dim", wrap=True)
        self.angle_note = label("", "muted", wrap=True)
        self.angle_note.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 10px 12px;")
        for w in (self.angle_note, self.s_angle, self.s_ffb, self.physics_label, self.physics_note, *self.s_force.values(), self.empty_label):
            self.sliders_lay.addWidget(w)
        self.sliders_lay.addStretch(1)

        self.s_angle.committed.connect(lambda v: self._apply("angle", v))
        self.s_ffb.committed.connect(lambda v: self._apply("ffb", v))
        self.reverse_switch.clicked.connect(self._reverse_clicked)
        for name, sl in self.s_force.items():
            sl.committed.connect(lambda v, n=name: self._apply(n, v))
        self.s_angle.hintClicked.connect(lambda: self._hint("angle"))
        self.s_ffb.hintClicked.connect(lambda: self._hint("ffb"))
        for name, sl in self.s_force.items():
            sl.hintClicked.connect(lambda n=name: self._hint(n))

        mapping = CardPanel("Pemetaan tombol", "Klik tombol pada diagram untuk mengubah fungsinya.")
        self.map_wheel = WheelMappingView()
        self.map_wheel.selected.connect(self._remap)
        mapping.body.addWidget(self.map_wheel, 1)
        lay.addWidget(params, 5)
        lay.addWidget(mapping, 5)
        self.stack.addWidget(page)
        self._pages = {"wheel": page}

    def _build_pedal(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        chart_card = CardPanel("Linearity", "Atur kurva respons injakan pedal.")
        hint = button("?", "icon")
        hint.clicked.connect(lambda: self._hint("chart"))
        reset = button("Reset kurva", "ghost")
        reset.clicked.connect(self._reset_curve)
        chart_card.add_header_widget(hint)
        chart_card.add_header_widget(reset)
        self.curve_tabs = SegmentedBar()
        self.curve_tabs.set_items([(k, CURVE_TITLES[k].upper()) for k in ("acc", "brake", "clutch")])
        self.curve_tabs.currentChanged.connect(self._curve_changed)
        chart_card.body.addWidget(self.curve_tabs, 0, Qt.AlignLeft)
        self.curve_note = label("Kurva ini belum dikonfigurasi di perangkat (semua nilai nol). Tekan “Reset kurva” untuk "
                                "menetapkan garis linear bawaan.", "muted", wrap=True)
        self.curve_note.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 10px 12px;")
        chart_card.body.addWidget(self.curve_note)
        self.chart = CurveChart()
        self.chart.set_color(CURVE_COLORS["acc"])
        self.chart.pointCommitted.connect(self._curve_point)
        chart_card.body.addWidget(self.chart, 1)

        map_card = CardPanel("Tombol pedal", "Pemetaan fungsi untuk Gas, Rem, dan Kopling.")
        self.map_pedal = PedalMappingView()
        self.map_pedal.selected.connect(self._remap)
        map_card.body.addWidget(self.map_pedal, 1)
        lay.addWidget(chart_card, 6)
        lay.addWidget(map_card, 4)
        self.stack.addWidget(page)
        self._pages["pedal"] = page

    def _build_lever(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        card = CardPanel("Shifter H-pattern", "Gigi 1–6, R, serta paddle LeverL / LeverR.")
        self.map_lever = LeverMappingView()
        self.map_lever.selected.connect(self._remap)
        card.body.addWidget(self.map_lever, 1)
        lay.addWidget(card)
        self.stack.addWidget(page)
        self._pages["lever"] = page

    def _build_brake(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        card = CardPanel("Handbrake", "Pemetaan fungsi rem tangan.")
        self.map_brake = BrakeMappingView()
        self.map_brake.selected.connect(self._remap)
        card.body.addWidget(self.map_brake, 1)
        lay.addWidget(card)
        self.stack.addWidget(page)
        self._pages["brake"] = page

    # --------------------------------------------------------------- context
    def set_hardware(self, pedal: bool, lever: bool, brake: bool) -> None:
        items = [("wheel", "WHEEL")]
        if pedal:
            items.append(("pedal", "PEDAL"))
        if lever:
            items.append(("lever", "SHIFTER"))
        if brake:
            items.append(("brake", "HANDBRAKE"))
        self.tabs.set_items(items, keep=True)

    def set_mode(self, mode: int, angle_enabled: bool = True) -> None:
        self.mode = mode
        self.angle_enabled = angle_enabled
        for v in (self.map_wheel, self.map_pedal, self.map_lever, self.map_brake):
            v.set_mode(mode)
        angle_ffb = mode in C.ANGLE_FFB_MODES
        forces = mode in C.FORCE_MODES
        self.s_angle.setVisible(angle_ffb and angle_enabled)
        self.s_ffb.setVisible(angle_ffb)
        self.physics_label.setVisible(forces)
        self.physics_note.setVisible(not forces and mode == C.MODE_PC_XINPUT)
        self.physics_note.setText("Physics forces (Spring/Damping/Friction/Inertia) tidak didukung pada mode X-Input "
                                  "sehingga disembunyikan. Pindah ke D-Input untuk mengaturnya.")
        for s in self.s_force.values():
            s.setVisible(forces)
        self.empty_label.setVisible(not angle_ffb)
        self.angle_note.setVisible(angle_ffb and not angle_enabled)
        self.angle_note.setText("Slider ANGLE disembunyikan: firmware melaporkan bahwa sudut kemudi tidak diatur dari "
                                "aplikasi (angle mode 0), sama seperti aplikasi Android asli.")
        self.refresh()

    def _tab_changed(self, key: str) -> None:
        if key in self._pages:
            self.stack.setCurrentWidget(self._pages[key])

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        p = self.backend.profile
        for slider, value in ((self.s_angle, p.angle), (self.s_ffb, p.ffb), *((self.s_force[n], getattr(p, n)) for n in self.s_force)):
            if not slider.is_dragging():
                slider.set_value(value)
        self.reverse_switch.setChecked(bool(p.ffb_reverse))
        self.reverse_state.setText("ON" if p.ffb_reverse else "OFF")
        for v in (self.map_wheel, self.map_pedal, self.map_lever, self.map_brake):
            v.set_keymap(p.keymap)
        self.chart.set_points(p.curve(self._curve))
        self._update_curve_note()

    def _update_curve_note(self) -> None:
        pts = self.backend.profile.curve(self._curve)
        self.curve_note.setVisible(all(x == 0 and y == 0 for x, y in pts))

    # --------------------------------------------------------------- actions
    def _apply(self, what: str, value: int) -> None:
        b = self.backend
        if what == "angle":
            b.set_angle(value)
        elif what == "ffb":
            b.set_ffb(value)
        else:
            b.set_force(what, value)
        self.changed.emit()

    def _reverse_clicked(self) -> None:
        on = self.reverse_switch.isChecked()
        self.reverse_state.setText("ON" if on else "OFF")
        self.backend.set_ffb_reverse(1 if on else 0)
        self.notify.emit("Arah force feedback diubah (Reverse " + ("ON" if on else "OFF") + ")")
        self.changed.emit()

    def _hint(self, key: str) -> None:
        title, text = HINTS[key]
        info(self, title, text)

    def _remap(self, code: int) -> None:
        current = self.backend.profile.mapped(code)
        picked = pick_key(self.window(), self.mode, code, current)
        for v in (self.map_wheel, self.map_pedal, self.map_lever, self.map_brake):
            v.set_selected(-1)
        if picked is None:
            return
        self.backend.set_mapping(code, picked)
        self.refresh()
        self.changed.emit()

    def _curve_changed(self, name: str) -> None:
        self._curve = name
        self.chart.set_color(CURVE_COLORS[name])
        self.chart.set_points(self.backend.profile.curve(name))
        self._update_curve_note()

    def _curve_point(self, i: int, x: int, y: int) -> None:
        self.backend.set_curve_point(self._curve, i, x, y)
        self.changed.emit()

    def _reset_curve(self) -> None:
        self.backend.reset_curve(self._curve)
        self.chart.set_points(self.backend.profile.curve(self._curve))
        self._update_curve_note()
        self.changed.emit()
