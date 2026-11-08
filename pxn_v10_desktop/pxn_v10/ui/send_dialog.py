"""'SENDING → COMPLETE' dialog used whenever a whole profile is written to the wheel
(V10ProfileActivity.writeProfile + TutorialDialog.sending()/complete())."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QProgressBar

from ..core import constants as C
from ..core.events import Change
from ..core.ffb_advanced import PARAM_LABELS, FfbAdvanced, compile_to_wheel
from ..core.models import DeviceProfile
from . import theme
from .context import AppContext
from .widgets.common import StyledDialog, button, label


def adv_summary(base: DeviceProfile, profile: DeviceProfile) -> str:
    parts = []
    for p, title in PARAM_LABELS.items():
        d = int(getattr(profile, p)) - int(getattr(base, p))
        if d:
            parts.append(f"{title} {getattr(base, p)}→{getattr(profile, p)}")
    return ", ".join(parts)


def send_profile(parent, ctx: AppContext, profile: DeviceProfile, mode: int, name: str = "",
                 tutorial: str = "", adv: FfbAdvanced | None = None) -> bool:
    """Write ``profile`` (6 pages of 20 bytes) to the wheel. Returns True when the transfer finished.

    With ``adv`` the advanced FFB settings are first translated to firmware parameters
    (``compile_to_wheel``) and the translated profile is what is written."""
    client = ctx.client
    compiled = None
    if adv is not None and adv.enabled:
        compiled = compile_to_wheel(profile, adv, mode)
        profile = compiled.profile
    if not client.is_ready:
        ctx.toast("Setir belum terhubung — tidak dapat mengirim preset.", "error")
        return False

    d = StyledDialog(parent, "Mengirim preset" if not name else f"Mengirim “{name}”", width=460)
    status = label("Mengirim 6 halaman konfigurasi ke setir…", "dim", wrap=True)
    d.root.addWidget(status)
    bar = QProgressBar()
    bar.setRange(0, 0)  # busy indicator
    bar.setTextVisible(False)
    d.root.addWidget(bar)
    mode_note = ""
    cur = client.device_state.mode
    if cur in C.SWITCHABLE_MODES and mode in C.SWITCHABLE_MODES and cur != mode:
        mode_note = f"Mode setir akan diganti ke {C.MODE_LONG_NAMES[mode]} setelah pengiriman."
    elif cur != mode and not (cur in C.SWITCHABLE_MODES and mode in C.SWITCHABLE_MODES):
        mode_note = (f"Preset ini untuk mode {C.MODE_NAMES.get(mode, mode)}, sedangkan setir sedang di mode "
                     f"{C.MODE_NAMES.get(cur, cur)} (mode konsol tidak dapat diganti dari aplikasi).")
    if mode_note:
        d.root.addWidget(label(mode_note, "muted", wrap=True))
    if compiled is not None and compiled.applied:
        txt = adv_summary(compiled.base, compiled.profile) or "tidak ada perubahan nilai"
        d.root.addWidget(label("FFB lanjutan diterjemahkan ke parameter setir: " + txt
                               + (chr(10) + compiled.note if compiled.note else ""), "muted", wrap=True))
    if tutorial:
        tut = label(tutorial, "dim", wrap=True)
        tut.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 12px;")
        d.root.addWidget(tut)
    close = button("Tutup", "primary")
    close.setEnabled(False)
    close.clicked.connect(d.accept)
    d.buttons.addWidget(close)
    d.finish()

    state = {"done": False}

    def on_change(kind: int, _detail: int) -> None:
        if kind == Change.PROFILE_WRITTEN and not state["done"]:
            state["done"] = True
            bar.setRange(0, 1)
            bar.setValue(1)
            status.setText("SELESAI — preset telah dikirim ke setir.")
            status.setStyleSheet(f"color: {theme.GREEN}; font-weight: 700;")
            close.setEnabled(True)
            close.setFocus()
            QTimer.singleShot(1400, lambda: d.accept() if d.isVisible() and not tutorial else None)

    ctx.bridge.changed.connect(on_change)
    if not client.write_profile(profile, mode):
        ctx.bridge.changed.disconnect(on_change)
        return False
    def on_timeout() -> None:  # never leave the dialog hanging, and never claim success without proof
        if d.isVisible() and not state["done"]:
            bar.setRange(0, 1)
            status.setText("Tidak ada konfirmasi dari setir (timeout). Periksa koneksi lalu coba kirim ulang.")
            status.setStyleSheet(f"color: {theme.RED}; font-weight: 700;")
            close.setEnabled(True)

    QTimer.singleShot(15000, on_timeout)
    d.exec()
    try:
        ctx.bridge.changed.disconnect(on_change)
    except (RuntimeError, TypeError):
        pass
    if state["done"]:
        ctx.toast("Preset terkirim ke setir", "ok")
    return state["done"]
