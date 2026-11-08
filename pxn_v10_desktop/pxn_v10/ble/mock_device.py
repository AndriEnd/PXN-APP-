"""Pure-logic simulation of a PXN-V10 wheel base (Task 6.1: "Mock BLE Peripheral Engine").

Answers the same opcodes as the real firmware (0x50 / 0x51 / 0x52 / 0x53 / 0x54) and produces
``0xD4 0x03`` telemetry frames, so the whole application can be developed and tested without a
physical wheel.
"""

from __future__ import annotations

import math
import struct

from ..core import constants as C
from ..core.models import DeviceProfile, DeviceState


class MockV10Device:
    def __init__(
        self,
        mode: int = C.MODE_PC_DINPUT,
        pedal: bool = True,
        lever: bool = True,
        brake: bool = True,
        firmware: tuple = (1, 5),  # (major, minor)
    ) -> None:
        self.state = DeviceState(
            mode=mode,
            version=(firmware[0] << 8) | firmware[1],
            minor_ver=firmware[1],
            major_ver=firmware[0],
            pedal_state=1 if pedal else 0,
            lever_state=1 if lever else 0,
            angle_mode=1,
            brake_state=1 if brake else 0,
        )
        self.profiles: dict[int, DeviceProfile] = {}
        self.testing = False
        self.received: list[bytes] = []  # every packet written to the "wheel" (for assertions)

    # ----------------------------------------------------------------- helpers
    def profile(self, mode: int | None = None) -> DeviceProfile:
        mode = self.state.mode if mode is None else mode
        if mode not in self.profiles:
            self.profiles[mode] = DeviceProfile()
        return self.profiles[mode]

    def _state_frame(self) -> bytes:
        s = self.state
        buf = bytearray(C.PACKET_SIZE)
        buf[0] = C.REPORT_ID_READ_STATE_RESP
        buf[1] = 0x09
        buf[2] = s.mode
        buf[3] = s.minor_ver
        buf[4] = s.major_ver
        buf[5] = s.pedal_state
        buf[6] = s.lever_state
        buf[7] = s.angle_mode
        buf[8] = s.brake_state
        return bytes(buf)

    # ---------------------------------------------------------------- dispatch
    def handle(self, packet: bytes) -> list[bytes]:
        """Process a packet written by the app and return the notifications it triggers."""
        self.received.append(bytes(packet))
        b = bytes(packet) + bytes(max(0, 8 - len(packet)))
        op = b[0]
        if op == C.REPORT_ID_READ_STATE_REQ:
            return [self._state_frame()]
        if op == C.REPORT_ID_READ_PROFILE_REQ:
            mode, page = b[1], b[2]
            if page >= C.PROFILE_PAGES:
                return []
            return [self.profile(mode).pack_page(page, mode, opcode=C.REPORT_ID_READ_PROFILE_RESP)]
        if op == C.REPORT_ID_WRITE_PROFILE_REQ:
            return self._write_profile(bytes(packet))
        if op == C.REPORT_ID_EDIT_PARAMS_REQ:
            return self._edit(b)
        if op == C.REPORT_ID_TESTING_REQ:
            self.testing = b[1] == C.CMD_TESTING_ENTER
            return [bytes([C.REPORT_ID_TESTING_RESP, b[1]]) + bytes(C.PACKET_SIZE - 2)]
        return []

    def _write_profile(self, packet: bytes) -> list[bytes]:
        mode = packet[1]
        prof = self.profile(mode)
        frame = packet + bytes(max(0, C.PACKET_SIZE - len(packet)))
        page = prof.unpack_page(frame)
        ack = bytearray(C.PACKET_SIZE)
        ack[0], ack[1], ack[2] = C.REPORT_ID_WRITE_PROFILE_RESP, mode, page
        return [bytes(ack)]

    def _edit(self, b: bytes) -> list[bytes]:
        sub = b[1]
        ack = bytearray(C.PACKET_SIZE)
        ack[0], ack[1] = C.REPORT_ID_EDIT_PARAMS_RESP, sub
        prof = self.profile()
        if sub == C.CMD_SWITCH_MODE:
            if b[2] in C.MODE_NAMES:
                self.state.mode = b[2]
            ack[2] = self.state.mode
        elif sub == C.CMD_UPDATE_KEYMAP:
            prof.keymap[b[3]] = b[4]
            ack[2], ack[3], ack[4] = b[2], b[3], b[4]
        elif sub == C.CMD_UPDATE_FFB:
            prof.ffb, prof.ffb_reverse = b[3], b[4]
            ack[2], ack[3], ack[4] = b[2], b[3], b[4]
        elif sub == C.CMD_UPDATE_ANGLE:
            prof.angle = struct.unpack_from("<H", b, 4)[0] if len(b) >= 6 else prof.angle
            ack[2], ack[3] = b[2], 1
            struct.pack_into("<H", ack, 4, prof.angle)
        elif sub == C.CMD_UPDATE_FORCE:
            prof.spring, prof.damping, prof.friction, prof.inertia = b[3], b[4], b[5], b[6]
            ack[2], ack[3], ack[4], ack[5], ack[6] = b[2], b[3], b[4], b[5], b[6]
        elif sub == C.CMD_RESET_PROFILE:
            self.profiles[self.state.mode] = DeviceProfile()
            ack[2] = b[2]
        elif sub == C.CMD_UPDATE_PEDAL:
            self.state.pedal_state = b[3]
            ack[2], ack[3] = b[2], b[3]
        elif sub == C.CMD_UPDATE_LEVER:
            self.state.lever_state = b[3]
            ack[2], ack[3] = b[2], b[3]
        elif sub == C.CMD_UPDATE_BRAKE:
            self.state.brake_state = b[3]
            ack[2], ack[3] = b[2], b[3]
        else:
            return []
        return [bytes(ack)]

    # --------------------------------------------------------------- telemetry
    def telemetry_frame(self, t: float) -> bytes:
        """A demo frame: steering sweep, pulsing pedals, gears cycling, a few buttons toggling."""
        buf = bytearray(C.PACKET_SIZE)
        buf[0], buf[1] = C.REPORT_ID_TESTING_RESP, C.CMD_TESTING_DATA
        steer = math.sin(t * 0.9)
        buf[6] = max(0, min(255, int(128 + steer * 127)))
        buf[8] = int(max(0.0, math.sin(t * 1.3)) * 255)  # gas
        buf[9] = int(max(0.0, math.sin(t * 1.3 + math.pi)) * 255)  # brake
        buf[10] = int(max(0.0, math.sin(t * 0.7 + 2.0)) ** 2 * 255)  # clutch
        step = int(t / 1.5) % 8
        buf[13] = (0, 1, 2, 3, 4, 5, 6, 255)[step]
        bank1 = 1 << (int(t * 2) % 8)
        buf[2] = bank1
        buf[3] = 1 << (int(t * 1.5) % 8)
        buf[4] = 1 << (int(t) % 2)
        buf[12] = 1 << (int(t * 2) % 4)
        return bytes(buf)
