"""Konfigurasi sisi-aplikasi untuk perangkat USB: kalibrasi sumbu, pemetaan gigi shifter, handbrake.

Perangkat USB game controller (shifter/handbrake/pedal) hanya mengirim posisi sumbu dan tombol;
konfigurasi di sini disimpan di PC dan dipakai untuk membaca perangkat dengan benar (test & tampilan),
tidak ditulis ke firmware perangkat.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

ROLE_WHEEL, ROLE_PEDALS, ROLE_SHIFTER, ROLE_HANDBRAKE, ROLE_OTHER = "wheel", "pedals", "shifter", "handbrake", "other"
ROLES = (ROLE_WHEEL, ROLE_PEDALS, ROLE_SHIFTER, ROLE_HANDBRAKE, ROLE_OTHER)
ROLE_TITLES = {ROLE_WHEEL: "Setir", ROLE_PEDALS: "Pedal", ROLE_SHIFTER: "Shifter", ROLE_HANDBRAKE: "Handbrake",
               ROLE_OTHER: "Lainnya"}
GEARS = ("1", "2", "3", "4", "5", "6", "R")


def guess_role(name: str, n_axes: int, n_buttons: int) -> str:
    n = (name or "").lower()
    if "shift" in n or "gearbox" in n:
        return ROLE_SHIFTER
    if any(k in n for k in ("handbrake", "hand brake", "e-brake", "ebrake")):
        return ROLE_HANDBRAKE
    if "pedal" in n:
        return ROLE_PEDALS
    if any(k in n for k in ("wheel", "pxn", "v10", "v9", "v12", "g29", "g920", "t300", "fanatec", "moza",
                            "thrustmaster", "driving force")):
        return ROLE_WHEEL
    if n_axes >= 3:
        return ROLE_WHEEL
    if n_axes <= 1 and n_buttons <= 2:
        return ROLE_HANDBRAKE
    if n_buttons >= 7 and n_axes <= 2:
        return ROLE_SHIFTER
    return ROLE_OTHER


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _from_dict(cls, d):
    d = d if isinstance(d, dict) else {}
    return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# ------------------------------------------------------------------------------------ axis
@dataclass
class AxisCalibration:
    axis: int = 0  # indeks pada JoyInfo.axes, -1 = tidak dipakai
    invert: bool = False
    raw_min: int = 0
    raw_max: int = 65535
    deadzone: float = 0.0  # 0..0.45 di ujung bawah
    saturation: float = 0.0  # 0..0.45 di ujung atas
    gamma: float = 1.0  # 1 = linear; >1 = lembut di awal, <1 = tajam di awal

    def normalize(self, raw: float) -> float:
        span = self.raw_max - self.raw_min
        t = 0.0 if span == 0 else _clamp((raw - self.raw_min) / span, 0.0, 1.0)
        if self.invert:
            t = 1.0 - t
        lo, hi = _clamp(self.deadzone, 0, 0.45), 1.0 - _clamp(self.saturation, 0, 0.45)
        t = 0.0 if hi <= lo else _clamp((t - lo) / (hi - lo), 0.0, 1.0)
        g = _clamp(self.gamma, 0.2, 5.0)
        return t ** g

    def read(self, state) -> float | None:
        if self.axis < 0 or self.axis >= len(state.axes):
            return None
        return self.normalize(state.axes[self.axis])

    def bipolar(self, raw: float) -> float:
        """-1..1 untuk kemudi (0.5 = tengah) memakai kalibrasi min/max."""
        return self.normalize(raw) * 2 - 1

    @classmethod
    def from_dict(cls, d) -> "AxisCalibration":
        return _from_dict(cls, d)


# ----------------------------------------------------------------------------------- wheel/pedals
@dataclass
class WheelUsbConfig:
    steer: AxisCalibration = field(default_factory=lambda: AxisCalibration(axis=0))
    acc: AxisCalibration = field(default_factory=lambda: AxisCalibration(axis=1))
    brake: AxisCalibration = field(default_factory=lambda: AxisCalibration(axis=2))
    clutch: AxisCalibration = field(default_factory=lambda: AxisCalibration(axis=-1))
    lock_degrees: int = 900  # rentang kunci-ke-kunci untuk tampilan derajat

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "WheelUsbConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        for name in ("steer", "acc", "brake", "clutch"):
            if name in d:
                setattr(out, name, AxisCalibration.from_dict(d[name]))
        out.lock_degrees = int(_clamp(d.get("lock_degrees", 900), 90, 3600))
        return out


# --------------------------------------------------------------------------------------- handbrake
@dataclass
class HandbrakeConfig:
    mode: str = "analog"  # analog | button
    cal: AxisCalibration = field(default_factory=lambda: AxisCalibration(axis=0))
    button: int = 0
    threshold: float = 0.10  # nilai di atas ini = tarikan aktif

    def decode(self, state) -> tuple:
        """(nilai 0..1, aktif?)"""
        if self.mode == "button":
            on = bool(state.buttons >> self.button & 1) if self.button >= 0 else False
            return (1.0 if on else 0.0), on
        v = self.cal.read(state)
        v = 0.0 if v is None else v
        return v, v > _clamp(self.threshold, 0.0, 1.0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "HandbrakeConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        out.mode = d.get("mode", "analog") if d.get("mode") in ("analog", "button") else "analog"
        out.cal = AxisCalibration.from_dict(d.get("cal"))
        out.button = int(d.get("button", 0))
        out.threshold = float(d.get("threshold", 0.10))
        return out


# ---------------------------------------------------------------------------------------- shifter
@dataclass
class ShifterConfig:
    kind: str = "h"  # h = H-pattern (satu tombol per gigi) | seq = sekuensial (tombol naik/turun)
    gears: dict = field(default_factory=lambda: {g: i for i, g in enumerate(GEARS)})  # gigi -> indeks tombol
    seq_up: int = 0
    seq_down: int = 1
    seq_max: int = 6
    use_pov: bool = False  # sekuensial lewat hat switch (atas/bawah)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "ShifterConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        out.kind = d.get("kind", "h") if d.get("kind") in ("h", "seq") else "h"
        gears = d.get("gears")
        if isinstance(gears, dict):
            out.gears = {str(k): int(v) for k, v in gears.items() if str(k) in GEARS and isinstance(v, int)}
        out.seq_up, out.seq_down = int(d.get("seq_up", 0)), int(d.get("seq_down", 1))
        out.seq_max = int(_clamp(d.get("seq_max", 6), 1, 10))
        out.use_pov = bool(d.get("use_pov", False))
        return out


# Pemetaan gigi bawaan untuk shifter yang sudah dikenal (VID, PID) -> {gigi: indeks tombol 0-based}.
# A7 Gear Shift (LiteStar, 11FF:B772): gigi 1-6 = tombol 1-6, gigi mundur R = tombol 8 (dikonfirmasi pengguna).
KNOWN_SHIFTER_GEARS = {
    (0x11FF, 0xB772): {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "R": 7},
}
_OLD_GENERIC_GEARS = {g: i for i, g in enumerate(GEARS)}  # bawaan lama: R = tombol 7


def parse_device_key(key: str):
    """'11FF:B772' / '11FF:B772#2' -> (0x11FF, 0xB772), atau None."""
    try:
        ids = key.split("#")[0].split(":")
        return int(ids[0], 16), int(ids[1], 16)
    except (ValueError, IndexError):
        return None


def apply_known_defaults(ds: "DeviceSettings", key: str, *, migrate: bool) -> bool:
    """Terapkan pemetaan gigi shifter yang dikenal. ``migrate=True`` hanya mengganti bila pemetaan yang tersimpan
    masih bawaan lama yang belum pernah diubah pengguna. Mengembalikan True bila ada perubahan."""
    ids = parse_device_key(key)
    known = KNOWN_SHIFTER_GEARS.get(ids) if ids else None
    if known is None or ds.shifter.kind != "h":
        return False
    if migrate and ds.shifter.gears != _OLD_GENERIC_GEARS:
        return False  # pengguna sudah mengatur sendiri: jangan ditimpa
    if ds.shifter.gears == known:
        return False
    ds.shifter.gears = dict(known)
    return True


class ShifterDecoder:
    """Menghasilkan gigi aktif ('N','1'..,'R') dari keadaan tombol. Memiliki status untuk mode sekuensial."""

    def __init__(self, config: ShifterConfig) -> None:
        self.cfg = config
        self.level = 0  # sekuensial: -1 = R, 0 = N, 1..max
        self._up = self._down = False

    def update(self, state) -> str:
        c = self.cfg
        if c.kind == "seq":
            if c.use_pov:
                up, down = state.pov == 0, state.pov == 180
            else:
                up = bool(state.buttons >> c.seq_up & 1) if c.seq_up >= 0 else False
                down = bool(state.buttons >> c.seq_down & 1) if c.seq_down >= 0 else False
            if up and not self._up:
                self.level = min(c.seq_max, self.level + 1)
            if down and not self._down:
                self.level = max(-1, self.level - 1)
            self._up, self._down = up, down
            return "R" if self.level < 0 else ("N" if self.level == 0 else str(self.level))
        for gear in ("R", "6", "5", "4", "3", "2", "1"):
            idx = c.gears.get(gear)
            if idx is not None and idx >= 0 and state.buttons >> idx & 1:
                return gear
        return "N"

    def reset(self) -> None:
        self.level = 0
        self._up = self._down = False


# ------------------------------------------------------------------------------------ wizards
class AxisProbe:
    """Mendeteksi sumbu mana yang digerakkan pengguna: panggil ``feed`` berulang, lalu ``result``."""

    def __init__(self, min_span: float = 0.25) -> None:
        self.min_span = min_span
        self._lo: list = []
        self._hi: list = []
        self._ranges: list = []

    def start(self, state, ranges) -> None:
        self._lo = list(state.axes)
        self._hi = list(state.axes)
        self._ranges = list(ranges)

    def feed(self, state) -> None:
        for i, v in enumerate(state.axes[: len(self._lo)]):
            self._lo[i] = min(self._lo[i], v)
            self._hi[i] = max(self._hi[i], v)

    def spans(self) -> list:
        out = []
        for i in range(len(self._lo)):
            lo, hi = self._ranges[i] if i < len(self._ranges) else (0, 65535)
            out.append(0.0 if hi == lo else (self._hi[i] - self._lo[i]) / (hi - lo))
        return out

    def result(self) -> int | None:
        spans = self.spans()
        if not spans:
            return None
        best = max(range(len(spans)), key=lambda i: spans[i])
        return best if spans[best] >= self.min_span else None

    def extent(self, axis: int) -> tuple:
        return int(self._lo[axis]), int(self._hi[axis])


class ButtonProbe:
    """Mendeteksi tombol baru yang ditekan setelah ``start``."""

    def __init__(self) -> None:
        self._base = 0
        self.found: int | None = None

    def start(self, state) -> None:
        self._base = state.buttons
        self.found = None

    def feed(self, state) -> int | None:
        if self.found is not None:
            return self.found
        fresh = state.buttons & ~self._base
        self._base &= state.buttons  # tombol yang sudah dilepas boleh ditekan lagi
        if fresh:
            self.found = (fresh & -fresh).bit_length() - 1
        return self.found


# ---------------------------------------------------------------------------------------- store
def device_key(vid: int, pid: int, ordinal: int = 0) -> str:
    base = f"{vid:04X}:{pid:04X}"
    return base if ordinal == 0 else f"{base}#{ordinal + 1}"


@dataclass
class DeviceSettings:
    role: str = ROLE_OTHER
    wheel: WheelUsbConfig = field(default_factory=WheelUsbConfig)
    handbrake: HandbrakeConfig = field(default_factory=HandbrakeConfig)
    shifter: ShifterConfig = field(default_factory=ShifterConfig)

    def to_dict(self) -> dict:
        return {"role": self.role, "wheel": self.wheel.to_dict(), "handbrake": self.handbrake.to_dict(),
                "shifter": self.shifter.to_dict()}

    @classmethod
    def from_dict(cls, d) -> "DeviceSettings":
        d = d if isinstance(d, dict) else {}
        return cls(role=d.get("role") if d.get("role") in ROLES else ROLE_OTHER,
                   wheel=WheelUsbConfig.from_dict(d.get("wheel")),
                   handbrake=HandbrakeConfig.from_dict(d.get("handbrake")),
                   shifter=ShifterConfig.from_dict(d.get("shifter")))
