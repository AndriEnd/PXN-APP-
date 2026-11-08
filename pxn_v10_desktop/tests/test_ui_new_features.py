"""Penyesuaian per template, gigi R shifter A7 (tombol 8), dan halaman Speedometer (Qt offscreen)."""

import shutil
import socket
import tempfile
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pxn_v10.core.ffb_advanced import LUT_PRESETS, compile_to_wheel  # noqa: E402
from pxn_v10.core.templates import get_template  # noqa: E402
from pxn_v10.telemetry import simulator  # noqa: E402
from pxn_v10.usb import config as U  # noqa: E402
from pxn_v10.usb.joystick import JoyInfo, JoyState  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from pxn_v10.ui import theme

    qapp = QApplication.instance() or QApplication([])
    qapp.setStyleSheet(theme.stylesheet())
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
    tmp = tempfile.mkdtemp(prefix="pxn_ui3_")
    monkeypatch.setenv("PXN_V10_DATA_DIR", tmp)
    from pxn_v10.ui.context import AppContext
    from pxn_v10.ui.main_window import MainWindow

    ctx = AppContext(simulator=True)
    w = MainWindow(ctx)
    w.show()
    yield w
    ctx.shutdown()
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    shutil.rmtree(tmp, ignore_errors=True)


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------- template: penyesuaian per template
def test_template_edits_are_remembered_per_template_and_level(app, win):
    page = win.pages["template"]
    page.load_spec("drift", "pro")
    default = get_template("drift", "pro")
    assert not page.is_modified() and not page.mod_chip.isVisibleTo(page)
    page.base_sliders["damping"].spin.setValue(60)
    page.adv_sliders["road_effect"].spin.setValue(77)
    page.reverse.setChecked(True)
    page.reverse.clicked.emit()
    assert page.is_modified() and page.mod_chip.isVisibleTo(page) and page.b_reset.isEnabled()
    stored = win.ctx.settings.get("template_overrides")["drift/pro"]
    assert stored["base"]["damping"] == 60 and stored["base"]["ffb_reverse"] == 1
    assert stored["adv"]["road_effect"] == 77
    # pindah template lain lalu kembali: penyesuaian tidak hilang, template lain tidak ikut berubah
    page.load_spec("race", "beginner")
    assert page.base.damping == get_template("race", "beginner").damping and not page.is_modified()
    page.load_spec("drift", "advanced")
    assert page.base.damping == get_template("drift", "advanced").damping
    page.load_spec("drift", "pro")
    assert page.base.damping == 60 and page.adv.road_effect == 77 and page.base.ffb_reverse == 1
    assert page.base_sliders["damping"].value() == 60 and page.reverse.isChecked()
    assert page.base.spring == default.spring  # nilai lain tetap bawaan


def test_template_customisation_survives_restart_and_reset_restores_defaults(app, win):
    from pxn_v10.ui.pages.templates_page import TemplatesPage

    page = win.pages["template"]
    page.load_spec("rally", "advanced")
    page.base_sliders["angle"].spin.setValue(540)
    page.lut_combo.setCurrentIndex(page.lut_combo.findData("soft"))
    page._lut_preset(page.lut_combo.currentIndex())
    fresh = TemplatesPage(win.ctx)  # instans baru = aplikasi dibuka ulang (setelan dibaca dari penyimpanan)
    fresh.load_spec("rally", "advanced")
    assert fresh.base.angle == 540 and fresh.adv.lut == list(LUT_PRESETS["soft"][1]) and fresh.is_modified()
    assert compile_to_wheel(fresh.base, fresh.adv).profile.ffb == round(fresh.base.ffb * fresh.adv.lut_gain())
    fresh.reset_template()
    spec = get_template("rally", "advanced")
    assert fresh.base.angle == spec.angle and fresh.adv == spec.advanced() and not fresh.is_modified()
    assert "rally/advanced" not in win.ctx.settings.get("template_overrides")
    assert not fresh.mod_chip.isVisibleTo(fresh) and not fresh.b_reset.isEnabled()


def test_setting_a_value_back_to_default_clears_the_override(app, win):
    page = win.pages["template"]
    page.load_spec("daily", "pro")
    original = get_template("daily", "pro").spring
    page.base_sliders["spring"].spin.setValue(original + 10)
    assert "daily/pro" in win.ctx.settings.get("template_overrides")
    page.base_sliders["spring"].spin.setValue(original)
    assert "daily/pro" not in win.ctx.settings.get("template_overrides") and not page.is_modified()


def test_custom_mode_keeps_its_own_settings_and_corrupt_overrides_are_ignored(app, win):
    page = win.pages["template"]
    page.load_spec("custom")
    page.base_sliders["ffb"].spin.setValue(33)
    page.load_spec("f1", "pro")
    page.load_spec("custom")
    assert page.base.ffb == 33
    win.ctx.settings.set("template_overrides", {"f1/pro": {"base": {"angle": "abc", "bogus": 5}, "adv": "x"}})
    page.load_spec("f1", "pro")  # tidak crash, memakai bawaan
    assert page.base.angle == 270


# -------------------------------------------------------------------------- shifter: R = tombol 8
def test_a7_shifter_reverse_is_button_8(app, win):
    ds = win.ctx.usb_settings("11FF:B772", "shifter")  # perangkat belum pernah disimpan
    assert ds.shifter.gears["R"] == 7 and [ds.shifter.gears[g] for g in "123456"] == [0, 1, 2, 3, 4, 5]
    dec = U.ShifterDecoder(ds.shifter)
    assert dec.update(JoyState([], 1 << 7)) == "R"  # tombol 8 -> R (sebelumnya tetap N)
    assert dec.update(JoyState([], 1 << 2)) == "3" and dec.update(JoyState([], 0)) == "N"
    assert U.ShifterDecoder(U.DeviceSettings().shifter).update(JoyState([], 1 << 7)) == "N"  # bawaan generik tetap


def test_old_saved_default_is_migrated_but_user_choice_is_kept(app, win):
    old = U.DeviceSettings(role=U.ROLE_SHIFTER)  # setelan lama: bawaan generik, R = tombol 7
    win.ctx.save_usb_settings("11FF:B772", old)
    migrated = win.ctx.usb_settings("11FF:B772", "shifter")
    assert migrated.shifter.gears["R"] == 7
    assert win.ctx.settings.get("usb_devices")["11FF:B772"]["shifter"]["gears"]["R"] == 7  # tersimpan permanen
    mine = U.DeviceSettings(role=U.ROLE_SHIFTER)
    mine.shifter.gears["R"] = 9  # pengguna memilih sendiri tombol 10
    win.ctx.save_usb_settings("11FF:B772", mine)
    assert win.ctx.usb_settings("11FF:B772", "shifter").shifter.gears["R"] == 9
    other = U.DeviceSettings(role=U.ROLE_SHIFTER)  # perangkat lain tidak tersentuh
    win.ctx.save_usb_settings("1234:0001", other)
    assert win.ctx.usb_settings("1234:0001", "shifter").shifter.gears["R"] == 6


def test_usb_page_shows_gear_r_for_the_a7_button_8(app, win):
    b = win.ctx.usb_backend
    b.add(JoyInfo(5, 0x11FF, 0xB772, "A7 Gear Shift", (0, 1), ((0, 65535),) * 2, 10, False))
    win.ctx.usb_monitor.scan_once()
    page = win.pages["usb"]
    pump(app, lambda: any(d.key == "11FF:B772" for d in page.devices))
    page.select("11FF:B772")
    win.show_page("usb")
    b.animated.pop(5, None)
    b.states[5] = JoyState([32767, 32767], 1 << 7)
    page._poll()
    assert page.gear.text == "R" and page.pattern._gear == "R"
    assert page.gear_labels["R"].text() == "Tombol 8"


# --------------------------------------------------------------------------------- speedometer
def test_speedometer_demo_mode_drives_the_gauge(app, win):
    page = win.pages["speedo"]
    assert "speedo" in win.nav and win.nav["speedo"].isEnabled()  # tidak butuh koneksi setir
    page.src_bar.set_current("demo")
    win.show_page("speedo")
    assert pump(app, lambda: page.last is not None and page.last.source == "demo", 3)
    assert page.chip.text() == "DEMO" and page.gear.text in list("N123456")
    win.show_page("connect")  # menyembunyikan halaman menghentikan sumber data
    assert not page.demo_timer.isActive() and not page.watch.isActive()


def test_speedometer_receives_real_udp_and_converts_units(app, win):
    page = win.pages["speedo"]
    port = free_udp_port()
    page.port_spin.setValue(port)
    page.src_bar.set_current("forza")
    win.show_page("speedo")
    assert page.receiver is not None and page.receiver.running
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pkt = simulator.build_forza_packet(speed_kmh=150, rpm=4000, max_rpm=8000, gear=4, lap=1, lap_time=61.5,
                                       best_lap=60.25)
    for _ in range(3):
        tx.sendto(pkt, ("127.0.0.1", port))
        pump(app, timeout=0.15)
    tx.close()
    assert pump(app, lambda: page.last is not None and page.last.source == "forza", 3)
    assert page.gauge.speed == pytest.approx(150, abs=0.1) and page.gear.text == "4"
    assert page.leds.lit == 12 and "Lap 2" in page.lap_label.text()
    assert "01:01.500" in page.lap_time.text() and "01:00.250" in page.best_lap.text()
    page.unit_bar.set_current("mph")
    assert page.gauge.speed == pytest.approx(150 * 0.621371, abs=0.1) and page.gauge._unit == "mph"
    page.scale_bar.set_current("200")
    assert page.gauge._max == 200.0
    assert win.ctx.settings.get("telemetry_unit") == "mph" and win.ctx.settings.get("telemetry_port") == port


def test_speedometer_reports_a_busy_port(app, win):
    page = win.pages["speedo"]
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind(("0.0.0.0", 0))
    try:
        page.port_spin.setValue(holder.getsockname()[1])
        page.src_bar.set_current("dirt")
        win.show_page("speedo")
        assert page.receiver is None and "tidak dapat dipakai" in page.status.text() and page.chip.text() == "ERROR"
    finally:
        holder.close()
    page.src_bar.set_current("demo")
    assert page.port_spin.isEnabled() is False
