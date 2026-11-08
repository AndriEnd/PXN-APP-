"""Domain models: DeviceState, DeviceProfile, TestData (ports of the Java classes)."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Iterable

from . import constants as C

Curve = list  # list[list[int]] -> 4 x [x, y]


def default_curve() -> Curve:
    return [list(p) for p in C.DEFAULT_CURVE]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _pad(data: bytes, size: int = C.PACKET_SIZE) -> bytes:
    """Notifications can be shorter than 20 bytes - never let a short frame raise IndexError."""
    return data if len(data) >= size else bytes(data) + bytes(size - len(data))


# ------------------------------------------------------------------ DeviceState
@dataclass
class DeviceState:
    mode: int = C.MODE_WAITING
    version: int = 0
    minor_ver: int = 0
    major_ver: int = 0
    pedal_state: int = 0
    lever_state: int = 0
    angle_mode: int = 0
    brake_state: int = 0

    def unpack(self, data: bytes) -> None:
        b = _pad(data)
        self.mode = b[2]
        self.version = struct.unpack_from("<H", b, 3)[0]
        self.minor_ver = b[3]
        self.major_ver = b[4]
        self.pedal_state = b[5]
        self.lever_state = b[6]
        self.angle_mode = b[7]
        self.brake_state = b[8]

    @property
    def is_pc_mode(self) -> bool:
        return self.mode in C.SWITCHABLE_MODES

    @property
    def has_pedal(self) -> bool:
        return self.pedal_state > 0

    @property
    def has_lever(self) -> bool:
        return self.lever_state > 0

    @property
    def has_brake(self) -> bool:
        return self.brake_state > 0

    @property
    def firmware_text(self) -> str:
        if not self.version:
            return "—"
        return f"v{self.version}  ({self.major_ver}.{self.minor_ver})"

    def copy(self) -> "DeviceState":
        return DeviceState(**self.__dict__)


# ---------------------------------------------------------------- DeviceProfile
@dataclass
class DeviceProfile:
    """Full configuration of the wheel (keymap, angle, FFB, 4 forces, 3 pedal curves)."""

    keymap: dict = field(default_factory=dict)  # physical code -> function code (missing = identity)
    angle: int = 900
    ffb: int = 100
    spring: int = 100
    damping: int = 100
    friction: int = 100
    inertia: int = 100
    ffb_reverse: int = 0
    acc_curve: Curve = field(default_factory=default_curve)
    brake_curve: Curve = field(default_factory=default_curve)
    clutch_curve: Curve = field(default_factory=default_curve)

    # ---- keymap helpers
    def mapped(self, code: int) -> int:
        return self.keymap.get(code, code)

    def set_mapping(self, code: int, function: int) -> None:
        self.keymap[code] = function

    def reset_mapping(self, code: int | None = None) -> None:
        if code is None:
            self.keymap.clear()
        else:
            self.keymap.pop(code, None)

    def custom_mappings(self) -> dict:
        return {k: v for k, v in self.keymap.items() if k != v and k != C.KEYCODE_RESERVED}

    # ---- curve helpers
    def curve(self, name: str) -> Curve:
        return {"acc": self.acc_curve, "brake": self.brake_curve, "clutch": self.clutch_curve}[name]

    def set_curve(self, name: str, points: Iterable) -> None:
        pts = [[int(x), int(y)] for x, y in points]
        if len(pts) != 4:
            raise ValueError("a pedal curve needs exactly 4 control points")
        setattr(self, {"acc": "acc_curve", "brake": "brake_curve", "clutch": "clutch_curve"}[name], pts)

    def reset_curve(self, name: str) -> None:
        self.set_curve(name, C.DEFAULT_CURVE)

    # ---- value sanity
    def clamp(self) -> "DeviceProfile":
        self.angle = _clamp(self.angle, C.ANGLE_MIN, C.ANGLE_MAX)
        for name in ("ffb", "spring", "damping", "friction", "inertia"):
            setattr(self, name, _clamp(getattr(self, name), 0, 100))
        self.ffb_reverse = 1 if self.ffb_reverse else 0
        for curve in (self.acc_curve, self.brake_curve, self.clutch_curve):
            for p in curve:
                p[0] = _clamp(p[0], 0, C.CURVE_X_MAX)
                p[1] = _clamp(p[1], 0, C.CURVE_Y_MAX)
        return self

    def copy(self) -> "DeviceProfile":
        return DeviceProfile(
            keymap=dict(self.keymap),
            angle=self.angle,
            ffb=self.ffb,
            spring=self.spring,
            damping=self.damping,
            friction=self.friction,
            inertia=self.inertia,
            ffb_reverse=self.ffb_reverse,
            acc_curve=[list(p) for p in self.acc_curve],
            brake_curve=[list(p) for p in self.brake_curve],
            clutch_curve=[list(p) for p in self.clutch_curve],
        )

    def __eq__(self, other: object) -> bool:  # keymap compared on effective mappings
        if not isinstance(other, DeviceProfile):
            return NotImplemented
        return (
            self.custom_mappings() == other.custom_mappings()
            and self.angle == other.angle
            and self.ffb == other.ffb
            and self.spring == other.spring
            and self.damping == other.damping
            and self.friction == other.friction
            and self.inertia == other.inertia
            and bool(self.ffb_reverse) == bool(other.ffb_reverse)
            and self.acc_curve == other.acc_curve
            and self.brake_curve == other.brake_curve
            and self.clutch_curve == other.clutch_curve
        )

    # ---- wire format: DeviceProfile.pack(page)
    def pack_page(self, page: int, mode: int = 0, opcode: int = C.REPORT_ID_WRITE_PROFILE_REQ) -> bytes:
        """Build the 20-byte frame ``[opcode, mode, page, payload...]`` for profile page 0..5."""
        buf = bytearray(C.PACKET_SIZE)
        buf[0] = opcode & 0xFF
        buf[1] = mode & 0xFF
        buf[2] = page & 0xFF
        pos = 3
        seq = C.KEYMAP_SEQUENCE
        if page == 0:
            for i in range(17):
                buf[pos + i] = self.mapped(seq[i]) & 0xFF
        elif page == 1:
            for i in range(17):
                buf[pos + i] = self.mapped(seq[i + 17]) & 0xFF
        elif page == 2:
            for i in range(2):
                buf[pos + i] = self.mapped(seq[i + 34]) & 0xFF
            struct.pack_into("<H", buf, 5, self.angle & 0xFFFF)
            buf[7] = self.ffb & 0xFF
            buf[8] = self.spring & 0xFF
            buf[9] = self.damping & 0xFF
            buf[10] = self.friction & 0xFF
            buf[11] = self.inertia & 0xFF
            buf[12] = self.ffb_reverse & 0xFF
        elif page in (3, 4, 5):
            curve = (self.acc_curve, self.brake_curve, self.clutch_curve)[page - 3]
            for i, (x, y) in enumerate(curve):
                struct.pack_into("<HH", buf, pos + i * 4, x & 0xFFFF, y & 0xFFFF)
        else:
            raise ValueError(f"profile page out of range: {page}")
        return bytes(buf)

    def pack_pages(self, mode: int, opcode: int = C.REPORT_ID_WRITE_PROFILE_REQ) -> list:
        return [self.pack_page(p, mode, opcode) for p in range(C.PROFILE_PAGES)]

    # ---- wire format: DeviceProfile.unpack(bArr) for a 0xD1 response
    def unpack_page(self, data: bytes) -> int:
        """Apply a 0xD1 profile page frame; returns the page index."""
        b = _pad(data)
        page = b[2]
        seq = C.KEYMAP_SEQUENCE
        if page == 0:
            for i in range(17):
                self.keymap[seq[i]] = b[i + 3]
        elif page == 1:
            for i in range(17):
                self.keymap[seq[i + 17]] = b[i + 3]
        elif page == 2:
            for i in range(2):
                self.keymap[seq[i + 34]] = b[i + 3]
            self.angle = struct.unpack_from("<H", b, 5)[0]
            self.ffb = b[7]
            self.spring = b[8]
            self.damping = b[9]
            self.friction = b[10]
            self.inertia = b[11]
            self.ffb_reverse = b[12]
        elif page in (3, 4, 5):
            pts = [list(struct.unpack_from("<HH", b, 3 + i * 4)) for i in range(4)]
            setattr(self, ("acc_curve", "brake_curve", "clutch_curve")[page - 3], pts)
        return page

    def to_dict(self) -> dict:
        return {
            "angle": self.angle,
            "ffb": self.ffb,
            "ffb_reverse": int(bool(self.ffb_reverse)),
            "spring": self.spring,
            "damping": self.damping,
            "friction": self.friction,
            "inertia": self.inertia,
            "keymap": {str(k): v for k, v in self.custom_mappings().items()},
            "acc_curve": self.acc_curve,
            "brake_curve": self.brake_curve,
            "clutch_curve": self.clutch_curve,
        }


# --------------------------------------------------------------------- TestData
class TestData:
    """Live telemetry from test mode (0xD4 0x03)."""

    __test__ = False  # not a pytest class

    def __init__(self) -> None:
        self.angle = 128  # raw 0..255 (128 = centre)
        self.acc = 0
        self.brake = 0
        self.clutch = 0
        self.gear_status = 0
        self.gear_level = 0
        self.pressed: dict = {}
        self._source: bytes | None = None

    @staticmethod
    def _bits(value: int) -> list:
        return [(value >> i) & 1 for i in range(8)]

    def unpack(self, data: bytes) -> bool:
        """Returns False if the frame is identical to the previous one."""
        b = _pad(data, 14)
        if self._source == bytes(b):
            return False
        self._source = bytes(b)
        for seq, byte in ((C.TEST_KEY_SEQUENCE_1, b[2]), (C.TEST_KEY_SEQUENCE_2, b[3]), (C.TEST_KEY_SEQUENCE_3, b[4])):
            bits = self._bits(byte)
            for i, code in enumerate(seq):
                self.pressed[code] = bits[i] == 1
        self.angle = b[6]
        self.acc, self.brake, self.clutch = b[8], b[9], b[10]
        self.pressed[20] = self.acc > 0
        self.pressed[21] = self.brake > 0
        self.pressed[22] = self.clutch > 0
        self.gear_status = b[11]
        bits = self._bits(b[12])
        for i, code in enumerate(C.TEST_KEY_SEQUENCE_4):
            self.pressed[code] = bits[i] == 1
        self.gear_level = b[13]
        for code, gear in ((27, 1), (28, 2), (29, 3), (30, 4), (31, 5), (32, 6), (33, 255)):
            self.pressed[code] = self.gear_level == gear
        return True

    def snapshot(self) -> "TestSnapshot":
        return TestSnapshot(
            self.angle, self.acc, self.brake, self.clutch, self.gear_level, dict(self.pressed)
        )

    # steering position as a fraction -1..1 (AngleTestView.setValue)
    @staticmethod
    def angle_fraction(raw: int) -> float:
        # the Android view divides with BigDecimal scale 2 / ROUND_UP (away from zero)
        delta = raw - 128
        if delta > 1:
            value = (raw - 129) / 127
        elif delta < -1:
            value = (raw - 127) / 127
        else:
            return 0.0
        return math.copysign(math.ceil(abs(value) * 100 - 1e-9) / 100, value)

    @staticmethod
    def gear_text(level: int) -> str:
        if level == 255:
            return "R"
        if 1 <= level <= 6:
            return str(level)
        return "N"


@dataclass
class TestSnapshot:
    __test__ = False
    angle: int
    acc: int
    brake: int
    clutch: int
    gear_level: int
    pressed: dict

    @property
    def fraction(self) -> float:
        return TestData.angle_fraction(self.angle)

    @property
    def gear(self) -> str:
        return TestData.gear_text(self.gear_level)
