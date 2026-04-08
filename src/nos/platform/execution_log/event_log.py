"""
Platform **event log**: same structured event model as
:class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer`, plus web transport and persistence hooks.

**Inheritance.** Extends :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` from :mod:`nos.core.execution_log`.
Event construction stays in the base class; this module adds:

- **Realtime:** :meth:`EventLog._emit` calls ``super()._emit`` then, when ``emit_realtime`` is true,
  schedules :meth:`_emit_to_socket` so every buffered event is also pushed as the Socket.IO
  payload ``execution_log`` (room or broadcast).
- **Persistence:** With ``persist_to_db=True``, each emitted event is stored in the ``execution_log``
  detail table (via :meth:`_persist_emit_event`). Lifecycle hooks still update ``execution_run``
  (start/end): node/workflow start use ``log_*`` overrides; workflow completion is detected when
  :meth:`~nos.core.execution_log.event_log_buffer.EventLogBuffer.log_custom` records
  ``event="workflow_execution_result"``, then :meth:`_persist_run_end_workflow` runs.
- **Bidirectional:** :meth:`request_and_wait` / :meth:`handle_response` for client prompts.

**When to use.** Engine / web runs where the UI subscribes to live logs or interactive
requests. For stateless REST responses that only need ``event_logs`` in JSON, prefer
:class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` alone.
"""

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from nos.core.execution_log.event_log_buffer import EventLogBuffer
from nos.core.execution_log.events import BaseEvent, CustomEvent

logger = logging.getLogger(__name__)


def _try_socketio():
    """
    Return Flask-SocketIO instance if the web platform stack is installed and importable.

    Library-only installs (no ``nos[web]``) get ``None`` — realtime emit and
    ``request_and_wait`` are degraded gracefully.
    """
    try:
        from nos.platform.extensions import socketio

        return socketio
    except ImportError:
        return None


def _schedule_background(fn: Callable[[], None]) -> None:
    """
    Run ``fn`` on a Socket.IO background task when available, else a daemon thread.
    """
    sock = _try_socketio()
    if sock is not None:
        try:
            sock.start_background_task(fn)
            return
        except Exception as exc:
            logger.warning(
                "Socket.IO background task unavailable (%s); falling back to thread",
                exc,
                exc_info=True,
            )
    threading.Thread(target=fn, daemon=True).start()


def _make_json_serializable(obj: Any) -> Any:
    """Recursively replace non-JSON-serializable values (e.g. PydanticUndefined) with None."""
    if obj is None:
        return None
    try:
        type_name = type(obj).__name__
        if type_name in ("PydanticUndefinedType", "UndefinedType"):
            return None
    except Exception:
        pass
    try:
        from pydantic_core import PydanticUndefined
        if obj is PydanticUndefined:
            return None
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return None


class EventLog(EventLogBuffer):
    """
    :class:`EventLogBuffer` with Socket.IO fan-out, optional ``execution_run`` persistence, and
    request/response routing for interactive runs.

    **Override layout:** :meth:`_emit` extends every event path at once. ``log_*`` overrides exist
    where DB start/end must run at specific lifecycle moments; workflow completion is tied to
    :meth:`log_custom` when ``event == "workflow_execution_result"``.
    """

    def __init__(
        self,
        execution_id: str,
        node_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        module_path: str = "",
        class_name: str = "",
        shared_state: Optional[Dict[str, Any]] = None,
        room: Optional[str] = None,
        append_to: Optional[list] = None,
        persist_to_db: bool = False,
        emit_realtime: bool = True,
        user_id: str = "anonymous",
        stop_event: Optional[threading.Event] = None,
    ):
        """
        Initialize platform event log (buffer + optional Socket.IO + DB hooks).

        Args:
            execution_id: Unique execution identifier
            node_id: Node identifier (for node executions)
            workflow_id: Workflow identifier (for workflow executions)
            module_path: Python module path of the plugin
            class_name: Class name of the plugin
            shared_state: Shared state dictionary
            room: Socket.IO room for targeted emission
            append_to: Optional list to append events to
            persist_to_db: If True, persist events to execution_log DB table
            emit_realtime: If True, emit events via Socket.IO (default True)
            user_id: Session username for audit trail (default "anonymous")
            stop_event: Optional shared :class:`threading.Event`; when set (e.g. workflow
                stop), cooperative cancellation applies to this buffer and any nested logs
                that reuse the same event.
        """
        super().__init__(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=workflow_id,
            module_path=module_path,
            class_name=class_name,
            shared_state=shared_state,
            append_to=append_to,
            stop_event=stop_event,
        )
        self._room = room
        self._persist_to_db = persist_to_db
        self._emit_realtime = emit_realtime
        self._user_id = user_id

        # Capture Flask app reference here (in request context) so it is available
        # later inside ThreadPoolExecutor threads that have no app context.
        self._flask_app = None
        try:
            from flask import current_app
            self._flask_app = current_app._get_current_object()
        except Exception:
            pass  # no Flask context at init time (e.g. CLI / tests)

        # Request-response tracking (interactive request_and_wait)
        self._pending_requests: Dict[str, threading.Event] = {}
        self._responses: Dict[str, Any] = {}
        self._response_lock = threading.Lock()

    def _emit(self, event: BaseEvent):
        """**Why override:** every ``log_*`` path funnels here after building the event.

        Base class buffers and logs to Python logging; we add a second sink (Socket.IO) so the
        web console sees the same structured payload without re-implementing each public helper.
        """
        super()._emit(event)

        if self._persist_to_db:
            self._persist_emit_event(event)

        if self._emit_realtime:
            self._emit_to_socket(event)

    def log_custom(
        self,
        level: str,
        message: str,
        *,
        event: str = "Logging event",
        include_base_fields: bool = True,
        **kwargs,
    ):
        super().log_custom(
            level, message, event=event, include_base_fields=include_base_fields, **kwargs
        )
        if self._persist_to_db and event == "workflow_execution_result":
            self._persist_run_end_workflow()

    # ── execution_run hooks (see class docstring: lifecycle-only overrides) ──

    def log_node_start(self, request: dict):
        """**Why override:** persist a DB row when a *node* run begins.

        ``super()`` still builds and records the normal start event (buffer + log + realtime).
        """
        super().log_node_start(request)
        if self._persist_to_db:
            self._persist_run_start()

    def log_node_end(self, result, level: str = "info", message: str = "Node execution completed"):
        """**Why override:** persist completion using :class:`NodeExecutionResult` fields.

        ``super()`` records the terminal node event first; we then update ``execution_run`` and
        notify via SSE.
        """
        super().log_node_end(result, level=level, message=message)
        if self._persist_to_db:
            self._persist_run_end(result)

    def log_workflow_start(self, initial_state: dict, state_mapping_desc=None):
        """**Why override:** same DB "run start" as nodes, but invoked from workflow entry.

        Distinguishes execution type inside :meth:`_persist_run_start` via ``workflow_id``.
        """
        super().log_workflow_start(initial_state, state_mapping_desc)
        if self._persist_to_db:
            self._persist_run_start()

    def _get_app(self):
        """Return Flask app reference (captured at init time, safe in background threads)."""
        if self._flask_app is not None:
            return self._flask_app
        try:
            from flask import current_app
            return current_app._get_current_object()
        except Exception:
            return None

    def _persist_emit_event(self, event: BaseEvent) -> None:
        """Append one row to ``execution_log`` for this emitted event (best-effort, background)."""
        app = self._get_app()
        if app is None:
            return

        execution_id = self.execution_id
        execution_type = "node" if self.node_id else "workflow"
        plugin_id = self.node_id or self.workflow_id
        user_id = self._user_id
        ts = time.time()

        try:
            payload = event.model_dump()
        except Exception:
            payload = {"_error": "model_dump failed", "_repr": repr(event)}
        data = _make_json_serializable(payload)
        if not isinstance(data, dict):
            data = {"value": data}

        ev_raw = getattr(event, "event", None)
        ev_name = (str(ev_raw) if ev_raw is not None else "event")[:50]
        level = (str(getattr(event, "level", "info") or "info"))[:20]
        msg = getattr(event, "message", None)
        if msg is not None:
            msg = str(msg)
            if len(msg) > 65000:
                msg = msg[:65000] + "…"

        def _run():
            try:
                with app.app_context():
                    from nos.platform.services.sqlalchemy.execution_log import repository as log_repo

                    log_repo.add_log(
                        execution_id=execution_id,
                        execution_type=execution_type,
                        plugin_id=plugin_id,
                        event=ev_name,
                        level=level,
                        message=msg,
                        data=data,
                        timestamp=ts,
                        end_timestamp=ts,
                        user_id=user_id,
                    )
            except Exception as exc:
                logger.debug("execution_log row persist failed: %s", exc, exc_info=True)

        _schedule_background(_run)

    def _persist_run_start(self):
        """Insert execution_run row when execution starts."""
        app = self._get_app()
        if app is None:
            logger.warning("execution_run: no Flask app context — skipping start persist")
            return

        execution_id   = self.execution_id
        execution_type = "node" if self.node_id else "workflow"
        plugin_id      = self.node_id or self.workflow_id
        user_id        = self._user_id
        started_at     = time.time()

        def _run():
            try:
                with app.app_context():
                    from nos.platform.services.sqlalchemy.execution_run import repository as run_repo
                    run_repo.create_run(
                        execution_id=execution_id,
                        execution_type=execution_type,
                        plugin_id=plugin_id,
                        user_id=user_id,
                        started_at=started_at,
                    )
                    logger.debug("execution_run created: %s", execution_id)
            except Exception as exc:
                logger.error("execution_run start persist failed: %s", exc, exc_info=True)

        _schedule_background(_run)

    def _persist_run_end(self, result):
        """Update execution_run row when a node execution ends, then fire SSE notification.

        The SSE publish happens in the ``finally`` block so the notification is
        delivered even when the DB write fails (best-effort notification).
        """
        app = self._get_app()
        if app is None:
            logger.warning("execution_run: no Flask app context — skipping end persist")
            return

        execution_id   = self.execution_id
        execution_type = "node" if self.node_id else "workflow"
        plugin_id      = self.node_id or self.workflow_id
        user_id        = self._user_id
        ended_at       = time.time()

        # Read result fields defensively; NodeExecutionResult attributes may vary
        status       = str(getattr(result, "status", "success"))
        message      = getattr(result, "message", None)
        elapsed_time = getattr(result, "elapsed_time", None)

        def _run():
            try:
                with app.app_context():
                    from nos.platform.services.sqlalchemy.execution_run import repository as run_repo
                    run_repo.complete_run(
                        execution_id=execution_id,
                        status=status,
                        message=message,
                        ended_at=ended_at,
                        elapsed_time=str(elapsed_time) if elapsed_time else None,
                    )
                    logger.debug(
                        "execution_run completed: %s status=%s", execution_id, status
                    )
            except Exception as exc:
                logger.error("execution_run end persist failed: %s", exc, exc_info=True)
            finally:
                try:
                    from nos.platform.services.sse.manager import sse_manager
                    sse_manager.publish(
                        user_id=user_id,
                        event="execution_end",
                        data={
                            "execution_id": execution_id,
                            "execution_type": execution_type,
                            "plugin_id": plugin_id,
                            "status": status,
                            "message": message,
                            "elapsed_time": str(elapsed_time) if elapsed_time else None,
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        "SSE publish failed (non-blocking): %s", exc, exc_info=True
                    )

        _schedule_background(_run)

    def _persist_run_end_workflow(self):
        """Update execution_run row at workflow completion and fire SSE notification.

        Workflows do not produce a single :class:`NodeExecutionResult`; the status
        is set to ``"completed"`` unconditionally. SSE notification fires in
        ``finally`` regardless of DB outcome.
        """
        app = self._get_app()
        if app is None:
            return

        execution_id   = self.execution_id
        plugin_id      = self.workflow_id or self.node_id
        user_id        = self._user_id
        ended_at       = time.time()

        def _run():
            try:
                with app.app_context():
                    from nos.platform.services.sqlalchemy.execution_run import repository as run_repo
                    run_repo.complete_run(
                        execution_id=execution_id,
                        status="completed",
                        ended_at=ended_at,
                    )
                    logger.debug("execution_run workflow completed: %s", execution_id)
            except Exception as exc:
                logger.error(
                    "execution_run workflow end persist failed: %s", exc, exc_info=True
                )
            finally:
                try:
                    from nos.platform.services.sse.manager import sse_manager
                    sse_manager.publish(
                        user_id=user_id,
                        event="execution_end",
                        data={
                            "execution_id": execution_id,
                            "execution_type": "workflow",
                            "plugin_id": plugin_id,
                            "status": "completed",
                            "message": None,
                            "elapsed_time": None,
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        "SSE publish (workflow) failed (non-blocking): %s", exc, exc_info=True
                    )

        _schedule_background(_run)

    def _emit_to_socket(self, event: BaseEvent):
        """Push structured event to subscribers via Socket.IO (``execution_log`` event name)."""
        socketio = _try_socketio()
        if socketio is None or not self._emit_realtime:
            return

        event_dict = event.to_dict()

        def emit_log():
            try:
                if self._room:
                    socketio.emit("execution_log", event_dict, namespace="/", room=self._room)
                else:
                    socketio.emit("execution_log", event_dict, namespace="/", broadcast=True)
            except Exception as e:
                logger.error("Socket.IO execution_log emit error: %s", e, exc_info=True)

        try:
            _schedule_background(emit_log)
        except Exception as e:
            logger.warning("Failed to schedule execution_log emit: %s", e)

    def request_and_wait(
        self,
        event_type: str,
        data: dict,
        timeout: float = 60.0,
    ) -> Optional[dict]:
        """
        Send a request to the client and wait for response.

        Args:
            event_type: Event type to emit (e.g., "user_approval_required")
            data: Event data
            timeout: Maximum time to wait (seconds)

        Returns:
            Response data from client, or None if timeout
        """
        from .registry import _event_log_registry

        socketio = _try_socketio()
        if socketio is None:
            logger.error(
                "request_and_wait requires Flask-SocketIO (web platform). "
                "Install e.g. pip install 'nos[web]'."
            )
            return None

        request_id = str(uuid.uuid4())

        wait_event = threading.Event()
        with self._response_lock:
            self._pending_requests[request_id] = wait_event

        _event_log_registry.register_pending_request(request_id, self)

        # EVENT 1: "execution_log" — history stream (unidirectional)
        event = CustomEvent(
            **self._base_fields(),
            event=event_type,
            level="info",
            message=f"Waiting for client response...",
            request_id=request_id,
            request_data=data,
            awaiting_response=True,
        )
        self._emit(event)

        # EVENT 2: "execution_request" — bidirectional prompt
        try:
            request_payload = {
                "request_id": request_id,
                "event_type": event_type,
                "execution_id": self.execution_id,
                "node_id": self.node_id,
                "workflow_id": self.workflow_id,
                "data": data,
            }
            request_payload = _make_json_serializable(request_payload)
            logger.info(
                "Emitting execution_request: request_id=%s event_type=%s room=%s workflow_id=%s node_id=%s",
                request_id,
                event_type,
                self._room or "broadcast",
                self.workflow_id,
                self.node_id,
            )
            if self._room:
                socketio.emit("execution_request", request_payload, namespace="/", room=self._room)
            else:
                socketio.emit("execution_request", request_payload, namespace="/", broadcast=True)
        except Exception as e:
            logger.exception("Failed to emit execution_request: %s", e)

        received = wait_event.wait(timeout=timeout)

        _event_log_registry.unregister_pending_request(request_id)
        with self._response_lock:
            self._pending_requests.pop(request_id, None)
            response = self._responses.pop(request_id, None)

        if not received:
            timeout_event = CustomEvent(
                **self._base_fields(),
                event=f"{event_type}_timeout",
                level="warning",
                message=f"Request timed out after {timeout}s: {event_type}",
                request_id=request_id,
            )
            self._emit(timeout_event)
            return None

        return response

    def handle_response(self, request_id: str, response_data: dict):
        """
        Handle a response from the client. Called by Socket.IO event handler.

        Args:
            request_id: The correlation ID from the original request
            response_data: Response data from client
        """
        with self._response_lock:
            if request_id in self._pending_requests:
                self._responses[request_id] = response_data
                self._pending_requests[request_id].set()
            else:
                logger.warning(f"Received response for unknown request_id: {request_id}")
