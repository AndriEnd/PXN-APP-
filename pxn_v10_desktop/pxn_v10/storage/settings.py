"""JSON settings (last device, bindings, window state ...)."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..ini.mapper import Binding
from .paths import app_data_dir

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "last_address": "",
    "auto_reconnect": True,
    "auto_connect": True,
    "haptics": True,
    "ini_bindings": [],
    "usb_devices": {},
    "telemetry_game": "auto",
    "telemetry_unit": "kmh",
    "telemetry_scale": "auto",
    "telemetry_port": 9000,
    "template_overrides": {},  # "drift/pro" -> {"base": {...}, "adv": {...}} penyesuaian pengguna per template
    "window": {},
    "last_ini_dir": "",
}


class Settings:
    def __init__(self, path=None) -> None:
        self.path = path or (app_data_dir() / "settings.json")
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                self.data.update(stored)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("settings file unreadable - using defaults", exc_info=True)

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)
        except OSError:
            log.warning("could not save settings", exc_info=True)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    # --- INI bindings
    def bindings(self) -> list:
        out = []
        for d in self.get("ini_bindings", []):
            try:
                out.append(Binding.from_dict(d))
            except (TypeError, ValueError):
                continue
        return out

    def set_bindings(self, bindings: list) -> None:
        self.set("ini_bindings", [b.to_dict() for b in bindings])
