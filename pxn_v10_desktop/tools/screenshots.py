"""Render every page of the app (simulator) to PNG files - used to review the UI headlessly.

    python tools/screenshots.py OUT_DIR [ini_path]
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "screenshots")
ini_path = sys.argv[2] if len(sys.argv) > 2 else ""
os.makedirs(out_dir, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="pxn_shot_")
os.environ["PXN_V10_DATA_DIR"] = tmp

from PySide6.QtWidgets import QApplication  # noqa: E402

from pxn_v10.ble.mock_transport import SIM_ADDRESS  # noqa: E402
from pxn_v10.ui import theme  # noqa: E402
from pxn_v10.ui.context import AppContext  # noqa: E402
from pxn_v10.ui.main_window import MainWindow  # noqa: E402

app = QApplication([])
from PySide6.QtGui import QFontDatabase  # noqa: E402

for f in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf", "consola.ttf"):
    path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", f)
    if os.path.exists(path):
        QFontDatabase.addApplicationFont(path)
app.setStyle("Fusion")
app.setFont(theme.app_font(10))
app.setStyleSheet(theme.stylesheet())
ctx = AppContext(simulator=True)
win = MainWindow(ctx)
win.resize(1360, 860)
win.show()


def pump(ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(name: str) -> None:
    pump(150)
    win.grab().save(os.path.join(out_dir, name + ".png"))
    print("saved", name)


shot("01_connect")
ctx.client.scan(timeout=3, auto_connect=False)
pump(1200)
shot("02_connect_found")
ctx.client.connect(SIM_ADDRESS)
pump(2500)
shot("03_dashboard_wheel")
ed = win.pages["dashboard"].editor
for key in ("pedal", "lever", "brake"):
    ed.tabs.set_current(key)
    shot(f"04_dashboard_{key}")
win.show_page("test")
pump(1800)
shot("05_test")
win.show_page("presets")
pump(300)
shot("06_presets")
if ini_path:
    shutil_dir = ctx.settings.path.parent / "ini_presets"
    shutil_dir.mkdir(exist_ok=True)
    import shutil

    shutil.copyfile(ini_path, shutil_dir / "shader drift.ini")
    ini = win.pages["ini"]
    ini.reload_library(select=str(shutil_dir / "shader drift.ini"))
    win.show_page("ini")
    pump(400)
    shot("07_ini_params")
    ini.search.setText("FFB")
    pump(200)
    shot("08_ini_search")
    ini.search.clear()
    ini.tabs.setCurrentIndex(2)
    ini._add_binding(__import__("pxn_v10.ini.mapper", fromlist=["Binding"]).Binding(
        "FFB_TWEAKS:CUSTOM_SOFT_LOCK", "DAMPER", "damping", 0.0, 0.1, 0.0, 100.0))
    pump(200)
    shot("09_ini_binding")
    ini.tabs.setCurrentIndex(1)
    pump(300)
    shot("10_ini_apply")
win.resize(1360, 1480)  # halaman template panjang: render utuh
win.show_page("template")
pump(300)
shot("12_template_race")
win.pages["template"].load_spec("drift", "pro")
pump(300)
shot("13_template_drift_pro")
win.pages["template"].base_sliders["damping"].spin.setValue(62)  # tampilkan penanda "dimodifikasi"
pump(300)
shot("13b_template_modified")
win.pages["template"].reset_template()
win.resize(1360, 860)
# speedometer (sumber Demo)
win.show_page("speedo")
win.pages["speedo"].src_bar.set_current("demo")
pump(7500)
shot("21_speedometer_demo")
win.show_page("template")
# halaman USB (perangkat demo simulasi)
usb = win.pages["usb"]
ctx.usb_monitor.scan_once()
pump(300)
win.show_page("usb")
pump(900)
shot("14_usb_wheel_test")
usb.tabs.set_current("config")
pump(200)
shot("15_usb_wheel_config")
for role, tab, name in (("shifter", "test", "16_usb_shifter_test"), ("shifter", "config", "17_usb_shifter_config"),
                        ("handbrake", "test", "18_usb_handbrake_test"), ("handbrake", "config", "19_usb_handbrake_config")):
    key = next(d.key for d in usb.devices if ctx.usb_settings(d.key, d.guessed_role).role == role)
    if usb.dev is None or usb.dev.key != key:
        usb.select(key)
    usb.tabs.set_current(tab)
    pump(1300)
    shot(name)
ctx.use_link("usb")
win.show_page("connect")
pump(300)
shot("20_connect_usb")
win.show_page("info")
pump(300)
shot("11_info")
ctx.shutdown()
print("done")
