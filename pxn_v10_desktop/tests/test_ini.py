from pathlib import Path

import pytest

from pxn_v10.core import constants as C
from pxn_v10.core.models import DeviceProfile
from pxn_v10.ini import mapper as M
from pxn_v10.ini import schema as S
from pxn_v10.ini.document import IniDocument, decode_embedded, encode_embedded, infer_type
from pxn_v10.storage.database import GameProfile, ProfileDatabase, load_recommended

USER_INI = Path(__file__).resolve().parents[2] / "shader PXN V10 Ai 4 (Drift)).ini"


# ----------------------------------------------------------------- parser
def test_parse_keeps_order_comments_and_unknown_keys():
    text = "[A:B]\r\nKEY=1\r\n# note\r\nFOO = 'x y'\r\nBAR=a=b\r\n\r\n[C]\r\nZ=\r\n"
    doc = IniDocument.parse(text)
    assert doc.section_names() == ["A:B", "C"]
    assert doc.get("a:b", "foo") == "'x y'"  # case-insensitive lookup, quotes preserved
    assert doc.get("A:B", "BAR") == "a=b"
    assert doc.get("C", "Z") == ""
    assert doc.to_text() == "[A:B]\r\nKEY=1\r\n# note\r\nFOO='x y'\r\nBAR=a=b\r\n\r\n[C]\r\nZ=\r\n"
    doc2 = IniDocument.parse(doc.to_text())
    assert list(doc2.iter_items()) == list(doc.iter_items())


def test_header_comment_before_first_section_is_kept():
    doc = IniDocument.parse("; made by hand\n[A]\nK=1\n")
    assert doc.to_text().startswith("; made by hand")


def test_duplicate_sections_merge_and_last_key_wins():
    doc = IniDocument.parse("[A]\nK=1\n[B]\nX=1\n[A]\nK=2\nL=3\n")
    assert doc.section_names() == ["A", "B"]
    assert doc.get("A", "K") == "2" and doc.get("A", "L") == "3"


def test_set_delete_and_new_sections():
    doc = IniDocument.parse("[A]\r\nK=1\r\n\r\n")
    doc.set("A", "k", "5")  # existing key keeps its spelling
    doc.set("A", "NEW", "x")
    doc.set("B", "Y", "2")
    assert doc.to_text() == "[A]\r\nK=5\r\nNEW=x\r\n\r\n[B]\r\nY=2\r\n"
    doc.delete("A", "K")
    assert not doc.has("A", "K")
    doc.delete("B")
    assert doc.section_names() == ["A"]


def test_infer_type():
    assert infer_type("") == "empty" and infer_type("1") == "bool" and infer_type("42") == "int"
    assert infer_type("0.5") == "float" and infer_type("ULTRA") == "text" and infer_type("-3") == "int"
    assert infer_type("W1NFVFRJTkdTXQ0KZnJvbnRGb3JjZUs9MQ0K") == "embedded"


def test_embedded_base64_roundtrip_keeps_padding_style():
    original = "W1NFVFRJTkdTXQ0KZnJvbnRGb3JjZUs9MQ0KZGFtcEs9MC4wMg0K"
    nested = decode_embedded(original)
    assert nested is not None and nested.get("SETTINGS", "dampK") == "0.02"
    nested.set("SETTINGS", "dampK", "0.5")
    new = encode_embedded(nested, like=original)
    assert "=" not in new
    assert decode_embedded(new).get("SETTINGS", "dampK") == "0.5"
    assert decode_embedded("just some plain words") is None


# ----------------------------------------------------------------- the user's real file
@pytest.mark.skipif(not USER_INI.exists(), reason="sample ini not present")
def test_user_shader_ini_roundtrips_without_losing_anything():
    original = USER_INI.read_bytes().decode("utf-8")
    doc = IniDocument.load(str(USER_INI))
    assert len(doc.sections) == 63 and doc.count() == 121
    assert doc.get("FFB_TWEAKS:POSTPROCESSING", "RANGE_COMPRESSION") == "1.1"
    assert doc.get("WEATHER_FX:BASIC", "CONTROLLER") == "'pureCtrl static'"
    assert doc.get("WEATHER_FX:__PLUGINS", "IMPLEMENTATION_SETTINGS") == ""
    assert doc.get("CONFIGURATION", "AFFECTED_SECTIONS").startswith("GENERAL,BRAKEDISC_FX")
    # nothing lost: re-parsing the written text yields the identical key/value list
    again = IniDocument.parse(doc.to_text())
    assert list(again.iter_items()) == list(doc.iter_items())
    # byte-for-byte (apart from trailing blank lines)
    assert doc.to_text().rstrip() == original.rstrip()
    # embedded script settings are discoverable
    emb = decode_embedded(doc.get("FFB_TWEAKS:__PLUGINS", "POSTPROCESSING_SCRIPT_SETTINGS"))
    assert emb is not None and emb.get("SETTINGS", "frontForceK") == "1"


@pytest.mark.skipif(not USER_INI.exists(), reason="sample ini not present")
def test_user_ini_has_no_native_params_so_bindings_are_needed():
    doc = IniDocument.load(str(USER_INI))
    res = M.extract(doc)
    assert not res.native and res.empty
    binding = M.Binding("FFB_TWEAKS:CUSTOM_SOFT_LOCK", "DAMPER", "damping", 0.0, 0.1, 0, 100)
    res = M.extract(doc, [binding])
    assert res.scalars == {"damping": 20}  # 0.02 on 0..0.1 -> 20 %


# ----------------------------------------------------------------- native mapping
def test_native_extract_and_apply():
    doc = IniDocument.parse(S.SAMPLE_NATIVE_INI)
    res = M.extract(doc)
    assert res.native and res.name == "Contoh preset PXN V10" and res.mode == 1
    assert res.scalars == {"angle": 900, "ffb": 80, "ffb_reverse": 0, "spring": 70, "damping": 60,
                           "friction": 50, "inertia": 50}
    assert res.keymap == {12: 13, 13: 12}
    assert res.curves["acc"] == [list(p) for p in C.DEFAULT_CURVE]
    base = DeviceProfile(angle=270, ffb=10)
    base.keymap[4] = 5
    out = M.apply_to_profile(res, base)
    assert out.angle == 900 and out.ffb == 80 and out.keymap == {4: 5, 12: 13, 13: 12}
    assert base.angle == 270  # the base is not modified


def test_partial_ini_only_overrides_defined_fields():
    doc = IniDocument.parse("[PXN_V10:WHEEL]\nANGLE=540\n")
    res = M.extract(doc)
    out = M.apply_to_profile(res, DeviceProfile(angle=900, ffb=33))
    assert out.angle == 540 and out.ffb == 33


def test_values_are_clamped_and_reported():
    doc = IniDocument.parse(
        "[PXN_V10:WHEEL]\nANGLE=5000\nFFB=-4\nSPRING=abc\nFFB_REVERSE=inverted\n"
        "[PXN_V10:GENERAL]\nMODE=banana\n"
        "[PXN_V10:CURVE_BRAKE]\nP0=0,0\nP1=3000,100\nP2=1000,200\nP3=9999,70000\n"
        "[PXN_V10:KEYMAP]\nL1=NOPE\nA=B\n"
    )
    res = M.extract(doc)
    assert res.scalars["angle"] == 900 and res.scalars["ffb"] == 0 and res.scalars["ffb_reverse"] == 1
    assert "spring" not in res.scalars and res.mode is None
    pts = res.curves["brake"]
    assert pts[3] == [4095, 65535]
    assert all(pts[i][0] <= pts[i + 1][0] and pts[i][1] <= pts[i + 1][1] for i in range(3))
    assert res.keymap == {10: 9}
    text = "\n".join(res.warnings)
    assert "SPRING" in text and "MODE" in text and "NOPE" in text and "titik harus naik" in text


def test_incomplete_curve_is_ignored():
    res = M.extract(IniDocument.parse("[PXN_V10:CURVE_ACC]\nP0=0,0\nP1=5,5\n"))
    assert "acc" not in res.curves and any("P2" in w for w in res.warnings)


def test_binding_scaling_invert_and_disabled():
    doc = IniDocument.parse("[X:Y]\nGAIN=0.5\nREV=1\nANG=180\nOFF=1\n")
    b = [
        M.Binding("X:Y", "GAIN", "ffb", 0, 1, 0, 100),
        M.Binding("X:Y", "REV", "ffb_reverse", invert=True),
        M.Binding("X:Y", "ANG", "angle", 0, 360, 90, 900),
        M.Binding("X:Y", "OFF", "spring", 0, 1, 0, 100, enabled=False),
        M.Binding("X:Y", "MISSING", "inertia"),
    ]
    res = M.extract(doc, b)
    assert res.scalars == {"ffb": 50, "ffb_reverse": 0, "angle": 495}
    assert M.Binding.from_dict(b[0].to_dict()) == b[0]


def test_export_roundtrip_and_foreign_sections_preserved():
    p = DeviceProfile(angle=360, ffb=55, spring=1, damping=2, friction=3, inertia=4, ffb_reverse=1)
    p.keymap = {12: 13, 20: 21}
    p.acc_curve = [[0, 0], [10, 20], [30, 40], [50, 60]]
    doc = M.profile_to_doc(p, C.MODE_PC_XINPUT, name="Test", platform=1)
    back = M.apply_to_profile(M.extract(IniDocument.parse(doc.to_text())), DeviceProfile())
    assert back == p
    assert doc.get("CONFIGURATION", "AFFECTED_SECTIONS") == "PXN_V10"
    assert doc.get(S.SEC_GENERAL, "MODE") == "2"
    assert doc.section_names()[0] == "CONFIGURATION"

    base = IniDocument.parse("[CONFIGURATION]\nVERSION=1\nAFFECTED_SECTIONS=GENERAL,GUI\n[GUI:BASIC]\nA=1\n")
    merged = M.profile_to_doc(p, 1, base=base)
    assert merged.get("GUI:BASIC", "A") == "1"
    assert merged.get("CONFIGURATION", "AFFECTED_SECTIONS") == "GENERAL,GUI,PXN_V10"
    # exporting twice replaces the PXN sections instead of duplicating them
    twice = M.profile_to_doc(p, 1, base=merged)
    assert twice.section_names().count(S.SEC_WHEEL) == 1


def test_diff_rows():
    res = M.extract(IniDocument.parse("[PXN_V10:WHEEL]\nANGLE=540\nFFB=100\n[PXN_V10:KEYMAP]\nL1=R1\n"))
    rows = M.diff_against(res, DeviceProfile(angle=900, ffb=100), 1)
    by = {r[0]: r for r in rows}
    assert by["Steering angle (°)"][1:3] == ("900", "540") and by["Steering angle (°)"][4] is True
    assert by["Force feedback (%)"][4] is False
    assert by["Tombol L1"][2] == "R1"


# ----------------------------------------------------------------- database / presets
def test_database_crud(tmp_path):
    db = ProfileDatabase(tmp_path / "p.db")
    gp = GameProfile(name="Drift", mode=1, platform=1)
    gp.set_profile(DeviceProfile(angle=360))
    db.save(gp)
    assert gp.id is not None
    assert db.get(gp.id).profile().angle == 360
    db.rename(gp.id, "Drift 2")
    dup = db.save(db.get(gp.id).duplicate())
    assert [g.name for g in db.list(platform=1)] == ["Drift 2", "Drift 2 (copy)"]
    assert db.list(platform=3) == []
    db.delete(dup.id)
    assert len(db.list()) == 1
    db.close()


def test_recommended_presets_load_and_are_valid():
    items = load_recommended()
    names = [g.name for g in items]
    assert len(items) >= 14
    assert "Assetto Corsa — Realistic" in names and "GT Sport" in names and "Forza Horizon 4" in names
    assert all(g.recommended and 90 <= g.profile().angle <= 900 for g in items)
    gt = next(g for g in items if g.name == "GT Sport")
    assert gt.mode == 5 and gt.platform == 3


def test_shipped_sample_preset_is_valid():
    sample = Path(__file__).resolve().parents[1] / "presets" / "PXN V10 contoh (native).ini"
    res = M.extract(IniDocument.load(str(sample)))
    assert res.native and not res.warnings and res.mode == 1
    assert res.scalars["angle"] == 900 and res.keymap == {12: 13, 13: 12}
