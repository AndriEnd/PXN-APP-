"""Template mode: Drift, Race, Daily, Rally, F1 270° dan Custom, masing-masing dengan tiga level
(Beginner / Advanced / Pro).

Nilai adalah *titik awal racikan* berdasarkan praktik umum sim racing (sudut kunci per jenis mobil,
semakin pro semakin sedikit peredaman/smoothing sehingga detail dan beban setir lebih jujur,
efek slip/kerb disesuaikan dengan karakter permukaan). Ini BUKAN data pabrikan PXN dan belum diuji
pada setir fisik - setel ulang sesuai selera dan game. Nilai di sini adalah nilai DASAR; saat
dikirim, ``ffb_advanced.compile_to_wheel`` menambahkan kontribusi parameter lanjutan.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import constants as C
from .ffb_advanced import LUT_PRESETS, FfbAdvanced
from .models import DeviceProfile

LEVELS = ("beginner", "advanced", "pro")
LEVEL_TITLES = {"beginner": "Beginner", "advanced": "Advanced", "pro": "Pro"}
LEVEL_BLURBS = {
    "beginner": "Pemaaf: lebih banyak peredaman & smoothing, FFB tidak terlalu keras, mudah dikontrol.",
    "advanced": "Seimbang: detail jalan jelas, peredaman sedang untuk pengemudi yang sudah terbiasa.",
    "pro": "Telanjang: smoothing minimal, gaya kuat dan detail penuh. Menuntut kontrol yang presisi.",
}


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    level: str
    title: str
    angle: int
    ffb: int
    spring: int
    damping: int
    friction: int
    inertia: int
    lut: str  # kunci LUT_PRESETS
    smoothing: int
    pneumatic: int
    mechanical: int
    road: int
    slip: int
    kerb: int
    note: str = ""

    def base_profile(self, reverse: int = 0) -> DeviceProfile:
        return DeviceProfile(angle=self.angle, ffb=self.ffb, spring=self.spring, damping=self.damping,
                             friction=self.friction, inertia=self.inertia, ffb_reverse=reverse).clamp()

    def advanced(self) -> FfbAdvanced:
        return FfbAdvanced(enabled=True, lut=list(LUT_PRESETS[self.lut][1]), smoothing=self.smoothing,
                           pneumatic_trail=self.pneumatic, mechanical_trail=self.mechanical,
                           road_effect=self.road, slip_effect=self.slip, kerb_effect=self.kerb).clamp()

    @property
    def name(self) -> str:
        return f"{self.title} — {LEVEL_TITLES[self.level]}"


@dataclass(frozen=True)
class TemplateGroup:
    key: str
    title: str
    subtitle: str
    description: str
    rationale: dict  # level -> alasan singkat


def _s(key, level, title, vals, lut, adv, note=""):
    angle, ffb, spring, damping, friction, inertia = vals
    smoothing, pneu, mech, road, slip, kerb = adv
    return TemplateSpec(key, level, title, angle, ffb, spring, damping, friction, inertia, lut,
                        smoothing, pneu, mech, road, slip, kerb, note)


GROUPS: tuple = (
    TemplateGroup(
        "drift", "Drift", "Counter-steer cepat, sudut besar",
        "Setir harus kembali ke tengah cepat tetapi tidak berosilasi saat flick. Spring tinggi untuk pemulihan, "
        "friction rendah supaya counter-steer bebas, slip effect tinggi agar pelepasan grip belakang terasa.",
        {"beginner": "Sudut 720° (lebih cepat dijangkau), peredaman tinggi supaya tidak berosilasi, LUT progresif "
                     "menjinakkan puncak gaya.",
         "advanced": "900° penuh, peredaman sedang, slip effect dinaikkan untuk membaca pelepasan grip.",
         "pro": "900°, peredaman rendah, LUT detail boost: gaya kecil (batas traksi) terasa jelas."}),
    TemplateGroup(
        "race", "Race", "GT / touring / sirkuit",
        "Presisi di batas grip. Sudut mengecil sesuai mobil balap (GT3 ≈ 540°), detail jalan & kerb jelas, "
        "peredaman turun mengikuti level agar beban ban depan terbaca.",
        {"beginner": "900° memaafkan, FFB 65%, smoothing 40 meredam lonjakan kerb.",
         "advanced": "720°, detail kerb lebih jelas, smoothing sedang.",
         "pro": "540° ala GT3, peredaman rendah, smoothing minimum, LUT detail boost."}),
    TemplateGroup(
        "daily", "Daily", "Mobil harian / kota / truk",
        "Nyaman dan stabil untuk sesi panjang: FFB lembut, pemulihan kuat seperti power steering, "
        "peredaman & smoothing tinggi, efek jalan tipis agar tidak melelahkan.",
        {"beginner": "FFB 45%, smoothing tinggi, pemulihan kuat: lurus & nyaman.",
         "advanced": "FFB 55%, sedikit lebih banyak informasi jalan.",
         "pro": "FFB 65%, smoothing lebih rendah untuk pengemudi yang ingin lebih banyak rasa."}),
    TemplateGroup(
        "rally", "Rally", "Aspal/kerikil/salju",
        "Permukaan licin dan tidak rata: road & kerb effect tinggi, slip effect tinggi untuk membaca slide, "
        "LUT anti-clipping agar benturan keras tidak membuat motor setir saturasi.",
        {"beginner": "900° dengan smoothing 45: lompatan kasar diredam.",
         "advanced": "720°, LUT anti-clipping, efek jalan kuat.",
         "pro": "640°, FFB 88%, smoothing rendah tetapi puncak tetap dikompresi agar tidak clipping."}),
    TemplateGroup(
        "f1", "F1 270°", "Open-wheel, sudut 270°",
        "Sudut kunci tetap 270° (stir F1 asli ≈ 270°–360°). Sudut kecil sangat sensitif: peredaman moderat "
        "mencegah osilasi, pneumatic trail tinggi agar kehilangan grip depan (understeer) terasa jelas.",
        {"beginner": "270°, FFB 60%, peredaman tinggi untuk menstabilkan sudut sempit.",
         "advanced": "270°, FFB 75%, pneumatic trail dinaikkan.",
         "pro": "270°, FFB 88%, peredaman rendah, pneumatic trail 75: understeer terbaca jelas."}),
)
GROUP_BY_KEY = {g.key: g for g in GROUPS}
CUSTOM_KEY = "custom"

_SPECS: dict = {}


def _register(*specs: TemplateSpec) -> None:
    for s in specs:
        _SPECS[(s.key, s.level)] = s


#          key     level       judul       (angle ffb spring damp fric inert)  lut        (smooth pneu mech road slip kerb)
_register(
    _s("drift", "beginner", "Drift", (720, 70, 75, 55, 25, 35), "soft", (35, 60, 55, 20, 55, 15)),
    _s("drift", "advanced", "Drift", (900, 80, 65, 40, 20, 30), "linear", (20, 65, 55, 25, 65, 20)),
    _s("drift", "pro", "Drift", (900, 90, 55, 28, 15, 25), "detail", (10, 70, 50, 30, 70, 20)),
    _s("race", "beginner", "Race", (900, 65, 60, 50, 35, 45), "soft", (40, 55, 55, 30, 40, 30)),
    _s("race", "advanced", "Race", (720, 75, 50, 40, 28, 40), "linear", (25, 60, 55, 40, 50, 35)),
    _s("race", "pro", "Race", (540, 85, 40, 30, 20, 35), "detail", (12, 65, 60, 45, 55, 40)),
    _s("daily", "beginner", "Daily", (900, 45, 80, 65, 45, 60), "soft", (55, 45, 50, 20, 20, 10)),
    _s("daily", "advanced", "Daily", (900, 55, 70, 55, 40, 55), "soft", (45, 50, 50, 25, 25, 15)),
    _s("daily", "pro", "Daily", (900, 65, 60, 45, 35, 50), "linear", (35, 55, 55, 30, 30, 20)),
    _s("rally", "beginner", "Rally", (900, 70, 65, 55, 40, 50), "soft", (45, 55, 60, 55, 60, 45)),
    _s("rally", "advanced", "Rally", (720, 80, 55, 45, 32, 45), "anticlip", (35, 60, 60, 60, 65, 50)),
    _s("rally", "pro", "Rally", (640, 88, 45, 35, 25, 40), "anticlip", (25, 65, 65, 65, 70, 55)),
    _s("f1", "beginner", "F1 270°", (270, 60, 55, 55, 30, 30), "soft", (40, 60, 55, 15, 45, 35)),
    _s("f1", "advanced", "F1 270°", (270, 75, 45, 42, 22, 25), "linear", (22, 68, 60, 20, 55, 40)),
    _s("f1", "pro", "F1 270°", (270, 88, 35, 30, 15, 20), "detail", (10, 75, 65, 25, 60, 45)),
)


def custom_spec(base: DeviceProfile | None = None) -> TemplateSpec:
    """Mode custom: mulai dari nilai netral (atau dari ``base`` bila diberikan)."""
    b = base or DeviceProfile(angle=900, ffb=70, spring=50, damping=50, friction=50, inertia=50)
    return TemplateSpec(CUSTOM_KEY, "advanced", "Custom", b.angle, b.ffb, b.spring, b.damping, b.friction,
                        b.inertia, "linear", 0, 50, 50, 0, 0, 0, "Mode custom: atur semuanya sendiri.")


def get_template(key: str, level: str = "advanced") -> TemplateSpec:
    if key == CUSTOM_KEY:
        return custom_spec()
    return _SPECS[(key, level)]


def all_templates() -> list:
    return [_SPECS[(g.key, lv)] for g in GROUPS for lv in LEVELS]


def template_game_profile_name(spec: TemplateSpec) -> str:
    return f"Template {spec.name}"


def template_mode(spec: TemplateSpec) -> int:
    """Semua template dirancang untuk D-Input (satu-satunya mode PC yang punya gaya fisika)."""
    return C.MODE_PC_DINPUT
