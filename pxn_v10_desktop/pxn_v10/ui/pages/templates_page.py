"""Template mode (Drift / Race / Daily / Rally / F1 270° / Custom × Beginner / Advanced / Pro) dan
force feedback lanjutan (LUT, smoothing, pneumatic & mechanical trail, road / slip / kerb effects).

Semua nilai diedit pada sebuah *draf*; kolom "Hasil ke setir" memperlihatkan persis parameter firmware
yang akan ditulis (``compile_to_wheel``). Menerapkan ke setir hanya menimpa angle, FFB, reverse, dan
empat gaya fisika - keymap dan kurva pedal setir tetap dipertahankan."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...core import constants as C
from ...core.ffb_advanced import (
    LUT_PRESETS, PARAM_LABELS, FfbAdvanced, compile_to_wheel, firmware_coverage, lut_name)
from ...core.models import DeviceProfile
from ...core.templates import (
    CUSTOM_KEY, GROUP_BY_KEY, GROUPS, LEVEL_BLURBS, LEVEL_TITLES, LEVELS, TemplateSpec, custom_spec,
    get_template, template_game_profile_name)
from ...ini import mapper as M
from ...storage.database import GameProfile
from .. import theme
from ..context import AppContext
from ..ini_io import pick_ini_save
from ..send_dialog import send_profile
from ..widgets.common import CardPanel, Chip, SegmentedBar, button, info, label, prompt
from ..widgets.lut_chart import LutChart
from ..widgets.param_slider import ParamSlider, ToggleSwitch

BASE_FIELDS = (
    ("angle", "Angle", C.ANGLE_MIN, C.ANGLE_MAX, 10, "°"),
    ("ffb", "Force feedback", 0, 100, 1, "%"),
    ("spring", "Spring force", 0, 100, 1, "%"),
    ("damping", "Damping force", 0, 100, 1, "%"),
    ("friction", "Friction force", 0, 100, 1, "%"),
    ("inertia", "Inertia force", 0, 100, 1, "%"),
)
ADV_FIELDS = (
    ("smoothing", "Smoothing (filter)", 0, 100, 1, "%"),
    ("pneumatic_trail", "Pneumatic trail", 0, 100, 1, "%"),
    ("mechanical_trail", "Mechanical trail", 0, 100, 1, "%"),
    ("road_effect", "Road effect", 0, 100, 1, "%"),
    ("slip_effect", "Slip effect", 0, 100, 1, "%"),
    ("kerb_effect", "Kerb effect", 0, 100, 1, "%"),
)
HINTS = {
    "lut": ("LUT (Look-Up Table)", "Tabel yang memetakan gaya mentah dari game (sumbu mendatar) ke output motor (sumbu "
            "tegak). Lekukan ke bawah = gaya kecil lebih halus, lekukan ke atas = gaya kecil lebih terasa, puncak "
            "<100% = pembatas anti-clipping. Di setir PXN V10 LUT diterjemahkan menjadi penskalaan kekuatan FFB "
            "rata-rata (firmware tidak punya LUT sendiri)."),
    "smoothing": ("Smoothing / filter", "Menghaluskan lonjakan data FFB dari game sebelum sampai ke setir. Berguna bila "
                  "benturan atau kerb terlalu tajam sehingga gear di dalam setir berisik (clipping / rattling). "
                  "Nilai tinggi meredam spike tetapi mengurangi sedikit detail jalan."),
    "pneumatic_trail": ("Pneumatic trail", "Gaya pemulih (self-aligning) dari ban depan. Saat ban depan kehilangan grip "
                        "(understeer) gaya ini turun dan kemudi tiba-tiba terasa ringan. 50 = netral; di atas 50 "
                        "perubahan itu lebih jelas."),
    "mechanical_trail": ("Mechanical trail", "Kontribusi geometri suspensi / caster pada bobot setir. Dikombinasikan dengan "
                         "pneumatic trail, ia membantu merasakan kapan ban belakang mulai membuang (oversteer). "
                         "50 = netral."),
    "road_effect": ("Road effect", "Efek buatan (canned): getaran statis dari tekstur aspal untuk imersi tambahan."),
    "slip_effect": ("Slip effect", "Efek buatan: getaran saat ban selip."),
    "kerb_effect": ("Kerb effect", "Efek buatan: hentakan saat melindas kerb / bump."),
}


class TemplatesPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.spec: TemplateSpec = get_template("race", "advanced")
        self.base: DeviceProfile = self.spec.base_profile()
        self.adv: FfbAdvanced = self.spec.advanced()
        self._pushing = False
        self.result = compile_to_wheel(self.base, self.adv)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        host = QWidget()
        scroll.setWidget(host)
        root = QVBoxLayout(host)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(16)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label("RACIKAN FORCE FEEDBACK", "eyebrow"))
        col.addWidget(label("Template mode & FFB lanjutan", "h1"))
        head.addLayout(col, 1)
        self.target_chip = Chip("SETIR TIDAK TERHUBUNG", theme.TEXT_DIM)
        head.addWidget(self.target_chip, 0, Qt.AlignBottom)
        root.addLayout(head)

        # ---------------------------------------------------------------- template
        top = QHBoxLayout()
        top.setSpacing(16)
        tpl = CardPanel("Template mode", "Pilih jenis berkendara dan level; nilainya langsung dimuat ke draf.")
        self.groups = SegmentedBar()
        self.groups.set_items([(g.key, g.title.upper()) for g in GROUPS] + [(CUSTOM_KEY, "CUSTOM")])
        self.groups.currentChanged.connect(self._group_changed)
        tpl.body.addWidget(self.groups, 0, Qt.AlignLeft)
        self.levels = SegmentedBar()
        self.levels.set_items([(lv, LEVEL_TITLES[lv].upper()) for lv in LEVELS])
        self.levels.currentChanged.connect(self._level_changed)
        tpl.body.addWidget(self.levels, 0, Qt.AlignLeft)
        self.desc = label("", "dim", wrap=True)
        tpl.body.addWidget(self.desc)
        self.level_note = label("", "muted", wrap=True)
        self.level_note.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 10px; padding: 10px 12px;")
        tpl.body.addWidget(self.level_note)
        self.origin = label("", "muted", wrap=True)
        tpl.body.addWidget(self.origin)
        mod_row = QHBoxLayout()
        self.mod_chip = Chip("DIMODIFIKASI", theme.AMBER)
        mod_row.addWidget(self.mod_chip)
        mod_row.addStretch(1)
        self.b_reset = button("Reset ke bawaan template", "ghost",
                              tooltip="Hapus penyesuaian Anda untuk template dan level ini")
        self.b_reset.clicked.connect(self.reset_template)
        mod_row.addWidget(self.b_reset)
        tpl.body.addLayout(mod_row)
        self.persist_note = label("Penyesuaian Anda tersimpan otomatis untuk tiap template dan level; "
                                  "berpindah template tidak menghilangkannya.", "muted", wrap=True)
        tpl.body.addWidget(self.persist_note)
        tpl.body.addStretch(1)
        top.addWidget(tpl, 4)

        base_card = CardPanel("Parameter dasar", "Nilai firmware sebelum ditambah kontribusi FFB lanjutan.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.base_sliders: dict = {}
        for i, (attr, title, lo, hi, step, suffix) in enumerate(BASE_FIELDS):
            s = ParamSlider(title, lo, hi, step, suffix, hint=False)
            s.committed.connect(lambda v, a=attr: self._edit_base(a, v))
            self.base_sliders[attr] = s
            grid.addWidget(s, i // 2, i % 2)
        base_card.body.addLayout(grid)
        rev = QHBoxLayout()
        rev.addWidget(label("FFB REVERSE", "eyebrow"))
        self.reverse = ToggleSwitch()
        self.reverse.clicked.connect(self._edit_reverse)
        rev.addWidget(self.reverse)
        rev.addStretch(1)
        base_card.body.addLayout(rev)
        top.addWidget(base_card, 6)
        root.addLayout(top)

        # ----------------------------------------------------------- FFB lanjutan + hasil
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        adv_card = CardPanel("FFB lanjutan", "Pemrosesan FFB tingkat game/driver yang diterjemahkan ke firmware.")
        self.adv_enable = ToggleSwitch()
        self.adv_enable.clicked.connect(self._edit_enabled)
        adv_card.add_header_widget(label("AKTIF", "eyebrow"))
        adv_card.add_header_widget(self.adv_enable)

        lut_row = QHBoxLayout()
        lut_row.addWidget(label("LUT", "eyebrow"))
        help_lut = button("?", "icon")
        help_lut.clicked.connect(lambda: info(self, *HINTS["lut"]))
        lut_row.addWidget(help_lut)
        lut_row.addStretch(1)
        self.lut_combo = QComboBox()
        for key, (title, _vals) in LUT_PRESETS.items():
            self.lut_combo.addItem(title, key)
        self.lut_combo.addItem("Custom (geser titik)", "custom")
        self.lut_combo.activated.connect(self._lut_preset)
        lut_row.addWidget(self.lut_combo)
        adv_card.body.addLayout(lut_row)
        self.lut = LutChart()
        self.lut.valuesChanged.connect(self._lut_dragged)
        adv_card.body.addWidget(self.lut)

        agrid = QGridLayout()
        agrid.setHorizontalSpacing(12)
        agrid.setVerticalSpacing(10)
        self.adv_sliders: dict = {}
        for i, (attr, title, lo, hi, step, suffix) in enumerate(ADV_FIELDS):
            s = ParamSlider(title, lo, hi, step, suffix, hint=True)
            s.committed.connect(lambda v, a=attr: self._edit_adv(a, v))
            hint_key = {"smoothing": "smoothing", "pneumatic_trail": "pneumatic_trail",
                        "mechanical_trail": "mechanical_trail", "road_effect": "road_effect",
                        "slip_effect": "slip_effect", "kerb_effect": "kerb_effect"}[attr]
            s.hintClicked.connect(lambda k=hint_key: info(self, *HINTS[k]))
            self.adv_sliders[attr] = s
            agrid.addWidget(s, i // 2, i % 2)
        adv_card.body.addLayout(agrid)
        bottom.addWidget(adv_card, 6)

        res_card = CardPanel("Hasil ke setir", "Parameter firmware yang benar-benar ditulis.")
        self.res_rows: dict = {}
        for p, title in PARAM_LABELS.items():
            f = QFrame()
            f.setObjectName("cardInner")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(14, 10, 14, 10)
            fl.setSpacing(2)
            top_r = QHBoxLayout()
            top_r.addWidget(label(title.upper(), "eyebrow"))
            top_r.addStretch(1)
            val = label("", "h3")
            top_r.addWidget(val)
            chip = Chip("", theme.TEXT_DIM)
            top_r.addWidget(chip)
            fl.addLayout(top_r)
            why = label("", "muted", wrap=True)
            fl.addWidget(why)
            res_card.body.addWidget(f)
            self.res_rows[p] = (val, chip, why)
        self.note = label("", "muted", wrap=True)
        res_card.body.addWidget(self.note)
        self.coverage = label("", "muted", wrap=True)
        res_card.body.addWidget(self.coverage)
        res_card.body.addStretch(1)
        self.b_apply = button("Terapkan ke setir", "primary")
        self.b_apply.clicked.connect(self.apply_to_wheel)
        res_card.body.addWidget(self.b_apply)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.b_pull = button("Ambil dari setir", "ghost", tooltip="Jadikan nilai setir saat ini sebagai parameter dasar")
        self.b_pull.clicked.connect(self.pull_from_wheel)
        self.b_save = button("Simpan preset", "ghost")
        self.b_save.clicked.connect(self.save_as_preset)
        self.b_export = button("Ekspor INI", "ghost")
        self.b_export.clicked.connect(self.export_ini)
        for b in (self.b_pull, self.b_save, self.b_export):
            row.addWidget(b)
        res_card.body.addLayout(row)
        bottom.addWidget(res_card, 4)
        root.addLayout(bottom)

        ctx.bridge.connChanged.connect(lambda _e: self._refresh_target())
        ctx.bridge.changed.connect(lambda _k, _d: self._refresh_target())
        ctx.clientReplaced.connect(self._refresh_target)
        self.groups.set_current("race")
        self.levels.set_current("advanced")
        self._load_spec(self.spec)
        self._refresh_target()

    # ================================================================ state
    def _mode(self) -> int:
        c = self.ctx.client
        if c.is_ready and c.device_state.mode in C.ANGLE_FFB_MODES:
            return c.device_state.mode
        return C.MODE_PC_DINPUT

    def _group_changed(self, key: str) -> None:
        if self._pushing:
            return
        self.levels.setVisible(key != CUSTOM_KEY)
        self._load_spec(custom_spec() if key == CUSTOM_KEY else get_template(key, self.levels.current or "advanced"))

    def _level_changed(self, level: str) -> None:
        if self._pushing or self.groups.current in ("", CUSTOM_KEY):
            return
        self._load_spec(get_template(self.groups.current, level))

    def load_spec(self, key: str, level: str = "advanced") -> None:
        """Pilih template lewat kode (dan sinkronkan tombol segmen)."""
        self._pushing = True
        self.groups.set_current(key)
        if key != CUSTOM_KEY:
            self.levels.set_current(level)
        self.levels.setVisible(key != CUSTOM_KEY)
        self._pushing = False
        self._load_spec(custom_spec() if key == CUSTOM_KEY else get_template(key, level))

    def _load_spec(self, spec: TemplateSpec) -> None:
        self.spec = spec
        self.base = spec.base_profile()
        self.adv = spec.advanced()
        self._apply_override()
        g = GROUP_BY_KEY.get(spec.key)
        if g is None:
            self.desc.setText("Mode custom: mulai dari nilai netral, atau tekan “Ambil dari setir” untuk memakai nilai "
                              "setir saat ini sebagai dasar, lalu racik sendiri.")
            self.level_note.setText("Semua parameter bebas diatur. Simpan hasilnya sebagai Game Preset.")
            self.origin.setText("")
        else:
            self.desc.setText(g.description)
            self.level_note.setText(f"{LEVEL_TITLES[spec.level]}: {LEVEL_BLURBS[spec.level]}\n{g.rationale[spec.level]}")
            self.origin.setText("Titik awal racikan berdasarkan praktik umum sim racing — bukan data pabrikan dan "
                                "belum diuji pada setir fisik. Setel ulang sesuai game dan selera.")
        self._push()

    def _push(self) -> None:
        self._pushing = True
        try:
            for attr, s in self.base_sliders.items():
                s.set_value(getattr(self.base, attr))
            self.reverse.setChecked(bool(self.base.ffb_reverse))
            self.adv_enable.setChecked(self.adv.enabled)
            for attr, s in self.adv_sliders.items():
                s.set_value(getattr(self.adv, attr))
            self.lut.set_values(self.adv.lut)
            self._sync_lut_combo()
        finally:
            self._pushing = False
        self._recompute()
        self._update_modified()

    def _sync_lut_combo(self) -> None:
        name = lut_name(self.adv.lut)
        self.lut_combo.setCurrentIndex(max(0, self.lut_combo.findData(name)))

    # ===================================================== penyesuaian per template
    BASE_ATTRS = ("angle", "ffb", "spring", "damping", "friction", "inertia", "ffb_reverse")

    def override_key(self, spec: TemplateSpec | None = None) -> str:
        spec = spec or self.spec
        return f"{spec.key}/{spec.level}"

    def overrides(self) -> dict:
        return dict(self.ctx.settings.get("template_overrides", {}) or {})

    def _apply_override(self) -> None:
        """Terapkan penyesuaian pengguna (bila ada) di atas nilai bawaan template yang baru dipilih."""
        ov = self.overrides().get(self.override_key())
        if not isinstance(ov, dict):
            return
        for attr, value in (ov.get("base") or {}).items():
            if attr in self.BASE_ATTRS and isinstance(value, (int, float)):
                setattr(self.base, attr, int(value))
        self.base.clamp()
        adv = FfbAdvanced.from_dict(ov["adv"]) if isinstance(ov.get("adv"), dict) else None
        if adv is not None:
            self.adv = adv

    def is_modified(self) -> bool:
        spec = self.spec
        default = spec.base_profile()
        same_base = all(int(getattr(self.base, a)) == int(getattr(default, a)) for a in self.BASE_ATTRS)
        return not (same_base and self.adv.copy().clamp() == spec.advanced())

    def _persist(self) -> None:
        """Simpan draf sebagai penyesuaian template ini; bila sama dengan bawaan, hapus penyesuaiannya."""
        data = self.overrides()
        key = self.override_key()
        if self.is_modified():
            data[key] = {"base": {a: int(getattr(self.base, a)) for a in self.BASE_ATTRS},
                         "adv": self.adv.copy().clamp().to_dict()}
        else:
            data.pop(key, None)
        self.ctx.settings.set("template_overrides", data)
        self._update_modified()

    def _update_modified(self) -> None:
        mod = self.is_modified()
        self.mod_chip.setVisible(mod)
        self.b_reset.setEnabled(mod)

    def reset_template(self) -> None:
        """Kembalikan template dan level ini ke nilai bawaan (menghapus penyesuaian tersimpan)."""
        data = self.overrides()
        data.pop(self.override_key(), None)
        self.ctx.settings.set("template_overrides", data)
        self._load_spec(self.spec)
        self.ctx.toast(f"“{self.spec.name}” dikembalikan ke nilai bawaan", "info")

    # ================================================================ edits
    def _edit_base(self, attr: str, value: int) -> None:
        if self._pushing:
            return
        setattr(self.base, attr, int(value))
        self._recompute()
        self._persist()

    def _edit_reverse(self) -> None:
        if self._pushing:
            return
        self.base.ffb_reverse = 1 if self.reverse.isChecked() else 0
        self._recompute()
        self._persist()

    def _edit_adv(self, attr: str, value: int) -> None:
        if self._pushing:
            return
        setattr(self.adv, attr, int(value))
        self._recompute()
        self._persist()

    def _edit_enabled(self) -> None:
        if self._pushing:
            return
        self.adv.enabled = self.adv_enable.isChecked()
        self._recompute()
        self._persist()

    def _lut_preset(self, index: int) -> None:
        key = self.lut_combo.itemData(index)
        if key in LUT_PRESETS:
            self.adv.lut = list(LUT_PRESETS[key][1])
            self.lut.set_values(self.adv.lut)
            self._recompute()
            self._persist()

    def _lut_dragged(self, vals: list) -> None:
        self.adv.lut = [int(v) for v in vals]
        self.adv.clamp()
        self._sync_lut_combo()
        self._recompute()
        self._persist()

    # ============================================================== preview
    def _recompute(self) -> None:
        mode = self._mode()
        self.result = res = compile_to_wheel(self.base, self.adv, mode)
        for p, (val, chip, why) in self.res_rows.items():
            base_v, final = int(getattr(res.base, p)), int(getattr(res.profile, p))
            d = final - base_v
            usable = p == "ffb" or mode in C.FORCE_MODES
            val.setText(f"{base_v}  →  {final}%" if d else f"{final}%")
            if not usable:
                chip.setText("TIDAK DIPAKAI")
                chip.set_style(theme.TEXT_MUTED)
                why.setText(f"Mode {C.MODE_NAMES.get(mode, mode)} tidak mendukung gaya ini.")
                continue
            chip.setText(f"{d:+d}" if d else "±0")
            chip.set_style(theme.AMBER if d > 0 else theme.BLUE if d < 0 else theme.TEXT_DIM)
            parts = [f"{c.source} {c.delta:+.0f}" for c in res.contributions_for(p) if c.source != "Batas"]
            if any(c.source == "Batas" for c in res.contributions_for(p)):
                parts.append("dibatasi 0–100")
            why.setText(" · ".join(parts) if parts else "Tidak ada kontribusi")
        self.note.setText(res.note or "")
        self.note.setVisible(bool(res.note))
        rows = firmware_coverage(self.adv, mode)
        approx = [r[0] for r in rows if r[3] == "perkiraan"]
        self.coverage.setText(
            ("Diterjemahkan (perkiraan): " + ", ".join(approx) + ". " if approx else "")
            + "Firmware V10 tidak punya LUT, filter, trail, maupun efek kanned; angka di atas adalah terjemahan ke "
              "FFB, Spring, Damping, Friction dan Inertia — bukan pemrosesan sinyal di dalam setir.")

    def _refresh_target(self) -> None:
        c = self.ctx.client
        if c.is_ready:
            self.target_chip.setText(f"SETIR TERHUBUNG · {C.MODE_NAMES.get(c.device_state.mode, '?').upper()}")
            self.target_chip.set_style(theme.GREEN)
        else:
            self.target_chip.setText("SETIR TIDAK TERHUBUNG")
            self.target_chip.set_style(theme.TEXT_DIM)
        self.b_apply.setEnabled(c.is_ready)
        self.b_apply.setToolTip("" if c.is_ready else "Hubungkan setir untuk menerapkan (simpan preset tetap bisa)")
        self.b_pull.setEnabled(c.is_ready)
        self._recompute()

    # ============================================================== actions
    def apply_to_wheel(self) -> bool:
        c = self.ctx.client
        if not c.is_ready:
            self.ctx.toast("Hubungkan setir terlebih dahulu.", "error")
            self.ctx.navigate("connect")
            return False
        cur = c.profile.copy()  # pertahankan keymap & kurva pedal milik setir
        for attr in ("angle", "ffb", "spring", "damping", "friction", "inertia", "ffb_reverse"):
            setattr(cur, attr, getattr(self.base, attr))
        return send_profile(self, self.ctx, cur, self._mode(), self.spec.name, adv=self.adv)

    def pull_from_wheel(self) -> None:
        c = self.ctx.client
        if not c.is_ready:
            return
        for attr in ("angle", "ffb", "spring", "damping", "friction", "inertia", "ffb_reverse"):
            setattr(self.base, attr, getattr(c.profile, attr))
        self.origin.setText("Parameter dasar diambil dari nilai setir saat ini. Jika nilai itu sudah hasil FFB "
                            "lanjutan sebelumnya, kembalikan efek lanjutan ke netral agar tidak terhitung dua kali.")
        self._push()
        self._persist()

    def suggested_name(self) -> str:
        return template_game_profile_name(self.spec)

    def save_as_preset(self) -> None:
        name = prompt(self, "Simpan sebagai Game Preset", "Nama preset", self.suggested_name(), ok="Simpan")
        if not name:
            return
        mode = C.MODE_PC_DINPUT
        gp = GameProfile(name=name, mode=mode, platform=C.platform_by_mode(mode))
        gp.set_profile(self.base.copy().clamp())
        gp.set_advanced(self.adv)
        self.ctx.db.save(gp)
        self.ctx.toast(f"Preset “{name}” disimpan di Game Presets (lengkap dengan FFB lanjutan)", "ok")

    def export_ini(self) -> None:
        path = pick_ini_save(self, self.ctx, self.suggested_name().replace("/", "-") + ".ini")
        if not path:
            return
        doc = M.profile_to_doc(self.base, self._mode(), name=self.suggested_name(), ffb_adv=self.adv)
        try:
            Path(path).write_text(doc.to_text(), encoding="utf-8")
        except OSError as exc:
            self.ctx.toast(f"Gagal menyimpan INI: {exc}", "error")
            return
        self.ctx.toast("INI diekspor — impor kembali lewat halaman INI Presets", "ok")
