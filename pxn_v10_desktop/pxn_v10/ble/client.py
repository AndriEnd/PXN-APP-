"""WheelClient - the desktop equivalent of ``Wheel_V10`` (connection FSM, 100 ms paced write
queue, inbound packet router, local mirror of device state / profile).

The client is UI agnostic: it runs an asyncio loop in a worker thread and reports through
plain callbacks (``add_listener``). The Qt layer converts these callbacks into signals.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Callable, Optional

from ..core import codec
from ..core import constants as C
from ..core.events import (
    Change,
    ChangeEvent,
    ConnEvent,
    ConnState,
    DeviceFound,
    ErrorEvent,
    LogEvent,
    TestEvent,
)
from ..core.models import DeviceProfile, DeviceState, TestData
from ..core.write_queue import WriteQueue
from .transport import Transport, TransportError

log = logging.getLogger(__name__)
Listener = Callable[[object], None]


class AsyncRunner:
    """An asyncio event loop living in a daemon thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="pxn-ble-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call_soon(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)


class WheelClient:
    def __init__(
        self,
        transport: Transport,
        runner: AsyncRunner | None = None,
        *,
        auto_sync: bool = True,
        auto_reconnect: bool = True,
        write_interval: float = C.WRITE_INTERVAL_S,
        ack_timeout: float = C.WRITE_ACK_TIMEOUT_S,
    ) -> None:
        self.transport = transport
        self.runner = runner or AsyncRunner()
        self._owns_runner = runner is None
        self.auto_sync = auto_sync
        self.auto_reconnect = auto_reconnect
        self.write_interval = write_interval
        self.ack_timeout = ack_timeout

        self.state = ConnState.DISCONNECTED
        self.device_state = DeviceState()
        self.profile = DeviceProfile()
        self.test_data = TestData()
        self.profile_synced = False
        self.last_address: Optional[str] = None
        self.last_error = ""

        self.queue = WriteQueue()
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._wake: asyncio.Event | None = None
        self._ack: asyncio.Event | None = None
        self._writer: asyncio.Task | None = None
        self._user_disconnect = False
        self._reconnecting = False
        self._testing = False

    # ================================================================== events
    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _emit(self, event: object) -> None:
        for fn in list(self._listeners):
            try:
                fn(event)
            except Exception:  # noqa: BLE001 - a broken listener must not kill the BLE loop
                log.exception("listener failed for %r", event)

    def _set_state(self, state: ConnState, message: str = "") -> None:
        self.state = state
        self._emit(ConnEvent(state, message))

    # ================================================================ properties
    @property
    def is_ready(self) -> bool:
        return self.state == ConnState.READY

    @property
    def mode(self) -> int:
        return self.device_state.mode

    # ============================================================ connect / scan
    def scan(self, timeout: float = 15.0, auto_connect: bool = True) -> concurrent.futures.Future:
        return self.runner.submit(self._scan(timeout, auto_connect))

    def stop_scan(self) -> concurrent.futures.Future:
        return self.runner.submit(self.transport.stop_scan())

    async def _scan(self, timeout: float, auto_connect: bool) -> None:
        if self.state not in (ConnState.DISCONNECTED,):
            return
        self._set_state(ConnState.SCANNING)
        found: list[DeviceFound] = []

        def on_found(dev: DeviceFound) -> None:
            self._emit(dev)
            if auto_connect and not found:
                found.append(dev)
                asyncio.get_running_loop().create_task(self._connect_after_scan(dev))

        try:
            await self.transport.scan(timeout, on_found)
        except TransportError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - e.g. bleak missing / radio problems
            log.exception("scan failed")
            self._fail(f"Pemindaian gagal: {exc}")
            return
        if not found and self.state == ConnState.SCANNING:
            self._set_state(ConnState.DISCONNECTED, "scan selesai")

    async def _connect_after_scan(self, dev: DeviceFound) -> None:
        await self.transport.stop_scan()
        await self._connect(dev.address)

    def connect(self, address: str) -> concurrent.futures.Future:
        return self.runner.submit(self._connect_from_ui(address))

    async def _connect_from_ui(self, address: str) -> None:
        if self.state == ConnState.SCANNING:
            await self.transport.stop_scan()
            self.state = ConnState.DISCONNECTED
        await self._connect(address)

    async def _connect(self, address: str, *, reconnect: bool = False) -> bool:
        if self.state not in (ConnState.DISCONNECTED, ConnState.SCANNING, ConnState.RECONNECTING):
            return False
        self._user_disconnect = False
        self.last_address = address
        self._set_state(ConnState.RECONNECTING if reconnect else ConnState.CONNECTING)
        try:
            await self.transport.connect(address, self._on_notify, self._on_link_lost)
            self._set_state(ConnState.DISCOVERING_SERVICES)
            self._set_state(ConnState.INITIALIZING_NOTIFY)
        except TransportError as exc:
            self._fail(str(exc))
            return False
        except Exception as exc:  # noqa: BLE001
            log.exception("connect failed")
            self._fail(str(exc))
            return False
        self._wake, self._ack = asyncio.Event(), asyncio.Event()
        self.queue.clear()
        self.profile_synced = False
        self._writer = asyncio.get_running_loop().create_task(self._writer_loop())
        self._set_state(ConnState.READY)
        self.read_state()  # handshake: [0x50, 0x01] -> 0xD0 -> [0x51, mode, 0..5]
        return True

    def disconnect(self) -> concurrent.futures.Future:
        return self.runner.submit(self._disconnect())

    async def _disconnect(self) -> None:
        self._user_disconnect = True
        if self.state in (ConnState.DISCONNECTED,):
            return
        if self.state == ConnState.SCANNING:
            await self.transport.stop_scan()
            self._set_state(ConnState.DISCONNECTED)
            return
        self._set_state(ConnState.DISCONNECTING)
        await self._teardown()
        self._set_state(ConnState.DISCONNECTED, "terputus")

    async def _teardown(self) -> None:
        self._testing = False
        if self._writer is not None:
            self._writer.cancel()
            self._writer = None
        self.queue.clear()
        try:
            await self.transport.disconnect()
        except Exception:  # noqa: BLE001
            log.debug("transport disconnect failed", exc_info=True)

    def _fail(self, message: str) -> None:
        self.last_error = message
        self._emit(ErrorEvent(message))
        self._set_state(ConnState.DISCONNECTED, message)

    def _on_link_lost(self) -> None:
        """Called by the transport (any thread) when the wheel disappears (GATT 133 / link loss)."""
        self.runner.call_soon(lambda: asyncio.get_running_loop().create_task(self._handle_link_lost()))

    async def _handle_link_lost(self) -> None:
        if self._user_disconnect or self.state in (ConnState.DISCONNECTED, ConnState.DISCONNECTING):
            return
        await self._teardown()
        address = self.last_address
        if self.auto_reconnect and address and not self._reconnecting:
            self._reconnecting = True
            try:
                for attempt, delay in enumerate((1.0, 2.0, 4.0), start=1):
                    self._set_state(ConnState.RECONNECTING, f"mencoba menyambung ulang ({attempt}/3)")
                    await asyncio.sleep(delay)
                    if self._user_disconnect:
                        return
                    if await self._connect(address, reconnect=True):
                        return
                    self.state = ConnState.RECONNECTING
            finally:
                self._reconnecting = False
        self._fail("Koneksi terputus")

    # ===================================================================== write
    def _enqueue(self, packet: bytes, *, on_sent: Callable[[], None] | None = None, urgent: bool = False) -> bool:
        """Queue a packet if the link is ready (Wheel_V10.write: ignored when not connected)."""
        if not self.is_ready or self._wake is None:
            return False
        self.queue.put(packet, on_sent=on_sent, urgent=urgent)
        self.runner.call_soon(self._wake.set)
        return True

    async def _writer_loop(self) -> None:
        assert self._wake is not None and self._ack is not None
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while True:
                    item = self.queue.pop()
                    if item is None:
                        break
                    self._ack.clear()
                    try:
                        await self.transport.write(item.packet)
                    except TransportError as exc:
                        log.warning("write failed: %s", exc)
                        self._emit(ErrorEvent(str(exc)))
                        break
                    self._emit(LogEvent("TX", item.packet))
                    try:  # response driven pacing (the next packet follows the ack) + safety timeout
                        await asyncio.wait_for(self._ack.wait(), self.ack_timeout)
                    except asyncio.TimeoutError:
                        pass
                    if item.on_sent is not None:
                        try:
                            item.on_sent()
                        except Exception:  # noqa: BLE001
                            log.exception("on_sent failed")
                    await asyncio.sleep(self.write_interval)  # >= 100 ms between packets
        except asyncio.CancelledError:
            pass

    # --- Wheel_V10 public API --------------------------------------------------
    def read_state(self) -> None:
        self._enqueue(codec.read_state())

    def read_profile(self) -> None:
        for page in range(C.PROFILE_PAGES):
            self._enqueue(codec.read_profile_page(self.device_state.mode, page))

    def write_profile(self, profile: DeviceProfile, mode: int, *, switch_mode: bool = True, resync: bool = True) -> bool:
        """Send a full profile (6 pages of 20 bytes, opcode 0x52). If the preset targets the other
        PC mode (D-Input <-> X-Input) the wheel is switched afterwards, like V10ProfileActivity."""
        if not self.is_ready:
            return False
        pages = profile.copy().clamp().pack_pages(mode)
        for page, frame in enumerate(pages):
            last = page == len(pages) - 1
            self._enqueue(frame, on_sent=(self._profile_sent if last else None))
        current = self.device_state.mode
        if switch_mode and current in C.SWITCHABLE_MODES and mode in C.SWITCHABLE_MODES and current != mode:
            self.switch_mode(mode)
        elif resync:
            self.read_state()  # state -> profile re-read keeps the local mirror honest
        return True

    def _profile_sent(self) -> None:
        self._emit(ChangeEvent(Change.PROFILE_WRITTEN))

    def write_profile_page(self, frame: bytes) -> None:
        """Send one pre-packed page (used by pedal-curve edits); header bytes are filled in here."""
        buf = bytearray(frame)
        buf[0] = C.REPORT_ID_WRITE_PROFILE_REQ
        buf[1] = self.device_state.mode & 0xFF
        self._enqueue(bytes(buf))

    def switch_mode(self, mode: int) -> None:
        self._enqueue(codec.switch_mode(mode))

    def write_mapping(self, original: int, mapped: int) -> None:
        self.profile.keymap[original] = mapped
        self._enqueue(codec.key_mapping(self.device_state.mode, original, mapped))

    def write_force_feedback(self, value: int) -> None:
        self.profile.ffb = value
        self._enqueue(codec.force_feedback(self.device_state.mode, value, self.profile.ffb_reverse))

    def write_force_feedback_reverse(self, reverse: int) -> None:
        self.profile.ffb_reverse = reverse
        self._enqueue(codec.force_feedback(self.device_state.mode, self.profile.ffb, reverse))

    def write_angle(self, angle: int) -> None:
        self.profile.angle = angle
        self._enqueue(codec.steering_angle(self.device_state.mode, angle))

    def write_profile_reset(self) -> None:
        self._enqueue(codec.profile_reset(self.device_state.mode))

    def write_force(self, spring: int, damping: int, friction: int, inertia: int) -> None:
        p = self.profile
        p.spring, p.damping, p.friction, p.inertia = spring, damping, friction, inertia
        self._enqueue(codec.physics_forces(spring, damping, friction, inertia))

    def write_spring(self, v: int) -> None:
        p = self.profile
        self.write_force(v, p.damping, p.friction, p.inertia)

    def write_damping(self, v: int) -> None:
        p = self.profile
        self.write_force(p.spring, v, p.friction, p.inertia)

    def write_friction(self, v: int) -> None:
        p = self.profile
        self.write_force(p.spring, p.damping, v, p.inertia)

    def write_inertia(self, v: int) -> None:
        p = self.profile
        self.write_force(p.spring, p.damping, p.friction, v)

    def write_curve(self, name: str, index: int, x: int, y: int) -> None:
        """Pedal chart edit: update one control point and push the whole page (3/4/5)."""
        self.profile.curve(name)[index] = [x, y]
        self.send_curve(name)

    def send_curve(self, name: str) -> None:
        page = {"acc": 3, "brake": 4, "clutch": 5}[name]
        self.write_profile_page(self.profile.pack_page(page, self.device_state.mode))

    def reset_curve(self, name: str) -> None:
        self.profile.reset_curve(name)
        self.send_curve(name)

    def toggle_test_mode(self, enable: bool) -> None:
        self._testing = enable
        # leaving test mode must not wait behind queued writes while telemetry floods the link
        self._enqueue(codec.test_mode(enable), urgent=not enable)

    @property
    def testing(self) -> bool:
        return self._testing

    # ================================================================== inbound
    def _on_notify(self, data: bytes) -> None:
        """Runs on the BLE thread. Mirrors Wheel_V10.handleNotifyData."""
        try:
            self._handle(codec.decode(data))
        except Exception:  # noqa: BLE001
            log.exception("failed to handle notification %s", bytes(data).hex())

    def _handle(self, msg: codec.Inbound) -> None:
        kind, raw = msg.kind, msg.raw
        if kind != "telemetry":
            self._emit(LogEvent("RX", raw))
        with self._lock:
            if kind == "state":
                self.device_state.unpack(raw)
                self._emit(ChangeEvent(Change.STATE))
                if self.auto_sync:
                    self.read_profile()
            elif kind == "profile_page":
                page = self.profile.unpack_page(raw)
                self._emit(ChangeEvent(Change.PROFILE_PAGE, page))
                if page == C.PROFILE_PAGES - 1:
                    self.profile_synced = True
                    self._emit(ChangeEvent(Change.PROFILE_READY))
            elif kind == "write_ack":
                pass  # completion is reported by the writer (on_sent) once the last page was acked
            elif kind == "edit_ack":
                self._handle_edit_ack(msg.data)
            elif kind == "telemetry":
                if self.test_data.unpack(raw):
                    self._emit(TestEvent(self.test_data.snapshot()))
        if kind != "telemetry" and self._ack is not None and self.runner.loop.is_running():
            self.runner.call_soon(self._ack.set)

    def _handle_edit_ack(self, d: dict) -> None:
        sub = d["sub"]
        ds, prof = self.device_state, self.profile
        if sub == C.CMD_SWITCH_MODE:
            ds.mode = d["mode"]
            self._emit(ChangeEvent(Change.MODE))
            self.read_state()
        elif sub == C.CMD_UPDATE_KEYMAP:
            prof.keymap[d["key"]] = d["mapped"]
            self._emit(ChangeEvent(Change.KEYMAP))
        elif sub == C.CMD_UPDATE_FFB:
            prof.ffb, prof.ffb_reverse = d["ffb"], d["reverse"]
            self._emit(ChangeEvent(Change.FFB))
        elif sub == C.CMD_UPDATE_ANGLE:
            ds.angle_mode = d["angle_mode"]
            prof.angle = d["angle"]
            self._emit(ChangeEvent(Change.ANGLE))
        elif sub == C.CMD_UPDATE_PEDAL:
            ds.pedal_state = d["state"]
            self._emit(ChangeEvent(Change.PEDAL_STATE))
            self.read_state()
        elif sub == C.CMD_UPDATE_LEVER:
            ds.lever_state = d["state"]
            self._emit(ChangeEvent(Change.LEVER_STATE))
            self.read_state()
        elif sub == C.CMD_UPDATE_BRAKE:
            ds.brake_state = d["state"]
            self._emit(ChangeEvent(Change.BRAKE_STATE))
            self.read_state()
        elif sub == C.CMD_RESET_PROFILE:
            self._emit(ChangeEvent(Change.RESET_DONE))
            self.read_profile()
        elif sub == C.CMD_UPDATE_FORCE:
            prof.spring, prof.damping = d["spring"], d["damping"]
            prof.friction, prof.inertia = d["friction"], d["inertia"]
            self._emit(ChangeEvent(Change.FORCE))

    # =================================================================== shutdown
    def shutdown(self) -> None:
        try:
            self.disconnect().result(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        if self._owns_runner:
            self.runner.stop()
