"""Halaman Template & FFB, Perangkat USB, dan pemilih jalur koneksi (Qt offscreen, setir/USB simulasi)."""

import shutil
import tempfile
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel  # noqa: E402

from pxn_v10.ble.mock_transport import SIM_ADDRESS  # noqa: E402
from pxn_v10.core import constants as C  # noqa: E402
from pxn_v10.core.ffb_advanced import LUT_PRESETS, compile_to_wheel  # noqa: E402
from pxn_v10.core.templates import get_template  # noqa: E402
from pxn_v10.ini import mapper as M  # noqa: E402
from pxn_v10.ini.document import IniDocument  # noqa: E402
from pxn_v10.usb import config as U  # noqa: E402
from pxn_v10.usb.joystick import JoyState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from pxn_v10.ui import theme

    qapp = QApplication.instance() or QApplication([])
    qapp.setStyleSheet(theme.stylesheet())  # sekali per modul: setStyleSheet memoles ulang semua widget yang hidup
    return qapp


def pump(app, cond=None, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond is not None and cond():
            return True
        time.sleep(0.01)
    return cond is None


@pytest.fixture
def win(app, monkeypatch):
    tmp = tempfile.mkdtemp(prefix="pxn_ui2_")
    monkeypatch.setenv("PXN_V10_DATA_DIR", tmp)
    from pxn_v10.ui.context import AppContext
    from pxn_v10.ui.main_window import MainWindow

    ctx = AppContext(simulator=True)
    ctx.client.write_interval = 0.01
    ctx.client.ack_timeout = 0.2
    w = MainWindow(ctx)
    w.show()
    yield w
    ctx.shutdown()
    w.close()
    w.deleteLater()  # jangan biarkan window bocor: tes berikutnya jadi makin lambat
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    shutil.rmtree(tmp, ignore_errors=True)


def connect(app, win):
    win.ctx.client.connect(SIM_ADDRESS)
    assert pump(app, lambda: win.ctx.client.profile_synced), "no sync"
    pump(app, timeout=0.3)


def auto_close_send_dialog(app, monkeypatch):
    from pxn_v10.ui.widgets.common import StyledDialog

    def fake_exec(self):
        self.show()
        pump(app, lambda: "SELESAI" in "".join(w.text() for w in self.findChildren(QLabel)), 8)
        self.accept()
        return QDialog.Accepted

    monkeypatch.setattr(StyledDialog, "exec", fake_exec)


# ------------------------------------------------------------------------------------ template
def test_new_pages_are_in_the_sidebar_and_need_no_connection(app, win):
    for key in ("template", "usb"):
        assert key in win.pages and win.nav[key].isEnabled()
        win.show_page(key)
        assert win.stack.currentWidget() is win.pages[key]


def test_selecting_a_template_loads_sliders_and_preview(app, win):
    page = win.pages["template"]
    page.load_spec("drift", "pro")
    spec = get_template("drift", "pro")
    assert page.base_sliders["angle"].value() == 900 and page.base_sliders["spring"].value() == spec.spring
    assert page.adv_sliders["slip_effect"].value() == spec.slip
    assert page.lut.values() == list(LUT_PRESETS["detail"][1])
    assert page.lut_combo.currentData() == "detail"
    res = compile_to_wheel(spec.base_profile(), spec.advanced())
    assert page.res_rows["friction"][0].text().endswith(f"{res.profile.friction}%")
    page.load_spec("f1", "beginner")
    assert page.base_sliders["angle"].value() == 270
    page.load_spec("custom")
    assert page.spec.key == "custom" and not page.levels.isVisibleTo(page)


def test_group_and_level_buttons_drive_the_draft(app, win):
    page = win.pages["template"]
    page.groups.set_current("rally")
    page.levels.set_current("pro")
    assert page.spec.key == "rally" and page.spec.level == "pro" and page.base.angle == 640
    page.levels.set_current("beginner")
    assert page.base.angle == 900


def test_editing_advanced_values_updates_the_firmware_preview(app, win):
    page = win.pages["template"]
    page.load_spec("custom")
    before = page.result.profile.damping
    page.adv_sliders["smoothing"].spin.setValue(60)  # sama dengan mengetik nilai
    assert page.adv.smoothing == 60 and page.result.profile.damping > before
    page.lut_combo.setCurrentIndex(page.lut_combo.findData("soft"))
    page._lut_preset(page.lut_combo.currentIndex())
    assert page.adv.lut == list(LUT_PRESETS["soft"][1]) and page.result.profile.ffb < page.base.ffb
    page.lut._vals[2] = 45  # seret titik tengah lalu lepas
    page.lut.valuesChanged.emit(page.lut.values())
    assert page.lut_combo.currentData() == "custom"
    page.adv_enable.setChecked(False)
    page.adv_enable.clicked.emit()
    assert not page.result.applied and page.result.profile == page.base


def test_apply_to_wheel_keeps_keymap_and_curves(app, win, monkeypatch):
    connect(app, win)
    dev = win.ctx.client.transport.device
    win.ctx.client.write_mapping(12, 13)
    pump(app, lambda: dev.profile().keymap.get(12) == 13)
    page = win.pages["template"]
    page.load_spec("f1", "pro")
    auto_close_send_dialog(app, monkeypatch)
    assert page.apply_to_wheel()
    spec = get_template("f1", "pro")
    want = compile_to_wheel(spec.base_profile(), spec.advanced()).profile
    got = dev.profile(1)
    assert (got.angle, got.ffb, got.spring, got.damping, got.friction, got.inertia) == (
        270, want.ffb, want.spring, want.damping, want.friction, want.inertia)
    assert got.keymap.get(12) == 13  # pemetaan tombol milik setir tidak tertimpa
    assert page.b_apply.isEnabled() and page.target_chip.text().startswith("SETIR TERHUBUNG")


def test_apply_without_wheel_is_refused(app, win):
    page = win.pages["template"]
    assert not page.b_apply.isEnabled()
    assert page.apply_to_wheel() is False


def test_save_preset_stores_profile_and_advanced_and_resends_compiled(app, win, monkeypatch):
    import pxn_v10.ui.pages.templates_page as tp

    page = win.pages["template"]
    page.load_spec("rally", "advanced")
    monkeypatch.setattr(tp, "prompt", lambda *a, **k: "Rally ku")
    page.save_as_preset()
    saved = win.ctx.db.list(platform=C.PLATFORM_PC)
    assert [g.name for g in saved] == ["Rally ku"]
    spec = get_template("rally", "advanced")
    assert saved[0].profile().angle == spec.angle and saved[0].advanced() == spec.advanced()
    # kirim dari Game Presets: nilai yang tertulis di setir adalah hasil terjemahan
    connect(app, win)
    auto_close_send_dialog(app, monkeypatch)
    win.pages["presets"].send(saved[0])
    want = compile_to_wheel(saved[0].profile(), saved[0].advanced()).profile
    assert pump(app, lambda: win.ctx.client.transport.device.profile(1).damping == want.damping)
    assert win.ctx.client.transport.device.profile(1).friction == want.friction


def test_export_ini_roundtrips_into_the_ini_mapper(app, win, monkeypatch, tmp_path):
    import pxn_v10.ui.pages.templates_page as tp

    page = win.pages["template"]
    page.load_spec("daily", "beginner")
    target = tmp_path / "daily.ini"
    monkeypatch.setattr(tp, "pick_ini_save", lambda *a, **k: str(target))
    page.export_ini()
    res = M.extract(IniDocument.load(str(target)))
    spec = get_template("daily", "beginner")
    assert res.ffb_adv == spec.advanced() and res.scalars["angle"] == spec.angle and not res.warnings


def test_pull_from_wheel_uses_current_values_as_base(app, win):
    connect(app, win)
    win.ctx.client.write_angle(450)
    pump(app, lambda: win.ctx.client.profile.angle == 450)
    page = win.pages["template"]
    page.pull_from_wheel()
    assert page.base.angle == 450 and page.base_sliders["angle"].value() == 450


# ---------------------------------------------------------------------------------------- USB
def backend(win):
    return win.ctx.usb_backend


def select_role(page, role):
    key = next(d.key for d in page.devices if page.ctx.usb_settings(d.key, d.guessed_role).role == role)
    page.select(key)
    return page.dev


def freeze(win, slot, state):
    b = backend(win)
    b.animated.pop(slot, None)
    b.states[slot] = state


def test_usb_page_lists_demo_devices_with_guessed_roles(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    assert pump(app, lambda: len(page.devices) == 3)
    roles = {d.name: win.ctx.usb_settings(d.key, d.guessed_role).role for d in page.devices}
    assert sorted(roles.values()) == [U.ROLE_HANDBRAKE, U.ROLE_SHIFTER, U.ROLE_WHEEL]
    assert page.count_label.text() == "3 perangkat terdeteksi" and not page.empty.isVisibleTo(page)


def test_usb_shifter_test_shows_the_gear(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_SHIFTER)
    win.show_page("usb")
    freeze(win, dev.joy.slot, JoyState([], 1 << 2))
    page._poll()
    assert page.pattern._gear == "3" and page.gear.text == "3" and page.grid.pressed() == [2]
    freeze(win, dev.joy.slot, JoyState([], 1 << 6))
    page._poll()
    assert page.gear.text == "R"
    freeze(win, dev.joy.slot, JoyState([], 0))
    page._poll()
    assert page.gear.text == "N"


def test_usb_handbrake_calibration_and_persistence(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_HANDBRAKE)
    win.show_page("usb")
    slot = dev.joy.slot
    freeze(win, slot, JoyState([30000], 0))
    page._poll()
    assert page.hand_chip.text() == "DITARIK" and 0.4 < page.b_hand._v < 0.5
    # kalibrasi: 0% pada nilai sekarang, 100% pada 60000
    page._set_extent(page.row_hand, lambda: page.ds.handbrake.cal, "min")
    freeze(win, slot, JoyState([60000], 0))
    page._set_extent(page.row_hand, lambda: page.ds.handbrake.cal, "max")
    page.row_hand.invert.setChecked(True)  # sama dengan klik pada kotak centang
    page._poll()
    assert page.b_hand._v == pytest.approx(0.0, abs=1e-6)  # 60000 = ujung terbalik
    saved = win.ctx.settings.get("usb_devices")[dev.key]["handbrake"]["cal"]
    assert saved["raw_min"] == 30000 and saved["raw_max"] == 60000 and saved["invert"] is True
    # perangkat yang sama dimuat ulang dengan kalibrasi tersimpan
    page.select(page.devices[0].key)
    page.select(dev.key)
    assert page.ds.handbrake.cal.raw_min == 30000 and page.row_hand.invert.isChecked()


def test_usb_axis_detect_wizard_sets_axis_and_range(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_WHEEL)
    win.show_page("usb")
    slot = dev.joy.slot
    freeze(win, slot, JoyState([32768, 0, 0, 0], 0))
    page.ds.wheel.acc.axis = 3  # sengaja salah
    page._detect_axis(page.row_acc, lambda: page.ds.wheel.acc)
    for v in (0, 20000, 40000, 65535):
        freeze(win, slot, JoyState([32768, v, 0, 0], 0))
        page._poll()
    page._axis_probe["end"] = time.monotonic() - 1
    page._poll()
    cal = page.ds.wheel.acc
    assert cal.axis == 1 and (cal.raw_min, cal.raw_max) == (0, 65535) and page._axis_probe is None
    assert win.ctx.settings.get("usb_devices")[dev.key]["wheel"]["acc"]["axis"] == 1
    # setir: sumbu kemudi memutar gauge dan menampilkan derajat
    freeze(win, slot, JoyState([65535, 0, 0, 0], 0))
    page._poll()
    assert page.b_steer._v == pytest.approx(1.0) and page.b_steer._text == "+450°"


def test_usb_button_learn_assigns_gear_and_is_exclusive(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_SHIFTER)
    win.show_page("usb")
    slot = dev.joy.slot
    freeze(win, slot, JoyState([], 0))
    btn = page.gear_learn["1"]
    page._learn_button(btn, lambda idx: page._set_gear("1", idx))
    assert btn.text() == "Tekan tombol…" and not btn.isEnabled()
    freeze(win, slot, JoyState([], 1 << 5))
    page._poll()
    assert page.ds.shifter.gears["1"] == 5 and btn.isEnabled() and page.gear_labels["1"].text() == "Tombol 6"
    assert "6" not in page.ds.shifter.gears  # tombol 6 sebelumnya milik gigi 6 -> dilepas dari gigi itu
    freeze(win, slot, JoyState([], 1 << 5))
    page._poll()
    assert page.gear.text == "1"
    # sekuensial
    page.shift_kind.setCurrentIndex(1)
    assert page.ds.shifter.kind == "seq" and not page.seq_box.isHidden() and page.h_box.isHidden()
    assert win.ctx.settings.get("usb_devices")[dev.key]["shifter"]["kind"] == "seq"


def test_usb_button_learn_times_out_cleanly(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_SHIFTER)
    win.show_page("usb")
    freeze(win, dev.joy.slot, JoyState([], 0))
    btn = page.gear_learn["2"]
    page._learn_button(btn, lambda idx: page._set_gear("2", idx))
    page._btn_probe["end"] = time.monotonic() - 1
    page._poll()
    assert btn.isEnabled() and btn.text() == "Pelajari" and page._btn_probe is None


def test_usb_hotplug_updates_list_and_selection(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    page.select(page.devices[2].key)
    backend(win).remove(2)
    win.ctx.usb_monitor.scan_once()
    assert pump(app, lambda: len(page.devices) == 2)
    assert page.dev is not None and page.dev.key in [d.key for d in page.devices]  # pilihan pindah, tidak crash


def test_role_override_is_saved_and_changes_the_view(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    dev = select_role(page, U.ROLE_HANDBRAKE)
    page.role_combo.setCurrentIndex(U.ROLES.index(U.ROLE_SHIFTER))
    assert page.ds.role == U.ROLE_SHIFTER and page.t_shifter.isVisibleTo(page) and not page.t_hand.isVisibleTo(page)
    assert win.ctx.settings.get("usb_devices")[dev.key]["role"] == U.ROLE_SHIFTER


def test_reset_config_restores_defaults_but_keeps_role(app, win):
    page = win.pages["usb"]
    win.ctx.usb_monitor.scan_once()
    pump(app, lambda: len(page.devices) == 3)
    select_role(page, U.ROLE_HANDBRAKE)
    page.hand_thr.setValue(55)
    assert page.ds.handbrake.threshold == pytest.approx(0.55)
    page._reset_config()
    assert page.ds.handbrake.threshold == pytest.approx(0.10) and page.ds.role == U.ROLE_HANDBRAKE


# ---------------------------------------------------------------------------- connection link
def test_link_selector_switches_transport_and_usb_shows_clear_error(app, win):
    from pxn_v10.usb.hid_transport import HidTransport

    conn = win.pages["connect"]
    assert win.ctx.link == "sim" and conn.links.current == "sim"
    conn.links.set_current("usb")
    assert win.ctx.link == "usb" and isinstance(win.ctx.client.transport, HidTransport)
    assert not win.ctx.simulator and conn.link_note.isVisibleTo(conn)
    win.ctx.client.transport._enumerator = lambda: []  # hermetis: tanpa perangkat USB sungguhan
    conn._go_clicked()
    assert pump(app, lambda: "kabel USB" in conn.error.text())
    conn.links.set_current("sim")
    assert win.ctx.simulator and win.ctx.client.transport.__class__.__name__ == "MockTransport"
    connect(app, win)  # simulator tetap bekerja penuh setelah bolak-balik
    assert win.ctx.connected


def test_usb_link_connects_through_hid_when_wheel_answers(app, win):
    from pxn_v10.ble.mock_device import MockV10Device
    from pxn_v10.usb.hid import HidInfo
    from pxn_v10.usb.hid_transport import FakeHidIO

    conn = win.pages["connect"]
    conn.links.set_current("usb")
    dev = MockV10Device(mode=C.MODE_PC_DINPUT)
    info = HidInfo("cfg", 1, 1, "PXN-V10", "PXN", 0xFF00, 1, 64, 64)
    t = win.ctx.client.transport
    t._enumerator = lambda: [info]
    t._io_factory = lambda i: FakeHidIO(dev)
    conn._go_clicked()
    assert pump(app, lambda: "cfg" in conn.cards)  # kandidat ditampilkan, TIDAK tersambung otomatis
    assert not win.ctx.connected
    conn.cards["cfg"].findChild(type(conn.go), "primary").click()
    assert pump(app, lambda: win.ctx.client.profile_synced)
    win.ctx.client.write_angle(300)
    assert pump(app, lambda: dev.profile().angle == 300)
