"""
Runtime factory for the platform realtime sink :class:`~nos.platform.execution_log.event_log.EventLog`.

This is **not** Python's :mod:`logging` module — it wires how the engine obtains ``EventLog``
instances (Socket.IO, DB hooks, nested runs). The node's ``channel`` may be
:class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` or ``EventLog``.

**Why.** :mod:`nos.core.engine` must not hard-code the platform class at import time. Any code path
that needs an ``EventLog`` (Socket.IO room, ``persist_to_db`` audit, nested workflow
node channels mirroring a realtime parent) resolves the concrete class through a **callable
registered once** at application bootstrap (see ``nos.platform``).

**Core-only.** If no factory is registered, :func:`build_event_log` raises
:class:`RuntimeError`. Use :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer`
and call ``run_node(..., room=None, persist_to_db=False)`` (and equivalent workflow paths).

**Mitigating indirection**

- Single registration site: :func:`register_event_log_factory` (typically from
  ``create_app`` via :func:`nos.platform.services.event_log_factory.register_default_event_log_factory`).
- Stable keyword interface: match :class:`~nos.platform.execution_log.event_log.EventLog.__init__`.
- Debug log line when a factory is registered (see :func:`register_event_log_factory`).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Returns an EventLog instance; typed loosely to avoid import cycles at module load.
EventLogFactory = Callable[..., Any]

_factory: Optional[EventLogFactory] = None


def register_event_log_factory(factory: EventLogFactory) -> None:
    """Install the callable used by :func:`build_event_log`.

    Args:
        factory: Typically a thin wrapper that forwards ``**kwargs`` to
            :class:`~nos.platform.execution_log.event_log.EventLog`.
    """
    global _factory
    _factory = factory
    name = getattr(factory, "__qualname__", None) or getattr(factory, "__name__", repr(factory))
    logger.debug("execution_log: EventLog factory registered (%s)", name)


def clear_event_log_factory() -> None:
    """Remove the factory (tests / isolated scripts)."""
    global _factory
    _factory = None


def get_event_log_factory() -> Optional[EventLogFactory]:
    """Return the registered factory, or ``None`` if core-only mode."""
    return _factory


def build_event_log(**kwargs: Any) -> Any:
    """Construct an :class:`~nos.platform.execution_log.event_log.EventLog` via the registered factory.

    Raises:
        RuntimeError: If no factory was registered but an ``EventLog`` is required.
    """
    if _factory is None:
        raise RuntimeError(
            "No EventLog factory is registered. The engine cannot build an "
            "EventLog (required when a Socket.IO room is set, when persist_to_db=True "
            "on run_node, or for nested workflow node channels that mirror a realtime parent). "
            "Core-only / library usage: use EventLogBuffer — e.g. run_node(..., room=None, "
            "persist_to_db=False). "
            "Web app: call register_default_event_log_factory() from module "
            "nos.platform.services.event_log_factory inside Flask create_app()."
        )
    return _factory(**kwargs)
