"""Thread-safe outgoing packet queue with in-place replacement of same-kind packets."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from . import codec


@dataclass
class QueueItem:
    packet: bytes
    key: Optional[tuple]
    on_sent: Optional[Callable[[], None]] = None


class WriteQueue:
    """FIFO of pending packets.

    ``put`` replaces a still-queued packet with the same dedup key (a slider dragged from
    50 -> 60 -> 70 must not flood the 100 ms paced link): the *position* is kept, the payload
    is the newest one.
    """

    def __init__(self) -> None:
        self._items: deque[QueueItem] = deque()
        self._lock = threading.Lock()
        self.replaced = 0  # statistics (visible in tests / the debug log)

    def put(
        self,
        packet: bytes,
        *,
        key: Optional[tuple] = ...,  # type: ignore[assignment]
        on_sent: Optional[Callable[[], None]] = None,
        urgent: bool = False,
    ) -> bool:
        """Queue a packet. Returns True when it replaced an older queued packet."""
        if key is ...:
            key = codec.dedup_key(packet)
        item = QueueItem(bytes(packet), key, on_sent)
        with self._lock:
            if key is not None:
                for existing in self._items:
                    if existing.key == key:
                        existing.packet = item.packet
                        if on_sent is not None:
                            existing.on_sent = on_sent
                        self.replaced += 1
                        return True
            if urgent:
                self._items.appendleft(item)
            else:
                self._items.append(item)
        return False

    def pop(self) -> Optional[QueueItem]:
        with self._lock:
            return self._items.popleft() if self._items else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def snapshot(self) -> list:
        with self._lock:
            return [i.packet for i in self._items]
