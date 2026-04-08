"""
Application-wide ``event_hooks`` listener registration (startup).

Single entry point: :func:`register_app_event_listeners`. Add further transports here
(e.g. another function for a future global fan-out); per-connection SSE registration
stays in the SSE manager.

**Node run hooks (scoped bus, not registered here)**

Per-node-run telemetry uses a **separate** :class:`nos.hooks.manager.EventHookManager`
instance for each execution — see :mod:`nos.core.execution_log.node_run_hooks`.
:meth:`nos.core.engine.node.node.Node.set_exec_log` (non-``None`` sink) calls
:func:`nos.core.execution_log.node_run_hooks.attach_node_run_hooks_bus` internally to
create that bus, register adapters to the run's ``EventLogBuffer`` /
platform ``EventLog``, and assign it to the node. Events use
:class:`nos.core.execution_log.node_run_hooks.NodeRunEventType` (e.g. ``node.start``) and
**do not** appear on the process-wide ``event_hooks`` singleton, so they are **not**
listed below. The scoped bus is cleared when :meth:`nos.core.engine.node.node.Node.run`
finishes (``finally``); do not keep a reference to it after the run.
"""

from __future__ import annotations

import logging
from typing import Any

from .manager import EventType, event_hooks

logger = logging.getLogger(__name__)


def register_app_event_listeners(socketio: Any) -> None:
    """Register all process-wide ``event_hooks`` subscribers for the running app."""
    _register_socketio_listeners(socketio)


def _register_socketio_listeners(socketio) -> None:
    """Subscribe ``event_hooks`` → Socket.IO broadcast (namespace ``/``)."""

    def broadcast_state_change(data):
        try:

            def emit_event():
                try:
                    socketio.emit("state_change", data, to=None, namespace="/")
                    logger.debug(
                        "SocketIO broadcasted state_change: %s", data.get("type", "unknown")
                    )
                except Exception as emit_error:
                    logger.error("Error in SocketIO emit: %s", emit_error, exc_info=True)

            socketio.start_background_task(emit_event)
        except Exception as e:
            logger.error("Error starting background task for state_change: %s", e, exc_info=True)

    def broadcast_user_event(data):
        try:

            def emit_event():
                try:
                    socketio.emit("user_event", data, to=None, namespace="/")
                    logger.debug(
                        "SocketIO broadcasted user_event: %s", data.get("type", "unknown")
                    )
                except Exception as emit_error:
                    logger.error("Error in SocketIO emit: %s", emit_error, exc_info=True)

            socketio.start_background_task(emit_event)
        except Exception as e:
            logger.error("Error starting background task for user_event: %s", e, exc_info=True)

    def broadcast_workflow_event(data):
        try:

            def emit_event():
                try:
                    socketio.emit("workflow_event", data, to=None, namespace="/")
                    logger.debug(
                        "SocketIO broadcasted workflow_event: %s",
                        data.get("type", "unknown"),
                    )
                except Exception as emit_error:
                    logger.error("Error in SocketIO emit: %s", emit_error, exc_info=True)

            socketio.start_background_task(emit_event)
        except Exception as e:
            logger.error(
                "Error starting background task for workflow_event: %s", e, exc_info=True
            )

    event_hooks.register(EventType.STATE_CHANGED, broadcast_state_change)
    event_hooks.register(EventType.USER_CREATED, broadcast_user_event)
    event_hooks.register(EventType.USER_UPDATED, broadcast_user_event)
    event_hooks.register(EventType.USER_DELETED, broadcast_user_event)
    event_hooks.register(EventType.WORKFLOW_STARTED, broadcast_workflow_event)
    event_hooks.register(EventType.WORKFLOW_COMPLETED, broadcast_workflow_event)
    event_hooks.register(EventType.WORKFLOW_ERROR, broadcast_workflow_event)
    event_hooks.register(EventType.WORKFLOW_STOPPED, broadcast_workflow_event)
