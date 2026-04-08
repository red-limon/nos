"""
SseManager — thread-safe fan-out registry for Server-Sent Events.

Each connected browser tab subscribes a dedicated Queue.
When an execution ends, platform ``EventLog`` (``nos.platform.execution_log``) calls ``publish()`` to push
the notification to every queue owned by that user.  The Flask SSE
streaming generator drains its queue and writes the SSE frame to the
HTTP response.

Thread-safety notes
-------------------
- The registry dict is protected by ``_lock`` (threading.Lock).
- ``Queue.put_nowait`` / ``Queue.get`` are safe for concurrent access.
- With eventlet monkey-patching active (Flask-SocketIO) these calls
  cooperate with the green-thread scheduler automatically.

Usage example
-------------
::

    # Background task (e.g. EventLog):
    from ...services.sse.manager import sse_manager
    sse_manager.publish(user_id="alice", event="execution_end", data={...})

    # Flask streaming route:
    q = sse_manager.subscribe(user_id)
    try:
        while True:
            item = q.get(timeout=25)  # yields green thread while waiting
            yield sse_frame(item)
    finally:
        sse_manager.unsubscribe(user_id, q)
"""

import logging
import queue
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel placed in a queue to ask the generator to exit cleanly.
_STOP_SENTINEL = object()


class SseManager:
    """Fan-out registry: maps user_id → list[Queue].

    One :class:`Queue` per open browser tab.  Multiple tabs of the same
    user each receive the same events independently.
    """

    def __init__(self) -> None:
        # user_id → list of Queue objects (one per open tab)
        self._registry: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    # ── Subscription management ───────────────────────────────────────────────

    def subscribe(self, user_id: str, maxsize: int = 50) -> "queue.Queue[Any]":
        """Register a new client queue for *user_id* and return it.

        Args:
            user_id:  Session username (key for fan-out).
            maxsize:  Queue capacity; excess events are dropped with a warning.

        Returns:
            A fresh :class:`queue.Queue` to be drained by the SSE generator.
        """
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._registry.setdefault(user_id, []).append(q)
        logger.debug(
            "SSE subscribe: user=%s  active_connections=%d",
            user_id,
            self._count_unsafe(),
        )
        return q

    def unsubscribe(self, user_id: str, q: "queue.Queue[Any]") -> None:
        """Remove a client queue when the SSE generator exits (client disconnected).

        Safe to call multiple times; silently ignores unknown queues.
        """
        with self._lock:
            queues = self._registry.get(user_id, [])
            try:
                queues.remove(q)
            except ValueError:
                pass
            if not queues:
                self._registry.pop(user_id, None)
        logger.debug(
            "SSE unsubscribe: user=%s  active_connections=%d",
            user_id,
            self._count_unsafe(),
        )

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, user_id: str, event: str, data: dict[str, Any]) -> int:
        """Push an SSE event to all queues registered for *user_id*.

        Args:
            user_id:  Target user.
            event:    SSE event name (e.g. ``"execution_end"``).
            data:     JSON-serialisable payload dict.

        Returns:
            Number of queues that actually received the event
            (0 if user has no open connections).
        """
        with self._lock:
            queues = list(self._registry.get(user_id, []))

        delivered = 0
        for q in queues:
            try:
                q.put_nowait({"event": event, "data": data})
                delivered += 1
            except queue.Full:
                logger.warning(
                    "SSE queue full — event dropped  user=%s event=%s",
                    user_id,
                    event,
                )

        logger.debug(
            "SSE publish: user=%s event=%s delivered=%d/%d",
            user_id,
            event,
            delivered,
            len(queues),
        )
        return delivered

    def publish_all(self, event: str, data: dict[str, Any]) -> int:
        """Broadcast *event* to ALL connected clients regardless of user.

        Useful for system-wide announcements (e.g. maintenance, reload).

        Returns:
            Total number of deliveries across all queues.
        """
        with self._lock:
            all_queues = [q for qs in self._registry.values() for q in qs]

        delivered = 0
        for q in all_queues:
            try:
                q.put_nowait({"event": event, "data": data})
                delivered += 1
            except queue.Full:
                logger.warning("SSE broadcast: queue full — event dropped  event=%s", event)

        logger.debug("SSE broadcast: event=%s delivered=%d", event, delivered)
        return delivered

    def stop_user(self, user_id: str) -> None:
        """Push the stop sentinel to all queues of *user_id* so generators exit."""
        with self._lock:
            queues = list(self._registry.get(user_id, []))
        for q in queues:
            try:
                q.put_nowait(_STOP_SENTINEL)
            except queue.Full:
                pass

    # ── Utilities ─────────────────────────────────────────────────────────────

    def is_stop(self, item: Any) -> bool:
        """Return True if *item* is the internal stop sentinel."""
        return item is _STOP_SENTINEL

    def connected_users(self) -> list[str]:
        """Return list of user_ids that currently have at least one open SSE connection."""
        with self._lock:
            return list(self._registry.keys())

    def connection_count(self) -> int:
        """Total number of active SSE connections across all users."""
        with self._lock:
            return self._count_unsafe()

    def _count_unsafe(self) -> int:
        """Count active queues WITHOUT acquiring the lock (caller must hold it or not care)."""
        return sum(len(qs) for qs in self._registry.values())


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
sse_manager: SseManager = SseManager()
