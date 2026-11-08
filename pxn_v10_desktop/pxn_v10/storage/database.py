"""Local preset storage (SQLite) - replacement for the GreenDAO ``GameProfile`` table."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from ..core import constants as C
from ..core.ffb_advanced import FfbAdvanced
from ..core.hexprofile import pack_profile, unpack_profile
from ..core.models import DeviceProfile
from .paths import app_data_dir, package_data

MODEL_V10 = 11  # GameProfile.model value used by the Android app for the V10


@dataclass
class GameProfile:
    name: str = ""
    mode: int = C.MODE_PC_DINPUT
    platform: int = C.PLATFORM_PC
    content: str = ""  # hex string (see core.hexprofile)
    id: Optional[int] = None
    img_url: str = ""
    model: int = MODEL_V10
    recommended: bool = False
    created_at: float = field(default_factory=time.time)
    tutorial: str = ""
    tutorial_url: str = ""
    ffb_adv: str = ""  # JSON dari FfbAdvanced ("" = tidak ada FFB lanjutan)

    def advanced(self):
        return FfbAdvanced.from_json(self.ffb_adv)

    def set_advanced(self, adv) -> None:
        self.ffb_adv = adv.to_json() if adv is not None else ""

    def profile(self) -> DeviceProfile:
        if not self.content:
            return DeviceProfile()
        return unpack_profile(self.content)

    def set_profile(self, profile: DeviceProfile) -> None:
        self.content = pack_profile(profile)

    def duplicate(self, suffix: str = " (copy)") -> "GameProfile":
        return replace(self, id=None, name=self.name + suffix, recommended=False, created_at=time.time())


class ProfileDatabase:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = str(path or (app_data_dir() / "profiles.db"))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS game_profile (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   img_url TEXT DEFAULT '',
                   mode INTEGER NOT NULL,
                   platform INTEGER NOT NULL,
                   model INTEGER NOT NULL DEFAULT 11,
                   content_hex TEXT NOT NULL,
                   is_recommended INTEGER NOT NULL DEFAULT 0,
                   created_at REAL NOT NULL
               )"""
        )
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(game_profile)").fetchall()}
        if "ffb_adv" not in cols:  # migrasi dari versi sebelum FFB lanjutan
            self._db.execute("ALTER TABLE game_profile ADD COLUMN ffb_adv TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> GameProfile:
        return GameProfile(
            id=row["id"],
            name=row["name"],
            img_url=row["img_url"] or "",
            mode=row["mode"],
            platform=row["platform"],
            model=row["model"],
            content=row["content_hex"],
            recommended=bool(row["is_recommended"]),
            created_at=row["created_at"],
            ffb_adv=row["ffb_adv"] or "",
        )

    def save(self, gp: GameProfile) -> GameProfile:
        """insertOrReplace"""
        with self._lock:
            if gp.id is None:
                cur = self._db.execute(
                    "INSERT INTO game_profile (name, img_url, mode, platform, model, content_hex, is_recommended, created_at,"
                    " ffb_adv) VALUES (?,?,?,?,?,?,?,?,?)",
                    (gp.name, gp.img_url, gp.mode, gp.platform, gp.model, gp.content, int(gp.recommended), gp.created_at,
                     gp.ffb_adv),
                )
                gp.id = cur.lastrowid
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO game_profile (id, name, img_url, mode, platform, model, content_hex,"
                    " is_recommended, created_at, ffb_adv) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (gp.id, gp.name, gp.img_url, gp.mode, gp.platform, gp.model, gp.content, int(gp.recommended), gp.created_at,
                     gp.ffb_adv),
                )
            self._db.commit()
        return gp

    def rename(self, profile_id: int, name: str) -> None:
        with self._lock:
            self._db.execute("UPDATE game_profile SET name=? WHERE id=?", (name, profile_id))
            self._db.commit()

    def delete(self, profile_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM game_profile WHERE id=?", (profile_id,))
            self._db.commit()

    def get(self, profile_id: int) -> Optional[GameProfile]:
        with self._lock:
            row = self._db.execute("SELECT * FROM game_profile WHERE id=?", (profile_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, platform: int | None = None, model: int = MODEL_V10) -> list:
        sql, args = "SELECT * FROM game_profile WHERE model=?", [model]
        if platform is not None:
            sql += " AND platform=?"
            args.append(platform)
        sql += " ORDER BY created_at ASC, id ASC"
        with self._lock:
            return [self._row(r) for r in self._db.execute(sql, args).fetchall()]


# ------------------------------------------------------------------ recommended presets
def _builtin_game_presets() -> list:
    """Starter presets named in Task 4.4 of DEVELOPMENT_TASKS.md (D-Input / X-Input values chosen
    from the guidance given there; they are starting points to be tuned, not vendor tested)."""

    def make(name, mode, angle, ffb, spring, damping, friction, inertia, reverse=0, note=""):
        p = DeviceProfile(angle=angle, ffb=ffb, spring=spring, damping=damping, friction=friction,
                          inertia=inertia, ffb_reverse=reverse)
        gp = GameProfile(name=name, mode=mode, platform=C.PLATFORM_PC, recommended=True, tutorial=note)
        gp.set_profile(p)
        return gp

    return [
        make("Assetto Corsa — Realistic", C.MODE_PC_DINPUT, 900, 80, 50, 80, 60, 50,
             note="D-Input, 900°, FFB realistis, damping tinggi."),
        make("Forza Horizon 5", C.MODE_PC_XINPUT, 540, 80, 80, 50, 50, 50,
             note="X-Input, 540°, spring cepat. (Slider physics tidak dipakai pada X-Input.)"),
        make("F1 23 / F1 24", C.MODE_PC_DINPUT, 360, 70, 60, 50, 80, 50,
             note="D-Input, 360°, friction tinggi, sudut kecil."),
        make("Dirt Rally 2.0 / EA WRC", C.MODE_PC_DINPUT, 540, 85, 60, 50, 60, 50,
             note="D-Input, 540°. Aktifkan FFB Reverse jika arah gaya terasa terbalik."),
        make("Euro Truck Simulator 2", C.MODE_PC_DINPUT, 900, 70, 80, 60, 50, 90,
             note="D-Input, 900°, inertia & spring berat."),
    ]


def load_recommended() -> list:
    """Bundled ``recommended_presets.json`` (copied from the Android assets) + the Task 4.4 presets."""
    items: list = _builtin_game_presets()
    path = package_data("recommended_presets.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = []
    for d in data:
        try:
            gp = GameProfile(
                name=d["name"],
                mode=int(d["mode"]),
                platform=int(d["platform"]),
                content=d["content"],
                img_url=d.get("img", ""),
                recommended=True,
            )
            gp.profile()  # validate
            items.append(gp)
        except (KeyError, ValueError, TypeError):
            continue
    return items
