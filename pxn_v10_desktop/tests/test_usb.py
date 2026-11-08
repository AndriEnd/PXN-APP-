"""Lapisan USB: kalibrasi, shifter/handbrake, pemindaian perangkat, dan transport HID (dengan HID virtual)."""

import time

import pytest

from pxn_v10.ble.client import WheelClient
from pxn_v10.ble.mock_device import MockV10Device
from pxn_v10.core import constants as C
from pxn_v10.core.events import ConnState
from pxn_v10.usb import config as U
from pxn_v10.usb.devices import ComPort, UsbMonitor, UsbScanner
from pxn_v10.usb.hid import HidInfo
from pxn_v10.usb.hid_transport import FakeHidIO, HidTransport, TransportError
from pxn_v10.usb.joystick import FakeJoystickBackend, JoyInfo, JoyState


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------------------------ kalibrasi
def test_axis_normalize_invert_deadzone_gamma():
    cal = U.AxisCalibration(raw_min=1000, raw_max=3000)
    assert cal.normalize(1000) == 0 and cal.normalize(3000) == 1 and cal.normalize(2000) == pytest.approx(0.5)
    assert cal.normalize(0) == 0 and cal.normalize(9999) == 1  # di luar rentang dibatasi
    assert U.AxisCalibration(invert=True).normalize(0) == 1
    dz = U.AxisCalibration(deadzone=0.1, saturation=0.1)
    assert dz.normalize(0.05 * 65535) == 0 and dz.normalize(0.95 * 65535) == 1
    assert dz.normalize(0.5 * 65535) == pytest.approx(0.5)
    assert U.AxisCalibration(gamma=2.0).normalize(0.5 * 65535) == pytest.approx(0.25, abs=1e-3)
    assert U.AxisCalibration(raw_min=5, raw_max=5).normalize(5) == 0  # span nol tidak membagi nol
    assert U.AxisCalibration().bipolar(32767.5) == pytest.approx(0, abs=1e-3)


def test_handbrake_analog_and_button_modes():
    hb = U.HandbrakeConfig(cal=U.AxisCalibration(axis=0, raw_min=0, raw_max=1000), threshold=0.2)
    assert hb.decode(JoyState([0], 0)) == (0.0, False)
    v, on = hb.decode(JoyState([500], 0))
    assert v == pytest.approx(0.5) and on
    assert hb.decode(JoyState([], 0))[0] == 0.0  # sumbu tidak ada
    btn = U.HandbrakeConfig(mode="button", button=3)
    assert btn.decode(JoyState([], 1 << 3)) == (1.0, True) and btn.decode(JoyState([], 0)) == (0.0, False)


def test_h_pattern_shifter_decoder():
    dec = U.ShifterDecoder(U.ShifterConfig(gears={"1": 0, "2": 1, "R": 6, "3": 2}))
    assert dec.update(JoyState([], 0)) == "N"
    assert dec.update(JoyState([], 1 << 1)) == "2"
    assert dec.update(JoyState([], 1 << 6)) == "R"
    assert dec.update(JoyState([], (1 << 6) | 1)) == "R"  # R diprioritaskan


def test_sequential_shifter_counts_edges_and_clamps():
    dec = U.ShifterDecoder(U.ShifterConfig(kind="seq", seq_up=0, seq_down=1, seq_max=3))
    up, down, idle = JoyState([], 1), JoyState([], 2), JoyState([], 0)
    seen = []
    for st in (up, up, idle, up, idle, up, idle, up, idle, down, idle, down, idle, down, idle, down, idle, down):
        seen.append(dec.update(st))
    assert seen[0] == "1" and seen[1] == "1"  # menahan tombol tidak mengulang
    assert "3" in seen and "4" not in seen  # dibatasi seq_max
    assert seen[-1] == "R"  # turun di bawah netral = mundur, tidak lebih rendah
    pov = U.ShifterDecoder(U.ShifterConfig(kind="seq", use_pov=True))
    assert pov.update(JoyState([], 0, pov=0)) == "1"


def test_axis_probe_picks_the_moved_axis():
    rng = [(0, 65535)] * 3
    probe = U.AxisProbe()
    probe.start(JoyState([100, 200, 300]), rng)
    for v in range(0, 60000, 5000):
        probe.feed(JoyState([100 + v % 7, v, 300]))
    assert probe.result() == 1 and probe.extent(1)[1] >= 55000
    idle = U.AxisProbe()
    idle.start(JoyState([1, 2, 3]), rng)
    idle.feed(JoyState([5, 2, 3]))
    assert idle.result() is None  # gerakan kecil bukan niat pengguna


def test_button_probe_ignores_buttons_already_held():
    probe = U.ButtonProbe()
    probe.start(JoyState([], 0b0100))
    assert probe.feed(JoyState([], 0b0100)) is None
    assert probe.feed(JoyState([], 0b0100 | 0b1000)) == 3
    assert probe.feed(JoyState([], 0)) == 3  # hasil bertahan
    again = U.ButtonProbe()
    again.start(JoyState([], 1))
    again.feed(JoyState([], 0))
    assert again.feed(JoyState([], 1)) == 0  # ditekan ulang setelah dilepas


def test_role_guessing():
    g = U.guess_role
    assert g("PXN-V10", 4, 24) == U.ROLE_WHEEL
    assert g("Generic USB Shifter", 0, 8) == U.ROLE_SHIFTER
    assert g("USB Handbrake", 1, 1) == U.ROLE_HANDBRAKE
    assert g("Pedals", 3, 0) == U.ROLE_PEDALS
    assert g("USB Game Controller", 1, 1) == U.ROLE_HANDBRAKE
    assert g("USB Game Controller", 0, 10) == U.ROLE_SHIFTER
    assert g("Mystery", 2, 4) == U.ROLE_OTHER


def test_device_settings_roundtrip_and_tolerance():
    s = U.DeviceSettings(role=U.ROLE_SHIFTER)
    s.shifter = U.ShifterConfig(kind="seq", seq_up=4, seq_down=5, seq_max=7)
    s.handbrake = U.HandbrakeConfig(mode="button", button=9, cal=U.AxisCalibration(axis=2, invert=True))
    s.wheel.lock_degrees = 540
    back = U.DeviceSettings.from_dict(s.to_dict())
    assert back.to_dict() == s.to_dict()
    junk = U.DeviceSettings.from_dict({"role": "???", "shifter": {"kind": "x", "gears": {"1": "a"}}, "wheel": 5})
    assert junk.role == U.ROLE_OTHER and junk.shifter.kind == "h" and junk.wheel.lock_degrees == 900
    assert U.device_key(0x1234, 0xABCD) == "1234:ABCD" and U.device_key(1, 2, 1) == "0001:0002#2"


# ------------------------------------------------------------------------------------ scanner
def make_joy(slot, vid, pid, name, axes=1, buttons=2):
    return JoyInfo(slot, vid, pid, name, tuple(range(axes)), ((0, 65535),) * axes, buttons, False)


def test_scanner_merges_joysticks_and_hid_and_handles_duplicates():
    backend = FakeJoystickBackend()
    backend.add(make_joy(0, 0x1111, 0x0001, "USB Game Controller", 4, 24))
    backend.add(make_joy(1, 0x2222, 0x0002, "USB Game Controller", 0, 8))
    backend.add(make_joy(2, 0x2222, 0x0002, "USB Game Controller", 0, 8))
    hids = [HidInfo("p1", 0x1111, 0x0001, "PXN-V10", "PXN", 0x01, 0x04, 9, 0),
            HidInfo("p2", 0x1111, 0x0001, "PXN-V10", "PXN", 0xFF00, 0x01, 64, 64),
            HidInfo("p3", 0x3333, 0x0003, "PXN Pedal Hub", "PXN", 0x01, 0x80, 4, 0)]
    devices = UsbScanner(backend, lambda: hids).scan()
    names = [d.name for d in devices]
    assert names[0] == "PXN-V10" and devices[0].guessed_role == U.ROLE_WHEEL  # nama produk HID menggantikan nama generik
    assert [d.key for d in devices[1:3]] == ["2222:0002", "2222:0002#2"]
    assert devices[0].config_interfaces and devices[0].config_interfaces[0].path == "p2"
    assert not devices[1].config_interfaces
    assert any(d.joy is None and d.name == "PXN Pedal Hub" for d in devices)  # PXN hanya-HID tetap terdeteksi


def test_monitor_notifies_only_on_change_and_hotplug():
    backend = FakeJoystickBackend()
    events = []
    mon = UsbMonitor(UsbScanner(backend, lambda: []), interval=0.02, on_change=lambda d: events.append(len(d)))
    mon.start()
    try:
        assert wait_for(lambda: events == [0])
        time.sleep(0.15)
        assert events == [0]  # tidak ada perubahan -> tidak ada notifikasi ulang
        backend.add(make_joy(0, 1, 1, "Handbrake X"))
        assert wait_for(lambda: events[-1] == 1)
        backend.remove(0)
        assert wait_for(lambda: events[-1] == 0)
    finally:
        mon.stop()


def test_demo_backend_has_animated_wheel_shifter_handbrake():
    b = FakeJoystickBackend.demo()
    infos = b.enumerate()
    assert [i.n_axes for i in infos] == [4, 0, 1]
    s1, s2 = b.read(0), None
    time.sleep(0.05)
    s2 = b.read(0)
    assert s1.axes != s2.axes and b.read(9) is None


def test_com_port_usb_heuristic():
    assert ComPort("COM3", r"\Device\USBSER000").is_usb and not ComPort("COM1", r"\Device\Serial0").is_usb


# ------------------------------------------------------------------------------ HID transport
def vendor_info(path="usb-config"):
    return HidInfo(path, 0x1111, 0x0001, "PXN-V10", "PXN", 0xFF00, 0x01, 64, 64)


def hid_rig(respond=True):
    dev = MockV10Device(mode=C.MODE_PC_DINPUT)
    io = FakeHidIO(dev, respond=respond)
    info = vendor_info()
    transport = HidTransport(enumerator=lambda: [info, HidInfo("pad", 0x1111, 0x0001, "PXN-V10", "PXN", 1, 4, 9, 0)],
                             io_factory=lambda i: io, probe_timeout=0.4)
    client = WheelClient(transport, write_interval=0.01, ack_timeout=0.2, auto_reconnect=False)
    return client, transport, io, dev


def test_hid_candidates_require_vendor_interface_with_input_and_output():
    t = HidTransport(enumerator=lambda: [])
    pad = HidInfo("pad", 1, 1, "Wheel", "", 1, 4, 9, 0)
    only_in = HidInfo("in", 1, 1, "Wheel", "", 0xFF00, 1, 64, 0)
    ok = HidInfo("cfg", 1, 1, "Wheel", "", 0xFF00, 1, 64, 64)
    unrelated = HidInfo("tp", 9, 9, "Touchpad", "", 0xFF00, 1, 12, 12)
    assert [i.path for i in t.candidates([pad, only_in, ok, unrelated])] == ["cfg"]
    assert HidTransport(include_all=True).candidates([unrelated])[0].path == "tp"


def test_hid_scan_explains_when_no_config_interface():
    client = WheelClient(HidTransport(enumerator=lambda: [HidInfo("pad", 1, 1, "Wheel", "", 1, 4, 9, 0)]),
                         auto_reconnect=False)
    try:
        client.scan(auto_connect=False)
        assert wait_for(lambda: client.last_error and client.state == ConnState.DISCONNECTED)
        assert "Bluetooth" in client.last_error
    finally:
        client.shutdown()
    empty = WheelClient(HidTransport(enumerator=lambda: []), auto_reconnect=False)
    try:
        empty.scan(auto_connect=False)
        assert wait_for(lambda: "kabel USB" in empty.last_error)
    finally:
        empty.shutdown()


def test_full_usb_session_over_hid_matches_ble_behaviour():
    client, transport, io, dev = hid_rig()
    try:
        client.scan(auto_connect=True)
        assert wait_for(lambda: client.profile_synced), client.last_error
        assert client.state == ConnState.READY and transport.verified
        assert client.device_state.mode == C.MODE_PC_DINPUT
        assert io.written[0][1][:2] == bytes([0x50, 0x01])  # probe = permintaan baca state
        client.write_angle(360)
        client.write_force_feedback(55)
        assert wait_for(lambda: dev.profile().angle == 360 and dev.profile().ffb == 55)
        client.write_profile(DeviceProfile_for_test(), C.MODE_PC_DINPUT)
        assert wait_for(lambda: dev.profile(1).spring == 33)
        assert all(rid == 0 and 2 <= len(p) <= 20 for rid, p in io.written)
    finally:
        client.shutdown()


def DeviceProfile_for_test():
    from pxn_v10.core.models import DeviceProfile

    return DeviceProfile(angle=540, ffb=60, spring=33, damping=44, friction=55, inertia=66)


def test_silent_device_is_rejected_and_no_write_ever_sent():
    client, transport, io, dev = hid_rig(respond=False)
    try:
        client.scan(auto_connect=True)
        assert wait_for(lambda: client.state == ConnState.DISCONNECTED and client.last_error)
        assert "tidak menjawab" in client.last_error
        assert [p[:2] for _rid, p in io.written] == [bytes([0x50, 0x01])]  # hanya satu permintaan baca
        assert not transport.verified and not transport.is_connected
    finally:
        client.shutdown()


def test_writes_are_refused_until_verified():
    import asyncio

    t = HidTransport(io_factory=lambda i: FakeHidIO(respond=False), enumerator=lambda: [vendor_info()],
                     probe_timeout=0.1)
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(TransportError):
            loop.run_until_complete(t.write(bytes([0x53, 3, 50])))
    finally:
        loop.close()


def test_unplug_triggers_link_loss():
    client, transport, io, dev = hid_rig()
    try:
        client.scan(auto_connect=True)
        assert wait_for(lambda: client.profile_synced)
        io.unplug()
        assert wait_for(lambda: client.state == ConnState.DISCONNECTED)
        assert client.last_error
    finally:
        client.shutdown()


def test_winmm_axes_are_filtered_to_the_ones_the_device_reports():
    from pxn_v10.usb.joystick import select_axes

    raw = (11, 22, 33, 44, 55, 66)  # X Y Z R U V
    assert select_axes(raw, (0, 1)) == [11, 22]  # shifter dengan 2 sumbu
    assert select_axes(raw, (0, 1, 2, 3, 4)) == [11, 22, 33, 44, 55]  # board 5 sumbu
    assert select_axes(raw, (0, 1, 3)) == [11, 22, 44]  # sumbu Z tidak ada -> R menjadi indeks 2


def test_winmm_backend_read_returns_one_value_per_reported_axis():
    from pxn_v10.usb.joystick import default_backend

    b = default_backend()
    if b is None:
        pytest.skip("hanya Windows")
    for info in b.enumerate():  # perangkat nyata bila ada; kosong bila tidak ada
        st = b.read(info.slot)
        assert st is not None and len(st.axes) == info.n_axes


# --------------------------------------------------------------------- backend HID (deskriptor)
def test_hid_value_helpers():
    from pxn_v10.usb.hid_joystick import axis_name, hat_to_degrees, scale_to_raw, sign_extend

    assert scale_to_raw(0, 0, 1023) == 0 and scale_to_raw(1023, 0, 1023) == 65535
    assert scale_to_raw(512, 0, 1023) == pytest.approx(32799, abs=2)  # handbrake 10-bit
    assert scale_to_raw(5, 5, 5) == 0 and scale_to_raw(-10, 0, 100) == 0 and scale_to_raw(999, 0, 100) == 65535
    assert sign_extend(0xFF, 8, -128) == -1 and sign_extend(0x7F, 8, -128) == 127 and sign_extend(0xFF, 8, 0) == 255
    assert [hat_to_degrees(v, 0, 7) for v in (0, 2, 4, 6)] == [0, 90, 180, 270] and hat_to_degrees(8, 0, 7) == -1
    assert hat_to_degrees(1, 1, 8) == 0 and hat_to_degrees(0, 1, 8) == -1  # varian 1..8, 0 = netral
    assert axis_name(1, 0x31) == "Y" and axis_name(2, 0xC5) == "Brake" and axis_name(0xFF00, 1) == "FF00:1"


def test_duplicate_axis_names_are_numbered():
    from pxn_v10.usb.hid_joystick import unique_names

    assert unique_names(["Rx", "Slider", "Slider", "X", "Slider"]) == ["Rx", "Slider", "Slider 2", "X", "Slider 3"]


def test_hid_backend_on_real_devices_is_consistent():
    from pxn_v10.usb.hid_joystick import best_backend

    b = best_backend()
    if b is None:
        pytest.skip("hanya Windows")
    for info in b.enumerate():
        st = b.read(info.slot)
        assert st is not None and len(st.axes) == info.n_axes == len(info.axis_labels())
        assert all(0 <= v <= 65535 for v in st.axes)
