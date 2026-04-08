"""
Per-run hook bus for :class:`nos.core.engine.node.node.Node` execution telemetry.

Each execution gets a fresh :class:`nos.hooks.manager.EventHookManager` instance.
Handlers forward to the run's :class:`EventLogBuffer` / :class:`~nos.platform.execution_log.EventLog`.
Do not retain the bus beyond the run — :meth:`Node.run` clears it in ``finally``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from nos.hooks.manager import EventHookManager

from .event_log_buffer import EventLogBuffer


class NodeRunEventType(str, Enum):
    """Scoped per-run hook event names (not registered on the global ``event_hooks`` singleton)."""

    NODE_RUN = "node.run"
    NODE_START = "node.start"
    NODE_INIT = "node.init"
    NODE_INIT_COMPLETED = "node.init_completed"
    NODE_FORM_RESPONSE = "node.form_response"
    NODE_STATE_CHANGED = "node.state_changed"
    NODE_ERROR = "node.error"
    NODE_STOP = "node.stop"
    NODE_END = "node.end"


def register_node_run_hooks_adapters(bus: EventHookManager, exec_log: EventLogBuffer) -> None:
    """Wire scoped bus events to structured execution-log calls for one run."""

    def on_node_run(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_run(request=d.get("request") or {})

    def on_node_start(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_start(request=d.get("request") or {})

    def on_node_init(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_init(
            initial_state=d.get("initial_state") or {},
            initial_params=d.get("initial_params"),
        )

    def on_node_init_completed(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_init_completed(
            state=d.get("state") or {},
            input_params=d.get("input_params") or {},
            output_format=d.get("output_format"),
        )

    def on_node_form_response(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_form_response_received(form_response=d.get("form_response") or {})

    def on_node_state_changed(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_node_state_changed(
            key=d.get("key", ""),
            old_value=d.get("old_value"),
            new_value=d.get("new_value"),
        )

    def on_node_error(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        result = d.get("result")
        if result is not None:
            exec_log.log_node_error(result, message=d.get("message") or "")

    def on_node_stop(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        result = d.get("result")
        if result is not None:
            exec_log.log_node_stop(result, message=d.get("message") or "Execution cancelled by user")

    def on_node_end(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        result = d.get("result")
        if result is not None:
            exec_log.log_node_end(
                result=result,
                level=d.get("level") or "info",
                message=d.get("message") or "Node execution completed",
            )

    bus.register(NodeRunEventType.NODE_RUN, on_node_run)
    bus.register(NodeRunEventType.NODE_START, on_node_start)
    bus.register(NodeRunEventType.NODE_INIT, on_node_init)
    bus.register(NodeRunEventType.NODE_INIT_COMPLETED, on_node_init_completed)
    bus.register(NodeRunEventType.NODE_FORM_RESPONSE, on_node_form_response)
    bus.register(NodeRunEventType.NODE_STATE_CHANGED, on_node_state_changed)
    bus.register(NodeRunEventType.NODE_ERROR, on_node_error)
    bus.register(NodeRunEventType.NODE_STOP, on_node_stop)
    bus.register(NodeRunEventType.NODE_END, on_node_end)


def attach_node_run_hooks_bus(node: Any, exec_log: EventLogBuffer) -> EventHookManager:
    """
    Create a scoped bus, register channel adapters, assign to ``node``.

    Invoked from :meth:`nos.core.engine.node.node.Node.set_exec_log` when a non-``None`` exec log
    is set. Do not keep references to the returned bus beyond the node run.
    """
    bus = EventHookManager()
    register_node_run_hooks_adapters(bus, exec_log)
    node.set_run_event_hook(bus)
    return bus
