"""Telemetri UDP untuk speedometer: parser (offset dari aplikasi asli), penerima UDP, sumber demo."""

import math
import socket
import struct
import time

import pytest

from pxn_v10.telemetry import parsers, simulator
from pxn_v10.telemetry.models import Telemetry, format_lap_time
from pxn_v10.telemetry.receiver import UdpTelemetryReceiver, local_ips
from pxn_v10.ui.widgets.speedo import nice_scale


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------------------------ parser
def test_forza_packet_uses_the_offsets_of_the_original_app():
    pkt = simulator.build_forza_packet(speed_kmh=180, rpm=6500, max_rpm=8200, gear=4, lap=2, lap_time=75.5,
                                       best_lap=71.25)
    assert len(pkt) == 324
    t = parsers.parse_forza(pkt)
    assert t.speed_kmh == pytest.approx(180, abs=0.01)
    assert (t.rpm, t.max_rpm, t.gear, t.lap) == (6500, 8200, 4, 3)  # lap short@312 ditampilkan +1
    assert (t.lap_time, t.best_lap) == (75.5, 71.25) and t.rpm_exact
    # tepat pada byte yang dibaca aplikasi asli
    assert struct.unpack_from("<f", pkt, 256)[0] * 3.6 == pytest.approx(180, abs=0.01) and pkt[319] == 4


def test_forza_gear_zero_is_reverse_and_speed_is_never_negative():
    t = parsers.parse_forza(simulator.build_forza_packet(speed_kmh=20, gear=0))
    assert t.gear == -1 and t.gear_text == "R"
    neg = bytearray(simulator.build_forza_packet())
    struct.pack_into("<f", neg, 256, -5.0)
    assert parsers.parse_forza(bytes(neg)).speed_kmh == 0.0


def test_dirt_packet_uses_the_offsets_of_the_original_app():
    pkt = simulator.build_dirt_packet(speed_kmh=100, rpm=450, max_rpm=900, gear=3)
    assert len(pkt) == 264
    t = parsers.parse_dirt(pkt)
    assert t.speed_kmh == pytest.approx(100, abs=0.01) and t.gear == 3 and t.gear_text == "3"
    assert t.rpm_fraction == pytest.approx(0.5) and not t.rpm_exact  # skala RPM Codemasters tidak pasti
    assert parsers.parse_dirt(simulator.build_dirt_packet(gear=-1)).gear_text == "R"
    assert parsers.parse_dirt(simulator.build_dirt_packet(gear=0)).gear_text == "N"


def test_detect_and_parse_auto_by_length_and_reject_bad_packets():
    assert parsers.detect(simulator.build_forza_packet()) == "forza"
    assert parsers.detect(simulator.build_dirt_packet()) == "dirt"
    assert parsers.detect(b"\x00" * 100) is None
    assert parsers.parse(b"\x00" * 100, "auto") is None
    assert parsers.parse(simulator.build_forza_packet(speed_kmh=60), "auto").source == "forza"
    assert parsers.parse_forza(b"\x00" * 100) is None and parsers.parse_dirt(b"\x00" * 100) is None
    # pilihan manual dihormati, tapi paket yang terlalu pendek untuk offset game itu ditolak (bukan dibaca ngawur)
    assert parsers.parse(simulator.build_dirt_packet(), "forza") is None
    assert parsers.parse(simulator.build_forza_packet(speed_kmh=30), "dirt").source == "dirt"  # cukup panjang


def test_nan_and_inf_never_reach_the_display():
    pkt = bytearray(simulator.build_forza_packet(speed_kmh=50, rpm=3000, max_rpm=7000))
    struct.pack_into("<f", pkt, 256, float("nan"))
    struct.pack_into("<f", pkt, 16, float("inf"))
    t = parsers.parse_forza(bytes(pkt))
    assert t.speed_kmh == 0.0 and t.rpm == 0.0 and math.isfinite(t.rpm_fraction)
    assert Telemetry(max_rpm=0).rpm_fraction == 0.0 and Telemetry(rpm=9, max_rpm=3).rpm_fraction == 1.0


def test_unit_conversion_and_lap_time_format():
    t = Telemetry(speed_kmh=100)
    assert t.speed("kmh") == 100 and t.speed("mph") == pytest.approx(62.1371)
    assert format_lap_time(83.5) == "01:23.500" and format_lap_time(None) == "--:--.---" and format_lap_time(0) == "--:--.---"
    assert Telemetry().gear_text == "–" and Telemetry(gear=0).gear_text == "N"


def test_nice_scale_is_readable():
    assert nice_scale(237) == (240.0, 20.0) or nice_scale(237)[0] >= 237
    for v in (50, 100, 187, 237, 312, 480):
        top, step = nice_scale(v)
        assert top >= v and top % step == 0 and top / step <= 14
    assert nice_scale(0) == (100.0, 10.0)


def test_demo_source_is_plausible():
    speeds = [simulator.demo(t / 2).speed_kmh for t in range(0, 96)]
    assert 0 <= min(speeds) and 200 < max(speeds) <= 241
    for t in range(0, 48):
        d = simulator.demo(t / 2)
        assert 0 <= d.rpm_fraction <= 1.1 and d.gear in range(0, 7)


# ---------------------------------------------------------------------------------- penerima UDP
def send(port, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(data, ("127.0.0.1", port))
    s.close()


def test_udp_receiver_end_to_end_on_loopback():
    got = []
    r = UdpTelemetryReceiver(0, "auto", on_data=got.append, host="127.0.0.1")
    assert r.start()
    try:
        send(r.bound_port, simulator.build_forza_packet(speed_kmh=120, gear=3))
        send(r.bound_port, b"bukan telemetri")
        send(r.bound_port, simulator.build_dirt_packet(speed_kmh=80, gear=2))
        assert wait_for(lambda: len(got) == 2)
        assert [g.source for g in got] == ["forza", "dirt"] and r.rejected == 1 and r.packets == 2
        assert got[0].speed_kmh == pytest.approx(120, abs=0.01) and r.age() < 1.0
    finally:
        r.stop()
    assert not r.running


def test_receiver_reports_a_busy_port_clearly_and_survives_a_broken_callback():
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind(("127.0.0.1", 0))
    try:
        busy = UdpTelemetryReceiver(holder.getsockname()[1], host="127.0.0.1")
        assert busy.start() is False and "tidak dapat dipakai" in busy.error and not busy.running
    finally:
        holder.close()

    def boom(_t):
        raise RuntimeError("callback rusak")

    r = UdpTelemetryReceiver(0, "forza", on_data=boom, host="127.0.0.1")
    assert r.start()
    try:
        send(r.bound_port, simulator.build_forza_packet(speed_kmh=10))
        send(r.bound_port, simulator.build_forza_packet(speed_kmh=20))
        assert wait_for(lambda: r.packets == 2)  # thread tetap hidup
    finally:
        r.stop()


def test_local_ips_are_ipv4_strings():
    for ip in local_ips():
        assert ip.count(".") == 3 and not ip.startswith("127.")
