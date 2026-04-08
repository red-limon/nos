"""
Pending-request registry for :class:`~nos.platform.execution_log.event_log.EventLog`.

**Problem.** The server blocks inside :meth:`~nos.platform.execution_log.event_log.EventLog.request_and_wait`
while the user acts in the UI (forms, confirmations, etc.). When the client sends an answer over Socket.IO, the handler
only receives ``request_id`` and payload — it needs the **same** :class:`EventLog` instance that is waiting.

**Role.** :class:`EventLogRegistry` stores a thread-safe map ``request_id → EventLog``. The event log registers
before waiting and unregisters after a response, timeout, or error. Socket handlers resolve the instance via
:meth:`EventLogRegistry.get_for_request` and call :meth:`~nos.platform.execution_log.event_log.EventLog.handle_response`.

**Exports.** Module attribute :data:`_event_log_registry` is the process-wide singleton used by
:mod:`nos.platform.execution_log.event_log` and
by platform socket code. Use :meth:`EventLogRegistry.clear` only in tests.
"""

import threading
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .event_log import EventLog


class EventLogRegistry:
    """
    Process-wide map from interactive ``request_id`` to the :class:`EventLog` waiting for a client response.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, "EventLog"] = {}

    def register_pending_request(self, request_id: str, event_log: "EventLog"):
        """Register a pending request for later response routing."""
        with self._lock:
            self._pending[request_id] = event_log

    def unregister_pending_request(self, request_id: str):
        """Remove a pending request (after response or timeout)."""
        with self._lock:
            self._pending.pop(request_id, None)

    def get_for_request(self, request_id: str) -> Optional["EventLog"]:
        """Return the event log waiting for this ``request_id``, if any."""
        with self._lock:
            return self._pending.get(request_id)

    def clear(self):
        """Clear all pending requests (for testing)."""
        with self._lock:
            self._pending.clear()


_event_log_registry = EventLogRegistry()
