"""
Per-run hook bus for :class:`nos.core.engine.workflow.workflow.Workflow` execution telemetry.

Each workflow run that attaches an execution log gets a fresh
:class:`nos.hooks.manager.EventHookManager`. Handlers forward to the run's sink
(:class:`EventLogBuffer` / platform ``EventLog``) so :meth:`Workflow._on_start`,
:meth:`Workflow._on_init`, and related lifecycle hooks emit on the bus instead of calling sink methods directly.

Do not retain the bus beyond the run — :meth:`Workflow.set_exec_log` replaces it when a new
sink is attached.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from nos.hooks.manager import EventHookManager


class WorkflowRunEventType(str, Enum):
    """Scoped per-run hook event names (not registered on the global ``event_hooks`` singleton)."""

    WORKFLOW_INIT = "workflow.init"
    WORKFLOW_INIT_COMPLETED = "workflow.init_completed"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_FORM_RESPONSE = "workflow.form_response"
    WORKFLOW_ERROR = "workflow.error"
    WORKFLOW_END = "workflow.end"


def register_workflow_run_hooks_adapters(bus: EventHookManager, exec_log: Any) -> None:
    """Wire scoped bus events to structured execution-log calls for one workflow run."""

    def on_workflow_init(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        initial_state = d.get("initial_state") or {}
        exec_log.log_workflow_init(dict(initial_state) if initial_state else {})

    def on_workflow_init_completed(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        state = d.get("state") or {}
        exec_log.log_workflow_init_completed(dict(state) if state else {})

    def on_workflow_start(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        initial_state = d.get("initial_state") or {}
        state_mapping_desc = d.get("state_mapping_desc")
        workflow_id = d.get("workflow_id") or ""
        exec_log.log_workflow_start(
            dict(initial_state) if initial_state else {},
            state_mapping_desc=state_mapping_desc,
        )
        exec_log.log("info", f"Workflow {workflow_id} started")

    def on_workflow_form_response(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        exec_log.log_workflow_form_response_received(dict(d.get("form_response") or {}))

    def on_workflow_error(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        result = d.get("result")
        if result is None:
            return
        status = getattr(result, "status", "error")
        msg = getattr(result, "message", None) or ""
        exec_log.log(
            "error",
            f"Workflow execution failed: {status}",
            event="workflow_error",
            workflow_status=status,
            detail=str(msg),
        )

    def on_workflow_end(data: Any) -> None:
        d = data if isinstance(data, dict) else {}
        result = d.get("result")
        if result is None:
            return
        level = d.get("level") or "info"
        message = d.get("message") or "Workflow execution completed"
        exec_log.log(
            level,
            message,
            event="workflow_execution_result",
            initial_state=dict(getattr(result, "initial_state", None) or {}),
            final_state=dict(getattr(result, "state", None) or {}),
            state_changed=dict(getattr(result, "state_changed", None) or {}),
            workflow_status=getattr(result, "status", ""),
        )

    bus.register(WorkflowRunEventType.WORKFLOW_INIT, on_workflow_init)
    bus.register(WorkflowRunEventType.WORKFLOW_INIT_COMPLETED, on_workflow_init_completed)
    bus.register(WorkflowRunEventType.WORKFLOW_START, on_workflow_start)
    bus.register(WorkflowRunEventType.WORKFLOW_FORM_RESPONSE, on_workflow_form_response)
    bus.register(WorkflowRunEventType.WORKFLOW_ERROR, on_workflow_error)
    bus.register(WorkflowRunEventType.WORKFLOW_END, on_workflow_end)


def attach_workflow_run_hooks_bus(workflow: Any, exec_log: Any) -> EventHookManager:
    """
    Create a scoped bus, register channel adapters, assign to ``workflow``.

    Invoked from :meth:`nos.core.engine.workflow.workflow.Workflow.set_exec_log` when a non-``None``
    exec log is set.
    """
    bus = EventHookManager()
    register_workflow_run_hooks_adapters(bus, exec_log)
    workflow.set_run_event_hook(bus)
    return bus
