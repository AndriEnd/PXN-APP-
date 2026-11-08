"""Helpers shared by the pages that import / export INI presets."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ..core.models import DeviceProfile
from ..ini import mapper as M
from ..ini.document import IniDocument
from .context import AppContext

INI_FILTER = "INI preset (*.ini);;Semua file (*)"


def pick_ini_files(parent, ctx: AppContext, multiple: bool = True) -> list:
    start = ctx.settings.get("last_ini_dir", "") or str(Path.home())
    if multiple:
        paths, _ = QFileDialog.getOpenFileNames(parent, "Impor preset INI", start, INI_FILTER)
    else:
        path, _ = QFileDialog.getOpenFileName(parent, "Impor preset INI", start, INI_FILTER)
        paths = [path] if path else []
    if paths:
        ctx.settings.set("last_ini_dir", os.path.dirname(paths[0]))
    return paths


def pick_ini_save(parent, ctx: AppContext, suggested: str) -> str:
    start = ctx.settings.get("last_ini_dir", "") or str(Path.home())
    path, _ = QFileDialog.getSaveFileName(parent, "Simpan preset INI", str(Path(start) / suggested), INI_FILTER)
    if path:
        if not path.lower().endswith(".ini"):
            path += ".ini"
        ctx.settings.set("last_ini_dir", os.path.dirname(path))
    return path


def load_into_profile(ctx: AppContext, path: str, base: DeviceProfile) -> tuple:
    """Parse ``path`` and overlay its wheel parameters on ``base``. Returns (profile, IniResult)."""
    doc = IniDocument.load(path)
    res = M.extract(doc, ctx.settings.bindings())
    return M.apply_to_profile(res, base), res
