"""
Workflow and Node execution engine.

Handles:
- Synchronous execution
- Background execution (threading)
- Scheduled execution (stub)
- Node execution with state management
- Link routing
- Error handling
- Execution tracking and cancellation
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Literal, Optional, TYPE_CHECKING, Union
from concurrent.futures import ThreadPoolExecutor, Future
from .base import (
    Workflow,
    Node,
    Link,
    WorkflowStatus,
    NodeOutput,
    LinkResult,
    WorkflowExecutionResult,
    WorkflowOutput,
    WorkflowResponseData,
)
from .node import NodeExecutionResult, NodeResponseData
from ..execution_log import (
    EventLogBuffer,
    ObservableStateDict,
    create_default_workflow_exec_log,
    normalize_debug_mode,
)
from ..execution_log.event_log_buffer import CancellationError
from ..execution_log.logger_factory import build_event_log
from nos.io_adapters.output_formats_schema import OUTPUT_FORMATS, validate_output_for_format

if TYPE_CHECKING:
    from nos.platform.execution_log.event_log import EventLog

logger = logging.getLogger(__name__)

_platform_event_log_cls: Optional[type] = None


def _get_platform_event_log_type() -> type:
    """Lazy import to avoid circular import (core package → engine → platform.event_log → core.execution_log)."""
    global _platform_event_log_cls
    if _platform_event_log_cls is None:
        from nos.platform.execution_log.event_log import EventLog as _EventLog

        _platform_event_log_cls = _EventLog
    return _platform_event_log_cls


def _is_platform_event_log(sink: Any) -> bool:
    return isinstance(sink, _get_platform_event_log_type())


def _is_interactive_exec_log(sink: Any) -> bool:
    """True for platform :class:`~nos.platform.execution_log.event_log.EventLog` or worker proxy (RPC to parent)."""
    if _is_platform_event_log(sink):
        return True
    return bool(getattr(sink, "is_interactive_worker_proxy", False))


def _synthetic_node_execution_result_from_exception(
    exc: Exception,
    *,
    node: Node,
    current_node_id: str,
    exec_log: Union[EventLogBuffer, "EventLog"],
) -> NodeExecutionResult:
    """
    When ``node.run`` raises (unexpected path), build a structured result so the workflow can still
    evaluate links and apply :class:`~nos.core.engine.link.failure_policy.OnNodeFailure` / link policies.
    """
    ended_at = datetime.now(timezone.utc)
    err_msg = str(exc)
    ea = ended_at.isoformat()
    ev = exec_log.get_events() if exec_log else []
    return NodeExecutionResult(
        execution_id=getattr(exec_log, "execution_id", "") or "",
        node_id=current_node_id,
        module_path=node.__class__.__module__,
        class_name=node.__class__.__name__,
        command=getattr(exec_log, "_command", "") if exec_log else "",
        status="internal_error",
        response=NodeResponseData(
            output={
                "output_format": "json",
                "data": {
                    "internal_error": True,
                    "detail": err_msg,
                    "stage": "workflow_engine_node_run",
                },
            },
            metadata={},
        ),
        initial_state={},
        input_params={},
        final_state={},
        started_at=ea,
        ended_at=ea,
        elapsed_time="0s",
        event_logs=ev,
    )


def _command_from_run_request(request: Optional[Dict[str, Any]]) -> str:
    """Build ``WorkflowExecutionResult.command`` from ``execute_sync(..., request=...)``."""
    if not request or not isinstance(request, dict):
        return ""
    c = request.get("command")
    if c is None:
        return ""
    return str(c)


def _make_workflow_error_result(
    workflow: Workflow,
    exec_log: Union[EventLogBuffer, EventLog],
    *,
    started_at: float,
    initial_state_snapshot: Dict[str, Any],
    node_ids_executed: list,
    exc: Exception,
    current_node_id: Optional[str] = None,
) -> WorkflowExecutionResult:
    """Build a terminal :class:`WorkflowExecutionResult` for an exception path (engine / validation)."""
    ended_at_time = time.time()
    duration = ended_at_time - started_at
    started_at_iso = datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
    ended_at_iso = datetime.fromtimestamp(ended_at_time, tz=timezone.utc).isoformat()
    final_state = dict(workflow.state)
    err_msg = str(exc)
    wf_cmd = _command_from_run_request(getattr(workflow, "_run_context_request", None))
    all_keys = set(initial_state_snapshot.keys()) | set(final_state.keys())
    state_changed: Dict[str, Dict[str, Any]] = {}
    for k in all_keys:
        old_v = initial_state_snapshot.get(k)
        new_v = final_state.get(k)
        if old_v != new_v:
            state_changed[k] = {"old": old_v, "new": new_v}
    data: Dict[str, Any] = {"internal_error": True, "detail": err_msg}
    if current_node_id is not None:
        data["node_id"] = current_node_id
    return WorkflowExecutionResult(
        execution_id=exec_log.execution_id,
        workflow_id=workflow.workflow_id,
        module_path=workflow.__class__.__module__,
        class_name=workflow.__class__.__name__,
        command=wf_cmd,
        status="error",
        response=WorkflowResponseData(
            output={"output_format": "json", "data": data},
            metadata={"error": True},
        ),
        state=final_state,
        state_changed=state_changed,
        initial_state=initial_state_snapshot,
        started_at=started_at_iso,
        ended_at=ended_at_iso,
        message=err_msg,
        duration=duration,
        node_ids_executed=list(node_ids_executed),
        event_logs=exec_log.get_events(),
    )


@dataclass
class ExecutionContext:
    """Context for a running execution (node or workflow)."""
    execution_id: str
    execution_type: Literal["node", "workflow"]
    started_at: float
    node_id: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow: Optional[Workflow] = None
    node: Optional[Node] = None
    exec_log: Optional[Union[EventLogBuffer, EventLog]] = None
    cancelled: bool = False
    child_process: Any = None
    mp_stop_event: Any = None


class WorkflowEngine:
    """
    Core workflow and node execution engine.
    
    Supports multiple execution modes:
    - Synchronous: Blocks until completion
    - Background: Runs in separate thread
    - Scheduled: Runs at specified intervals (stub implementation)
    
    All executions (nodes and workflows) are tracked and can be stopped.
    """
    
    # Default: scale with available CPUs, min 16, max 64
    _DEFAULT_MAX_WORKERS: int = min(64, max(16, (os.cpu_count() or 4) * 4))

    def __init__(self, max_workers: int | None = None):
        """
        Initialize workflow engine.

        Args:
            max_workers: Maximum concurrent background executions.
                         Defaults to min(64, max(16, cpu_count * 4)).
        """
        workers = max_workers if max_workers is not None else self._DEFAULT_MAX_WORKERS
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._running_executions: Dict[str, Future] = {}
        self._execution_contexts: Dict[str, ExecutionContext] = {}
    
    def execute_sync(
        self,
        workflow: Workflow,
        initial_state: Dict[str, Any] = None,
        exec_log: Optional[Union[EventLogBuffer, EventLog]] = None,
        debug_mode: Literal["trace", "debug"] = "trace",
        output_format: str = "json",
        request: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionResult:
        """
        Execute workflow synchronously (blocks until completion).

        Args:
            workflow: Workflow instance to execute
            initial_state: Initial state for workflow
            exec_log: EventLogBuffer (REST API) or EventLog (Socket.IO)
            debug_mode: ``trace`` — logs only (no per-node interactive forms); ``debug`` — per-node forms when
                using a platform log with ``request_and_wait``. Initial shared-state form (if any) is driven only by
                ``state_schema`` and a platform sink, not by this flag.
            output_format: Output format for result rendering (json, text, html, table, code, tree, chart, download)
            request: Optional caller context (e.g. ``{"command": "run workflow …"}``, ``tenant_id``, …).
                Stored on the workflow as ``_run_context_request`` for :meth:`Workflow._on_start` and each
                node's ``run(..., request=...)`` under key ``workflow_run_request``. Drives ``WorkflowExecutionResult.command``
                when ``request`` contains a string ``command`` key.

        Returns:
            WorkflowExecutionResult with response.output (output_format + data), state, state_changed,
            execution_id, timestamps, status, duration, node_ids_executed, event_logs.
        
        Raises:
            Exception: If execution fails
        """
        workflow._run_context_request = dict(request) if isinstance(request, dict) else None
        try:
            if os.environ.get("NOS_EXECUTION_WORKER") == "1":
                return self._execute_sync_inner(
                    workflow,
                    initial_state or {},
                    exec_log,
                    debug_mode,
                    output_format,
                )
            el = exec_log or create_default_workflow_exec_log(workflow.workflow_id)
            of = str(output_format).lower().strip()
            if of not in OUTPUT_FORMATS:
                raise ValueError(
                    f"Invalid output_format '{output_format}'. Allowed: {', '.join(OUTPUT_FORMATS)}"
                )
            dm = normalize_debug_mode(debug_mode)
            from nos.platform.execution_process.runner import run_workflow_in_process_sync

            return run_workflow_in_process_sync(
                self,
                workflow,
                initial_state,
                el,
                dm,
                of,
                request,
            )
        finally:
            workflow._run_context_request = None

    def _execute_sync_inner(
        self,
        workflow: Workflow,
        initial_state: Dict[str, Any],
        exec_log: Optional[Union[EventLogBuffer, EventLog]],
        debug_mode: Literal["trace", "debug"],
        output_format: str,
    ) -> WorkflowExecutionResult:
        debug_mode = normalize_debug_mode(debug_mode)
        if exec_log is None:
            exec_log = create_default_workflow_exec_log(workflow.workflow_id)

        run_started_at = time.time()

        # Attach exec log and scoped hook bus first (Workflow._on_start / prepare need bus + sink).
        workflow.set_exec_log(exec_log)

        output_format = str(output_format).lower().strip()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError(
                f"Invalid output_format '{output_format}'. Allowed: {', '.join(OUTPUT_FORMATS)}"
            )

        # Same order as Node.run: _on_start (pre-init) before prepare (= define + _initialize_state + _on_init).
        workflow._on_start(initial_state)

        # Prepare workflow (define + initialize_state + _on_init internally).
        # Form below uses workflow.state after validation.
        workflow.prepare(initial_state)

        # Initial shared-state form when the sink supports interactive I/O (same condition for trace and debug;
        # per-node forms are gated by debug_mode inside :meth:`_execute_workflow`).
        if _is_interactive_exec_log(exec_log) and workflow.state_schema:
            from nos.io_adapters.input_form_mapping import create_form_request_payload

            state_values = dict(workflow.state)
            form_payload = create_form_request_payload(
                state_schema=workflow.state_schema,
                params_schema=None,
                state_values=state_values,
                params_values={},
                workflow_id=workflow.workflow_id,
                execution_id=exec_log.execution_id,
                title=f"Configure initial state: {workflow.name}",
            )
            has_state_fields = form_payload.get("state", {}).get("fields", [])
            if has_state_fields:
                exec_log.log("info", "📝 Waiting for initial state input...")
                form_response = exec_log.request_and_wait(
                    event_type="form_input",
                    data=form_payload,
                    timeout=300.0,
                )
                if form_response:
                    workflow._on_input(form_response)
                    if form_response.get("cancelled"):
                        exec_log.log("warning", "Workflow cancelled by user")
                        _now = datetime.now(timezone.utc).isoformat()
                        cancel_result = WorkflowExecutionResult(
                            execution_id=exec_log.execution_id,
                            workflow_id=workflow.workflow_id,
                            module_path=workflow.__class__.__module__,
                            class_name=workflow.__class__.__name__,
                            command=_command_from_run_request(
                                getattr(workflow, "_run_context_request", None)
                            ),
                            status="cancelled",
                            response=WorkflowResponseData(
                                output={"output_format": output_format, "data": {}},
                                metadata={"cancelled": True},
                            ),
                            state={},
                            state_changed={},
                            initial_state=dict(initial_state or {}),
                            started_at=_now,
                            ended_at=_now,
                            message=None,
                            duration=0.0,
                            node_ids_executed=[],
                            event_logs=exec_log.get_events(),
                        )
                        workflow._on_end(
                            cancel_result,
                            level="warning",
                            message="Workflow cancelled by user",
                        )
                        return cancel_result
                    if form_response.get("state"):
                        try:
                            validated = workflow.state_schema(**form_response["state"])
                            workflow._state = validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)
                        except Exception as e:
                            exec_log.log_error(f"Form validation failed: {e}", error_type="form_validation_error", detail=str(e))
                            val_result = _make_workflow_error_result(
                                workflow,
                                exec_log,
                                started_at=run_started_at,
                                initial_state_snapshot=dict(initial_state or {}),
                                node_ids_executed=[],
                                exc=e,
                            )
                            workflow._on_error(val_result)
                            raise ValueError(f"Initial state validation failed: {e}") from e
                        exec_log.log("info", "✓ Form submitted, starting workflow...")

        # Register so stop_execution / engine.shutdown can request_stop on this exec_log.
        # Console and API often use execute_sync (blocking); without this, Ctrl+C / stop <id>
        # finds no context and cooperative cancel never reaches ParallelNode / scrapers.
        eid = exec_log.execution_id
        self._execution_contexts[eid] = ExecutionContext(
            execution_id=eid,
            execution_type="workflow",
            started_at=time.time(),
            workflow_id=workflow.workflow_id,
            workflow=workflow,
            exec_log=exec_log,
        )
        try:
            return self._execute_workflow(
                workflow,
                exec_log,
                output_format=output_format,
                workflow_debug_mode=debug_mode,
            )
        finally:
            self._execution_contexts.pop(eid, None)
            workflow._on_stop()
    
    def execute_background(
        self,
        workflow: Workflow,
        initial_state: Dict[str, Any] = None,
        exec_log: Optional[Union[EventLogBuffer, EventLog]] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        debug_mode: Literal["trace", "debug"] = "trace",
        output_format: str = "json",
        request: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Execute workflow in a child OS process (non-blocking: parent runs a short drain loop in a daemon thread).

        Args:
            workflow: Workflow instance to execute
            initial_state: Initial state for workflow
            exec_log: EventLogBuffer (REST API) or EventLog (Socket.IO)
            callback: Optional callback function called with final state
            debug_mode: Same semantics as :meth:`execute_sync`.
            output_format: Output format for result rendering (json, text, html, table, etc.)
            request: Same optional run context as :meth:`execute_sync` (``command``, tracing fields, …).

        Returns:
            Execution ID (can be used to track/cancel execution)
        """
        if os.environ.get("NOS_EXECUTION_WORKER") == "1":
            raise RuntimeError(
                "execute_background cannot run inside NOS execution worker process"
            )
        debug_mode = normalize_debug_mode(debug_mode)
        if exec_log is None:
            exec_log = create_default_workflow_exec_log(workflow.workflow_id)

        output_format = str(output_format).lower().strip()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError(
                f"Invalid output_format '{output_format}'. Allowed: {', '.join(OUTPUT_FORMATS)}"
            )

        from nos.platform.execution_process.runner import run_workflow_in_process_background

        return run_workflow_in_process_background(
            self,
            workflow,
            initial_state,
            exec_log,
            debug_mode,
            output_format,
            request,
            callback,
        )

    def _run_node_sync_impl(
        self,
        *,
        execution_id: str,
        node_id: str,
        node: Node,
        exec_log: Union[EventLogBuffer, "EventLog"],
        state: Dict[str, Any],
        input_params: Dict[str, Any],
        mode: str,
        room: Optional[str],
        debug_mode: str,
        command: Optional[str],
        run_request_extras: Optional[Dict[str, Any]],
        output_format: Optional[str],
        context: ExecutionContext,
        callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Dict[str, Any]:
        """Run one node synchronously (in-process); used by tests / worker process entrypoint."""
        try:
            if context.cancelled:
                logger.info("Node execution %s cancelled before start", execution_id)
                cancelled_dict = {
                    "cancelled": True,
                    "execution_id": execution_id,
                    "node_id": node_id,
                }
                if callback:
                    callback(cancelled_dict)
                return cancelled_dict

            if debug_mode == "debug" and (_is_interactive_exec_log(exec_log) or room):
                node.set_debug_mode(True)

            def on_state_set(key, old_val, new_val):
                node._on_state_changed(key, old_val, new_val)

            observable_state = ObservableStateDict(state.copy(), on_set=on_state_set)

            extras = dict(run_request_extras) if run_request_extras else {}
            if command is not None:
                cmd_str = str(command)
            else:
                c = extras.get("command")
                cmd_str = str(c) if c is not None else ""
            run_request = {
                **extras,
                "node_id": node_id,
                "state": state.copy(),
                "input_params": input_params.copy(),
                "mode": mode,
                "execution_id": execution_id,
                "command": cmd_str,
            }
            if output_format is not None:
                run_request["output_format"] = str(output_format).lower().strip()
            logger.info("Executing node %s (mode=%s, execution_id=%s)", node_id, mode, execution_id)
            result = node.run(
                observable_state,
                input_params,
                request=run_request,
                output_format=output_format,
            )

            success = result.status == "completed"
            cancelled = result.status == "cancelled"
            error_msg = None
            if result.status in ("validation_error", "output_validation_error"):
                out = result.response.output if hasattr(result, "response") else {}
                error_msg = out.get("detail", str(result.status))
            elif not success and not cancelled:
                out = getattr(getattr(result, "response", None), "output", None) or {}
                error_msg = out.get("detail") or out.get("reason") or str(result.status)

            result_dict = {
                "success": success,
                "cancelled": cancelled,
                "error": error_msg,
                "execution_id": execution_id,
                "node_id": node_id,
                "status": result.status,
                "result": result.model_dump() if hasattr(result, "model_dump") else result.__dict__,
                "elapsed_time": result.elapsed_time,
                "event_logs": exec_log.get_events(),
            }

            if callback:
                callback(result_dict)

            return result_dict

        except CancellationError as e:
            logger.info("Node execution %s stopped cooperatively: %s", execution_id, e)
            result_dict = {
                "success": False,
                "cancelled": True,
                "error": None,
                "execution_id": execution_id,
                "node_id": node_id,
                "status": "cancelled",
                "result": {
                    "status": "cancelled",
                    "node_id": node_id,
                    "execution_id": execution_id,
                    "response": {
                        "output": {
                            "output_format": "json",
                            "data": {"cancelled": True, "reason": "Execution stopped by user"},
                        },
                        "metadata": {},
                    },
                },
                "elapsed_time": None,
                "event_logs": exec_log.get_events() if exec_log else [],
            }
            if callback:
                callback(result_dict)
            return result_dict

        except Exception as e:
            error_msg = str(e)
            logger.error("Node execution %s failed: %s", execution_id, error_msg, exc_info=True)

            error_dict = {
                "success": False,
                "execution_id": execution_id,
                "node_id": node_id,
                "status": "error",
                "error": error_msg,
                "event_logs": exec_log.get_events() if exec_log else [],
            }

            if callback:
                callback(error_dict)

            return error_dict

        finally:
            if execution_id in self._running_executions:
                del self._running_executions[execution_id]
            if execution_id in self._execution_contexts:
                del self._execution_contexts[execution_id]

    def run_node(
        self,
        node_id: str,
        state: Optional[Dict[str, Any]] = None,
        input_params: Optional[Dict[str, Any]] = None,
        mode: Literal["dev", "prod"] = "prod",
        module_path: Optional[str] = None,
        class_name: Optional[str] = None,
        room: Optional[str] = None,
        background: bool = True,
        persist_to_db: bool = True,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        debug_mode: str = "debug",
        command: Optional[str] = None,
        user_id: str = "anonymous",
        run_request_extras: Optional[Dict[str, Any]] = None,
        output_format: Optional[str] = None,
    ) -> str:
        """
        Execute a node through the engine with tracking and stop support.
        
        Args:
            node_id: Node identifier
            state: Initial state dict
            input_params: Input parameters dict
            mode: Execution mode:
                - "dev": Load class from module_path/class_name
                - "prod": Use in-memory workflow_registry
            module_path: Python module path (required for mode="dev")
            class_name: Python class name (required for mode="dev")
            room: Socket.IO room/client_id for real-time streaming
            background: If True, run in background thread (default)
            persist_to_db: If True, persist execution logs to DB for audit trail (default True)
            callback: Optional callback called with result when done
            debug_mode: Interaction mode when a ``room`` is set:
                - "trace": real-time logs; no per-node interactive forms
                - "debug": real-time logs + interactive forms (default)
                Non-interactive runs use ``background=True`` (no Socket.IO room), not a separate mode.
            run_request_extras: Optional dict merged into the ``request`` passed to ``node.run``;
                engine fields (``node_id``, ``state``, ``input_params``, ``mode``, ``execution_id``, ``command``) win on conflict.
            output_format: Optional rendering hint forwarded as ``node.run(..., output_format=...)`` (not merged into ``input_params``).
            
        Returns:
            execution_id for tracking and stop
        """
        import importlib
        from .registry import workflow_registry
        
        state = state or {}
        input_params = input_params or {}
        debug_mode = normalize_debug_mode(debug_mode, default="debug")

        if mode not in ("dev", "prod"):
            raise ValueError(f"Invalid mode: '{mode}'. Use 'dev' or 'prod'.")
        
        # Generate execution ID
        execution_id = f"node_{node_id}_{int(time.time())}"
        
        # Get or create node instance based on mode
        node = None
        actual_module_path = module_path
        actual_class_name = class_name
        
        if mode == "dev":
            if not module_path or not class_name:
                raise ValueError("mode='dev' requires module_path and class_name")
            import sys

            try:
                # After `pip install` in the same session, refresh meta-path finders so new dists resolve.
                importlib.invalidate_caches()
                module = importlib.import_module(module_path)
                node_class = getattr(module, class_name)
                node = node_class(node_id=node_id)
                actual_module_path = module_path
                actual_class_name = class_name
            except (ImportError, AttributeError) as e:
                raise ValueError(
                    f"Failed to load {module_path}.{class_name}: {e}\n"
                    f"Interpreter: {sys.executable}\n"
                    f"Hint: this process must be the same Python where `plugin install` ran (your "
                    f"`.venv`). Restart the server after installing a new package, stop duplicate "
                    f"`nos` instances, and ensure the Engine UI is not hitting an old process."
                ) from e
                
        elif mode == "prod":
            node = workflow_registry.create_node_instance(node_id)
            if not node:
                raise ValueError(f"Node '{node_id}' not found in registry")
            actual_module_path = node.__class__.__module__
            actual_class_name = node.__class__.__name__
            
        
        # Create exec_log based on room parameter and execution mode
        # For background execution without room: persist to DB, no real-time emit
        # For background execution with room: persist to DB AND emit real-time
        # For sync execution: emit real-time (if room), persist to DB for audit
        if room:
            exec_log = build_event_log(
                execution_id=execution_id,
                node_id=node_id,
                workflow_id=None,
                module_path=actual_module_path,
                class_name=actual_class_name,
                shared_state=state.copy(),
                room=room,
                persist_to_db=persist_to_db,
                emit_realtime=True,
                user_id=user_id,
            )
        else:
            # No room: use EventLogBuffer (no Socket.IO), optionally persist to DB
            if persist_to_db:
                exec_log = build_event_log(
                    execution_id=execution_id,
                    node_id=node_id,
                    workflow_id=None,
                    module_path=actual_module_path,
                    class_name=actual_class_name,
                    shared_state=state.copy(),
                    room=None,
                    persist_to_db=True,
                    emit_realtime=False,
                    user_id=user_id,
                )
            else:
                exec_log = EventLogBuffer(
                    execution_id=execution_id,
                    node_id=node_id,
                    workflow_id=None,
                    module_path=actual_module_path,
                    class_name=actual_class_name,
                    shared_state=state.copy(),
                )
        
        node.set_exec_log(exec_log)
        exec_log.set_execution_flags(background=background, debug_mode=debug_mode)

        if os.environ.get("NOS_EXECUTION_WORKER") != "1":
            from nos.platform.execution_process.runner import (
                run_node_in_process_background,
                run_node_in_process_sync,
            )

            if background:
                return run_node_in_process_background(
                    self,
                    node_id=node_id,
                    state=state,
                    input_params=input_params,
                    mode=mode,
                    module_path=actual_module_path,
                    class_name=actual_class_name,
                    parent_log=exec_log,
                    debug_mode=debug_mode,
                    command=command,
                    user_id=user_id,
                    run_request_extras=run_request_extras,
                    output_format=output_format,
                    callback=callback,
                )
            return run_node_in_process_sync(
                self,
                node_id=node_id,
                state=state,
                input_params=input_params,
                mode=mode,
                module_path=actual_module_path,
                class_name=actual_class_name,
                parent_log=exec_log,
                debug_mode=debug_mode,
                command=command,
                user_id=user_id,
                run_request_extras=run_request_extras,
                output_format=output_format,
            )

        context = ExecutionContext(
            execution_id=execution_id,
            execution_type="node",
            started_at=time.time(),
            node_id=node_id,
            node=node,
            exec_log=exec_log,
        )
        self._execution_contexts[execution_id] = context

        def run_node_execution():
            return self._run_node_sync_impl(
                execution_id=execution_id,
                node_id=node_id,
                node=node,
                exec_log=exec_log,
                state=state,
                input_params=input_params,
                mode=mode,
                room=room,
                debug_mode=debug_mode,
                command=command,
                run_request_extras=run_request_extras,
                output_format=output_format,
                context=context,
                callback=callback,
            )

        if background:
            future = self._executor.submit(run_node_execution)
            self._running_executions[execution_id] = future
            return execution_id
        result_dict = run_node_execution()
        return execution_id, result_dict
    
    def is_cancelled(self, execution_id: str) -> bool:
        """Check if an execution has been cancelled."""
        context = self._execution_contexts.get(execution_id)
        return context.cancelled if context else False
    
    def _execute_workflow(
        self, 
        workflow: Workflow, 
        exec_log: Union[EventLogBuffer, EventLog],
        output_format: str = "json",
        workflow_debug_mode: Literal["trace", "debug"] = "trace",
    ) -> WorkflowExecutionResult:
        """
        Internal method to execute workflow logic.

        Args:
            workflow: Workflow instance
            exec_log: EventLogBuffer or EventLog for event logging
            workflow_debug_mode: ``debug`` enables per-node interactive forms when using a realtime platform sink.

        Returns:
            WorkflowExecutionResult with full execution context.
        """
        workflow_debug_mode = normalize_debug_mode(workflow_debug_mode)
        workflow._workflow_error_already_handled = False
        if not workflow._entry_node_id:
            raise ValueError(f"Workflow {workflow.workflow_id} has no entry node")
        
        started_at = time.time()
        execution_id = exec_log.execution_id
        node_ids_executed: list = []
        
        initial_state_snapshot = dict(workflow.state)
        current_node_id = workflow._entry_node_id
        iteration_count = 0
        max_iterations = 1000  # Safety limit to prevent infinite loops
        workflow_cancelled = False
        cancel_at_node: Optional[str] = None
        cancel_detail: Optional[str] = None

        # Determine if we should use real-time (EventLog) for per-node runtime hook sinks
        use_realtime = _is_interactive_exec_log(exec_log)
        
        while current_node_id and workflow.status == WorkflowStatus.RUNNING:
            try:
                iteration_count += 1
                if iteration_count > max_iterations:
                    raise RuntimeError(f"Workflow {workflow.workflow_id} exceeded max iterations ({max_iterations})")

                node = workflow.get_node(current_node_id)
                if not node:
                    raise ValueError(f"Node {current_node_id} not found in workflow {workflow.workflow_id}")

                node_ids_executed.append(current_node_id)

                from .workflow.state_mapping import create_identity_mapping
                state_mapping = workflow.get_node_mapping(current_node_id)
                if state_mapping is None:
                    state_mapping = create_identity_mapping()
                
                # StateMapping maps workflow state ↔ node state only (not input_params)
                node_input_dict = state_mapping.map_to_node(workflow.state)
                defaults = workflow.get_node_default_input_params(current_node_id)
                input_params = {**defaults}

                # Create exec_log for this node (same type as workflow exec_log)
                node_module_path = node.__class__.__module__
                node_class_name = node.__class__.__name__
                root_stop = getattr(exec_log, "_stop_event", None)

                if use_realtime:
                    node_exec_log = build_event_log(
                        execution_id=exec_log.execution_id,
                        node_id=current_node_id,
                        workflow_id=workflow.workflow_id,
                        module_path=node_module_path,
                        class_name=node_class_name,
                        shared_state=dict(workflow.state),
                        room=getattr(exec_log, '_room', None),
                        append_to=exec_log._event_buffer,
                        stop_event=root_stop,
                    )
                else:
                    node_exec_log = EventLogBuffer(
                        execution_id=exec_log.execution_id,
                        node_id=current_node_id,
                        workflow_id=workflow.workflow_id,
                        module_path=node_module_path,
                        class_name=node_class_name,
                        shared_state=dict(workflow.state),
                        append_to=exec_log._event_buffer,
                        stop_event=root_stop,
                    )
                node.set_exec_log(node_exec_log)

                # Observable state for tracking state changes during execution (node._on_state_changed emits to exec_log)
                def on_state_set(key, old_val, new_val):
                    node._on_state_changed(key, old_val, new_val)

                observable_state = ObservableStateDict(node_input_dict.copy(), on_set=on_state_set)

                wf_req = getattr(workflow, "_run_context_request", None)
                run_request = {
                    "node_id": current_node_id,
                    "workflow_id": workflow.workflow_id,
                    "state": dict(node_input_dict),
                    "input_params": input_params,
                    "output_format": output_format,
                    "workflow_run_request": wf_req,
                    "workflow_engine_debug_mode": workflow_debug_mode,
                }
                prev_node_debug = node._debug_mode
                try:
                    node.set_debug_mode(workflow_debug_mode == "debug" and use_realtime)
                    try:
                        result = node.run(
                            observable_state,
                            input_params,
                            request=run_request,
                            output_format=output_format,
                        )
                    except TypeError as e:
                        if "not subscriptable" in str(e):
                            raise TypeError(
                                f"Node {current_node_id}: input_params is a Pydantic model instance, not a dict. "
                                "Use params_dict = input_params.model_dump() if hasattr(input_params, 'model_dump') else (input_params or {}), "
                                "then access keys via params_dict['key'] or params_dict.get('key', default). See docs/README.md."
                            ) from e
                        raise
                    except CancellationError:
                        raise
                    except Exception as run_exc:
                        result = _synthetic_node_execution_result_from_exception(
                            run_exc,
                            node=node,
                            current_node_id=current_node_id,
                            exec_log=exec_log,
                        )
                finally:
                    node.set_debug_mode(prev_node_debug)

                # node_start and node_end are emitted inside Node.execute(); result has complete events

                state_updates = state_mapping.map_to_shared(observable_state)
                old_values = {k: workflow._state.get(k) for k in state_updates}
                workflow._on_state_changed(current_node_id, state_updates, old_values)
                workflow.apply_state_updates(state_updates)
                workflow.validate_state_or_raise(node_id=current_node_id)

                # Cooperative cancel: Node.execute returns status="cancelled" (no exception).
                if getattr(result, "status", None) == "cancelled":
                    workflow_cancelled = True
                    cancel_at_node = current_node_id
                    try:
                        out = getattr(getattr(result, "response", None), "output", None) or {}
                        data = out.get("data") if isinstance(out, dict) else {}
                        if isinstance(data, dict):
                            cancel_detail = data.get("reason") or data.get("detail")
                    except Exception:
                        cancel_detail = None
                    exec_log.log(
                        "info",
                        f"Workflow cancelled at node {current_node_id} (cooperative stop)",
                        node_id=current_node_id,
                    )
                    break

            except CancellationError as e:
                logger.info(
                    "Workflow node %s stopped cooperatively: %s",
                    current_node_id,
                    e,
                )
                workflow_cancelled = True
                cancel_at_node = current_node_id
                cancel_detail = str(e)
                exec_log.log(
                    "info",
                    f"Workflow cancelled at node {current_node_id} (cooperative stop)",
                    node_id=current_node_id,
                )
                break

            except Exception as e:
                err_result = _make_workflow_error_result(
                    workflow,
                    exec_log,
                    started_at=started_at,
                    initial_state_snapshot=initial_state_snapshot,
                    node_ids_executed=node_ids_executed,
                    exc=e,
                    current_node_id=current_node_id,
                )
                workflow._on_error(err_result)
                raise
            
            # Find links from this node
            links = workflow.get_links_from_node(current_node_id)
            
            if not links:
                exec_log.log(
                    "info",
                    f"Workflow ended at node {current_node_id} (no links)",
                    node_id=current_node_id,
                )
                break
            
            # Evaluate links (take first matching link)
            next_node_id = None
            for link in links:
                try:
                    link_result = link.route(
                        workflow._state,
                        result,
                        current_node_id=current_node_id,
                    )
                    
                    if link_result.should_continue and link_result.next_node_id:
                        next_node_id = link_result.next_node_id
                        workflow._on_link_decision(
                            link.link_id,
                            f"routing to {next_node_id}",
                            next_node_id,
                        )
                        break
                    elif not link_result.should_continue:
                        workflow._on_link_decision(link.link_id, "stopping workflow", None)
                        next_node_id = None
                        break
                except Exception as e:
                    logger.error(f"Link {link.link_id} routing error: {e}", exc_info=True)
                    workflow._on_link_error(link.link_id, e)
                    # Continue to next link
            
            if next_node_id is None:
                exec_log.log(
                    "info",
                    f"Workflow ended at node {current_node_id} (no valid route)",
                    node_id=current_node_id,
                )
                break
            
            current_node_id = next_node_id
        
        # Workflow result: build WorkflowExecutionResult
        ended_at_time = time.time()
        duration = ended_at_time - started_at
        started_at_iso = datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
        ended_at_iso = datetime.fromtimestamp(ended_at_time, tz=timezone.utc).isoformat()
        
        final_state = dict(workflow.state)
        all_keys = set(initial_state_snapshot.keys()) | set(final_state.keys())
        state_changed = {}
        for k in all_keys:
            old_v = initial_state_snapshot.get(k)
            new_v = final_state.get(k)
            if old_v != new_v:
                state_changed[k] = {"old": old_v, "new": new_v}
        wf_status = "cancelled" if workflow_cancelled else "success"
        wf_message = (
            (cancel_detail or f"Cancelled at node {cancel_at_node}")
            if workflow_cancelled
            else None
        )

        # Mandatory output validation (internal to workflow)
        try:
            data = workflow.validate_output(final_state)
        except Exception as val_err:
            if workflow_cancelled:
                logger.warning("Workflow validate_output skipped after cancel: %s", val_err)
                data = dict(final_state)
            else:
                raise
        event_logs = exec_log.get_events()

        # Metadata: workflow provides it, engine validates against metadata_schema if defined
        metadata = workflow.get_metadata(
            final_state=final_state,
            state_changed=state_changed,
            node_ids_executed=node_ids_executed,
            status=wf_status,
        )
        if workflow_cancelled:
            metadata = {**(metadata or {}), "cancelled": True, "cancelled_at_node": cancel_at_node}
        try:
            metadata = workflow.validate_metadata(metadata)
        except Exception as val_err:
            logger.warning(f"Workflow metadata validation failed: {val_err}")
            if workflow_cancelled:
                metadata = {"cancelled": True, "cancelled_at_node": cancel_at_node}
            else:
                metadata = {}

        # Format-specific validation: if output doesn't match format schema, fallback to json
        effective_format = output_format
        valid, _ = validate_output_for_format(data, output_format)
        if not valid:
            logger.warning(
                f"Workflow output does not match format '{output_format}' schema; falling back to json"
            )
            effective_format = "json"

        wf_render = WorkflowOutput(
            output={"output_format": effective_format, "data": data},
            metadata=metadata,
        )
        wf_cmd = _command_from_run_request(getattr(workflow, "_run_context_request", None))
        wf_result = WorkflowExecutionResult(
            execution_id=execution_id,
            workflow_id=workflow.workflow_id,
            module_path=workflow.__class__.__module__,
            class_name=workflow.__class__.__name__,
            command=wf_cmd,
            status=wf_status,
            response=WorkflowResponseData(
                output=dict(wf_render.output),
                metadata=dict(wf_render.metadata),
            ),
            state=final_state,
            state_changed=state_changed,
            initial_state=initial_state_snapshot,
            started_at=started_at_iso,
            ended_at=ended_at_iso,
            message=wf_message,
            duration=duration,
            node_ids_executed=node_ids_executed,
            event_logs=event_logs,
        )
        end_msg = (
            wf_message
            or ("Workflow cancelled" if workflow_cancelled else "Workflow execution completed")
        )
        workflow._on_end(
            wf_result,
            level="warning" if workflow_cancelled else "info",
            message=end_msg,
        )
        return wf_result
    
    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a background execution (node or workflow)."""
        if execution_id not in self._execution_contexts:
            return None
        
        context = self._execution_contexts[execution_id]
        future = self._running_executions.get(execution_id)
        
        status = {
            "execution_id": execution_id,
            "execution_type": context.execution_type,
            "started_at": context.started_at,
            "cancelled": context.cancelled,
        }
        
        if context.execution_type == "workflow" and context.workflow:
            status["workflow_id"] = context.workflow_id
            status["status"] = context.workflow.status.value
        elif context.execution_type == "node":
            status["node_id"] = context.node_id
            status["status"] = "cancelled" if context.cancelled else "running"
        
        if future:
            status["running"] = not future.done()
            if future.done():
                try:
                    result = future.result()
                    if isinstance(result, dict):
                        status["result"] = result
                    elif hasattr(result, "__dataclass_fields__"):
                        status["result"] = dataclasses.asdict(result)
                    else:
                        status["result"] = result
                except Exception as e:
                    status["error"] = str(e)
        elif getattr(context, "child_process", None) is not None:
            cp = context.child_process
            try:
                status["running"] = bool(cp.is_alive())
            except Exception:
                status["running"] = False

        return status
    
    def stop_execution(self, execution_id: str) -> Dict[str, Any]:
        """
        Stop a running background execution (node or workflow).
        
        Args:
            execution_id: Execution ID to stop
            
        Returns:
            Dict with stop result: {"stopped": bool, "execution_id": str, ...}
        """
        result = {
            "execution_id": execution_id,
            "stopped": False,
        }
        
        if execution_id not in self._execution_contexts:
            result["error"] = f"Execution '{execution_id}' not found"
            return result
        
        context = self._execution_contexts[execution_id]
        result["execution_type"] = context.execution_type
        
        # Mark as cancelled
        context.cancelled = True

        # Do not log here: cooperative cancel surfaces as a single Node end / Workflow end
        # via Node.execute's CancellationError handler (execution_log + NodeExecutionResult).
        # A proactive log would duplicate "Execution cancelled by user" and break the
        # standard node_end pattern.

        # Signal cooperative cancellation: the exec log's stop_event lets _do_execute
        # loops exit cleanly at the next check point (e.g. BFS URL iteration).
        if context.exec_log is not None:
            try:
                context.exec_log.request_stop()
            except Exception as exc:
                logger.warning("stop_execution: request_stop failed: %s", exc)

        if context.mp_stop_event is not None:
            try:
                context.mp_stop_event.set()
            except Exception as exc:
                logger.warning("stop_execution: mp_stop_event.set failed: %s", exc)
        proc = context.child_process
        if proc is not None:
            try:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5.0)
                result["process_terminated"] = True
            except Exception as exc:
                logger.warning("stop_execution: process terminate failed: %s", exc)

        # Cancel future if running (only effective before the thread actually starts;
        # for already-running threads the cooperative stop_event above is the mechanism).
        future = self._running_executions.get(execution_id)
        if future and not future.done():
            future.cancel()
            result["future_cancelled"] = True

        # Type-specific stop logic
        if context.execution_type == "workflow" and context.workflow:
            context.workflow._on_stop()
            result["workflow_id"] = context.workflow_id
            result["stopped"] = True
            logger.info(f"Stopped workflow execution: {execution_id}")
            
        elif context.execution_type == "node":
            result["node_id"] = context.node_id
            result["stopped"] = True
            logger.info(f"Stopped node execution: {execution_id}")
        
        return result
    
    def list_executions(self) -> list[Dict[str, Any]]:
        """List all active executions."""
        executions = []
        for execution_id, context in self._execution_contexts.items():
            future = self._running_executions.get(execution_id)
            cp = getattr(context, "child_process", None)
            if future:
                running = not future.done()
            elif cp is not None:
                try:
                    running = bool(cp.is_alive())
                except Exception:
                    running = False
            else:
                running = False
            executions.append({
                "execution_id": execution_id,
                "execution_type": context.execution_type,
                "node_id": context.node_id,
                "workflow_id": context.workflow_id,
                "started_at": context.started_at,
                "cancelled": context.cancelled,
                "running": running,
            })
        return executions
    
    def shutdown(self):
        """Shutdown the engine and cleanup resources."""
        # Include sync runs (execute_sync / blocking console workflow) — they are not in
        # _running_executions but must still receive request_stop (e.g. server Ctrl+C).
        for execution_id in list(self._execution_contexts.keys()):
            self.stop_execution(execution_id)
        self._executor.shutdown(wait=True)


# ── Shared singleton ────────────────────────────────────────────────────────
_shared_engine: "WorkflowEngine | None" = None
_shared_engine_lock = threading.Lock()


def get_shared_engine() -> "WorkflowEngine":
    """Return the process-wide shared WorkflowEngine instance (thread-safe).

    All entry points (REST API, Socket.IO, Webhook, MCP, Console) should use
    this singleton so that:
    - The background thread pool is shared and capped consistently.
    - Execution tracking (_running_executions) is unified — stop/status
      queries work regardless of which entry point started the execution.
    """
    global _shared_engine
    if _shared_engine is None:
        with _shared_engine_lock:
            if _shared_engine is None:
                _shared_engine = WorkflowEngine()
                logger.info(
                    "Shared WorkflowEngine created (max_workers=%d)",
                    _shared_engine._DEFAULT_MAX_WORKERS,
                )
    return _shared_engine
