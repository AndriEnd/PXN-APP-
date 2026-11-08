"""Key codes and their display labels (port of KeyCode_V10 + the virtual keyboards layouts)."""

from __future__ import annotations

from .constants import MODE_PC_DINPUT, MODE_SWITCH_PRO, MODE_XBOX_ONE_WHEEL

# --------------------------------------------------------------- numeric ids
KEYCODE_VIEW = 0
KEYCODE_L3 = 1
KEYCODE_R3 = 2
KEYCODE_MENU = 3
KEYCODE_UP = 4
KEYCODE_RIGHT = 5
KEYCODE_DOWN = 6
KEYCODE_LEFT = 7
KEYCODE_Y = 8
KEYCODE_B = 9
KEYCODE_A = 10
KEYCODE_X = 11
KEYCODE_L1 = 12
KEYCODE_R1 = 13
KEYCODE_L2 = 14
KEYCODE_R2 = 15
KEYCODE_HOME = 16
KEYCODE_SHARE = 17
KEYCODE_ACCELERATOR = 20
KEYCODE_BRAKE = 21
KEYCODE_CLUTCH = 22
KEYCODE_HAND_BRAKE = 23  # label "Handbrake"
KEYCODE_GD = 24
KEYCODE_GEAR_RIGHT = 25  # label "LeverR"
KEYCODE_GEAR_LEFT = 26  # label "LeverL"
KEYCODE_GEAR_1 = 27
KEYCODE_GEAR_2 = 28
KEYCODE_GEAR_3 = 29
KEYCODE_GEAR_4 = 30
KEYCODE_GEAR_5 = 31
KEYCODE_GEAR_6 = 32
KEYCODE_GEAR_R = 33
KEYCODE_LX_MINUS = 34
KEYCODE_LX_PLUS = 35
KEYCODE_RESET = 46
KEYCODE_RESERVED = 47
KEYCODE_MOUSE_LEFT = 48
KEYCODE_MOUSE_RIGHT = 49
KEYCODE_MOUSE_MIDDLE = 50

# ------------------------------------------------- canonical (INI) names + labels
# code -> (canonical name, default label)
_BASE: dict[int, tuple[str, str]] = {
    0: ("VIEW", "View"),
    1: ("L3", "L3"),
    2: ("R3", "R3"),
    3: ("MENU", "Menu"),
    4: ("UP", "▲"),
    5: ("RIGHT", "▶"),
    6: ("DOWN", "▼"),
    7: ("LEFT", "◀"),
    8: ("Y", "Y"),
    9: ("B", "B"),
    10: ("A", "A"),
    11: ("X", "X"),
    12: ("L1", "L1"),
    13: ("R1", "R1"),
    14: ("L2", "L2"),
    15: ("R2", "R2"),
    16: ("HOME", "Home"),
    17: ("SHARE", "Share"),
    20: ("ACCELERATOR", "Accelerator"),
    21: ("BRAKE", "Brake"),
    22: ("CLUTCH", "Clutch"),
    23: ("HANDBRAKE", "Handbrake"),
    24: ("GD", "GD"),
    25: ("LEVER_R", "LeverR"),
    26: ("LEVER_L", "LeverL"),
    27: ("GEAR_1", "1 gear"),
    28: ("GEAR_2", "2 gear"),
    29: ("GEAR_3", "3 gear"),
    30: ("GEAR_4", "4 gear"),
    31: ("GEAR_5", "5 gear"),
    32: ("GEAR_6", "6 gear"),
    33: ("GEAR_R", "R gear"),
    34: ("LX_MINUS", "LX-"),
    35: ("LX_PLUS", "LX+"),
    46: ("RESET", "Reset"),
    47: ("RESERVED", "—"),
    48: ("MOUSE_LEFT", "MouseL"),
    49: ("MOUSE_RIGHT", "MouseR"),
    50: ("MOUSE_MIDDLE", "MouseM"),
}

_KBD_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
for _i, _c in enumerate(_KBD_LETTERS):
    _BASE[64 + _i] = (f"KEY_{_c}", _c)

# digits: 90..98 = 1..9, 99 = 0
_DIGIT_LABEL = {90: "1!", 91: "2@", 92: "3#", 93: "4$", 94: "5%", 95: "6^", 96: "7&", 97: "8*", 98: "9(", 99: "0)"}
for _code, _lbl in _DIGIT_LABEL.items():
    _BASE[_code] = (f"KEY_{_lbl[0]}", _lbl)

for _n in range(12):
    _BASE[100 + _n] = (f"KEY_F{_n + 1}", f"F{_n + 1}")

_BASE.update(
    {
        112: ("KEY_ESC", "Esc"),
        113: ("KEY_GRAVE", "~"),
        114: ("KEY_MINUS", "-"),
        115: ("KEY_EQUALS", "="),
        116: ("KEY_TAB", "Tab"),
        117: ("KEY_CAPS_LOCK", "Cap"),
        118: ("KEY_CTRL_LEFT", "Ctrl"),
        119: ("KEY_SHIFT_LEFT", "Shift"),
        120: ("KEY_ALT_LEFT", "Alt"),
        121: ("KEY_WIN_LEFT", "Win"),
        122: ("KEY_CTRL_RIGHT", "Ctrl"),
        123: ("KEY_SHIFT_RIGHT", "Shift"),
        124: ("KEY_ALT_RIGHT", "Alt"),
        125: ("KEY_WIN_RIGHT", "Win"),
        126: ("KEY_ENTER", "Enter"),
        127: ("KEY_BACKSPACE", "Backspace"),
        128: ("KEY_LEFT_BRACKET", "[{"),
        129: ("KEY_RIGHT_BRACKET", "]}"),
        130: ("KEY_BACKSLASH", "|"),
        131: ("KEY_SEMICOLON", ";:"),
        132: ("KEY_APOSTROPHE", "'\""),
        133: ("KEY_COMMA", ",<"),
        134: ("KEY_PERIOD", ".>"),
        135: ("KEY_SLASH", "/?"),
        136: ("KEY_SPACE", "Space"),
        137: ("KEY_UP", "↑"),
        138: ("KEY_DOWN", "↓"),
        139: ("KEY_LEFT", "←"),
        140: ("KEY_RIGHT", "→"),
        141: ("NUM_DIVIDE", "/"),
        142: ("NUM_MULTIPLY", "*"),
        143: ("NUM_SUBTRACT", "-"),
        144: ("NUM_ADD", "+"),
        145: ("NUM_ENTER", "Enter"),
        146: ("NUM_DOT", "."),
    }
)
for _n in range(10):
    _BASE[147 + _n] = (f"NUM_{_n}", str(_n))
# Mouse buttons 4..15 exist in the enum (51..62) but are not exposed by any keyboard
for _n, _code in enumerate(range(51, 63), start=4):
    _BASE[_code] = (f"MOUSE_{_n}", f"Mouse{_n}")

CODE_TO_NAME: dict[int, str] = {c: n for c, (n, _) in _BASE.items()}
NAME_TO_CODE: dict[str, int] = {n: c for c, n in CODE_TO_NAME.items()}
# a few friendly aliases accepted when reading INI files
NAME_TO_CODE.update(
    {
        "PS_CROSS": 10, "PS_CIRCLE": 9, "PS_SQUARE": 11, "PS_TRIANGLE": 8,
        "LB": 12, "RB": 13, "LT": 14, "RT": 15,
        "GAS": 20, "THROTTLE": 20, "CLUTCH_PEDAL": 22,
        "PADDLE_LEFT": 26, "PADDLE_RIGHT": 25,
    }
)


def key_name(code: int) -> str:
    return CODE_TO_NAME.get(code, f"CODE_{code}")


def key_code(name_or_number: str | int) -> int | None:
    """Resolve a canonical name (``L1``), alias or number to a key code."""
    if isinstance(name_or_number, int):
        return name_or_number
    text = str(name_or_number).strip().upper().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    if text.lstrip("-").isdigit():
        value = int(text)
        return value if 0 <= value <= 255 else None
    if text.startswith("CODE_") and text[5:].isdigit():
        return int(text[5:])
    return NAME_TO_CODE.get(text)


def key_label(code: int, mode: int = MODE_PC_DINPUT) -> str:
    """Display text of a function for a given wheel mode (KeyCode_V10.getString)."""
    if code == 8:
        return "X" if mode == MODE_SWITCH_PRO else "Y"
    if code == 9:
        return "A" if mode == MODE_SWITCH_PRO else "B"
    if code == 10:
        return "B" if mode == MODE_SWITCH_PRO else "A"
    if code == 11:
        return "Y" if mode == MODE_SWITCH_PRO else "X"
    if code in (12, 13, 14, 15):
        idx = code - 12
        if mode == MODE_XBOX_ONE_WHEEL:
            return ("LB", "RB", "LT", "RT")[idx]
        if mode == MODE_SWITCH_PRO:
            return ("L", "R", "ZL", "ZR")[idx]
        return ("L1", "R1", "L2", "R2")[idx]
    entry = _BASE.get(code)
    return entry[1] if entry else "?"


# ----------------------------------------------------------- keyboard layouts
# GamepadKeyboard (all modes except D-Input)
GAMEPAD_ROWS = ((4, 12, 14, 1, 8), (7, 5, 13, 15, 2, 11, 9), (6, 46, 10))
# WheelKeyboard (D-Input "GAMEPAD" tab: includes pedals and shifter functions)
WHEEL_ROWS = (
    (12, 14, 1, 16, 2, 15, 13),
    (4, 0, 3, 8),
    (7, 5, 17, 11, 9),
    (6, 26, 25, 10),
    (27, 28, 29, 30, 31, 32, 33),
    (22, 21, 20, 46),
)
# LetterKeyboard (D-Input "KEYBOARD" tab, first page)
LETTER_ROWS = (
    tuple(range(100, 112)),
    (112, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99),
    # the original lists Tab (116) a second time at the end of this row; Backspace fits better
    (116, 80, 86, 68, 81, 83, 88, 84, 72, 78, 79, 127),
    (117, 64, 82, 67, 69, 70, 71, 73, 74, 75, 126),
    (119, 89, 87, 66, 85, 65, 77, 76, 123),
    (118, 120, 136, 46, 124, 122),
)
# NumKeyboard (D-Input "KEYBOARD" tab, second page)
NUM_ROWS = (
    (113, 114, 115, 128, 129, 130, 131, 132, 133, 134, 135),
    (137, 141, 142, 143, 144),
    (139, 140, 154, 155, 156, 147),
    (138, 151, 152, 153, 146),
    (48, 50, 49, 148, 149, 150, 145),
)

# --------------------------------------------------------------- physical keys
WHEEL_PHYSICAL = (14, 12, 13, 15, 4, 6, 7, 5, 10, 9, 11, 8, 1, 2, 16, 0, 17, 3)
D_INPUT_ONLY_PHYSICAL = (0, 3, 16, 17)  # View / Menu / Home / Share only in D-Input
PEDAL_PHYSICAL = (22, 21, 20)
LEVER_PHYSICAL = (25, 26, 27, 28, 29, 30, 31, 32, 33)
BRAKE_PHYSICAL = (23,)
