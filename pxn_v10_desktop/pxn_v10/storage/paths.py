"""Per-user application data locations."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PXN-V10-Desktop"


def app_data_dir() -> Path:
    override = os.environ.get("PXN_V10_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_DIR_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def ini_library_dir() -> Path:
    d = app_data_dir() / "ini_presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def package_data(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / "data" / name
