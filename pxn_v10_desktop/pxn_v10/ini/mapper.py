"""INI <-> DeviceProfile mapping.

``extract`` reads (1) the native ``[PXN_V10:*]`` sections and (2) user-defined *bindings*, which
link any ``SECTION / KEY`` of a foreign INI (for example ``FFB_TWEAKS:CUSTOM_SOFT_LOCK / DAMPER``)
to a wheel parameter with a linear scale. ``apply_to_profile`` overlays the result on a base profile
so a preset that only defines some parameters leaves the others untouched.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from ..core import constants as C
from ..core.ffb_advanced import LUT_PRESETS, FfbAdvanced, lut_name
from ..core.keycodes import key_code, key_name
from ..core.models import DeviceProfile
from . import schema as S
from .document import IniDocument


# --------------------------------------------------------------------------- bindings
@dataclass
class Binding:
    section: str
    key: str
    target: str  # one of schema.SCALAR_TARGETS
    in_min: float = 0.0
    in_max: float = 1.0
    out_min: float = 0.0
    out_max: float = 100.0
    invert: bool = False
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Binding":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    def convert(self, raw: float) -> float:
        span = self.in_max - self.in_min
        t = 0.0 if span == 0 else (raw - self.in_min) / span
        t = max(0.0, min(1.0, t))
        if self.invert:
            t = 1.0 - t
        return self.out_min + t * (self.out_max - self.out_min)


# ---------------------------------------------------------------------------- result
@dataclass
class ResolvedItem:
    field: str  # scalar id, "keymap:12", "curve:acc:1" ...
    label: str
    value: object
    source: str
    note: str = ""


@dataclass
class IniResult:
    items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    name: Optional[str] = None
    mode: Optional[int] = None
    platform: Optional[int] = None
    scalars: dict = field(default_factory=dict)
    keymap: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)  # name -> list of 4 [x, y]
    native: bool = False
    ffb_adv: Optional[FfbAdvanced] = None  # [PXN_V10:FFB_ADV]

    @property
    def empty(self) -> bool:
        return not (self.scalars or self.keymap or self.curves or self.mode or self.ffb_adv)

    def __len__(self) -> int:
        return len(self.items)


# ---------------------------------------------------------------------------- parsing helpers
def _to_number(text: str) -> Optional[float]:
    t = text.strip().strip("'\"").rstrip("%").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _to_bool(text: str) -> Optional[int]:
    t = text.strip().strip("'\"").lower()
    if t in S.BOOL_TRUE:
        return 1
    if t in S.BOOL_FALSE:
        return 0
    n = _to_number(t)
    return None if n is None else (1 if n else 0)


def parse_mode(text: str) -> Optional[int]:
    t = text.strip().strip("'\"")
    if t.isdigit():
        n = int(t)
        return n if n in C.MODE_NAMES else None
    return S.MODE_ALIASES.get(t.upper().replace(" ", "_")) or S.MODE_ALIASES.get(t.upper())


def parse_point(text: str) -> Optional[list]:
    parts = re.split(r"[,;:\s]+", text.strip().strip("'\""))
    parts = [p for p in parts if p]
    if len(parts) != 2:
        return None
    x, y = _to_number(parts[0]), _to_number(parts[1])
    return None if x is None or y is None else [int(round(x)), int(round(y))]


def _clamp(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(v))))


# ---------------------------------------------------------------------------- extraction
def is_native(doc: IniDocument) -> bool:
    return any(n.upper().startswith(S.GROUP + ":") or n.upper() == S.GROUP for n in doc.section_names())


def extract(doc: IniDocument, bindings: Iterable[Binding] = ()) -> IniResult:
    res = IniResult(native=is_native(doc))
    _extract_native(doc, res)
    _extract_bindings(doc, list(bindings), res)
    return res


def _set_scalar(res: IniResult, spec: S.ParamSpec, value: int, source: str, note: str = "") -> None:
    res.scalars[spec.id] = value
    res.items.append(ResolvedItem(spec.id, spec.label, value, source, note))


def _extract_native(doc: IniDocument, res: IniResult) -> None:
    g = S.SEC_GENERAL
    if doc.has(g, "NAME"):
        res.name = doc.get(g, "NAME", "").strip().strip("'\"") or None
    if doc.has(g, "MODE"):
        raw = doc.get(g, "MODE", "")
        mode = parse_mode(raw)
        if mode is None:
            res.warnings.append(f"{g}/MODE = '{raw}' bukan mode yang dikenal - diabaikan")
        else:
            res.mode = mode
            res.items.append(ResolvedItem("mode", S.PARAM_BY_ID["mode"].label, mode, f"{g}/MODE",
                                          C.MODE_NAMES.get(mode, "")))
    if doc.has(g, "PLATFORM"):
        n = _to_number(doc.get(g, "PLATFORM", ""))
        if n is not None and int(n) in C.PLATFORM_NAMES:
            res.platform = int(n)

    for spec in S.PARAMS:
        if spec.id == "mode" or not doc.has(spec.section, spec.key):
            continue
        raw = doc.get(spec.section, spec.key, "")
        source = f"{spec.section}/{spec.key}"
        if spec.kind == "bool":
            b = _to_bool(raw)
            if b is None:
                res.warnings.append(f"{source} = '{raw}' bukan nilai 0/1 - diabaikan")
                continue
            _set_scalar(res, spec, b, source)
            continue
        n = _to_number(raw)
        if n is None:
            res.warnings.append(f"{source} = '{raw}' bukan angka - diabaikan")
            continue
        value = _clamp(n, spec.lo, spec.hi)
        note = f"dibatasi ke {spec.lo}–{spec.hi}" if value != int(round(n)) else ""
        if note:
            res.warnings.append(f"{source} = {raw} {note}")
        _set_scalar(res, spec, value, source, note)

    # pedal curves
    for name, section in S.SEC_CURVES.items():
        sec = doc.section(section)
        if not sec:
            continue
        pts = _read_curve(doc, section, res)
        if pts is not None:
            fixed, note = _validate_curve(pts)
            if note:
                res.warnings.append(f"{section}: {note}")
            res.curves[name] = fixed
            res.items.append(ResolvedItem(f"curve:{name}", f"Kurva {S.CURVE_LABELS[name]}",
                                          " → ".join(f"({x},{y})" for x, y in fixed), section, note))

    _extract_ffb_adv(doc, res)

    # keymap
    sec = doc.section(S.SEC_KEYMAP)
    if sec:
        for entry in sec.items():
            phys, func = key_code(entry.key), key_code(entry.value)
            if phys is None or func is None:
                res.warnings.append(f"{S.SEC_KEYMAP}: '{entry.key}={entry.value}' tidak dikenali - diabaikan")
                continue
            res.keymap[phys] = func
            res.items.append(ResolvedItem(f"keymap:{phys}", f"Tombol {key_name(phys)}", key_name(func),
                                          f"{S.SEC_KEYMAP}/{entry.key}"))


def _parse_lut(text: str) -> Optional[list]:
    parts = [p for p in re.split(r"[,;\s]+", text.strip().strip("'\"")) if p]
    nums = [_to_number(p) for p in parts]
    if len(nums) != 5 or any(n is None for n in nums):
        return None
    return [_clamp(n, 0, 100) for n in nums]


def _extract_ffb_adv(doc: IniDocument, res: IniResult) -> None:
    sec_name = S.SEC_FFB_ADV
    if not doc.section(sec_name):
        return
    adv = FfbAdvanced()
    src = sec_name
    if doc.has(sec_name, "ENABLED"):
        b = _to_bool(doc.get(sec_name, "ENABLED", ""))
        if b is None:
            res.warnings.append(f"{src}/ENABLED bukan nilai 0/1 - diabaikan")
        else:
            adv.enabled = bool(b)
    if doc.has(sec_name, "LUT"):
        lut = _parse_lut(doc.get(sec_name, "LUT", ""))
        if lut is None:
            res.warnings.append(f"{src}/LUT harus berisi 5 angka (output untuk input 0,25,50,75,100 %) - diabaikan")
        else:
            adv.lut = lut
    for key, (attr, _label) in S.FFB_ADV_KEYS.items():
        if not doc.has(sec_name, key):
            continue
        raw = doc.get(sec_name, key, "")
        n = _to_number(raw)
        if n is None:
            res.warnings.append(f"{src}/{key} = '{raw}' bukan angka - diabaikan")
            continue
        if n < 0 or n > 100:
            res.warnings.append(f"{src}/{key} = {raw} dibatasi ke 0–100")
        setattr(adv, attr, _clamp(n, 0, 100))
    fixed = adv.copy().clamp()
    if fixed.lut != adv.lut:
        res.warnings.append(f"{src}/LUT diperbaiki agar naik monoton dan dimulai dari 0")
    res.ffb_adv = fixed
    res.items.append(ResolvedItem("ffb_adv:enabled", "FFB lanjutan", "ON" if fixed.enabled else "OFF", f"{src}/ENABLED"))
    res.items.append(ResolvedItem("ffb_adv:lut", "LUT FFB", ", ".join(str(v) for v in fixed.lut), f"{src}/LUT",
                                  LUT_PRESETS.get(lut_name(fixed.lut), ("Custom",))[0]))
    for key, (attr, label) in S.FFB_ADV_KEYS.items():
        if doc.has(sec_name, key):
            res.items.append(ResolvedItem(f"ffb_adv:{attr}", label, getattr(fixed, attr), f"{src}/{key}"))


def _read_curve(doc: IniDocument, section: str, res: IniResult) -> Optional[list]:
    pts: list = []
    for i in range(4):
        raw = doc.get(section, f"P{i}")
        if raw is not None:
            p = parse_point(raw)
        else:
            x, y = doc.get(section, f"X{i}"), doc.get(section, f"Y{i}")
            xn, yn = (_to_number(x), _to_number(y)) if x is not None and y is not None else (None, None)
            p = None if xn is None or yn is None else [int(round(xn)), int(round(yn))]
        if p is None:
            res.warnings.append(f"{section}: titik P{i} tidak ada / tidak valid - kurva diabaikan")
            return None
        pts.append(p)
    return pts


def _validate_curve(pts: list) -> tuple:
    """Clamp to the ADC/DAC ranges and keep the curve monotonic like the chart widget does."""
    note = ""
    fixed = [[_clamp(x, 0, C.CURVE_X_MAX), _clamp(y, 0, C.CURVE_Y_MAX)] for x, y in pts]
    if fixed != [list(map(int, p)) for p in pts]:
        note = "nilai dibatasi ke 0–4095 / 0–65535"
    for i in range(1, 4):
        if fixed[i][0] < fixed[i - 1][0] or fixed[i][1] < fixed[i - 1][1]:
            fixed[i][0] = max(fixed[i][0], fixed[i - 1][0])
            fixed[i][1] = max(fixed[i][1], fixed[i - 1][1])
            note = (note + "; " if note else "") + "titik harus naik (diperbaiki)"
    return fixed, note


def _extract_bindings(doc: IniDocument, bindings: list, res: IniResult) -> None:
    for b in bindings:
        if not b.enabled:
            continue
        raw = doc.get(b.section, b.key)
        if raw is None:
            continue
        spec = S.PARAM_BY_ID.get(b.target)
        if spec is None:
            res.warnings.append(f"Binding {b.section}/{b.key}: target '{b.target}' tidak dikenal")
            continue
        source = f"binding {b.section}/{b.key}"
        if spec.kind == "bool":
            v = _to_bool(raw)
            if v is None:
                res.warnings.append(f"{source} = '{raw}' bukan nilai boolean")
                continue
            _set_scalar(res, spec, 1 - v if b.invert else v, source)
            continue
        if spec.kind == "mode":
            mode = parse_mode(raw)
            if mode is None:
                res.warnings.append(f"{source} = '{raw}' bukan mode yang dikenal")
                continue
            res.mode = mode
            res.items.append(ResolvedItem("mode", spec.label, mode, source, C.MODE_NAMES.get(mode, "")))
            continue
        n = _to_number(raw)
        if n is None:
            res.warnings.append(f"{source} = '{raw}' bukan angka")
            continue
        value = _clamp(b.convert(n), spec.lo, spec.hi)
        _set_scalar(res, spec, value, source, f"{raw} → {value}")


# ---------------------------------------------------------------------------- apply / export
def apply_to_profile(res: IniResult, base: DeviceProfile) -> DeviceProfile:
    """Overlay everything the INI defined on a copy of ``base``."""
    out = base.copy()
    for field_id, value in res.scalars.items():
        setattr(out, field_id, value)
    for phys, func in res.keymap.items():
        out.keymap[phys] = func
    for name, pts in res.curves.items():
        out.set_curve(name, pts)
    return out.clamp()


def profile_to_doc(
    profile: DeviceProfile,
    mode: int,
    name: str = "",
    platform: int | None = None,
    base: IniDocument | None = None,
    ffb_adv: FfbAdvanced | None = None,
) -> IniDocument:
    """Write the wheel configuration as native sections. When ``base`` is given (a foreign INI)
    all its sections are kept and only the ``[PXN_V10:*]`` sections are added / replaced."""
    doc = base.copy() if base is not None else IniDocument()
    for sec_name in [s for s in doc.section_names() if s.upper().startswith(S.GROUP + ":")]:
        doc.delete(sec_name)
    cfg = doc.section("CONFIGURATION", create=True)
    if cfg is not None and base is None:
        doc.set("CONFIGURATION", "VERSION", "1")
    if doc.has("CONFIGURATION", "AFFECTED_SECTIONS"):
        groups = [g for g in doc.get("CONFIGURATION", "AFFECTED_SECTIONS", "").split(",") if g.strip()]
        if S.GROUP not in groups:
            groups.append(S.GROUP)
        doc.set("CONFIGURATION", "AFFECTED_SECTIONS", ",".join(groups))
    else:
        doc.set("CONFIGURATION", "AFFECTED_SECTIONS", S.GROUP)
    # CONFIGURATION must be the first section (CSP convention)
    cfg = doc.section("CONFIGURATION")
    if cfg in doc.sections:
        doc.sections.remove(cfg)
        doc.sections.insert(0, cfg)

    p = profile.copy().clamp()
    g = S.SEC_GENERAL
    if name:
        doc.set(g, "NAME", name)
    doc.set(g, "MODE", str(mode))
    doc.set(g, "PLATFORM", str(platform or C.platform_by_mode(mode)))
    for spec in S.PARAMS:
        if spec.id == "mode":
            continue
        doc.set(spec.section, spec.key, str(int(getattr(p, spec.id))))
    if ffb_adv is not None:
        a = ffb_adv.copy().clamp()
        doc.set(S.SEC_FFB_ADV, "ENABLED", "1" if a.enabled else "0")
        doc.set(S.SEC_FFB_ADV, "LUT", ",".join(str(v) for v in a.lut))
        for key, (attr, _label) in S.FFB_ADV_KEYS.items():
            doc.set(S.SEC_FFB_ADV, key, str(int(getattr(a, attr))))
    for cname, section in S.SEC_CURVES.items():
        for i, (x, y) in enumerate(p.curve(cname)):
            doc.set(section, f"P{i}", f"{x},{y}")
    doc.section(S.SEC_KEYMAP, create=True)
    for phys, func in sorted(p.custom_mappings().items()):
        doc.set(S.SEC_KEYMAP, key_name(phys), key_name(func))
    return doc


def diff_against(res: IniResult, current: DeviceProfile, current_mode: int,
                 current_adv: FfbAdvanced | None = None) -> list:
    """Rows for the preview table: (label, current, new, source, changed)."""
    rows = []
    for item in res.items:
        cur: object = "—"
        if item.field.startswith("ffb_adv:"):
            attr = item.field.split(":")[1]
            new = item.value
            if current_adv is not None:
                if attr == "enabled":
                    cur = "ON" if current_adv.enabled else "OFF"
                elif attr == "lut":
                    cur = ", ".join(str(v) for v in current_adv.lut)
                else:
                    cur = getattr(current_adv, attr)
            rows.append((item.label, str(cur), str(new), item.source, str(cur) != str(new)))
            continue
        if item.field == "mode":
            cur = C.MODE_NAMES.get(current_mode, current_mode)
            new: object = C.MODE_NAMES.get(item.value, item.value)
        elif item.field.startswith("keymap:"):
            code = int(item.field.split(":")[1])
            cur = key_name(current.mapped(code))
            new = item.value
        elif item.field.startswith("curve:"):
            name = item.field.split(":")[1]
            cur = " → ".join(f"({x},{y})" for x, y in current.curve(name))
            new = item.value
        else:
            cur = getattr(current, item.field)
            new = item.value
            if item.field == "ffb_reverse":
                cur, new = ("ON" if cur else "OFF"), ("ON" if new else "OFF")
        rows.append((item.label, str(cur), str(new), item.source, str(cur) != str(new)))
    return rows
