"""Enumerasi perangkat HID Windows (SetupAPI + hid.dll) lewat ctypes - tanpa dependensi tambahan.

Dipakai untuk (1) mengenali nama/VID/PID perangkat USB game controller dan (2) menemukan antarmuka
*vendor-defined* (Usage Page >= 0xFF00) yang mungkin dipakai untuk konfigurasi lewat USB.
Pada platform non-Windows ``enumerate_hid`` mengembalikan daftar kosong.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

USAGE_PAGE_GENERIC_DESKTOP = 0x01
USAGE_JOYSTICK, USAGE_GAMEPAD, USAGE_MULTI_AXIS = 0x04, 0x05, 0x08


@dataclass(frozen=True)
class HidInfo:
    path: str
    vid: int
    pid: int
    product: str = ""
    manufacturer: str = ""
    usage_page: int = 0
    usage: int = 0
    input_len: int = 0
    output_len: int = 0
    feature_len: int = 0

    @property
    def is_game_controller(self) -> bool:
        return self.usage_page == USAGE_PAGE_GENERIC_DESKTOP and self.usage in (
            USAGE_JOYSTICK, USAGE_GAMEPAD, USAGE_MULTI_AXIS)

    @property
    def is_vendor(self) -> bool:
        return self.usage_page >= 0xFF00

    @property
    def can_exchange_reports(self) -> bool:
        """Antarmuka yang punya report input DAN output (syarat untuk transport konfigurasi)."""
        return self.input_len > 0 and self.output_len > 0

    @property
    def id_text(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"


def enumerate_hid() -> list:
    if not IS_WINDOWS:
        return []
    try:
        return _enumerate_windows()
    except Exception:  # noqa: BLE001 - enumerasi tidak boleh menjatuhkan aplikasi
        return []


# ------------------------------------------------------------------------------- windows impl
def _enumerate_windows() -> list:
    import ctypes
    from ctypes import wintypes as w

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("InterfaceClassGuid", GUID), ("Flags", w.DWORD),
                    ("Reserved", ctypes.c_void_p)]

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", w.ULONG), ("VendorID", w.USHORT), ("ProductID", w.USHORT), ("VersionNumber", w.USHORT)]

    class HIDP_CAPS(ctypes.Structure):
        _fields_ = [("Usage", w.USHORT), ("UsagePage", w.USHORT), ("InputReportByteLength", w.USHORT),
                    ("OutputReportByteLength", w.USHORT), ("FeatureReportByteLength", w.USHORT),
                    ("Reserved", w.USHORT * 17), ("NumberLinkCollectionNodes", w.USHORT),
                    ("NumberInputButtonCaps", w.USHORT), ("NumberInputValueCaps", w.USHORT),
                    ("NumberInputDataIndices", w.USHORT), ("NumberOutputButtonCaps", w.USHORT),
                    ("NumberOutputValueCaps", w.USHORT), ("NumberOutputDataIndices", w.USHORT),
                    ("NumberFeatureButtonCaps", w.USHORT), ("NumberFeatureValueCaps", w.USHORT),
                    ("NumberFeatureDataIndices", w.USHORT)]

    hid = ctypes.WinDLL("hid", use_last_error=True)
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = ctypes.c_void_p

    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), w.LPCWSTR, w.HWND, w.DWORD]
    setupapi.SetupDiGetClassDevsW.restype = HANDLE
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), w.DWORD,
                                                     ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    setupapi.SetupDiEnumDeviceInterfaces.restype = w.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                          ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD),
                                                          ctypes.c_void_p]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = w.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]
    kernel32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, HANDLE]
    kernel32.CreateFileW.restype = HANDLE
    kernel32.CloseHandle.argtypes = [HANDLE]
    hid.HidD_GetAttributes.argtypes = [HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
    hid.HidD_GetAttributes.restype = w.BOOLEAN
    hid.HidD_GetProductString.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]
    hid.HidD_GetProductString.restype = w.BOOLEAN
    hid.HidD_GetManufacturerString.argtypes = [HANDLE, ctypes.c_void_p, w.ULONG]
    hid.HidD_GetManufacturerString.restype = w.BOOLEAN
    hid.HidD_GetPreparsedData.argtypes = [HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_GetPreparsedData.restype = w.BOOLEAN
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    hid.HidP_GetCaps.restype = ctypes.c_long

    DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
    FILE_SHARE_RW, OPEN_EXISTING = 0x3, 3
    invalid = HANDLE(-1).value

    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev in (None, invalid):
        return []
    out: list = []
    try:
        index = 0
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), index, ctypes.byref(did)):
                break
            index += 1
            required = w.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0, ctypes.byref(required), None)
            if required.value < 8:
                continue
            buf = ctypes.create_string_buffer(required.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), buf, required.value,
                                                             None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            handle = kernel32.CreateFileW(path, 0, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
            if handle in (None, invalid):
                continue
            try:
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
                if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue
                strbuf = ctypes.create_unicode_buffer(128)
                product = strbuf.value if hid.HidD_GetProductString(handle, strbuf, 256) else ""
                strbuf2 = ctypes.create_unicode_buffer(128)
                maker = strbuf2.value if hid.HidD_GetManufacturerString(handle, strbuf2, 256) else ""
                caps = HIDP_CAPS()
                pre = ctypes.c_void_p()
                have_caps = False
                if hid.HidD_GetPreparsedData(handle, ctypes.byref(pre)):
                    try:
                        have_caps = hid.HidP_GetCaps(pre, ctypes.byref(caps)) == 0x110000
                    finally:
                        hid.HidD_FreePreparsedData(pre)
                out.append(HidInfo(
                    path=path, vid=attrs.VendorID, pid=attrs.ProductID, product=product.strip(),
                    manufacturer=maker.strip(),
                    usage_page=caps.UsagePage if have_caps else 0, usage=caps.Usage if have_caps else 0,
                    input_len=caps.InputReportByteLength if have_caps else 0,
                    output_len=caps.OutputReportByteLength if have_caps else 0,
                    feature_len=caps.FeatureReportByteLength if have_caps else 0))
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out
