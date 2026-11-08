"""Pembacaan USB Game Controller (setir, shifter, handbrake) lewat Windows Multimedia joystick API.

``WinMMBackend`` memakai ``winmm.dll`` (joyGetDevCapsW / joyGetPosEx) sehingga tidak perlu driver atau
pustaka tambahan. Batasan API ini: maksimum 6 sumbu (X Y Z R U V), 1 POV dan 32 tombol per perangkat.
``FakeJoystickBackend`` dipakai simulator dan test.
"""

from __future__ import annotations

import math
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

AXIS_NAMES = ("X", "Y", "Z", "R", "U", "V")
RAW_MAX = 65535


@dataclass(frozen=True)
class JoyInfo:
    """Kemampuan sebuah joystick (hasil ``joyGetDevCapsW``)."""

    slot: int  # indeks winmm 0..15
    vid: int
    pid: int
    name: str
    axes: tuple  # indeks sumbu yang ada (0=X .. 5=V)
    ranges: tuple  # (min, max) per sumbu pada ``axes``
    n_buttons: int
    has_pov: bool
    axis_names: tuple = ()  # nama tiap sumbu bila diketahui (backend HID); kosong -> X Y Z R U V

    @property
    def n_axes(self) -> int:
        return len(self.axes)

    @property
    def id_text(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    def axis_label(self, i: int) -> str:
        if not 0 <= i < len(self.axes):
            return "—"
        if i < len(self.axis_names):
            return self.axis_names[i]
        return AXIS_NAMES[self.axes[i]]

    def axis_labels(self) -> list:
        return [self.axis_label(i) for i in range(len(self.axes))]


@dataclass
class JoyState:
    axes: list = field(default_factory=list)  # nilai mentah per ``JoyInfo.axes``
    buttons: int = 0  # bitmask, bit i = tombol i
    pov: int = -1  # derajat (0..359) atau -1 = netral

    def pressed(self, n_buttons: int = 32) -> list:
        return [i for i in range(n_buttons) if self.buttons >> i & 1]


class JoystickBackend(ABC):
    @abstractmethod
    def enumerate(self) -> list:
        """Daftar ``JoyInfo`` perangkat yang terpasang."""

    @abstractmethod
    def read(self, slot: int) -> JoyState | None:
        """Keadaan terkini, atau None bila perangkat dicabut."""


# ------------------------------------------------------------------------------------ winmm
class WinMMBackend(JoystickBackend):
    JOYERR_NOERROR = 0
    JOY_RETURNALL = 0xFF
    HASZ, HASR, HASU, HASV, HASPOV = 0x1, 0x2, 0x4, 0x8, 0x10

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w

        class JOYCAPSW(ctypes.Structure):
            _fields_ = [("wMid", w.WORD), ("wPid", w.WORD), ("szPname", ctypes.c_wchar * 32),
                        ("wXmin", w.UINT), ("wXmax", w.UINT), ("wYmin", w.UINT), ("wYmax", w.UINT),
                        ("wZmin", w.UINT), ("wZmax", w.UINT), ("wNumButtons", w.UINT),
                        ("wPeriodMin", w.UINT), ("wPeriodMax", w.UINT), ("wRmin", w.UINT), ("wRmax", w.UINT),
                        ("wUmin", w.UINT), ("wUmax", w.UINT), ("wVmin", w.UINT), ("wVmax", w.UINT),
                        ("wCaps", w.UINT), ("wMaxAxes", w.UINT), ("wNumAxes", w.UINT), ("wMaxButtons", w.UINT),
                        ("szRegKey", ctypes.c_wchar * 32), ("szOEMVxD", ctypes.c_wchar * 260)]

        class JOYINFOEX(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("dwFlags", w.DWORD), ("dwXpos", w.DWORD), ("dwYpos", w.DWORD),
                        ("dwZpos", w.DWORD), ("dwRpos", w.DWORD), ("dwUpos", w.DWORD), ("dwVpos", w.DWORD),
                        ("dwButtons", w.DWORD), ("dwButtonNumber", w.DWORD), ("dwPOV", w.DWORD),
                        ("dwReserved1", w.DWORD), ("dwReserved2", w.DWORD)]

        self._ct = ctypes
        self._caps_t, self._info_t = JOYCAPSW, JOYINFOEX
        self._winmm = ctypes.WinDLL("winmm")
        self._num = int(self._winmm.joyGetNumDevs())
        self._axes: dict = {}  # slot -> indeks sumbu yang ada (hasil enumerate)
        self._pov: dict = {}  # slot -> apakah perangkat punya POV

    def enumerate(self) -> list:
        out = []
        ct = self._ct
        for slot in range(self._num):
            caps = self._caps_t()
            if self._winmm.joyGetDevCapsW(slot, ct.byref(caps), ct.sizeof(caps)) != self.JOYERR_NOERROR:
                continue
            probe = self._info_t()
            probe.dwSize = ct.sizeof(probe)
            probe.dwFlags = self.JOY_RETURNALL
            if self._winmm.joyGetPosEx(slot, ct.byref(probe)) != self.JOYERR_NOERROR:
                continue  # slot kosong / perangkat dicabut
            axes = [0, 1]
            ranges = [(caps.wXmin, caps.wXmax), (caps.wYmin, caps.wYmax)]
            for bit, idx, lo, hi in ((self.HASZ, 2, caps.wZmin, caps.wZmax), (self.HASR, 3, caps.wRmin, caps.wRmax),
                                     (self.HASU, 4, caps.wUmin, caps.wUmax), (self.HASV, 5, caps.wVmin, caps.wVmax)):
                if caps.wCaps & bit:
                    axes.append(idx)
                    ranges.append((lo, hi))
            self._axes[slot] = tuple(axes)
            self._pov[slot] = bool(caps.wCaps & self.HASPOV)
            out.append(JoyInfo(slot, int(caps.wMid), int(caps.wPid), _oem_name(caps.wMid, caps.wPid, caps.szPname),
                               tuple(axes), tuple(ranges), int(caps.wNumButtons), bool(caps.wCaps & self.HASPOV)))
        return out

    def read(self, slot: int) -> JoyState | None:
        ct = self._ct
        info = self._info_t()
        info.dwSize = ct.sizeof(info)
        info.dwFlags = self.JOY_RETURNALL
        if self._winmm.joyGetPosEx(slot, ct.byref(info)) != self.JOYERR_NOERROR:
            return None
        raw = (info.dwXpos, info.dwYpos, info.dwZpos, info.dwRpos, info.dwUpos, info.dwVpos)
        if slot not in self._axes:
            self.enumerate()
        pov = info.dwPOV
        no_pov = not self._pov.get(slot, False)  # tanpa POV, dwPOV berisi 0 (bukan "atas")
        return JoyState(select_axes(raw, self._axes.get(slot, (0, 1))), int(info.dwButtons),
                        -1 if no_pov or pov == 0xFFFF or pov > 35999 else int(pov // 100))


def select_axes(raw: tuple, present: tuple) -> list:
    """Nilai mentah X..V -> hanya sumbu yang dilaporkan perangkat, urut sesuai ``JoyInfo.axes``.
    (JoyInfo.axes[i] adalah sumbu ke-i; seluruh UI/kalibrasi memakai indeks posisi i itu.)"""
    return [raw[a] for a in present]


def _oem_name(vid: int, pid: int, fallback: str) -> str:
    """Nama produk yang dilihat pengguna di 'Set up USB game controllers' (registry OEMName)."""
    if sys.platform == "win32":
        try:
            import winreg

            key = (r"System\CurrentControlSet\Control\MediaProperties\PrivateProperties\Joystick\OEM"
                   rf"\VID_{vid:04X}&PID_{pid:04X}")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                name, _ = winreg.QueryValueEx(k, "OEMName")
                if name:
                    return str(name)
        except OSError:
            pass
    return fallback or "USB Game Controller"


def default_backend() -> JoystickBackend | None:
    if sys.platform != "win32":
        return None
    try:
        return WinMMBackend()
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------ simulator
class FakeJoystickBackend(JoystickBackend):
    """Joystick virtual: perangkat dan keadaannya diatur kode (test) atau dianimasikan (demo)."""

    def __init__(self) -> None:
        self.devices: dict = {}  # slot -> JoyInfo
        self.states: dict = {}  # slot -> JoyState
        self.animated: dict = {}  # slot -> fungsi(t) -> JoyState
        self._t0 = time.monotonic()

    def add(self, info: JoyInfo, state: JoyState | None = None, animate=None) -> JoyInfo:
        self.devices[info.slot] = info
        self.states[info.slot] = state or JoyState([info.ranges[i][0] for i in range(info.n_axes)], 0, -1)
        if animate is not None:
            self.animated[info.slot] = animate
        return info

    def remove(self, slot: int) -> None:
        self.devices.pop(slot, None)
        self.states.pop(slot, None)
        self.animated.pop(slot, None)

    def enumerate(self) -> list:
        return [self.devices[s] for s in sorted(self.devices)]

    def read(self, slot: int) -> JoyState | None:
        if slot not in self.devices:
            return None
        fn = self.animated.get(slot)
        if fn is not None:
            return fn(time.monotonic() - self._t0)
        return self.states[slot]

    # ---- demo: setir + shifter + handbrake yang bergerak
    @classmethod
    def demo(cls) -> "FakeJoystickBackend":
        b = cls()
        rng = (0, RAW_MAX)

        def wheel(t: float) -> JoyState:
            steer = int(RAW_MAX * (0.5 + 0.42 * math.sin(t * 0.9)))
            acc = int(RAW_MAX * max(0.0, math.sin(t * 0.6)) ** 1.5)
            brake = int(RAW_MAX * max(0.0, -math.sin(t * 0.6 + 0.4)) ** 2)
            btn = 1 << (int(t * 1.4) % 12)
            return JoyState([steer, acc, brake, 0], btn, -1)

        def shifter(t: float) -> JoyState:
            gear = int(t / 1.6) % 8  # 0 = netral, 1..6, 7 = R
            return JoyState([], 0 if gear == 0 else 1 << (gear - 1), -1)

        def handbrake(t: float) -> JoyState:
            v = max(0.0, math.sin(t * 0.8)) ** 1.2
            return JoyState([int(RAW_MAX * v)], 0, -1)

        b.add(JoyInfo(0, 0xF0F0, 0x0001, "PXN-V10 (simulasi USB)", (0, 1, 2, 3), (rng,) * 4, 24, False), animate=wheel)
        b.add(JoyInfo(1, 0xF0F0, 0x0002, "PXN Shifter (simulasi USB)", (), (), 8, False), animate=shifter)
        b.add(JoyInfo(2, 0xF0F0, 0x0003, "PXN Handbrake (simulasi USB)", (0,), (rng,), 1, False), animate=handbrake)
        return b
