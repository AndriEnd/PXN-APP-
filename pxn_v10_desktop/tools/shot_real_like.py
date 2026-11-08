"""Renders the dashboard as it looks with the firmware values seen on a real V10 (angle_mode 0, zero curves)."""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PXN_V10_DATA_DIR"] = tempfile.mkdtemp(prefix="pxn_shot_")
out = sys.argv[1]
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from pxn_v10.ble.mock_transport import SIM_ADDRESS
from pxn_v10.ui import theme
from pxn_v10.ui.context import AppContext
from pxn_v10.ui.main_window import MainWindow
app = QApplication([])
for f in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
    QFontDatabase.addApplicationFont(os.path.join("C:/Windows/Fonts", f))
app.setStyle("Fusion"); app.setFont(theme.app_font(10)); app.setStyleSheet(theme.stylesheet())
ctx = AppContext(simulator=True)
dev = ctx.client.transport.device
dev.state.angle_mode = 0; dev.state.lever_state = 0; dev.state.brake_state = 0; dev.state.pedal_state = 2
p = dev.profile(); p.angle, p.spring, p.damping, p.friction, p.inertia = 270, 60, 0, 10, 60
p.brake_curve = [[0, 0]] * 4
win = MainWindow(ctx); win.resize(1360, 860); win.show()
def pump(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
ctx.client.connect(SIM_ADDRESS); pump(2500)
win.grab().save(os.path.join(out, "r1_wheel.png"))
ed = win.pages["dashboard"].editor
ed.tabs.set_current("pedal"); ed.curve_tabs.set_current("brake"); pump(300)
win.grab().save(os.path.join(out, "r2_pedal_zero.png"))
ctx.shutdown(); print("ok")
