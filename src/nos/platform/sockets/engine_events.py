"""
SocketIO event handlers for Engine run flow.

Handles:
- engine_request_run: client requests run → server emits form_schema (or empty)
- engine_form_data: client submits form → server initializes state and runs execution
"""

import logging
import time

from flask_socketio import emit
from flask import request

from ..api.form_wire import node_engine_run_form_payload, workflow_engine_run_form_payload

logger = logging.getLogger(__name__)

# Pending EventLog instances: created at request_run, consumed at form_data
_pending_node_exec_logs: dict = {}
_pending_workflow_exec_logs: dict = {}


def register_engine_socket_events(socketio):
    """Register engine-related SocketIO handlers."""

    @socketio.on("engine_stop")
    def handle_engine_stop(data):
        """Handle client request to stop a running node or workflow execution.

        Expected payload::

            {"type": "nd"|"wk"|"ass", "id": "<execution_id>"}

        Calls ``engine.stop_execution()`` on the shared engine singleton so the
        cooperative cancellation event is set and the running thread exits cleanly
        at the next :meth:`~nos.core.execution_log.event_log_buffer.EventLogBuffer.log` call on the run's exec log.
        """
        client_id = request.sid
        try:
            from nos.core.engine import get_shared_engine

            exec_type = data.get("type")
            exec_id   = data.get("id", "").strip()
            type_label = {"nd": "Node", "wk": "Workflow", "ass": "Assistant"}.get(
                exec_type, "Execution"
            )

            if not exec_id:
                emit(
                    "engine_error",
                    {"message": "engine_stop: missing execution id"},
                    room=client_id,
                )
                return

            engine = get_shared_engine()
            result = engine.stop_execution(exec_id)

            if result.get("stopped"):
                emit(
                    "engine_stopped",
                    {"message": f"{type_label} '{exec_id}' stop signal sent", "result": result},
                    room=client_id,
                )
                logger.info(
                    "Stop signal sent for %s '%s' by client %s", type_label, exec_id, client_id
                )
            else:
                error_msg = result.get("error", f"Execution '{exec_id}' not found or already finished")
                emit(
                    "engine_error",
                    {"message": error_msg, "result": result},
                    room=client_id,
                )
                logger.warning(
                    "Stop failed for '%s': %s (client %s)", exec_id, error_msg, client_id
                )

        except Exception as e:
            logger.error("handle_engine_stop failed: %s", e, exc_info=True)
            try:
                emit("engine_error", {"message": str(e)}, room=client_id)
            except Exception:
                pass

    @socketio.on("engine_request_run")
    def handle_engine_request_run(data):
        """
        Client requests execution. Emit ``form_schema`` (see ``engine_form_wire``).
        """
        from flask import session
        client_id = request.sid
        user_id = session.get("username", "developer")
        try:
            exec_type = data.get("type")  # "nd" | "wk"
            exec_id = data.get("id")
            background = data.get("background", True)
            if "output_mode" in data:
                emit(
                    "engine_error",
                    {"message": "Unsupported key 'output_mode'. Use 'debug_mode' ('trace' or 'debug')."},
                    room=client_id,
                )
                return
            if "job" in data:
                emit(
                    "engine_error",
                    {"message": "Unsupported key 'job'. Use 'background' for non-blocking execution."},
                    room=client_id,
                )
                return
            dm = data.get("debug_mode", "trace")
            debug_mode = str(dm).lower().strip() if dm is not None else "trace"
            if debug_mode not in ("trace", "debug"):
                emit(
                    "engine_error",
                    {"message": "debug_mode must be 'trace' or 'debug'."},
                    room=client_id,
                )
                return
            if background:
                debug_mode = "trace"

            if not exec_type or not exec_id:
                emit("engine_error", {"message": "Missing type or id"}, room=client_id)
                return

            if exec_type == "ass":
                emit("engine_error", {"message": "Assistant execution is not yet implemented"}, room=client_id)
                return

            if exec_type == "nd":
                form_schema = node_engine_run_form_payload(exec_id)
            elif exec_type == "wk":
                form_schema = workflow_engine_run_form_payload(exec_id)
            else:
                emit("engine_error", {"message": f"Unknown type: {exec_type}"}, room=client_id)
                return

            context = {
                "type": exec_type,
                "id": exec_id,
                "background": background,
                "debug_mode": debug_mode,
            }

            schema_dump = form_schema

            if exec_type == "nd":
                from nos.platform.execution_log import EventLog
                execution_id = f"node_{exec_id}_{int(time.time())}"
                # Note: module_path and class_name will be set when node is loaded
                node_exec_log = EventLog(
                    execution_id=execution_id,
                    node_id=exec_id,
                    workflow_id=None,
                    module_path="",
                    class_name="",
                    shared_state={},
                    room=client_id,
                    persist_to_db=True,
                    user_id=user_id,
                )
                _pending_node_exec_logs[execution_id] = node_exec_log
                node_exec_log.log_form_schema_sent(schema_dump)
                context["execution_id"] = execution_id
            elif exec_type == "wk":
                from nos.platform.execution_log import EventLog
                execution_id = f"workflow_{exec_id}_{int(time.time())}"
                workflow_exec_log = EventLog(
                    execution_id=execution_id,
                    node_id=None,
                    workflow_id=exec_id,
                    module_path="",
                    class_name="",
                    shared_state={},
                    room=client_id,
                    persist_to_db=True,
                    user_id=user_id,
                )
                _pending_workflow_exec_logs[execution_id] = workflow_exec_log
                workflow_exec_log.log_form_schema_sent(schema_dump)
                context["execution_id"] = execution_id

            payload = {"form_schema": schema_dump, "context": context}
            logger.info("Emitting engine_form_schema to client %s: %s", client_id, payload)
            emit(
                "engine_form_schema",
                payload,
                room=client_id,
            )
        except Exception as e:
            logger.error("handle_engine_request_run failed: %s", e, exc_info=True)
            try:
                emit("engine_error", {"message": str(e)}, room=client_id)
            except Exception:
                pass

    @socketio.on("engine_form_data")
    def handle_engine_form_data(data):
        """
        Client submits form data. Initialize state and run execution.
        - background: emit "Workflow started. Job runs in background. You can close this window."
        - sync: stream logs via execution_log
        """
        from flask import session as _session
        client_id = request.sid
        user_id = _session.get("username", "developer")
        try:
            form_data = data.get("form_data") or {}
            context = data.get("context") or {}
            exec_type = context.get("type")
            exec_id = context.get("id")
            background = context.get("background", True)

            if isinstance(form_data, dict):
                if "output_mode" in form_data:
                    emit(
                        "engine_error",
                        {"message": "Unsupported field 'output_mode' in form_data. Use 'debug_mode'."},
                        room=client_id,
                    )
                    return
                if "job" in form_data:
                    emit(
                        "engine_error",
                        {"message": "Unsupported field 'job' in form_data. Use execution context 'background'."},
                        room=client_id,
                    )
                    return

            if not exec_type or not exec_id:
                emit("engine_error", {"message": "Missing context type or id"}, room=client_id)
                return

            def _run_and_notify():
                try:
                    node_exec_log = None
                    workflow_exec_log = None
                    if exec_type == "nd":
                        execution_id = context.get("execution_id")
                        if execution_id:
                            node_exec_log = _pending_node_exec_logs.pop(execution_id, None)
                        if node_exec_log:
                            node_exec_log.log_form_data_received(form_data)
                    elif exec_type == "wk":
                        execution_id = context.get("execution_id")
                        if execution_id:
                            workflow_exec_log = _pending_workflow_exec_logs.pop(execution_id, None)
                        if workflow_exec_log:
                            workflow_exec_log.log_form_data_received(form_data)
                    if exec_type == "nd":
                        _run_node(
                            exec_id,
                            form_data,
                            background,
                            client_id,
                            socketio,
                            exec_log=node_exec_log,
                            user_id=user_id,
                        )
                    elif exec_type == "wk":
                        _run_workflow(
                            exec_id,
                            form_data,
                            background,
                            client_id,
                            socketio,
                            exec_log=workflow_exec_log,
                            user_id=user_id,
                        )
                    else:
                        emit("engine_error", {"message": f"Unknown type: {exec_type}"}, room=client_id)
                except Exception as e:
                    logger.error("_run_and_notify failed: %s", e, exc_info=True)
                    try:
                        emit("engine_error", {"message": str(e)}, room=client_id)
                    except Exception:
                        pass

            from nos.core.engine import get_shared_engine
            get_shared_engine()._executor.submit(_run_and_notify)

        except Exception as e:
            logger.error("handle_engine_form_data failed: %s", e, exc_info=True)
            try:
                emit("engine_error", {"message": str(e)}, room=client_id)
            except Exception:
                pass


def _run_node(
    node_id: str,
    form_data: dict,
    background: bool,
    client_id: str,
    socketio,
    exec_log=None,
    user_id: str = "developer",
):
    """Execute node directly (same process) and emit to client via Socket.IO."""
    from nos.core.engine.registry import workflow_registry
    from nos.platform.execution_log import EventLog
    from ..api.node.routes import _run_node_sync

    try:
        node_class = workflow_registry.get_node(node_id)
        if not node_class:
            socketio.emit("engine_error", {"message": f"Node {node_id} not found"}, room=client_id)
            return

        node = workflow_registry.create_node_instance(node_id)
        if not node:
            socketio.emit("engine_error", {"message": f"Failed to create node {node_id}"}, room=client_id)
            return

        if exec_log is None:
            execution_id = f"node_{node_id}_{int(time.time())}"
            exec_log = EventLog(
                execution_id=execution_id,
                node_id=node_id,
                workflow_id=None,
                module_path=node.__class__.__module__,
                class_name=node.__class__.__name__,
                shared_state={},
                room=client_id,
                persist_to_db=True,
                user_id=user_id,
            )
        else:
            # Update module_path, class_name, and user_id now that node is loaded
            exec_log.module_path = node.__class__.__module__
            exec_log.class_name = node.__class__.__name__
            exec_log._user_id = user_id
            exec_log._persist_to_db = True
        node.set_exec_log(exec_log)

        fd = dict(form_data)
        of_socket = fd.pop("output_format", None)
        state = fd.copy()
        input_params = fd

        if background:
            def bg_run():
                try:
                    _run_node_sync(
                        node,
                        state,
                        input_params,
                        node_id,
                        exec_log,
                        output_format=of_socket,
                    )
                except Exception as e:
                    logger.error("Background node %s failed: %s", node_id, e, exc_info=True)
                    exec_log.log("error", str(e))

            from nos.core.engine import get_shared_engine
            get_shared_engine()._executor.submit(bg_run)
            socketio.emit(
                "engine_message",
                {"message": "Node started. Job runs in background. You can close this window.", "type": "success"},
                room=client_id,
            )
        else:
            try:
                result = _run_node_sync(
                    node,
                    state,
                    input_params,
                    node_id,
                    exec_log,
                    output_format=of_socket,
                )
                out = result.model_dump()
                socketio.emit("engine_result", out, room=client_id)
            except Exception as e:
                logger.error("Sync node %s failed: %s", node_id, e, exc_info=True)
                socketio.emit("engine_error", {"message": str(e)}, room=client_id)
    except Exception as e:
        logger.error("_run_node failed: %s", e, exc_info=True)
        socketio.emit("engine_error", {"message": str(e)}, room=client_id)


def _run_workflow(
    workflow_id: str,
    form_data: dict,
    background: bool,
    client_id: str,
    socketio,
    exec_log=None,
    output_format: str = "json",
    user_id: str = "developer",
):
    """Execute workflow and emit result/status to client via Socket.IO."""
    from nos.core.engine.registry import workflow_registry
    from nos.core.engine import get_shared_engine
    from nos.platform.execution_log import EventLog
    from nos.io_adapters.output_formats_schema import OUTPUT_FORMATS
    from nos.hooks import event_hooks, EventType

    try:
        # Extract output_format / debug_mode from form_data (don't pass as initial state)
        form_data = dict(form_data) if form_data else {}
        if "output_mode" in form_data:
            socketio.emit(
                "engine_error",
                {"message": "Unsupported field 'output_mode' in form_data. Use 'debug_mode'."},
                room=client_id,
            )
            return
        if "job" in form_data:
            socketio.emit(
                "engine_error",
                {"message": "Unsupported field 'job' in form_data. Use execution context 'background'."},
                room=client_id,
            )
            return
        output_format = str(form_data.pop("output_format", output_format or "json")).lower().strip()
        if output_format not in OUTPUT_FORMATS:
            output_format = "json"
        raw_dm = form_data.pop("debug_mode", "trace")
        dm = str(raw_dm).lower().strip() if raw_dm is not None else "trace"
        if dm not in ("trace", "debug"):
            socketio.emit(
                "engine_error",
                {"message": "debug_mode must be 'trace' or 'debug'."},
                room=client_id,
            )
            return
        workflow_class = workflow_registry.get_workflow(workflow_id)
        if not workflow_class:
            socketio.emit("engine_error", {"message": f"Workflow {workflow_id} not found"}, room=client_id)
            return

        workflow = workflow_registry.create_workflow_instance(workflow_id)
        engine = get_shared_engine()

        # Create exec log if not provided (e.g. first run without pending form step)
        if exec_log is None:
            execution_id = f"workflow_{workflow_id}_{int(time.time())}"
            exec_log = EventLog(
                execution_id=execution_id,
                node_id=None,
                user_id=user_id,
                workflow_id=workflow_id,
                module_path="",
                class_name="",
                shared_state={},
                room=client_id,
            )

        event_hooks.emit(EventType.WORKFLOW_STARTED, {"workflow_id": workflow_id, "background": background})

        if background:
            try:
                execution_id = engine.execute_background(
                    workflow=workflow,
                    initial_state=form_data,
                    exec_log=exec_log,
                    output_format=output_format,
                    debug_mode=dm,
                )
                socketio.emit(
                    "engine_message",
                    {
                        "message": "Workflow started. Job runs in background. You can close this window.",
                        "type": "success",
                        "execution_id": execution_id,
                    },
                    room=client_id,
                )
            except Exception as e:
                logger.error("Background workflow %s failed: %s", workflow_id, e, exc_info=True)
                event_hooks.emit(EventType.WORKFLOW_ERROR, {"workflow_id": workflow_id, "error": str(e)})
                socketio.emit("engine_error", {"message": str(e)}, room=client_id)
        else:
            try:
                result = engine.execute_sync(
                    workflow=workflow,
                    initial_state=form_data,
                    exec_log=exec_log,
                    output_format=output_format,
                    debug_mode=dm,
                )
                event_hooks.emit(
                    EventType.WORKFLOW_COMPLETED,
                    {
                        "workflow_id": workflow_id,
                        "final_state": result.response.output.get("data"),
                    },
                )
                payload = {
                    "workflow_id": workflow_id,
                    "status": result.status if result.status == "cancelled" else "completed",
                    "execution_id": result.execution_id,
                    "module_path": result.module_path,
                    "class_name": result.class_name,
                    "response": {
                        "output": dict(result.response.output),
                        "metadata": dict(result.response.metadata),
                    },
                    "state": result.state,
                    "initial_state": result.initial_state,
                    "state_changed": result.state_changed,
                    "event_logs": result.event_logs,
                    "started_at": result.started_at,
                    "ended_at": result.ended_at,
                    "duration": result.duration,
                    "node_ids_executed": result.node_ids_executed,
                    "message": result.message,
                }
                socketio.emit("engine_result", payload, room=client_id)
            except Exception as e:
                logger.error("Sync workflow %s failed: %s", workflow_id, e, exc_info=True)
                event_hooks.emit(EventType.WORKFLOW_ERROR, {"workflow_id": workflow_id, "error": str(e)})
                socketio.emit("engine_error", {"message": str(e)}, room=client_id)
    except Exception as e:
        logger.error("_run_workflow failed: %s", e, exc_info=True)
        try:
            socketio.emit("engine_error", {"message": str(e)}, room=client_id)
        except Exception:
            pass
