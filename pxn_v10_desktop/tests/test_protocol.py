"""Byte-level checks of the codec against the packet formats documented in the PRD and the
behaviour of the original Java implementation."""

import struct

import pytest

from pxn_v10.core import codec
from pxn_v10.core import constants as C
from pxn_v10.core.hexprofile import HexProfileError, pack_profile, unpack_profile
from pxn_v10.core.models import DeviceProfile, DeviceState, TestData
from pxn_v10.core.write_queue import WriteQueue


# ------------------------------------------------------------------ encoders
def test_request_encoders_match_prd():
    assert codec.read_state() == bytes([0x50, 0x01])
    assert codec.read_profile_page(1, 3) == bytes([0x51, 0x01, 0x03])
    assert codec.switch_mode(2) == bytes([0x53, 0x01, 0x02])
    assert codec.key_mapping(1, 12, 13) == bytes([0x53, 0x02, 0x01, 12, 13])
    assert codec.force_feedback(1, 80, 1) == bytes([0x53, 0x03, 0x01, 80, 1])
    assert codec.profile_reset(2) == bytes([0x53, 0x08, 0x02])
    assert codec.physics_forces(10, 20, 30, 40) == bytes([0x53, 0x09, 0x01, 10, 20, 30, 40])
    assert codec.test_mode(True) == bytes([0x54, 0x01])
    assert codec.test_mode(False) == bytes([0x54, 0x02])


def test_steering_angle_is_little_endian():
    assert codec.steering_angle(1, 900) == bytes([0x53, 0x04, 0x01, 0x01, 900 & 0xFF, 900 >> 8])
    assert codec.steering_angle(1, 90) == bytes([0x53, 0x04, 0x01, 0x01, 90, 0])
    assert codec.steering_angle(2, 360)[4:] == bytes([0x68, 0x01])


# ------------------------------------------------------------------ profile pages
def make_profile() -> DeviceProfile:
    p = DeviceProfile(angle=540, ffb=70, spring=10, damping=20, friction=30, inertia=40, ffb_reverse=1)
    p.keymap = {12: 13, 13: 12, 20: 21}
    p.acc_curve = [[0, 0], [1000, 2000], [2000, 30000], [4095, 65535]]
    p.brake_curve = [[10, 20], [30, 40], [50, 60], [70, 80]]
    p.clutch_curve = [[1, 2], [3, 4], [5, 6], [7, 8]]
    return p


def test_page_pack_layout():
    p = make_profile()
    page0 = p.pack_page(0, mode=1)
    assert len(page0) == 20 and page0[:3] == bytes([0x52, 1, 0])
    # identity keys 0..13 then 17, 16 then reserved 47
    assert list(page0[3:3 + 17]) == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 12, 17, 16, 47]
    page1 = p.pack_page(1, mode=1)
    assert page1[3:6] == bytes([14, 15, 47])
    assert page1[6] == 21  # key 20 remapped to 21
    page2 = p.pack_page(2, mode=1)
    assert list(page2[3:5]) == [34, 35]
    assert struct.unpack_from("<H", page2, 5)[0] == 540
    assert list(page2[7:13]) == [70, 10, 20, 30, 40, 1]
    page3 = p.pack_page(3, mode=1)
    assert struct.unpack_from("<8H", page3, 3) == (0, 0, 1000, 2000, 2000, 30000, 4095, 65535)


def test_pack_unpack_pages_roundtrip():
    p = make_profile()
    q = DeviceProfile()
    for frame in p.pack_pages(1, opcode=0xD1):
        q.unpack_page(frame)
    assert q == p
    assert q.acc_curve == p.acc_curve and q.clutch_curve == p.clutch_curve


def test_short_frames_do_not_raise():
    DeviceProfile().unpack_page(bytes([0xD1, 1, 2]))
    s = DeviceState()
    s.unpack(bytes([0xD0, 9, 1]))
    assert s.mode == 1 and s.version == 0


# ------------------------------------------------------------------ decoder
def test_decode_state_and_device_state():
    frame = bytes([0xD0, 9, 2, 5, 1, 1, 0, 1, 1]) + bytes(11)
    msg = codec.decode(frame)
    assert msg.kind == "state"
    s = DeviceState()
    s.unpack(msg.raw)
    assert (s.mode, s.minor_ver, s.major_ver, s.version) == (2, 5, 1, (1 << 8) | 5)
    assert s.has_pedal and not s.has_lever and s.has_brake and s.is_pc_mode and s.angle_mode == 1


@pytest.mark.parametrize("opcode", [0xD3, 0x53])
def test_decode_edit_acks(opcode):
    frame = lambda *b: bytes([opcode, *b]) + bytes(20 - 1 - len(b))
    assert codec.decode(frame(1, 2)).data == {"sub": 1, "mode": 2}
    assert codec.decode(frame(2, 1, 12, 13)).data == {"sub": 2, "key": 12, "mapped": 13}
    assert codec.decode(frame(3, 1, 55, 1)).data == {"sub": 3, "ffb": 55, "reverse": 1}
    d = codec.decode(frame(4, 1, 1, 0x68, 0x01)).data
    assert d["angle"] == 360 and d["angle_mode"] == 1
    d = codec.decode(frame(9, 1, 11, 22, 33, 44)).data
    assert (d["spring"], d["damping"], d["friction"], d["inertia"]) == (11, 22, 33, 44)


def test_decode_routes():
    assert codec.decode(bytes([0xD1, 1, 4]) + bytes(17)).data == {"page": 4, "mode": 1}
    assert codec.decode(bytes([0xD2, 1, 2]) + bytes(17)).kind == "write_ack"
    assert codec.decode(bytes([0xD4, 3]) + bytes(18)).kind == "telemetry"
    assert codec.decode(bytes([0xD4, 1]) + bytes(18)).kind == "test_ack"
    assert codec.decode(bytes([0x99])).kind == "unknown"
    assert codec.decode(b"").kind == "unknown"


# ------------------------------------------------------------------ telemetry
def test_telemetry_decoding():
    frame = bytearray(20)
    frame[0], frame[1] = 0xD4, 3
    frame[2] = 0b00000101  # keys 0 and 2
    frame[3] = 0b10000000  # key 15
    frame[4] = 0b00000010  # key 17
    frame[6] = 255
    frame[8], frame[9], frame[10] = 200, 0, 7
    frame[12] = 0b0101  # 25 and 23
    frame[13] = 255
    t = TestData()
    assert t.unpack(bytes(frame)) is True
    assert t.unpack(bytes(frame)) is False  # identical frame is ignored (like TestData.unpack)
    assert t.pressed[0] and not t.pressed[1] and t.pressed[2]
    assert t.pressed[15] and t.pressed[17] and not t.pressed[16]
    assert t.pressed[25] and not t.pressed[26] and t.pressed[23] and not t.pressed[24]
    assert (t.acc, t.brake, t.clutch) == (200, 0, 7)
    assert t.pressed[20] and not t.pressed[21] and t.pressed[22]
    assert t.pressed[33] and not t.pressed[27]  # gear R
    assert TestData.gear_text(255) == "R" and TestData.gear_text(0) == "N" and TestData.gear_text(4) == "4"


def test_angle_fraction_like_angle_test_view():
    assert TestData.angle_fraction(128) == 0
    assert TestData.angle_fraction(129) == 0
    assert TestData.angle_fraction(255) == 1.0
    assert TestData.angle_fraction(1) == -1.0
    assert TestData.angle_fraction(0) <= -1.0


# ------------------------------------------------------------------ hex profile
def test_hex_roundtrip_v3():
    p = make_profile()
    text = pack_profile(p)
    assert len(text) == 93 * 2 and text.startswith("03")
    assert unpack_profile(text) == p


def test_hex_legacy_recommended_preset():
    legacy = "000102030405060708090A0B0C0D11100E0F1415161718191A1B1C1D1E1F2021222303844B50505050"
    p = unpack_profile(legacy)
    assert p.angle == 900  # big endian 0x0384
    assert (p.ffb, p.spring, p.damping, p.friction, p.inertia) == (75, 80, 80, 80, 80)
    assert p.custom_mappings() == {}  # identity map
    assert p.acc_curve == [list(pt) for pt in C.DEFAULT_CURVE]  # curves absent -> defaults


def test_hex_errors():
    with pytest.raises(HexProfileError):
        unpack_profile("0102")
    with pytest.raises(HexProfileError):
        unpack_profile("ZZ")
    with pytest.raises(HexProfileError):
        unpack_profile("123")


# ------------------------------------------------------------------ write queue
def test_queue_replaces_same_kind_but_keeps_order():
    q = WriteQueue()
    q.put(codec.read_state())
    q.put(codec.force_feedback(1, 50, 0))
    q.put(codec.steering_angle(1, 900))
    assert q.put(codec.force_feedback(1, 60, 0)) is True
    assert q.put(codec.force_feedback(1, 80, 0)) is True
    assert len(q) == 3
    assert q.pop().packet == codec.read_state()
    assert q.pop().packet == codec.force_feedback(1, 80, 0)  # newest wins, original position
    assert q.pop().packet == codec.steering_angle(1, 900)
    assert q.pop() is None


def test_queue_keymap_dedup_is_per_physical_key():
    q = WriteQueue()
    q.put(codec.key_mapping(1, 12, 13))
    q.put(codec.key_mapping(1, 13, 12))
    q.put(codec.key_mapping(1, 12, 14))
    assert [i.packet[4] for i in [q.pop(), q.pop()]] == [14, 12]


def test_queue_never_merges_unrelated_and_supports_urgent():
    q = WriteQueue()
    q.put(codec.test_mode(True))
    q.put(codec.test_mode(False), urgent=True)
    assert q.pop().packet == codec.test_mode(False)
    assert q.pop().packet == codec.test_mode(True)
