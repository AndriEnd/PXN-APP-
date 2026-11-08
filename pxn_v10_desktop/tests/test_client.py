"""End-to-end tests of WheelClient against the simulated wheel (no hardware needed)."""

import time

import pytest

from pxn_v10.ble.client import WheelClient
from pxn_v10.ble.mock_device import MockV10Device
from pxn_v10.ble.mock_transport import SIM_ADDRESS, MockTransport
from pxn_v10.core import constants as C
from pxn_v10.core.events import Change, ChangeEvent, ConnEvent, ConnState, TestEvent
from pxn_v10.core.models import DeviceProfile


def wait_for(cond, timeout=5.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False


@pytest.fixture
def rig():
    device = MockV10Device(mode=C.MODE_PC_DINPUT)
    transport = MockTransport(device, latency=0.002, telemetry_hz=200)
    client = WheelClient(transport, write_interval=0.01, ack_timeout=0.2)
    events: list = []
    client.add_listener(events.append)
    yield client, device, transport, events
    client.shutdown()


def connect(client):
    client.connect(SIM_ADDRESS)
    assert wait_for(lambda: client.profile_synced), "handshake / profile sync did not finish"


def test_handshake_reads_state_then_all_six_profile_pages(rig):
    client, device, transport, events = rig
    connect(client)
    assert client.state == ConnState.READY
    sent = device.received
    assert sent[0] == bytes([0x50, 0x01])
    assert sent[1:7] == [bytes([0x51, 1, p]) for p in range(6)]
    assert client.device_state.mode == C.MODE_PC_DINPUT
    assert client.device_state.has_pedal and client.device_state.has_lever and client.device_state.has_brake
    assert client.device_state.firmware_text.startswith("v")
    types = [e.type for e in events if isinstance(e, ChangeEvent)]
    assert Change.STATE in types and Change.PROFILE_READY in types
    states = [e.state for e in events if isinstance(e, ConnEvent)]
    assert states[:2] == [ConnState.CONNECTING, ConnState.DISCOVERING_SERVICES]
    assert ConnState.INITIALIZING_NOTIFY in states and states[-1] == ConnState.READY


def test_scan_autoconnects_to_simulated_wheel():
    transport = MockTransport(latency=0.002)
    client = WheelClient(transport, write_interval=0.01, ack_timeout=0.2)
    try:
        client.scan(timeout=3)
        assert wait_for(lambda: client.profile_synced, 6)
    finally:
        client.shutdown()


def test_parameter_writes_reach_the_wheel_and_are_acked(rig):
    client, device, *_ = rig
    connect(client)
    client.write_angle(360)
    client.write_force_feedback(70)
    client.write_force_feedback_reverse(1)
    client.write_force(10, 20, 30, 40)
    client.write_mapping(12, 13)
    assert wait_for(lambda: device.profile().keymap.get(12) == 13)  # last queued packet
    p = device.profile()
    assert (p.ffb, p.ffb_reverse) == (70, 1)
    assert (p.spring, p.damping, p.friction, p.inertia) == (10, 20, 30, 40)
    assert p.keymap[12] == 13
    # the local mirror follows the acks
    assert wait_for(lambda: client.profile.angle == 360 and client.profile.keymap.get(12) == 13)


def test_single_force_writes_compose_with_latest_values(rig):
    client, device, *_ = rig
    connect(client)
    client.write_spring(50)
    client.write_damping(60)  # sent before the first ack: must still carry spring=50
    assert wait_for(lambda: device.profile().damping == 60)
    assert device.profile().spring == 50


def test_rapid_slider_drag_is_collapsed(rig):
    client, device, transport, events = rig
    connect(client)
    before = len(device.received)
    for v in range(0, 100, 10):  # a fast drag, queue is paced so most packets are replaced
        client.write_force_feedback(v)
    assert wait_for(lambda: device.profile().ffb == 90)  # the device default is 100
    ffb_packets = [p for p in device.received[before:] if p[:2] == bytes([0x53, 0x03])]
    assert len(ffb_packets) < 10
    assert ffb_packets[-1][3] == 90
    assert client.queue.replaced >= 1


def test_mode_switch_acks_and_resyncs_profile(rig):
    client, device, *_ = rig
    connect(client)
    client.switch_mode(C.MODE_PC_XINPUT)
    assert wait_for(lambda: client.device_state.mode == C.MODE_PC_XINPUT)
    n = len(device.received)
    assert wait_for(lambda: any(p[:3] == bytes([0x51, 2, 5]) for p in device.received[n:] + device.received))


def test_write_profile_sends_six_pages_then_reports_complete(rig):
    client, device, transport, events = rig
    connect(client)
    prof = DeviceProfile(angle=360, ffb=55, spring=20, damping=30, friction=40, inertia=50, ffb_reverse=1)
    prof.keymap[12] = 13
    prof.acc_curve = [[100, 200], [300, 400], [500, 600], [700, 800]]
    n = len(device.received)
    assert client.write_profile(prof, C.MODE_PC_DINPUT)
    assert wait_for(lambda: any(isinstance(e, ChangeEvent) and e.type == Change.PROFILE_WRITTEN for e in events))
    writes = [p for p in device.received[n:] if p[0] == 0x52]
    assert [p[2] for p in writes] == [0, 1, 2, 3, 4, 5]
    assert all(len(p) == 20 and p[1] == 1 for p in writes)
    dp = device.profile(1)
    assert dp.angle == 360 and dp.ffb == 55 and dp.keymap[12] == 13 and dp.acc_curve[0] == [100, 200]
    # the client re-syncs its mirror afterwards
    assert wait_for(lambda: client.profile.angle == 360 and client.profile.acc_curve[1] == [300, 400])


def test_write_profile_for_other_pc_mode_switches_mode(rig):
    client, device, *_ = rig
    connect(client)
    client.write_profile(DeviceProfile(angle=270), C.MODE_PC_XINPUT)
    assert wait_for(lambda: client.device_state.mode == C.MODE_PC_XINPUT)
    assert device.profile(C.MODE_PC_XINPUT).angle == 270


def test_factory_reset_restores_defaults_and_rereads(rig):
    client, device, transport, events = rig
    connect(client)
    client.write_angle(180)
    assert wait_for(lambda: device.profile().angle == 180)
    events.clear()
    client.write_profile_reset()
    assert wait_for(lambda: any(isinstance(e, ChangeEvent) and e.type == Change.RESET_DONE for e in events))
    assert wait_for(lambda: client.profile.angle == 900)


def test_pedal_curve_edit_sends_page(rig):
    client, device, *_ = rig
    connect(client)
    client.write_curve("brake", 1, 1234, 4321)
    assert wait_for(lambda: device.profile().brake_curve[1] == [1234, 4321])
    page4 = [p for p in device.received if p[0] == 0x52 and p[2] == 4]
    assert page4 and page4[-1][1] == C.MODE_PC_DINPUT


def test_test_mode_streams_telemetry_and_stops(rig):
    client, device, transport, events = rig
    connect(client)
    client.toggle_test_mode(True)
    assert wait_for(lambda: sum(isinstance(e, TestEvent) for e in events) > 5)
    snap = [e for e in events if isinstance(e, TestEvent)][-1].snapshot
    assert 0 <= snap.angle <= 255 and snap.gear in list("123456RN")
    client.toggle_test_mode(False)
    assert wait_for(lambda: not device.testing)
    count = sum(isinstance(e, TestEvent) for e in events)
    time.sleep(0.15)
    assert sum(isinstance(e, TestEvent) for e in events) - count <= 2


def test_writes_are_paced(rig):
    client, device, *_ = rig
    client.write_interval = 0.05
    connect(client)
    stamps = []
    orig = device.handle

    def spy(p):
        stamps.append(time.monotonic())
        return orig(p)

    device.handle = spy
    client.write_angle(300)
    client.write_mapping(12, 13)
    client.write_mapping(13, 12)
    assert wait_for(lambda: len(stamps) >= 3)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.045 for g in gaps), gaps


def test_link_loss_triggers_reconnect(rig):
    client, device, transport, events = rig
    client.auto_reconnect = True
    connect(client)
    transport.simulate_link_loss()
    assert wait_for(lambda: any(isinstance(e, ConnEvent) and e.state == ConnState.RECONNECTING for e in events))
    assert wait_for(lambda: client.state == ConnState.READY, timeout=8)


def test_user_disconnect_does_not_reconnect(rig):
    client, device, transport, events = rig
    connect(client)
    client.disconnect().result(3)
    assert client.state == ConnState.DISCONNECTED
    time.sleep(0.3)
    assert client.state == ConnState.DISCONNECTED
    assert not client.write_profile(DeviceProfile(), 1)  # writes are ignored while offline


def test_failed_connect_reports_error():
    transport = MockTransport(latency=0.001)
    transport.fail_next_connect = True
    client = WheelClient(transport, write_interval=0.01)
    errors = []
    client.add_listener(errors.append)
    try:
        client.connect(SIM_ADDRESS).result(3)
        assert client.state == ConnState.DISCONNECTED
        assert "GATT" in client.last_error
    finally:
        client.shutdown()
