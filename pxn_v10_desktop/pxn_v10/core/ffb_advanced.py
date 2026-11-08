"""Parameter force feedback lanjutan (LUT, smoothing, pneumatic/mechanical trail, road/slip/kerb)
dan penerjemahannya ke parameter yang benar-benar dimengerti firmware PXN V10.

Firmware V10 hanya punya: FFB (kekuatan), SPRING, DAMPING, FRICTION, INERTIA, ANGLE dan REVERSE.
Parameter lanjutan di bawah ini adalah model pemrosesan FFB tingkat game/driver yang TIDAK ada di
firmware, jadi ia tidak bisa dikirim apa adanya. ``compile_to_wheel`` menerjemahkannya menjadi
perubahan pada parameter firmware dengan rumus yang transparan (lihat ``COEFFICIENTS``) dan
mengembalikan daftar kontribusi supaya UI bisa menampilkan persis apa yang dikirim dan kenapa.
Hasilnya adalah *perkiraan*, bukan pemrosesan sinyal FFB di dalam setir.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from . import constants as C
from .models import DeviceProfile

LUT_INPUTS = (0, 25, 50, 75, 100)  # titik input (% gaya dari game)

# Bentuk LUT bawaan: nilai output (%) pada LUT_INPUTS
LUT_PRESETS: dict = {
    "linear": ("Linear (1:1)", (0, 25, 50, 75, 100)),
    "soft": ("Progresif (lembut di gaya kecil)", (0, 15, 38, 66, 100)),
    "detail": ("Detail boost (gaya kecil lebih terasa)", (0, 38, 62, 82, 100)),
    "anticlip": ("Anti-clipping (puncak dikompresi)", (0, 28, 55, 78, 92)),
    "compress": ("Kompresi dinamis", (0, 40, 64, 80, 90)),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lut_name(points: list) -> str:
    """Nama preset bila ``points`` sama persis dengan salah satunya, selain itu 'custom'."""
    for key, (_title, vals) in LUT_PRESETS.items():
        if list(vals) == [int(p) for p in points]:
            return key
    return "custom"


@dataclass
class FfbAdvanced:
    """Pengaturan FFB lanjutan. Semua 0..100 (%), kecuali ``lut`` (5 nilai output untuk LUT_INPUTS)."""

    enabled: bool = True
    lut: list = field(default_factory=lambda: list(LUT_PRESETS["linear"][1]))
    smoothing: int = 0  # 0 = mati
    pneumatic_trail: int = 50  # 50 = netral
    mechanical_trail: int = 50  # 50 = netral
    road_effect: int = 0
    slip_effect: int = 0
    kerb_effect: int = 0

    # ---------------------------------------------------------------- sanity
    def clamp(self) -> "FfbAdvanced":
        vals = [int(_clamp(v, 0, 100)) for v in (list(self.lut) + [0] * 5)[:5]]
        vals[0] = 0  # tanpa gaya masuk tidak boleh ada gaya keluar
        for i in range(1, 5):  # LUT tidak boleh turun (output tidak berbalik arah)
            vals[i] = max(vals[i], vals[i - 1])
        self.lut = vals
        for name in ("smoothing", "pneumatic_trail", "mechanical_trail", "road_effect", "slip_effect", "kerb_effect"):
            setattr(self, name, int(_clamp(getattr(self, name), 0, 100)))
        self.enabled = bool(self.enabled)
        return self

    def copy(self) -> "FfbAdvanced":
        return FfbAdvanced(**{**asdict(self), "lut": list(self.lut)})

    def is_neutral(self) -> bool:
        return self.copy().clamp() == FfbAdvanced()

    # ---------------------------------------------------------------- LUT
    def lut_value(self, force_pct: float) -> float:
        """Output (%) untuk input ``force_pct`` (%), interpolasi linear antar titik."""
        pts = self.copy().clamp().lut
        x = _clamp(force_pct, 0, 100)
        for i in range(4):
            x0, x1 = LUT_INPUTS[i], LUT_INPUTS[i + 1]
            if x <= x1:
                t = (x - x0) / (x1 - x0)
                return pts[i] + (pts[i + 1] - pts[i]) * t
        return float(pts[4])

    def lut_gain(self) -> float:
        """Penskalaan gaya rata-rata (1.0 = linear): luas di bawah kurva LUT dibanding garis lurus."""
        pts = self.copy().clamp().lut
        area = sum((pts[i] + pts[i + 1]) / 2 * (LUT_INPUTS[i + 1] - LUT_INPUTS[i]) for i in range(4))
        return area / (100 * 100 / 2)

    # ---------------------------------------------------------------- (de)serialisasi
    def to_dict(self) -> dict:
        d = asdict(self.copy().clamp())
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FfbAdvanced":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known).clamp()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "FfbAdvanced | None":
        if not text:
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return cls.from_dict(data) if isinstance(data, dict) else None


# ---------------------------------------------------------------------------- terjemahan ke firmware
# koefisien (poin firmware per poin parameter lanjutan). Dasarnya adalah keterangan tiap slider di
# aplikasi asli (lihat HINTS di config_editor): friction = "detail permukaan jalan, benturan",
# damping = "meredam laju putar / terasa lebih berat", spring = "gaya pemulih ke tengah",
# inertia = "kelembaman / beban setir".
COEFFICIENTS = {
    "smoothing→damping": 0.35,
    "smoothing→inertia": 0.10,
    "road→friction": 0.30,
    "kerb→friction": 0.20,
    "slip→friction": 0.15,
    "slip→damping": -0.10,
    "pneumatic→spring": 0.40,  # (nilai-50) × koef
    "mechanical→inertia": 0.40,  # (nilai-50) × koef
    "mechanical→damping": 0.15,  # (nilai-50) × koef
}


@dataclass
class Contribution:
    param: str  # ffb | spring | damping | friction | inertia
    source: str  # nama parameter lanjutan
    delta: float
    explanation: str


@dataclass
class CompileResult:
    profile: DeviceProfile
    base: DeviceProfile
    contributions: list = field(default_factory=list)
    applied: bool = True
    note: str = ""

    def delta(self, param: str) -> int:
        return int(getattr(self.profile, param)) - int(getattr(self.base, param))

    def contributions_for(self, param: str) -> list:
        return [c for c in self.contributions if c.param == param]


PARAM_LABELS = {"ffb": "Force feedback", "spring": "Spring", "damping": "Damping", "friction": "Friction",
                "inertia": "Inertia"}


def compile_to_wheel(base: DeviceProfile, adv: FfbAdvanced | None, mode: int = C.MODE_PC_DINPUT) -> CompileResult:
    """Terapkan ``adv`` di atas ``base`` dan hasilkan profil yang dikirim ke firmware.

    ``base`` tidak diubah. Hanya FFB (+ 4 gaya fisika bila mode mendukungnya) yang disentuh; angle,
    reverse, keymap dan kurva pedal selalu dibawa apa adanya.
    """
    base = base.copy().clamp()
    out = base.copy()
    if adv is None or not adv.enabled:
        return CompileResult(out, base, [], applied=False, note="FFB lanjutan nonaktif - nilai dasar dikirim apa adanya.")
    a = adv.copy().clamp()
    contrib: list = []
    K = COEFFICIENTS

    def add(param: str, source: str, delta: float, why: str) -> None:
        if abs(delta) >= 0.05:
            contrib.append(Contribution(param, source, delta, why))

    # 1) LUT -> penskalaan kekuatan FFB (rata-rata luas kurva); puncak LUT membatasi pula gain maksimum
    gain = a.lut_gain()
    ffb_target = base.ffb * gain
    if abs(ffb_target - base.ffb) >= 0.05:
        add("ffb", "LUT", ffb_target - base.ffb,
            f"Rata-rata kurva LUT = {gain * 100:.0f}% dari linear → kekuatan FFB diskalakan sebesar itu")
    forces: dict = {}
    forces["ffb"] = ffb_target

    force_mode = mode in C.FORCE_MODES
    if force_mode:
        spring, damping, friction, inertia = float(base.spring), float(base.damping), float(base.friction), float(base.inertia)

        d = K["smoothing→damping"] * a.smoothing
        damping += d
        add("damping", "Smoothing", d, "Filter lonjakan: peredaman menahan perubahan gaya yang terlalu cepat")
        d = K["smoothing→inertia"] * a.smoothing
        inertia += d
        add("inertia", "Smoothing", d, "Sedikit kelembaman tambahan agar perubahan arah gaya tidak kasar")

        d = K["road→friction"] * a.road_effect
        friction += d
        add("friction", "Road effect", d, "Friction = detail permukaan jalan (sesuai keterangan slider di aplikasi asli)")
        d = K["kerb→friction"] * a.kerb_effect
        friction += d
        add("friction", "Kerb effect", d, "Benturan kerb/bump ditampilkan lewat detail friction")
        d = K["slip→friction"] * a.slip_effect
        friction += d
        add("friction", "Slip effect", d, "Getaran saat ban selip ikut lewat kanal detail")
        d = K["slip→damping"] * a.slip_effect
        damping += d
        add("damping", "Slip effect", d, "Kemudi sedikit lebih bebas saat selip supaya pelepasan grip terasa")

        d = K["pneumatic→spring"] * (a.pneumatic_trail - 50)
        spring += d
        add("spring", "Pneumatic trail", d, "Pneumatic trail tinggi = gaya pemulih (self-aligning) lebih jelas, "
                                            "hilangnya gaya ini terasa saat understeer")
        d = K["mechanical→inertia"] * (a.mechanical_trail - 50)
        inertia += d
        add("inertia", "Mechanical trail", d, "Mechanical trail (caster) = bobot setir yang naik bersama sudut")
        d = K["mechanical→damping"] * (a.mechanical_trail - 50)
        damping += d
        add("damping", "Mechanical trail", d, "Stabilitas arah dari geometri kemudi")
        forces.update(spring=spring, damping=damping, friction=friction, inertia=inertia)

    for name, value in forces.items():
        setattr(out, name, int(round(_clamp(value, 0, 100))))
    note = ""
    if not force_mode:
        note = (f"Mode {C.MODE_NAMES.get(mode, mode)} tidak mendukung gaya fisika (Spring/Damping/Friction/Inertia): "
                "hanya kekuatan FFB yang dapat disesuaikan, efek lainnya hanya disimpan.")
    # catat batas 0..100 yang menyebabkan nilai tidak mencapai target
    for name in forces:
        want = forces[name]
        got = getattr(out, name)
        if want > 100.5 or want < -0.5:
            contrib.append(Contribution(name, "Batas", got - want,
                                        f"Hasil {want:.0f} dibatasi ke {got} (rentang firmware 0–100)"))
    return CompileResult(out, base, contrib, applied=True, note=note)


def firmware_coverage(adv: FfbAdvanced, mode: int = C.MODE_PC_DINPUT) -> list:
    """Baris (parameter lanjutan, nilai, dikirim ke firmware sebagai, status) untuk tampilan UI."""
    force = mode in C.FORCE_MODES
    rows = [
        ("LUT", LUT_PRESETS.get(lut_name(adv.lut), ("Custom",))[0], "FFB (penskalaan rata-rata)", "perkiraan"),
        ("Smoothing", f"{adv.smoothing}%", "DAMPING + INERTIA" if force else "—", "perkiraan" if force else "tersimpan"),
        ("Pneumatic trail", f"{adv.pneumatic_trail}%", "SPRING" if force else "—", "perkiraan" if force else "tersimpan"),
        ("Mechanical trail", f"{adv.mechanical_trail}%", "INERTIA + DAMPING" if force else "—",
         "perkiraan" if force else "tersimpan"),
        ("Road effect", f"{adv.road_effect}%", "FRICTION" if force else "—", "perkiraan" if force else "tersimpan"),
        ("Slip effect", f"{adv.slip_effect}%", "FRICTION + DAMPING" if force else "—",
         "perkiraan" if force else "tersimpan"),
        ("Kerb effect", f"{adv.kerb_effect}%", "FRICTION" if force else "—", "perkiraan" if force else "tersimpan"),
    ]
    return rows
