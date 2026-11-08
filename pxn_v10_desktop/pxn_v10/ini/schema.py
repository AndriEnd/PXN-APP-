"""Native PXN-V10 INI sections and the parameter registry.

A preset ``.ini`` can contain any number of foreign sections (e.g. the Assetto Corsa / CSP
``[FFB_TWEAKS:...]`` groups) - they are preserved. The wheel parameters live in these sections::

    [PXN_V10:GENERAL]     NAME, MODE, PLATFORM
    [PXN_V10:WHEEL]       ANGLE, FFB, FFB_REVERSE, SPRING, DAMPING, FRICTION, INERTIA
    [PXN_V10:CURVE_ACC]   P0..P3 = "x,y"       (also CURVE_BRAKE / CURVE_CLUTCH)
    [PXN_V10:KEYMAP]      <PHYSICAL KEY> = <FUNCTION>   (names from keycodes.py, or numbers)
    [PXN_V10:FFB_ADV]     ENABLED, LUT=0,25,50,75,100, SMOOTHING, PNEUMATIC_TRAIL, MECHANICAL_TRAIL,
                          ROAD, SLIP, KERB   (FFB lanjutan, diterjemahkan ke parameter firmware)
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import constants as C

GROUP = "PXN_V10"
SEC_GENERAL = f"{GROUP}:GENERAL"
SEC_WHEEL = f"{GROUP}:WHEEL"
SEC_KEYMAP = f"{GROUP}:KEYMAP"
SEC_FFB_ADV = f"{GROUP}:FFB_ADV"
# [PXN_V10:FFB_ADV] key -> (atribut FfbAdvanced, label)
FFB_ADV_KEYS = {
    "SMOOTHING": ("smoothing", "Smoothing"),
    "PNEUMATIC_TRAIL": ("pneumatic_trail", "Pneumatic trail"),
    "MECHANICAL_TRAIL": ("mechanical_trail", "Mechanical trail"),
    "ROAD": ("road_effect", "Road effect"),
    "SLIP": ("slip_effect", "Slip effect"),
    "KERB": ("kerb_effect", "Kerb effect"),
}
SEC_CURVES = {
    "acc": f"{GROUP}:CURVE_ACC",
    "brake": f"{GROUP}:CURVE_BRAKE",
    "clutch": f"{GROUP}:CURVE_CLUTCH",
}
CURVE_LABELS = {"acc": "Gas", "brake": "Rem", "clutch": "Kopling"}

# the wheel parameters that can be sent as a *scalar* value (targets for custom bindings)


@dataclass(frozen=True)
class ParamSpec:
    id: str  # attribute name on DeviceProfile (or "mode")
    label: str
    section: str
    key: str
    kind: str  # int | bool | mode
    lo: int
    hi: int
    group: str
    help: str = ""
    # only meaningful in some modes (UI hint)
    modes: tuple | None = None


PARAMS: tuple = (
    ParamSpec("mode", "Mode perangkat", SEC_GENERAL, "MODE", "mode", 1, 11, "General",
              "1 = D-Input, 2 = X-Input, 5 = PS4, 8 = Xbox One, 10 = Android, 11 = Switch"),
    ParamSpec("angle", "Steering angle (°)", SEC_WHEEL, "ANGLE", "int", C.ANGLE_MIN, C.ANGLE_MAX, "Wheel",
              "Sudut putar kemudi 90–900°"),
    ParamSpec("ffb", "Force feedback (%)", SEC_WHEEL, "FFB", "int", 0, 100, "Wheel", "Kekuatan force feedback 0–100"),
    ParamSpec("ffb_reverse", "FFB reverse", SEC_WHEEL, "FFB_REVERSE", "bool", 0, 1, "Wheel", "0 = normal, 1 = dibalik"),
    ParamSpec("spring", "Spring force (%)", SEC_WHEEL, "SPRING", "int", 0, 100, "Physics", "Hanya D-Input / PS4",
              C.FORCE_MODES),
    ParamSpec("damping", "Damping force (%)", SEC_WHEEL, "DAMPING", "int", 0, 100, "Physics", "Hanya D-Input / PS4",
              C.FORCE_MODES),
    ParamSpec("friction", "Friction force (%)", SEC_WHEEL, "FRICTION", "int", 0, 100, "Physics", "Hanya D-Input / PS4",
              C.FORCE_MODES),
    ParamSpec("inertia", "Inertia force (%)", SEC_WHEEL, "INERTIA", "int", 0, 100, "Physics", "Hanya D-Input / PS4",
              C.FORCE_MODES),
)
PARAM_BY_ID = {p.id: p for p in PARAMS}
SCALAR_TARGETS = tuple(p.id for p in PARAMS)

MODE_ALIASES = {
    "DINPUT": 1, "D-INPUT": 1, "D_INPUT": 1, "DIRECTINPUT": 1, "PC": 1, "PC_DINPUT": 1,
    "XINPUT": 2, "X-INPUT": 2, "X_INPUT": 2, "PC_XINPUT": 2,
    "PS4": 5, "PS4_WHEEL": 5, "PLAYSTATION": 5,
    "XBOX": 8, "XBOXONE": 8, "XBOX_ONE": 8, "XBOX ONE": 8,
    "ANDROID": 10,
    "SWITCH": 11, "SWITCH_PRO": 11,
}
BOOL_TRUE = {"1", "true", "yes", "on", "reverse", "reversed", "inverted", "invert"}
BOOL_FALSE = {"0", "false", "no", "off", "normal", "none", ""}

SAMPLE_NATIVE_INI = f"""[CONFIGURATION]
VERSION=1
AFFECTED_SECTIONS={GROUP}

[{SEC_GENERAL}]
NAME=Contoh preset PXN V10
MODE=1
PLATFORM=1

[{SEC_WHEEL}]
ANGLE=900
FFB=80
FFB_REVERSE=0
SPRING=70
DAMPING=60
FRICTION=50
INERTIA=50

[{SEC_FFB_ADV}]
ENABLED=1
LUT=0,25,50,75,100
SMOOTHING=20
PNEUMATIC_TRAIL=60
MECHANICAL_TRAIL=55
ROAD=30
SLIP=40
KERB=25

[{SEC_CURVES['acc']}]
P0=0,0
P1=1365,21845
P2=2730,43690
P3=4095,65535

[{SEC_KEYMAP}]
L1=R1
R1=L1
"""
