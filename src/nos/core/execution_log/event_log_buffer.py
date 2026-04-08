"""
Structured execution log for nodes and workflows (offline / request-response path).

**Role.** Collects every emitted event as a typed :class:`~nos.core.execution_log.events.BaseEvent`
subclass, appends to an in-memory buffer (and optionally to a parent list), and mirrors a
human-readable line to Python :mod:`logging`. Callers read :meth:`EventLogBuffer.get_events`
to attach ``event_logs`` to API results.

**Extension point.** All concrete ``log_*`` helpers build an event and pass it through
:meth:`EventLogBuffer._emit`. Subclasses (notably :class:`~nos.platform.execution_log.event_log.EventLog`)
override :meth:`_emit` to add side effects **without** duplicating event construction — e.g. push
the same payload to Socket.IO after ``super()._emit``.

**When to use.** REST runs, tests, or any context where you do not need live WebSocket delivery
or :meth:`~nos.platform.execution_log.event_log.EventLog.request_and_wait`.
For interactive console / engine runs with realtime log streaming, use :class:`~nos.platform.execution_log.EventLog`.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any, Callable


class CancellationError(Exception):
    """Raised by :meth:`EventLogBuffer.log` / :meth:`EventLogBuffer.log_custom` when a stop has been requested.

    This is the infrastructure mechanism for cooperative cancellation: node
    developers never need to check ``channel.is_stop_requested()`` themselves —
    the next :meth:`~EventLogBuffer.log` call (alias of :meth:`~EventLogBuffer.log_custom`)
    will automatically raise this exception, which :meth:`Node.execute` catches and
    converts into a clean ``NodeExecutionResult(status="cancelled")``.

    Example flow::

        # User presses CTRL+C
        engine.stop_execution(execution_id)   # sets channel._stop_event
            ↓
        # In _do_execute loop, node logs progress:
        self.exec_log.log("info", f"Fetched {url}")  # raises CancellationError
            ↓
        # Propagates to Node.execute() outer handler:
        except CancellationError:
            return NodeExecutionResult(status="cancelled", ...)
    """
from datetime import datetime, timezone

from .events import (
    BaseEvent,
    NodeExecuteEvent,
    NodeRequestEvent,
    NodeExecutionRequestEvent,
    NodeInitEvent,
    NodeInitCompletedEvent,
    NodeFormResponseReceivedEvent,
    NodeStateChangedEvent,
    NodeOutputEvent,
    NodeEndEvent,
    NodeStopEvent,
    NodeErrorEvent,
    WorkflowStartEvent,
    WorkflowInitEvent,
    WorkflowInitCompletedEvent,
    WorkflowFormResponseReceivedEvent,
    FormSchemaSentEvent,
    FormDataReceivedEvent,
    CustomEvent,
)

logger = logging.getLogger(__name__)


class EventLogBuffer:
    """
    Default runtime sink: in-process event list + console logging.

    Public ``log_*`` methods encode domain milestones (node start, init, end, …) as Pydantic
    events. Subclasses hook :meth:`_emit` to layer transport (Socket.IO) or persistence (DB)
    on top of the same single implementation.
    """

    def __init__(
        self,
        execution_id: str,
        node_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        module_path: str = "",
        class_name: str = "",
        shared_state: Optional[Dict[str, Any]] = None,
        append_to: Optional[list] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.execution_id = execution_id
        self.node_id = node_id
        self.workflow_id = workflow_id
        self.module_path = module_path
        self.class_name = class_name
        self.shared_state = shared_state or {}
        self._append_to = append_to
        self._started_at: str = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()
        self._command: str = ""
        self._exec_flag: str = ""    # "--sync" or "--bk"
        self._output_flag: str = ""  # "--debug" or "--trace" (background runs omit realtime room)

        # Event buffer
        self._event_buffer: list[BaseEvent] = []

        # Cooperative cancellation — set by engine.stop_execution() via request_stop();
        # node _do_execute() loops should call self.exec_log.is_stop_requested() and exit early.
        # When ``stop_event`` is shared (e.g. workflow root buffer), all nested node / parallel
        # child buffers react to the same signal.
        self._stop_event: threading.Event = stop_event if stop_event is not None else threading.Event()

    def set_execution_flags(self, background: bool, debug_mode: str) -> None:
        """Store execution/output mode flags for effective_command reconstruction."""
        self._exec_flag = "--bk" if background else "--sync"
        self._output_flag = f"--{debug_mode}"

    # ── Cooperative cancellation ──────────────────────────────────────────────

    def request_stop(self) -> None:
        """Signal the running node/_do_execute loop to stop at the next check point.

        Called by :meth:`engine.WorkflowEngine.stop_execution` after setting
        ``ExecutionContext.cancelled = True``.  Node implementations should
        poll :meth:`is_stop_requested` at logical boundaries (e.g. BFS iteration,
        page loop) and return early when it returns ``True``.
        """
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        """Return ``True`` if a stop has been requested via :meth:`request_stop`.

        .. note::
            Node developers normally do **not** need to call this method.
            :meth:`log` / :meth:`log_custom` automatically raises :exc:`CancellationError` when
            a stop is pending, so any node that logs progress via :meth:`log` will be
            interrupted transparently by the infrastructure.

            This method is exposed for advanced use cases where a node performs
            expensive I/O *without* calling :meth:`log` between iterations
            (e.g. a tight loop that only logs at the end).  In that scenario,
            adding ``if self.exec_log.is_stop_requested(): break`` inside the loop
            provides faster response to the stop signal.
        """
        return self._stop_event.is_set()

    def _base_fields(self) -> dict:
        """Common fields for all events."""
        return {
            "started_at": self._started_at,
            "datetime": datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat(),
            "execution_id": self.execution_id,
            "node_id": self.node_id,
            "workflow_id": self.workflow_id,
        }

    def _emit(self, event: BaseEvent):
        """Append ``event`` to the buffer (and ``append_to``) and log to the console.

        Override in a subclass to forward the same ``event`` to other sinks after
        ``super()._emit(event)``.
        """
        # Buffer
        self._event_buffer.append(event)
        if self._append_to is not None:
            self._append_to.append(event)

        # Console logging
        self._log_to_console(event)

    def _log_to_console(self, event: BaseEvent):
        """Log event to console via Python logging."""
        log_method = getattr(logger, event.level.lower(), logger.info)
        
        # Build log message
        prefix_parts = [f"[{self.execution_id}]"]
        if event.node_id:
            prefix_parts.append(f"[node:{event.node_id}]")
        if event.workflow_id:
            prefix_parts.append(f"[workflow:{event.workflow_id}]")
        if event.link_id:
            prefix_parts.append(f"[link:{event.link_id}]")
        
        prefix = " ".join(prefix_parts)
        log_msg = f"{prefix} {event.message}"
        
        # Extra fields for structured logging
        extra = {k: v for k, v in event.model_dump().items() 
                 if k not in ("datetime", "level", "message")}
        
        try:
            log_method(log_msg, extra=extra)
        except KeyError as e:
            if "overwrite" in str(e) and "LogRecord" in str(e):
                raise KeyError(
                    f"Execution log used a reserved LogRecord key. "
                    "Avoid: name, msg, levelname, levelno, filename, lineno, module, pathname, process, thread, etc."
                ) from e
            raise

    # --- Structured log methods (typed events) ---

    def log_event(self, event: BaseEvent):
        """Append any :class:`~nos.core.execution_log.events.BaseEvent` to the buffer."""
        self._emit(event)

    def log_custom(
        self,
        level: str,
        message: str,
        *,
        event: str = "Logging event",
        include_base_fields: bool = True,
        **kwargs,
    ):
        """Record a custom execution-log event (:class:`CustomEvent`).

        **Cooperative cancellation**: if :meth:`request_stop` has been called
        (e.g. the user pressed CTRL+C), this method raises :exc:`CancellationError`
        *before* recording anything.  The exception propagates up through the node's
        ``_do_execute`` into :meth:`Node.execute`, which catches it and returns a
        clean ``NodeExecutionResult(status="cancelled")``.  Call sites often use
        :meth:`log` (thin wrapper around this method).

        Args:
            level: Log level ('debug', 'info', 'warning', 'error').
            message: Log message.
            event: Logical event type string stored on :class:`CustomEvent` (default
                ``Logging event``, same as the model field default). Use stable identifiers (e.g. ``fetch success``)
                for filtering and UI routing.
            include_base_fields: If True (default), merges execution context
                (_base_fields) into the payload.  If False, only level/message/kwargs
                are included.
            **kwargs: Additional fields to include in the event payload.

        Raises:
            CancellationError: if a stop has been requested via :meth:`request_stop`.
        """
        # Infrastructure-level cooperative cancellation check.
        # This is the ONLY place in the node execution path that needs to check the
        # stop flag — all _do_execute implementations naturally call log() for
        # progress logging, so cancellation is transparent to node developers.
        if self._stop_event.is_set():
            raise CancellationError(
                f"Execution cancelled (stop requested before log: {message!r})"
            )

        base = self._base_fields() if include_base_fields else {}
        merged = {
            **base,
            "level": level,
            "message": message,
            **kwargs,
            "event": event,
        }
        custom = CustomEvent(**merged)
        self._emit(custom)

    def log_error(self, message: str, error_type: str = "", detail: str = "", **kwargs):
        """
        Record a structured system error (:class:`NodeErrorEvent`).
        - Logs via logger.error() for Python logging
        - Appends NodeErrorEvent to the buffer (and realtime transport when using platform EventLog)
        Use for framework-level errors (validation, bad_request, etc.).
        For business-logic errors in plugins use :meth:`log` with level ``"error"`` or :meth:`log_error` as appropriate.
        """
        logger.error("%s — %s: %s", message, error_type or "error", detail or message)
        merged = {
            **self._base_fields(),
            "message": message,
            "error_type": error_type,
            "detail": detail or message,
            **kwargs,
        }
        event = NodeErrorEvent(**merged)
        self._emit(event)

    def log(self, level: str, message: str, **kwargs):
        """Preferred entry point for custom execution-log lines (delegates to :meth:`log_custom`)."""
        self.log_custom(level, message, **kwargs)

    def log_node_run(self, request: dict):
        """Log node_request event (from Node._on_request). request may contain 'command' (full command string)."""
        command = (request or {}).get("command", "")
        message = f"Client connected @{self.execution_id}. Serving {self.module_path}.{self.class_name}."
        event = NodeRequestEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            command=command,
            message=message,
        )
        self._emit(event)

    def log_node_start(self, request: dict):
        """Log node_start event (from Node._on_start). request may contain 'command' (full command string)."""
        command = (request or {}).get("command", "")
        self._command = command  # store for effective_command reconstruction after _on_init
        message = f"Preparing node for execution. Execution ID: {self.execution_id}."
        event = NodeExecutionRequestEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            command=command,
            message=message,
        )
        self._emit(event)

    def log_node_execute(self, state: dict, input_params: dict):
        """Log node_execute event (after init, before _do_execute)."""
        event = NodeExecuteEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            state=dict(state) if state else {},
            shared_state=dict(self.shared_state) if self.shared_state else {},
            input_params=dict(input_params) if input_params else {},
        )
        self._emit(event)

    def log_node_init(self, initial_state: dict, initial_params: dict = None):
        """Log node_init event."""
        event = NodeInitEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            shared_state=dict(self.shared_state) if self.shared_state else {},
            state=dict(initial_state) if initial_state else {},
            input_params=dict(initial_params) if initial_params else {},
        )
        self._emit(event)

    def _build_effective_command(self, params_dict: dict, state_dict: dict, output_format: Optional[str] = None) -> str:
        """Reconstruct the command string with all defaults applied after _on_init."""
        if not self._command:
            return ""
        # Strip --param, --state, --output_format, --sync/--bk, --debug/--trace
        # so they can be re-appended with effective values
        tokens = self._command.split()
        base_tokens = []
        skip = False
        strip_keys = {"param", "state", "output_format", "sync", "bk", "debug", "trace"}
        for tok in tokens:
            if tok.startswith("--") and tok[2:] in strip_keys:
                skip = True
                continue
            if skip and not tok.startswith("--"):
                continue
            skip = False
            base_tokens.append(tok)
        parts = [" ".join(base_tokens)]
        # Add execution/output mode flags (from set_execution_flags, with fallback to defaults)
        parts.append(self._exec_flag or "--sync")
        parts.append(self._output_flag or "--debug")
        # Add effective state, params, output_format from _on_init result
        if state_dict:
            parts.append("--state " + " ".join(f"{k}={v}" for k, v in state_dict.items()))
        if params_dict:
            parts.append("--param " + " ".join(f"{k}={v}" for k, v in params_dict.items()))
        if output_format:
            parts.append(f"--output_format {output_format}")
        return " ".join(filter(None, parts))

    def log_node_init_completed(self, state: dict, input_params: dict, output_format: Optional[str] = None):
        """Log node_init_completed event with flat fields (no nested dict)."""
        effective_command = self._build_effective_command(input_params, state, output_format)
        self._command = effective_command  # persist so subsequent events/result carry the full command
        event = NodeInitCompletedEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            shared_state=dict(self.shared_state) if self.shared_state else {},
            state=dict(state) if state else {},
            input_params=dict(input_params) if input_params else {},
            command=effective_command,
        )
        self._emit(event)

    def log_node_form_response_received(self, form_response: dict):
        """Log node_form_response_received event (form response from client)."""
        event = NodeFormResponseReceivedEvent(
            **self._base_fields(),
            module_path=self.module_path,
            class_name=self.class_name,
            form_response=dict(form_response) if form_response else {},
        )
        self._emit(event)

    def log_node_state_changed(self, key: str, old_value: Any, new_value: Any):
        """Log node_state_changed event."""
        event = NodeStateChangedEvent(
            **self._base_fields(),
            state_key=key,
            old_value=old_value,
            new_value=new_value,
        )
        self._emit(event)

    def log_node_output(self, output: dict, metadata: dict):
        """Log node_output event with NodeOutput payload (output + metadata)."""
        event = NodeOutputEvent(
            **self._base_fields(),
            output=dict(output) if output else {},
            metadata=dict(metadata) if metadata else {},
        )
        self._emit(event)

    def log_node_end(self, result, level: str = "info", message: str = "Node execution completed"):
        """Log node_end event with full NodeExecutionResult payload."""
        result_data = result.model_dump() if hasattr(result, "model_dump") else {}
        # Fields already in _base_fields (execution_id, node_id, started_at, datetime) are excluded
        # to avoid Pydantic conflicts; only NodeExecutionResult-specific fields are merged.
        base = self._base_fields()
        result_fields = {
            k: v for k, v in result_data.items()
            if k not in base and k not in ("execution_id", "node_id")
        }
        event = NodeEndEvent(
            **base,
            level=level,
            message=message,
            **result_fields,
        )
        self._emit(event)

    def log_node_error(self, result, message: str = ""):
        """
        Log node_error at node termination (distinct from :meth:`log_error` used for mid-execution errors).
        Does NOT re-call :meth:`log_error` (which was already called in the except handler): records NodeErrorEvent
        directly so no duplicate error events appear in the log.
        Called by Node._on_error() just before _on_end(level='error').
        """
        status = getattr(result, "status", "error")
        detail = ""
        response = getattr(result, "response", None)
        if response:
            out = getattr(response, "output", {}) or {}
            detail = (
                out.get("detail")
                or out.get("reason")
                or ""
            )
            if isinstance(detail, bool):
                detail = ""
        final_message = message or f"Node execution terminated with status: {status}"
        merged = {
            **self._base_fields(),
            "message": final_message,
            "error_type": status,
            "detail": str(detail) if detail else final_message,
        }
        event = NodeErrorEvent(**merged)
        self._emit(event)

    def log_node_stop(self, result, message: str = "Execution cancelled by user"):
        """Log cooperative cancellation (distinct from :meth:`log_node_end`, which follows with the full result)."""
        reason = ""
        response = getattr(result, "response", None)
        if response:
            out = getattr(response, "output", {}) or {}
            data = out.get("data")
            if isinstance(data, dict):
                reason = str(data.get("reason") or "")
        merged = {
            **self._base_fields(),
            "level": "warning",
            "message": message,
            "reason": reason,
        }
        self._emit(NodeStopEvent(**merged))

    def log_workflow_start(self, initial_state: dict, state_mapping_desc: Optional[str] = None):
        """Log workflow_start event."""
        event = WorkflowStartEvent(
            **self._base_fields(),
            initial_state=dict(initial_state) if initial_state else {},
            state_mapping=state_mapping_desc,
        )
        self._emit(event)

    def log_workflow_init(self, initial_state: dict):
        """Log workflow_init event (before schema validation; mirrors :meth:`log_node_init`)."""
        event = WorkflowInitEvent(
            **self._base_fields(),
            initial_state=dict(initial_state) if initial_state else {},
        )
        self._emit(event)

    def log_workflow_init_completed(self, state: dict):
        """Log workflow_init_completed event (after shared state validated; mirrors :meth:`log_node_init_completed`)."""
        event = WorkflowInitCompletedEvent(
            **self._base_fields(),
            state=dict(state) if state else {},
        )
        self._emit(event)

    def log_workflow_form_response_received(self, form_response: dict):
        """Log workflow_form_response_received (initial shared-state form; mirrors :meth:`log_node_form_response_received`)."""
        event = WorkflowFormResponseReceivedEvent(
            **self._base_fields(),
            form_response=dict(form_response) if form_response else {},
        )
        self._emit(event)

    def log_form_schema_sent(self, form_schema: dict):
        """Log form_schema_sent event."""
        event = FormSchemaSentEvent(
            **self._base_fields(),
            form_schema=form_schema,
        )
        self._emit(event)

    def log_form_data_received(self, form_data: dict):
        """Log form_data_received event."""
        event = FormDataReceivedEvent(
            **self._base_fields(),
            form_data=dict(form_data) if form_data else {},
        )
        self._emit(event)

    # --- Buffer access ---

    def get_events(self) -> list[dict]:
        """Return all buffered events as dicts."""
        return [e.to_dict() for e in self._event_buffer]

    def clear_events(self):
        """Clear event buffer."""
        self._event_buffer.clear()


# --- Observable state dict ---


class ObservableStateDict(dict):
    """
    Dict that invokes a callback on each __setitem__.
    Used to track node state changes during execution.
    """

    def __init__(self, *args, on_set: Optional[Callable[[str, Any, Any], None]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_set = on_set

    def __setitem__(self, key: str, value: Any):
        old = self.get(key)
        super().__setitem__(key, value)
        if self._on_set:
            self._on_set(key, old, value)
