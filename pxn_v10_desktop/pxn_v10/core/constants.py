"""Protocol constants for the PXN-V10 (ported from Cons_V10 / Mode_V10 / GamePlatform)."""

from __future__ import annotations

# ---------------------------------------------------------------- BLE / GATT
DEVICE_NAME = "PXN-V10"
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

# Write queue pacing (Wheel_V10 handler: 100 ms between packets)
WRITE_INTERVAL_S = 0.100
WRITE_ACK_TIMEOUT_S = 0.400  # safety net: the original stalls forever without an ack

# ---------------------------------------------------------------- Opcodes
REPORT_ID_READ_STATE_REQ = 0x50  # 80
REPORT_ID_READ_PROFILE_REQ = 0x51  # 81
REPORT_ID_WRITE_PROFILE_REQ = 0x52  # 82
REPORT_ID_EDIT_PARAMS_REQ = 0x53  # 83
REPORT_ID_TESTING_REQ = 0x54  # 84
REPORT_ID_READ_STATE_RESP = 0xD0  # 208
REPORT_ID_READ_PROFILE_RESP = 0xD1  # 209
REPORT_ID_WRITE_PROFILE_RESP = 0xD2  # 210
REPORT_ID_EDIT_PARAMS_RESP = 0xD3  # 211
REPORT_ID_TESTING_RESP = 0xD4  # 212

# Sub commands of 0x53 (EDIT_PARAMS)
CMD_SWITCH_MODE = 1
CMD_UPDATE_KEYMAP = 2
CMD_UPDATE_FFB = 3
CMD_UPDATE_ANGLE = 4
CMD_UPDATE_PEDAL = 6
CMD_UPDATE_LEVER = 7
CMD_RESET_PROFILE = 8
CMD_UPDATE_FORCE = 9
CMD_UPDATE_BRAKE = 14

CMD_TESTING_ENTER = 1
CMD_TESTING_EXIT = 2
CMD_TESTING_DATA = 3

PACKET_SIZE = 20  # every profile page frame is exactly 20 bytes
PROFILE_PAGES = 6

# ---------------------------------------------------------------- Modes
MODE_WAITING = 0
MODE_PC_DINPUT = 1
MODE_PC_XINPUT = 2
MODE_PS4_WHEEL = 5
MODE_XBOX_ONE_WHEEL = 8
MODE_ANDROID = 10
MODE_SWITCH_PRO = 11

MODE_NAMES = {
    MODE_PC_DINPUT: "D-Input",
    MODE_PC_XINPUT: "X-Input",
    MODE_PS4_WHEEL: "PS4",
    MODE_XBOX_ONE_WHEEL: "Xbox One",
    MODE_ANDROID: "Android",
    MODE_SWITCH_PRO: "Switch",
}
MODE_LONG_NAMES = {
    MODE_PC_DINPUT: "PC DirectInput (D-Input)",
    MODE_PC_XINPUT: "PC XInput (X-Input)",
    MODE_PS4_WHEEL: "PlayStation 4 Wheel",
    MODE_XBOX_ONE_WHEEL: "Xbox One Wheel",
    MODE_ANDROID: "Android",
    MODE_SWITCH_PRO: "Nintendo Switch Pro",
}
SWITCHABLE_MODES = (MODE_PC_DINPUT, MODE_PC_XINPUT)

# Modes that expose the angle / FFB sliders and the 4 physics forces (ParamsAdapter)
ANGLE_FFB_MODES = (MODE_PC_DINPUT, MODE_PC_XINPUT, MODE_PS4_WHEEL, MODE_XBOX_ONE_WHEEL)
FORCE_MODES = (MODE_PC_DINPUT, MODE_PS4_WHEEL)

# ---------------------------------------------------------------- Platforms
PLATFORM_PC = 1
PLATFORM_PS3 = 2
PLATFORM_PS4 = 3
PLATFORM_SWITCH = 4
PLATFORM_XBOX_ONE = 5
PLATFORM_ANDROID = 6
PLATFORM_XBOX_360 = 7

PLATFORM_NAMES = {
    PLATFORM_PC: "PC",
    PLATFORM_PS3: "PS3",
    PLATFORM_PS4: "PS4",
    PLATFORM_SWITCH: "Switch",
    PLATFORM_XBOX_ONE: "Xbox One",
    PLATFORM_ANDROID: "Android",
    PLATFORM_XBOX_360: "Xbox 360",
}


def platforms_by_mode(mode: int) -> list[int]:
    """GamePlatform.getPlatformsByV10Mode"""
    if mode in (MODE_PC_DINPUT, MODE_PC_XINPUT):
        return [PLATFORM_PC]
    if mode == MODE_PS4_WHEEL:
        return [PLATFORM_PS4]
    if mode == MODE_XBOX_ONE_WHEEL:
        return [PLATFORM_XBOX_ONE]
    if mode == MODE_ANDROID:
        return [PLATFORM_ANDROID]
    if mode == MODE_SWITCH_PRO:
        return [PLATFORM_SWITCH]
    return [PLATFORM_PC, PLATFORM_PS4, PLATFORM_XBOX_ONE]


def modes_by_platform(platform: int) -> list[int]:
    """GamePlatform.getV10ModesByPlatform"""
    return {
        PLATFORM_PS4: [MODE_PS4_WHEEL],
        PLATFORM_SWITCH: [MODE_SWITCH_PRO],
        PLATFORM_XBOX_ONE: [MODE_XBOX_ONE_WHEEL],
        PLATFORM_ANDROID: [MODE_ANDROID],
    }.get(platform, [MODE_PC_DINPUT, MODE_PC_XINPUT])


def platform_by_mode(mode: int) -> int:
    """V10ProfileActivity.getExtra(): derive platform from mode"""
    return platforms_by_mode(mode)[0]


def mode_by_platform(platform: int) -> int:
    return {
        PLATFORM_PC: MODE_PC_DINPUT,
        PLATFORM_PS4: MODE_PS4_WHEEL,
        PLATFORM_SWITCH: MODE_SWITCH_PRO,
        PLATFORM_XBOX_ONE: MODE_XBOX_ONE_WHEEL,
    }.get(platform, MODE_PC_DINPUT)


# ---------------------------------------------------------------- Ranges
ANGLE_MIN, ANGLE_MAX, ANGLE_STEP = 90, 900, 10
PERCENT_MIN, PERCENT_MAX, PERCENT_STEP = 0, 100, 10
CURVE_X_MAX = 4095  # 12-bit ADC
CURVE_Y_MAX = 65535  # 16-bit output

# Default pedal curve (MainActivity.preset_default) - four control points
DEFAULT_CURVE = ((0, 0), (1365, 21845), (2730, 43690), (4095, 65535))

# Keymap layout (DeviceProfile.KEYMAP_SEQUENCE): 36 slots over pages 0..2
KEYMAP_SEQUENCE = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 16, 47,
    14, 15, 47, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33,
    34, 35,
)
# Legacy (version-less) hex profile layout (V10ProfileActivity.PROFILE_KEY_SEQUENCE)
LEGACY_KEY_SEQUENCE = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 16, 14, 15,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
)
HEX_PROFILE_VERSION = 0x03

KEYCODE_RESERVED = 47

# Test-mode bit layout (TestData)
TEST_KEY_SEQUENCE_1 = (0, 1, 2, 3, 4, 5, 6, 7)
TEST_KEY_SEQUENCE_2 = (8, 9, 10, 11, 12, 13, 14, 15)
TEST_KEY_SEQUENCE_3 = (16, 17)
TEST_KEY_SEQUENCE_4 = (25, 26, 23, 24)
