"""FFB lanjutan, template mode, integrasi INI + database."""

import sqlite3

import pytest

from pxn_v10.core import constants as C
from pxn_v10.core.ffb_advanced import (
    COEFFICIENTS, LUT_PRESETS, FfbAdvanced, compile_to_wheel, firmware_coverage, lut_name)
from pxn_v10.core.models import DeviceProfile
from pxn_v10.core.templates import GROUPS, LEVELS, all_templates, get_template
from pxn_v10.ini import mapper as M
from pxn_v10.ini import schema as S
from pxn_v10.ini.document import IniDocument
from pxn_v10.storage.database import GameProfile, ProfileDatabase


def base():
    return DeviceProfile(angle=720, ffb=70, spring=50, damping=50, friction=50, inertia=50)


# ------------------------------------------------------------------------------------ model
def test_neutral_settings_change_nothing():
    res = compile_to_wheel(base(), FfbAdvanced())
    assert res.profile == base() and res.contributions == [] and res.applied


def test_disabled_or_missing_returns_base_untouched():
    adv = FfbAdvanced(smoothing=100, road_effect=100)
    adv.enabled = False
    for a in (adv, None):
        res = compile_to_wheel(base(), a)
        assert res.profile == base() and not res.applied


def test_each_effect_moves_the_documented_firmware_parameter():
    r = compile_to_wheel(base(), FfbAdvanced(smoothing=40)).profile
    assert r.damping == 50 + round(COEFFICIENTS["smoothing→damping"] * 40) and r.inertia > 50
    r = compile_to_wheel(base(), FfbAdvanced(road_effect=50, kerb_effect=50, slip_effect=50)).profile
    assert r.friction == 50 + round(50 * (0.30 + 0.20 + 0.15))  # friction = detail permukaan
    assert r.damping < 50  # slip effect melonggarkan kemudi
    r = compile_to_wheel(base(), FfbAdvanced(pneumatic_trail=80)).profile
    assert r.spring == 50 + round(0.40 * 30)
    r = compile_to_wheel(base(), FfbAdvanced(mechanical_trail=20)).profile
    assert r.inertia < 50 and r.damping < 50


def test_lut_scales_ffb_by_curve_area():
    assert FfbAdvanced().lut_gain() == pytest.approx(1.0)
    soft = FfbAdvanced(lut=list(LUT_PRESETS["soft"][1]))
    assert soft.lut_gain() < 1.0
    assert compile_to_wheel(base(), soft).profile.ffb == round(70 * soft.lut_gain())
    boost = FfbAdvanced(lut=list(LUT_PRESETS["detail"][1]))
    assert compile_to_wheel(DeviceProfile(ffb=95), boost).profile.ffb == 100  # dibatasi firmware
    assert FfbAdvanced().lut_value(40) == pytest.approx(40)
    assert soft.lut_value(100) == 100 and soft.lut_value(0) == 0


def test_lut_is_sanitised_monotonic_from_zero():
    a = FfbAdvanced(lut=[10, 80, 30, 120, -5]).clamp()
    assert a.lut[0] == 0 and a.lut == sorted(a.lut) and max(a.lut) <= 100
    assert lut_name(LUT_PRESETS["soft"][1]) == "soft" and lut_name([0, 1, 2, 3, 4]) == "custom"


def test_results_stay_inside_firmware_ranges_and_keep_other_fields():
    p = base()
    p.ffb_reverse = 1
    p.keymap[12] = 13
    p.brake_curve = [[0, 0], [1000, 2000], [2000, 3000], [4095, 65535]]
    worst = FfbAdvanced(smoothing=100, road_effect=100, slip_effect=100, kerb_effect=100, pneumatic_trail=100,
                        mechanical_trail=100)
    res = compile_to_wheel(DeviceProfile(spring=95, damping=95, friction=95, inertia=95), worst)
    for n in ("ffb", "spring", "damping", "friction", "inertia"):
        assert 0 <= getattr(res.profile, n) <= 100
    assert any(c.source == "Batas" for c in res.contributions)
    out = compile_to_wheel(p, worst).profile
    assert (out.angle, out.ffb_reverse, out.keymap, out.brake_curve) == (p.angle, 1, p.keymap, p.brake_curve)
    assert p.damping == 50  # input tidak diubah


def test_non_force_modes_only_adjust_ffb():
    adv = FfbAdvanced(lut=list(LUT_PRESETS["soft"][1]), smoothing=80, road_effect=80)
    res = compile_to_wheel(base(), adv, C.MODE_PC_XINPUT)
    assert (res.profile.damping, res.profile.friction) == (50, 50) and res.profile.ffb != 70 and res.note
    assert all(r[3] == "tersimpan" for r in firmware_coverage(adv, C.MODE_PC_XINPUT)[1:])
    assert all(r[3] == "perkiraan" for r in firmware_coverage(adv))


def test_json_roundtrip_and_garbage():
    a = FfbAdvanced(smoothing=33, lut=list(LUT_PRESETS["anticlip"][1]), kerb_effect=44)
    assert FfbAdvanced.from_json(a.to_json()) == a
    assert FfbAdvanced.from_json("") is None and FfbAdvanced.from_json("{oops") is None
    assert FfbAdvanced.from_json("[1,2]") is None


# --------------------------------------------------------------------------------- templates
def test_fifteen_templates_plus_custom_all_valid():
    specs = all_templates()
    assert len(specs) == len(GROUPS) * len(LEVELS) == 15
    assert {g.key for g in GROUPS} == {"drift", "race", "daily", "rally", "f1"}
    for s in specs:
        assert C.ANGLE_MIN <= s.angle <= C.ANGLE_MAX and s.angle % 10 == 0
        for v in (s.ffb, s.spring, s.damping, s.friction, s.inertia, s.smoothing, s.pneumatic, s.mechanical,
                  s.road, s.slip, s.kerb):
            assert 0 <= v <= 100
        assert s.lut in LUT_PRESETS
        out = compile_to_wheel(s.base_profile(), s.advanced()).profile
        assert out.clamp() == out
    custom = get_template("custom")
    assert custom.key == "custom" and custom.advanced().is_neutral()


def test_f1_is_270_degrees_for_every_level():
    assert [get_template("f1", lv).angle for lv in LEVELS] == [270, 270, 270]


def test_levels_follow_the_documented_trend():
    for g in GROUPS:
        b, a, p = (get_template(g.key, lv) for lv in LEVELS)
        assert b.smoothing > a.smoothing > p.smoothing, g.key  # makin pro makin sedikit smoothing
        assert b.damping > a.damping > p.damping, g.key
        assert b.ffb < a.ffb < p.ffb, g.key  # makin pro makin kuat
        if g.key != "drift":  # drift justru butuh sudut penuh di level lanjut
            assert b.angle >= a.angle >= p.angle, g.key  # makin pro sudut makin kecil/sama
    assert [get_template("drift", lv).angle for lv in LEVELS] == [720, 900, 900]
    assert get_template("race", "pro").angle == 540
    assert get_template("daily", "beginner").ffb < get_template("race", "beginner").ffb
    assert get_template("rally", "pro").road > get_template("race", "pro").road
    assert get_template("drift", "pro").spring < get_template("drift", "beginner").spring


# ----------------------------------------------------------------------------------------- INI
def test_ini_native_ffb_adv_roundtrip():
    adv = FfbAdvanced(smoothing=35, pneumatic_trail=62, mechanical_trail=44, road_effect=27, slip_effect=51,
                      kerb_effect=19, lut=list(LUT_PRESETS["detail"][1]))
    doc = M.profile_to_doc(base(), C.MODE_PC_DINPUT, name="X", ffb_adv=adv)
    assert doc.get(S.SEC_FFB_ADV, "LUT") == "0,38,62,82,100"
    doc2 = IniDocument.parse(doc.to_text())
    res = M.extract(doc2)
    assert res.ffb_adv == adv and not res.empty and not res.warnings
    assert any(i.field == "ffb_adv:lut" for i in res.items)
    rows = M.diff_against(res, base(), C.MODE_PC_DINPUT, FfbAdvanced())
    assert any(r[0] == "Smoothing" and r[1] == "0" and r[2] == "35" and r[4] for r in rows)


def test_ini_ffb_adv_validation_warnings():
    doc = IniDocument.parse(f"[{S.SEC_FFB_ADV}]\nLUT=1,2,3\nSMOOTHING=abc\nROAD=250\nENABLED=0\n")
    res = M.extract(doc)
    text = " ".join(res.warnings)
    assert "LUT" in text and "SMOOTHING" in text and "ROAD" in text
    assert res.ffb_adv.road_effect == 100 and res.ffb_adv.enabled is False


def test_sample_native_ini_includes_advanced_section():
    res = M.extract(IniDocument.parse(S.SAMPLE_NATIVE_INI))
    assert res.ffb_adv is not None and res.ffb_adv.smoothing == 20 and res.ffb_adv.kerb_effect == 25


def test_without_adv_section_nothing_is_written():
    doc = M.profile_to_doc(base(), C.MODE_PC_DINPUT)
    assert not doc.section(S.SEC_FFB_ADV) and M.extract(doc).ffb_adv is None


# ------------------------------------------------------------------------------------ database
def test_game_profile_persists_ffb_adv(tmp_path):
    db = ProfileDatabase(tmp_path / "p.db")
    gp = GameProfile(name="Drift pro")
    gp.set_profile(get_template("drift", "pro").base_profile())
    gp.set_advanced(get_template("drift", "pro").advanced())
    db.save(gp)
    back = db.get(gp.id)
    assert back.advanced() == get_template("drift", "pro").advanced()
    copy = back.duplicate()
    assert copy.advanced() == back.advanced()
    plain = db.save(GameProfile(name="plain"))
    assert db.get(plain.id).advanced() is None
    db.close()


def test_database_migrates_old_schema(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE game_profile (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                   img_url TEXT DEFAULT '', mode INTEGER NOT NULL, platform INTEGER NOT NULL,
                   model INTEGER NOT NULL DEFAULT 11, content_hex TEXT NOT NULL,
                   is_recommended INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)""")
    con.execute("INSERT INTO game_profile (name, mode, platform, content_hex, created_at) VALUES ('lama',1,1,'',1.0)")
    con.commit()
    con.close()
    db = ProfileDatabase(path)
    rows = db.list()
    assert [r.name for r in rows] == ["lama"] and rows[0].advanced() is None
    db.close()
