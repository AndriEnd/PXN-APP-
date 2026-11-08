"""Headless UI tests (Qt offscreen) running the real windows against the simulated wheel."""

import shutil
import tempfile
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from pxn_v10.ble.mock_transport import SIM_ADDRESS  # noqa: E402
from pxn_v10.core import constants as C  # noqa: E402
from pxn_v10.core.models import DeviceProfile  # noqa: E402
from pxn_v10.ini import mapper as M  # noqa: E402
from pxn_v10.ini import schema as S  # noqa: E402
from pxn_v10.storage.database import GameProfile  # noqa: E402

USER_INI = Path(__file__).resolve().parents[2] / "shader PXN V10 Ai 4 (Drift)).ini"


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
    tmp = tempfile.mkdtemp(prefix="pxn_ui_")
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


def test_connect_flow_opens_dashboard_with_hardware_tabs(app, win):
    assert win.pages["connect"].go.text() == "GO"
    assert not win.nav["dashboard"].isEnabled()  # dashboard / test need a connection
    connect(app, win)
    assert win.nav["dashboard"].isEnabled()
    assert win.stack.currentWidget() is win.pages["dashboard"]  # auto-navigation like the Android app
    ed = win.pages["dashboard"].editor
    assert list(ed.tabs._buttons) == ["wheel", "pedal", "lever", "brake"]
    assert win.pages["dashboard"].mode_btn.text().startswith("D-Input")
    assert ed.s_angle.value() == 900 and ed.s_ffb.value() == 100


def test_physics_sliders_follow_mode(app, win):
    connect(app, win)
    ed = win.pages["dashboard"].editor
    assert ed.s_force["spring"].isVisibleTo(ed) and ed.s_angle.isVisibleTo(ed)
    win.ctx.client.switch_mode(C.MODE_PC_XINPUT)
    pump(app, lambda: win.ctx.client.device_state.mode == C.MODE_PC_XINPUT)
    pump(app, timeout=0.4)
    assert not ed.s_force["spring"].isVisibleTo(ed)  # hidden in X-Input (PRD 5.2)
    assert ed.s_ffb.isVisibleTo(ed) and ed.physics_note.isVisibleTo(ed)
    win.ctx.client.switch_mode(C.MODE_PC_DINPUT)
    pump(app, lambda: ed.s_force["spring"].isVisibleTo(ed))
    assert ed.s_force["spring"].isVisibleTo(ed)


def test_slider_edits_reach_wheel(app, win):
    connect(app, win)
    dash = win.pages["dashboard"]
    dev = win.ctx.client.transport.device
    dash.editor.s_angle.spin.setValue(360)  # same path as typing a value
    dash.editor.s_ffb.slider.setValue(7)  # keyboard / click on the groove (70 %)
    dash.editor.reverse_switch.click()
    dash.editor.s_force["damping"].spin.setValue(40)
    assert pump(app, lambda: dev.profile().damping == 40)
    p = dev.profile()
    assert (p.angle, p.ffb, p.ffb_reverse) == (360, 70, 1)
    assert dash.editor.reverse_state.text() == "ON"


def test_remap_and_curve_edit_reach_wheel(app, win, monkeypatch):
    connect(app, win)
    ed = win.pages["dashboard"].editor
    dev = win.ctx.client.transport.device
    import pxn_v10.ui.widgets.config_editor as ce

    monkeypatch.setattr(ce, "pick_key", lambda parent, mode, physical, current: 13 if physical == 12 else None)
    ed.map_wheel.selected.emit(12)
    assert pump(app, lambda: dev.profile().keymap.get(12) == 13)
    assert win.ctx.client.profile.mapped(12) == 13
    ed.curve_tabs.set_current("brake")
    ed.chart._values[1] = [1500, 20000]
    ed.chart.pointCommitted.emit(1, 1500, 20000)
    assert pump(app, lambda: dev.profile().brake_curve[1] == [1500, 20000])


def test_factory_reset_flow(app, win, monkeypatch):
    connect(app, win)
    dash = win.pages["dashboard"]
    dev = win.ctx.client.transport.device
    win.ctx.client.write_angle(180)
    pump(app, lambda: dev.profile().angle == 180)
    import pxn_v10.ui.pages.dashboard_page as dp

    monkeypatch.setattr(dp, "confirm", lambda *a, **k: True)
    dash._factory_reset()
    assert pump(app, lambda: dash._loading is None and win.ctx.client.profile.angle == 900)
    assert dev.profile().angle == 900


def test_test_page_enters_and_leaves_test_mode(app, win):
    connect(app, win)
    dev = win.ctx.client.transport.device
    win.show_page("test")
    assert pump(app, lambda: dev.testing)
    test = win.pages["test"]
    assert pump(app, lambda: test.stream_label.text().endswith("Data langsung"))
    assert test.gear.text in list("N123456R")
    win.show_page("dashboard")
    assert pump(app, lambda: not dev.testing)


def test_disconnect_returns_to_connect_page(app, win):
    connect(app, win)
    win.ctx.client.disconnect()
    assert pump(app, lambda: win.stack.currentWidget() is win.pages["connect"])
    assert not win.nav["dashboard"].isEnabled()


def test_preset_crud_and_editor(app, win, monkeypatch):
    connect(app, win)
    page = win.pages["presets"]
    page.platforms.set_current(str(C.PLATFORM_PC))
    assert len(page.recommended) >= 14 and page.g_rec.rows.count() >= 5
    from pxn_v10.ui.pages.profile_editor import ProfileEditorDialog

    gp = GameProfile(name="My Drift", mode=C.MODE_PC_DINPUT, platform=C.PLATFORM_PC)
    gp.set_profile(DeviceProfile(angle=360))
    dlg = ProfileEditorDialog(win, win.ctx, gp)
    dlg.editor.s_angle.spin.setValue(540)
    dlg.editor.reverse_switch.click()
    dlg._save()
    saved = win.ctx.db.list(platform=C.PLATFORM_PC)
    assert [g.name for g in saved] == ["My Drift"]
    prof = saved[0].profile()
    assert prof.angle == 540 and prof.ffb_reverse == 1
    page.reload()
    assert page.g_custom.rows.count() == 1
    page.duplicate(saved[0])
    assert len(win.ctx.db.list()) == 2


def test_sending_a_preset_via_dialog(app, win, monkeypatch):
    connect(app, win)
    dev = win.ctx.client.transport.device
    from pxn_v10.ui import send_dialog
    from pxn_v10.ui.widgets.common import StyledDialog

    def fake_exec(self):
        self.show()
        pump(app, lambda: not self.isVisible() or "SELESAI" in "".join(
            w.text() for w in self.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)), 8)
        self.accept()
        return QDialog.Accepted

    monkeypatch.setattr(StyledDialog, "exec", fake_exec)
    prof = DeviceProfile(angle=270, ffb=40, spring=10, damping=20, friction=30, inertia=50)
    ok = send_dialog.send_profile(win, win.ctx, prof, C.MODE_PC_DINPUT, "Test preset")
    assert ok
    assert dev.profile(1).angle == 270 and dev.profile(1).inertia == 50


@pytest.mark.skipif(not USER_INI.exists(), reason="sample ini not present")
def test_ini_page_end_to_end_with_user_file(app, win, monkeypatch):
    connect(app, win)
    page = win.pages["ini"]
    dev = win.ctx.client.transport.device
    import pxn_v10.ui.pages.ini_page as ip

    monkeypatch.setattr(ip, "pick_ini_files", lambda *a, **k: [str(USER_INI)])
    page.import_files()
    assert page.list.count() == 1 and page.doc is not None
    assert page.doc.count() == 121
    assert page.result.empty  # nothing PXN specific in the CSP file -> needs bindings
    assert page.banner_box.isVisibleTo(page)
    assert not page.b_send.isEnabled()

    # bind CSP's FFB soft-lock damper to the wheel's damping, then it becomes sendable
    page._add_binding(M.Binding("FFB_TWEAKS:CUSTOM_SOFT_LOCK", "DAMPER", "damping", 0.0, 0.1, 0.0, 100.0))
    assert page.result.scalars == {"damping": 20}
    assert page.b_send.isEnabled()
    assert win.ctx.settings.bindings()[0].target == "damping"  # persisted

    # editing a key in the tree updates the document and the preview
    entry = page.doc.section("FFB_TWEAKS:CUSTOM_SOFT_LOCK").find("DAMPER")
    entry.value = "0.05"
    page._doc_edited()
    assert page.result.scalars == {"damping": 50}
    assert page.dirty

    # add the native sections from the wheel's current values and push to the device
    page.add_native_sections()
    assert page.result.native
    page.doc.set(S.SEC_WHEEL, "ANGLE", "420")
    page.doc.set(S.SEC_WHEEL, "FFB", "65")
    page._doc_edited()
    from pxn_v10.ui.widgets.common import StyledDialog

    def fake_exec(self):
        self.show()
        pump(app, lambda: "SELESAI" in "".join(
            w.text() for w in self.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)), 8)
        self.accept()
        return QDialog.Accepted

    monkeypatch.setattr(StyledDialog, "exec", fake_exec)
    page.send_to_wheel()
    p = dev.profile(1)
    assert p.angle == 420 and p.ffb == 65
    # the binding (0.05 on 0..0.1 -> 50) wins for damping because it is defined last
    assert p.damping == 50
    # saving writes to the library copy only; the user's original file is untouched
    original = USER_INI.read_bytes()
    page.save()
    assert USER_INI.read_bytes() == original
    assert "[PXN_V10:WHEEL]" in page.path.read_text(encoding="utf-8")


def test_ini_embedded_value_roundtrip(app, win):
    from pxn_v10.ini.document import IniDocument, decode_embedded
    from pxn_v10.ui.widgets.ini_tree import IniTreeWidget

    doc = IniDocument.parse("[A:B]\nSCRIPT_SETTINGS=W1NFVFRJTkdTXQ0KZnJvbnRGb3JjZUs9MQ0KZGFtcEs9MC4wMg0K\nX=1\n")
    tree = IniTreeWidget()
    tree.set_document(doc)
    tree.expandAll()
    leaf = tree.topLevelItem(0).child(0).child(0)
    assert leaf.text(2) == "embedded" and decode_embedded(leaf.text(1)) is not None
    leaf2 = tree.topLevelItem(0).child(0).child(1)
    leaf2.setText(1, "42")  # same path as the delegate's commit
    assert doc.get("A:B", "X") == "42" and leaf2.text(2) == "int"
    tree.apply_filter("zzz")
    assert tree.topLevelItem(0).isHidden()
    tree.apply_filter("42")
    assert not tree.topLevelItem(0).isHidden()
