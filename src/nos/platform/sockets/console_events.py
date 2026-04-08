"""
Console Socket.IO event handlers.

Handles real-time console commands and output streaming.
"""

import dataclasses
import json
import logging
import os
import re
import time
from pathlib import Path
from flask_socketio import emit
from flask import request

from nos.platform.console import (
    validate_command,
    execute_command,
    console_router,
    ConsoleOutput,
    command_registry,
)

logger = logging.getLogger(__name__)


def _write_execution_snapshot_json(execution_id: str, payload: dict) -> str | None:
    """Write ``payload`` to ~/.nos/execution_logs/{execution_id}.json (pretty JSON). Shared root, not per-user."""
    if not execution_id or not isinstance(payload, dict):
        return None
    safe_id = re.sub(r"[^\w.\-]", "_", str(execution_id).strip())[:200]
    if not safe_id:
        return None
    try:
        root = Path.home() / ".nos" / "execution_logs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{safe_id}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.debug("Execution snapshot written: %s", path)
        return str(path)
    except Exception as exc:
        logger.error("Failed to write execution snapshot: %s", exc, exc_info=True)
        return None


def _snapshot_node_callback_dict(user_id: str, result: dict) -> str | None:
    """Persist :class:`NodeExecutionResult` dict (inner ``result``) for History download / reload."""
    inner = result.get("result")
    payload = inner if isinstance(inner, dict) else result
    if not isinstance(payload, dict):
        return None
    eid = payload.get("execution_id") or result.get("execution_id")
    if not eid:
        return None
    path = _write_execution_snapshot_json(str(eid), payload)
    if path:
        _persist_execution_log_path(str(eid), path)
    return path


def _snapshot_workflow_result_dict(user_id: str, result_dict: dict, fallback_execution_id: str = "") -> str | None:
    """Persist :class:`WorkflowExecutionResult` as dict."""
    if not isinstance(result_dict, dict):
        return None
    eid = result_dict.get("execution_id") or fallback_execution_id
    if not eid:
        return None
    path = _write_execution_snapshot_json(str(eid), result_dict)
    if path:
        _persist_execution_log_path(str(eid), path)
    return path


def _save_execution_result(result, user_id: str) -> str | None:
    """Backward-compatible helper used by ``--save`` (same on-disk layout as auto-snapshot)."""
    if isinstance(result, dict):
        return _snapshot_node_callback_dict(user_id, result)
    try:
        execution_id = getattr(result, "execution_id", None) or getattr(result, "node_id", "unknown")
        data = result.model_dump() if hasattr(result, "model_dump") else vars(result)
        if isinstance(data, dict):
            path = _write_execution_snapshot_json(str(execution_id), data)
            if path:
                _persist_execution_log_path(str(execution_id), path)
            return path
    except Exception as exc:
        logger.error("Failed to save execution result: %s", exc, exc_info=True)
    return None


def _persist_execution_log_path(execution_id: str, path: str):
    """Update execution_run.execution_log with the saved file path (background)."""
    try:
        from ..extensions import socketio as _sio
        from flask import current_app
        app = current_app._get_current_object()

        def _update():
            try:
                with app.app_context():
                    from ..services.sqlalchemy.execution_run import repository as run_repo
                    run_repo.set_execution_log_path(execution_id, path)
            except Exception as e:
                logger.error("Failed to persist execution_log path: %s", e)

        _sio.start_background_task(_update)
    except Exception as e:
        logger.error("_persist_execution_log_path setup failed: %s", e)


def register_console_socket_events(socketio):
    """
    Register Console-related SocketIO event handlers.
    
    Events:
    - console_command: Client sends a command to execute
    - console_output: Server sends output back to client
    
    Args:
        socketio: SocketIO instance
    """
    
    @socketio.on("console_command")
    def handle_console_command(data):
        """
        Handle console command from client.
        
        Receives raw command, validates it, and executes or routes accordingly.
        All communication is via Socket.IO - no REST API needed.
        
        Args:
            data: Command payload with raw_command string
                {
                    "raw_command": "help"
                }
        """
        client_id = request.sid
        raw_command = data.get("raw_command", "").strip()
        
        logger.info(f"Console command from {client_id}: {raw_command}")
        
        # Empty command
        if not raw_command:
            emit("console_output", ConsoleOutput(
                type="error",
                format="text",
                message="Empty command",
                timestamp=time.time()
            ).model_dump())
            return
        
        try:
            # Step 1: Validate command using console module
            validation = validate_command(raw_command)
            
            if not validation.valid:
                # Invalid command - send error
                emit("console_output", ConsoleOutput(
                    type="error",
                    format="text",
                    message=validation.error,
                    timestamp=time.time()
                ).model_dump())
                return
            
            # Step 2: Extract routing info
            routing = validation.routing
            action = routing.payload.get("action", "")
            args = routing.payload.get("args", [])
            
            # Step 3: Try sync execution first
            output = execute_command(action, args)
            
            if output:
                # Sync command - send output directly
                emit("console_output", output.model_dump())
                logger.debug(f"Console sync output: {output.type} - {output.message[:50]}...")
            else:
                # Async command - handle it (pass full request data for save payload)
                _handle_async_command(socketio, client_id, action, routing.payload, request_data=data)
                
        except Exception as e:
            logger.error(f"Console command error: {e}", exc_info=True)
            emit("console_output", ConsoleOutput(
                type="error",
                format="text",
                message=f"Error executing command: {str(e)}",
                timestamp=time.time()
            ).model_dump())
    
    def _handle_async_command(socketio, client_id, action: str, data: dict, request_data: dict = None):
        """
        Handle async console commands (run, list, create, save).
        
        These commands may take longer and stream output progressively.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Command action (e.g., "run_node", "list_nodes", "create_node", "save")
            data: Full command data (routing payload)
            request_data: Original request data (for save_payload etc.)
        """
        args = data.get("args", [])
        req = request_data or {}
        
        # Handle list commands
        if action.startswith("list_"):
            _handle_list_command(socketio, client_id, action, args)
            return
        
        # Handle run commands (pass raw_command for node_start event)
        if action.startswith("run_"):
            _handle_run_command(socketio, client_id, action, args, raw_command=req.get("raw_command", ""))
            return
        
        # Handle create commands
        if action.startswith("create_"):
            _handle_create_command(socketio, client_id, action, args)
            return
        
        # Handle open commands
        if action.startswith("open_"):
            _handle_open_command(socketio, client_id, action, args)
            return
        
        # Handle save command (payload from editor)
        if action == "save":
            _handle_save_command(socketio, client_id, req)
            return
        
        # Handle register commands
        if action.startswith("reg_"):
            _handle_reg_command(socketio, client_id, action, args)
            return
        
        # Handle dir command
        if action == "dir":
            _handle_dir_command(socketio, client_id)
            return
        
        # Handle stop command
        if action == "stop":
            _handle_stop_command(socketio, client_id, args)
            return
        
        # Handle ps command (list executions)
        if action == "ps":
            _handle_ps_command(socketio, client_id)
            return
        
        # Handle logs command (retrieve execution logs from DB)
        if action == "logs":
            _handle_logs_command(socketio, client_id, args)
            return
        
        # Handle unreg commands
        if action.startswith("unreg_"):
            _handle_unreg_command(socketio, client_id, action, args)
            return
        
        # Handle pub commands
        if action.startswith("pub_"):
            _handle_pub_command(socketio, client_id, action, args)
            return
        
        # Handle unpub commands
        if action.startswith("unpub_"):
            _handle_unpub_command(socketio, client_id, action, args)
            return
        
        # Handle update commands
        if action.startswith("update_"):
            _handle_update_command(socketio, client_id, action, args)
            return
        
        # Handle info commands
        if action.startswith("info_"):
            _handle_info_command(socketio, client_id, action, args)
            return
        
        # Handle reload commands
        if action.startswith("reload_"):
            _handle_reload_command(socketio, client_id, action, args)
            return
        
        # Handle rm commands
        if action.startswith("rm_"):
            _handle_rm_command(socketio, client_id, action, args)
            return
        
        # Handle mv commands
        if action.startswith("mv_"):
            _handle_mv_command(socketio, client_id, action, args)
            return
        
        # Handle sql command
        if action == "sql":
            _handle_sql_command(socketio, client_id, args, raw_command=req.get("raw_command", ""))
            return
        
        # Handle query command (SELECT only)
        if action == "query":
            _handle_query_command(socketio, client_id, args, raw_command=req.get("raw_command", ""))
            return
        
        # Handle tables command
        if action == "tables":
            _handle_tables_command(socketio, client_id)
            return
        
        # Handle describe command
        if action == "describe":
            _handle_describe_command(socketio, client_id, args)
            return
        
        # Handle ai commands
        if action.startswith("ai_"):
            _handle_ai_command(socketio, client_id, action, args)
            return
        
        # Handle ollama commands
        if action.startswith("ollama_"):
            _handle_ollama_command(socketio, client_id, action, args)
            return
        
        # Handle vect commands (vector DB)
        if action.startswith("vect_"):
            _handle_vect_command(socketio, client_id, action, args)
            return

        # plugin create / install (scaffold + pip install -e)
        if action.startswith("plugin_"):
            _handle_plugin_command(socketio, client_id, action, args)
            return
        
        # Unknown async command
        error_output = ConsoleOutput(
            type="error",
            format="text",
            message=f"Unknown async command: {action}",
            timestamp=time.time()
        )
        socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_list_command(socketio, client_id, action: str, args: list):
        """
        Handle list commands (list_nodes, list_workflows, list_assistants).
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: List action type
            args: Command arguments
        """
        try:
            if action == "list_nodes":
                # Import node repository
                from nos.platform.services.sqlalchemy.node import repository as node_repo
                nodes = node_repo.get_all() or []
                
                columns = ["node_id", "name", "registration_status"]
                rows = []
                for node in nodes:
                    status = node.registration_status if node.registration_status else "unknown"
                    if hasattr(status, 'value'):
                        status = status.value
                    rows.append({
                        "node_id": node.node_id,
                        "name": node.name or "",
                        "registration_status": status,
                    })
                
                message = f"Registered nodes ({len(rows)})" if rows else "No nodes registered."
                output = ConsoleOutput(
                    type="info",
                    format="table",
                    message=message,
                    data={
                        "columns": columns,
                        "rows": rows,
                        "count": len(rows),
                    },
                    timestamp=time.time()
                )
            
            elif action == "list_workflows":
                # Import workflow repository
                from ..services.sqlalchemy.workflow import repository as wf_repo
                workflows = wf_repo.get_all() or []
                
                columns = ["workflow_id", "name", "registration_status"]
                rows = []
                for wf in workflows:
                    status = wf.registration_status if wf.registration_status else "unknown"
                    if hasattr(status, 'value'):
                        status = status.value
                    rows.append({
                        "workflow_id": wf.workflow_id,
                        "name": wf.name or "",
                        "registration_status": status,
                    })
                
                message = f"Registered workflows ({len(rows)})" if rows else "No workflows registered."
                output = ConsoleOutput(
                    type="info",
                    format="table",
                    message=message,
                    data={
                        "columns": columns,
                        "rows": rows,
                        "count": len(rows),
                    },
                    timestamp=time.time()
                )
            
            elif action == "list_assistants":
                # Placeholder - assistants not yet implemented
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message="Assistants listing not yet implemented.",
                    timestamp=time.time()
                )
            
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown list command: {action}",
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"List command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_run_command(socketio, client_id, action: str, args: list, raw_command: str = ""):
        """
        Handle run commands (run_node, run_workflow).
        
        Syntax:
            run node dev <module_path> <class_name> [--state k=v] [--param k=v] [--request JSON|k=v…]
            run node prod <node_id> [--state k=v] [--param k=v] [--request JSON|k=v…]
            run workflow dev <module_path> <class_name> [--state k=v] [--param k=v]
            run workflow prod <workflow_id> [--state k=v] [--param k=v]
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Run action type (run_node, run_workflow)
            args: Command arguments [mode, module_path|id, class_name?, --param k=v, ...]
            raw_command: Full command string (for node_start event)
        """
        if len(args) < 2:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Usage: run <node|workflow> <dev|prod> <module_path|id> [class_name] [--state k=v] [--param k=v] [--output_format ...]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        mode_raw = args[0].lower()
        if mode_raw not in ("dev", "prod"):
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Invalid mode: '{mode_raw}'. Use 'dev' or 'prod'.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        mode = mode_raw
        
        try:
            if action == "run_node":
                _execute_node_command(socketio, client_id, mode, args[1:], command=raw_command)
            elif action == "run_workflow":
                _execute_workflow_command(socketio, client_id, mode, args[1:])
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown run command: {action}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"Run command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _parse_params(args: list) -> dict:
        """
        Parse command-line style parameters.
        
        Supports: --key value, --key=value, --key v1 v2 (multiple space-separated values joined)
        
        Args:
            args: List of argument strings
            
        Returns:
            Dict of parsed parameters
        """
        params = {}
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                if "=" in arg:
                    key, value = arg[2:].split("=", 1)
                    params[key] = value
                elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                    # Collect all consecutive non-flag tokens (e.g. --param a=1 b=2)
                    values = []
                    j = i + 1
                    while j < len(args) and not args[j].startswith("--"):
                        values.append(args[j])
                        j += 1
                    params[arg[2:]] = " ".join(values) if len(values) > 1 else values[0]
                    i = j - 1  # will be incremented to j at end of loop
                else:
                    params[arg[2:]] = True
            i += 1
        return params
    
    def _execute_node_command(socketio, client_id, mode: str, args: list, command: str = ""):
        """
        Execute a node plugin via the WorkflowEngine.
        
        Execution is tracked by the engine and can be stopped with the 'stop' command.
        
        Syntax:
            run node <dev|prod> <id|path> [class_name] [--sync|--bk] [--trace|--debug] [--log|--nolog] [--state k=v] [--param JSON|k=v ...] [--request JSON|k=v…] [--output_format ...]
            
            --param: prefer a JSON object, e.g. --param '{"urls":["https://a","https://b"]}' .
            Or k=v with JSON array/object values, e.g. --param urls='["https://a","https://b"]' .
        
        Source modes: dev (load by module/class), prod (in-memory registry)
        
        Execution modes:
            --sync: Blocking in the Flask process until the worker process finishes. Supports --trace / --debug. (default)
            --bk:   Non-blocking: a child OS process runs the node; the parent returns immediately and replays
                    events to this session. Non-interactive (no forms); --trace / --debug are ignored with --bk.
        
        Output modes (--sync only):
            --trace: Real-time log streaming via WebSocket, skips interactive forms.
            --debug: Real-time logs + interactive forms via WebSocket. (default)
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            mode: 'dev' or 'prod'
            args: [module_path|node_id, class_name?, --sync|--bk, --trace|--debug, --state k=v, --param k=v, ...]
        """
        from nos.core.engine import get_shared_engine
        from flask import session
        engine = get_shared_engine()
        user_id = session.get("username", "developer")

        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: module_path/node_id required.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Parse execution mode (--sync or --bk), output mode (--trace, --debug),
        # execution log file: default ON (--log); --nolog skips writing JSON; --save is legacy alias of --log
        background = False  # Default: sync execution (blocking)
        debug_mode = "debug"  # Default: full interactive with real-time output
        write_exec_log = True

        filtered_args = []
        for arg in args:
            if arg == "--sync":
                background = False
            elif arg == "--bk":
                background = True
            elif arg in ("--trace", "trace"):
                debug_mode = "trace"
            elif arg in ("--debug", "debug"):
                debug_mode = "debug"
            elif arg in ("--nolog", "nolog"):
                write_exec_log = False
            elif arg in ("--save", "--log", "save", "log"):
                write_exec_log = True
            else:
                filtered_args.append(arg)

        args = filtered_args

        # --bk is always non-interactive: use trace (no realtime room) regardless of --trace/--debug
        if background:
            if debug_mode in ("trace", "debug"):
                socketio.emit("console_output", ConsoleOutput(
                    type="warning",
                    format="text",
                    message=f"--{debug_mode} ignored in --bk mode. Background executions are non-interactive.",
                    timestamp=time.time(),
                ).model_dump(), to=client_id)
            debug_mode = "trace"
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: module_path/node_id required.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Parse arguments based on mode
        node_id = None
        module_path = None
        class_name = None
        
        if mode == "dev":
            # dev mode: module_path class_name [--state k=v] [--param k=v]
            if len(args) < 2:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message="Dev mode requires: <module_path> <class_name>",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            
            module_path = args[0]
            class_name = args[1]
            # Import path as given (external packages use e.g. my_pkg.node_plugin; optional ext: prefix)
            from ..services.plugin_code_service import _module_path_for_import
            module_path = _module_path_for_import(module_path or "")
            node_id = class_name or "adhoc"  # dev: use class name as-is (e.g. SimpleSumNode)
            params = _parse_params(args[2:])
            
        elif mode == "prod":
            # prod mode: node_id [--state k=v] [--param k=v]
            node_id = args[0]
            params = _parse_params(args[1:])
            
        else:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown execution mode. Use 'dev' or 'prod'.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        # Validate that only known flags are used
        _VALID_NODE_FLAGS = {"param", "state", "output_format", "request"}
        unknown_flags = [f"--{k}" for k in params if k not in _VALID_NODE_FLAGS]
        if unknown_flags:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown flag(s): {', '.join(unknown_flags)}. Valid flags: --param, --state, --output_format, --request",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        # Parse state and input_params
        state = _parse_json_param(params.get("state", "{}"))
        input_params = _parse_json_param(params.get("param", "{}"))
        run_request_extras = None
        if "request" in params:
            ctx = _parse_json_param(params.get("request", "{}"))
            if ctx:
                run_request_extras = {"context": ctx}

        # Parse and validate --output_format when explicitly provided; otherwise node uses its default
        from nos.core.engine.node.node import NODE_OUTPUT_FORMATS
        output_format = params.get("output_format")
        if output_format is not None:
            output_format = str(output_format).lower().strip()
            if output_format not in NODE_OUTPUT_FORMATS:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Invalid --output_format '{output_format}'. Allowed: {', '.join(NODE_OUTPUT_FORMATS)}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
        # Callback to emit result when execution completes
        def on_execution_complete(result: dict):
            """Called when node execution completes (success, cancelled, or error)."""
            success = result.get("success", result.get("status") == "completed")
            cancelled = result.get("cancelled", result.get("status") == "cancelled")
            def _get_node_result_format(wrapper: dict) -> str:
                inner = wrapper.get("result")
                if not isinstance(inner, dict):
                    return "json"
                resp = inner.get("response") or {}
                if not isinstance(resp, dict):
                    return "json"
                out = resp.get("output") or {}
                if not isinstance(out, dict):
                    return "json"
                return str(out.get("output_format") or "json").lower()

            if success:
                result_format = _get_node_result_format(result)
                success_output = ConsoleOutput(
                    type="success",
                    format=result_format,
                    message=f"Node '{result.get('node_id')}' executed successfully",
                    data=result.get("result"),
                    timestamp=time.time(),
                    target="output",
                )
            elif cancelled:
                # Same delivery pattern as success/error: Output panel + full NodeExecutionResult payload.
                result_format = _get_node_result_format(result)
                nid = result.get("node_id") or "node"
                eid = result.get("execution_id") or ""
                cancel_msg = f"Node '{nid}' execution cancelled" + (f" ({eid})" if eid else "")
                success_output = ConsoleOutput(
                    type="warning",
                    format=result_format,
                    message=cancel_msg,
                    data=result.get("result"),
                    timestamp=time.time(),
                    target="output",
                )
            else:
                result_format = _get_node_result_format(result)
                success_output = ConsoleOutput(
                    type="error",
                    format=result_format,
                    message=f"Node '{result.get('node_id')}' execution failed: {result.get('status', 'error')}",
                    data=result.get("result"),
                    timestamp=time.time(),
                    target="output",
                )
            socketio.emit("console_output", success_output.model_dump(), to=client_id)

            saved_path = None
            if write_exec_log:
                saved_path = _snapshot_node_callback_dict(user_id, result)
            if write_exec_log and saved_path:
                socketio.emit("console_output", ConsoleOutput(
                    type="info",
                    format="text",
                    message=f"Execution log written: {saved_path}",
                    timestamp=time.time(),
                ).model_dump(), to=client_id)
        
        # Execute via engine
        try:
            # Sync: realtime to client room. Background: no room (DB / polling only).
            realtime_room = None if background else client_id

            # Build execution mode description
            exec_mode_str = "background" if background else "sync"
            debug_mode_str = debug_mode
            
            # Notify client that execution is starting (commented out for now)
            # start_output = ConsoleOutput(
            #     type="info",
            #     format="progress",
            #     message=f"Executing node ({mode}, {exec_mode_str}, {debug_mode_str}): {node_id}...",
            #     data={
            #         "debug_mode": debug_mode,
            #         "background": background,
            #         "realtime": realtime_room is not None,
            #     },
            #     timestamp=time.time()
            # )
            # socketio.emit("console_output", start_output.model_dump(), to=client_id)
            
            ret = engine.run_node(
                node_id=node_id,
                state=state,
                input_params=input_params,
                mode=mode,
                module_path=module_path,
                class_name=class_name,
                room=realtime_room,
                background=background,
                callback=on_execution_complete,  # Always pass callback
                debug_mode=debug_mode,
                command=command,
                user_id=user_id,
                output_format=output_format,
                run_request_extras=run_request_extras,
            )
            execution_id = ret[0] if isinstance(ret, tuple) else ret

            # Message depends on execution and output mode
            if background:
                if realtime_room is None:
                    bg_info_output = ConsoleOutput(
                        type="info",
                        format="text",
                        message=f"Job started [ID: {execution_id}]. Use 'ps' to check status, 'logs {execution_id}' for logs.",
                        data={"execution_id": execution_id},
                        timestamp=time.time()
                    )
                else:
                    bg_info_output = ConsoleOutput(
                        type="info",
                        format="text",
                        message=f"Background execution started [ID: {execution_id}]. Real-time logs enabled ({debug_mode} mode).",
                        data={"execution_id": execution_id, "realtime": True},
                        timestamp=time.time()
                    )
                socketio.emit("console_output", bg_info_output.model_dump(), to=client_id)
            # For sync execution: callback is called synchronously within run_node,
            # so result is already emitted via on_execution_complete
            
        except ValueError as e:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=str(e),
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        except Exception as e:
            logger.error(f"Failed to start node execution: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Failed to start execution: {e}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Note: Result is emitted via on_execution_complete callback when execution finishes
        # The function returns immediately after starting the background execution
    
    def _coerce_cli_kv_value(v: str):
        """Parse one side of key=value for --state / --param (JSON literals, bool, int, float, str)."""
        import json

        v = (v or "").strip()
        if not v:
            return ""
        if (v.startswith("[") and v.endswith("]")) or (v.startswith("{") and v.endswith("}")):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
        low = v.lower()
        if low in ("true", "false"):
            return low == "true"
        if low == "null":
            return None
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            pass
        return v

    def _parse_json_param(value) -> dict:
        """Parse a JSON object string, or space-separated k=v pairs (values may be JSON arrays/objects)."""
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
            # Try space-separated k=v pairs: "a=1 b=hello urls=[\"https://a\",\"https://b\"]"
            try:
                result = {}
                for pair in value.split():
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        k = k.strip()
                        if not k:
                            continue
                        result[k] = _coerce_cli_kv_value(v)
                if result:
                    return result
            except Exception:
                pass
        return {}
    
    def _execute_workflow_command(socketio, client_id, mode: str, args: list):
        """
        Execute a workflow plugin via the WorkflowEngine.

        Syntax:
            run workflow <dev|prod> <workflow_id|module_path> [class_name] [--sync|--bk] [--trace|--debug] [--log|--nolog] [--state k=v] [--param k=v] [--request JSON|k=v…]

        Execution modes:
            --sync: Blocking in the Flask process until the worker process finishes. Supports --trace / --debug. (default)
            --bk:   Non-blocking: a child OS process runs the workflow; the parent returns immediately and replays
                    events to this session. Non-interactive; --trace / --debug are ignored with --bk.

        Output modes (--sync only):
            --trace: Real-time log streaming via WebSocket, skips interactive forms.
            --debug: Real-time logs + interactive forms via WebSocket. (default)

        Modes: dev (load by module/class), prod (in-memory registry)
        """
        from nos.core.engine import get_shared_engine
        from nos.core.engine.registry import workflow_registry
        from nos.platform.execution_log import EventLog
        from flask import session
        engine = get_shared_engine()
        user_id = session.get("username", "developer")

        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: workflow_id required.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        # Parse execution mode (--sync or --bk), output mode (--trace, --debug), --log / --nolog
        background = False
        debug_mode = "debug"
        write_exec_log = True
        filtered_args = []
        for arg in args:
            if arg == "--sync":
                background = False
            elif arg == "--bk":
                background = True
            elif arg in ("--trace", "trace"):
                debug_mode = "trace"
            elif arg in ("--debug", "debug"):
                debug_mode = "debug"
            elif arg in ("--nolog", "nolog"):
                write_exec_log = False
            elif arg in ("--save", "--log", "save", "log"):
                write_exec_log = True
            else:
                filtered_args.append(arg)
        args = filtered_args

        # --bk is always non-interactive: trace + no realtime room (same as node run)
        if background:
            if debug_mode in ("trace", "debug"):
                socketio.emit("console_output", ConsoleOutput(
                    type="warning",
                    format="text",
                    message=f"--{debug_mode} ignored in --bk mode. Background executions are non-interactive.",
                    timestamp=time.time(),
                ).model_dump(), to=client_id)
            debug_mode = "trace"

        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: workflow_id or (module_path, class_name) required.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        workflow_id = None
        if mode == "dev":
            if len(args) < 2:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message="Dev mode requires: <module_path> <class_name>",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            module_path, class_name = args[0], args[1]
            params = _parse_params(args[2:])
            from nos.core.engine.plugin_loader import try_register_workflow
            from ..services.plugin_code_service import _module_path_for_import
            module_path = _module_path_for_import(module_path or "")
            reg_id = f"direct_{class_name}"
            ok, err = try_register_workflow(module_path, class_name, reg_id)
            if not ok:
                error_output = ConsoleOutput(type="error", format="text", message=f"Failed to load workflow: {err}", timestamp=time.time())
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            workflow_id = reg_id
        else:
            workflow_id = args[0]
            params = _parse_params(args[1:])

        # Build initial_state from --state
        initial_state = _parse_json_param(params.get("state", {}))
        wf_request = None
        if "request" in params:
            wf_request = _parse_json_param(params.get("request", "{}"))
            if not wf_request:
                wf_request = None
        # Parse output_format for result rendering
        output_format = params.get("output_format", "json")
        if output_format is not None:
            output_format = str(output_format).lower().strip()
            from nos.io_adapters.output_formats_schema import OUTPUT_FORMATS
            if output_format not in OUTPUT_FORMATS:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Invalid --output_format '{output_format}'. Allowed: {', '.join(OUTPUT_FORMATS)}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return

        # Load workflow (for dev, already registered above)
        workflow_class = workflow_registry.get_workflow(workflow_id)

        if workflow_class is None:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Workflow '{workflow_id}' not found. Use 'reg workflow' to register.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        workflow = workflow_registry.create_workflow_instance(workflow_id)
        if workflow is None:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Failed to create workflow instance: {workflow_id}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return

        engine = get_shared_engine()

        execution_id = f"workflow_{workflow_id}_{int(time.time())}"
        realtime_room = None if background else client_id

        def on_complete(result):
            # Payload: result + event_logs (same schema as node completion)
            if isinstance(result, dict) and result.get("error"):
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.get("error", "Unknown error"),
                    data={
                        "result": {
                            "status": "error",
                            "error": result.get("error"),
                        },
                        "event_logs": result.get("event_logs", []),
                    },
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            if isinstance(result, dict) and result.get("cancelled"):
                cancel_data = {
                    "result": {"status": "cancelled", "cancelled": True},
                    "event_logs": result.get("event_logs", []),
                }
                out = ConsoleOutput(
                    type="warning",
                    format="json",
                    message="Workflow execution cancelled.",
                    data=cancel_data,
                    timestamp=time.time(),
                    target="output",
                )
                socketio.emit("console_output", out.model_dump(), to=client_id)
                if write_exec_log:
                    _snapshot_workflow_result_dict(
                        user_id,
                        {
                            "execution_id": execution_id,
                            "workflow_id": workflow_id,
                            "status": "cancelled",
                            "result": cancel_data.get("result"),
                            "event_logs": cancel_data.get("event_logs", []),
                        },
                        execution_id,
                    )
                return
            # WorkflowExecutionResult from execute_sync / background callback (dataclass)
            if dataclasses.is_dataclass(result) and getattr(result, "status", None) == "cancelled":
                rd = dataclasses.asdict(result)
                ro = (rd.get("response") or {}).get("output") or {}
                result_format = str(ro.get("output_format") or "json").lower()
                out = ConsoleOutput(
                    type="warning",
                    format=result_format,
                    message=getattr(result, "message", None) or "Workflow execution cancelled.",
                    data=rd,
                    timestamp=time.time(),
                    target="output",
                )
                socketio.emit("console_output", out.model_dump(), to=client_id)
                if write_exec_log:
                    _snapshot_workflow_result_dict(user_id, rd, execution_id)
                return
            # Success: same envelope as node — full execution result dict (includes event_logs)
            result_dict = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
            ro = (
                (result_dict.get("response") or {}).get("output")
                if isinstance(result_dict, dict)
                else {}
            ) or {}
            result_format = str(ro.get("output_format") or "json").lower()
            success_output = ConsoleOutput(
                type="success",
                format=result_format,
                message="Workflow completed.",
                data=result_dict,
                timestamp=time.time(),
                target="output",
            )
            socketio.emit("console_output", success_output.model_dump(), to=client_id)
            if write_exec_log and isinstance(result_dict, dict):
                sp = _snapshot_workflow_result_dict(user_id, result_dict, execution_id)
                if sp:
                    socketio.emit("console_output", ConsoleOutput(
                        type="info",
                        format="text",
                        message=f"Execution log written: {sp}",
                        timestamp=time.time(),
                    ).model_dump(), to=client_id)

        # Notify client that execution is starting (commented out for now)
        # start_output = ConsoleOutput(
        #     type="info",
        #     format="progress",
        #     message=f"Executing workflow ({mode}, {'background' if background else 'sync'}, {debug_mode}): {workflow_id}...",
        #     data={"debug_mode": debug_mode, "background": background, "realtime": realtime_room is not None},
        #     timestamp=time.time()
        # )
        # socketio.emit("console_output", start_output.model_dump(), to=client_id)

        channel = None
        if realtime_room:
            channel = EventLog(
                execution_id=execution_id,
                workflow_id=workflow_id,
                room=realtime_room,
                emit_realtime=True,
                persist_to_db=True,
                user_id=user_id,
            )

        try:
            if background:
                # If workflow needs initial-state form, collect it in this request first; then start background and send message.
                needs_form = channel is not None and getattr(workflow, "state_schema", None) is not None
                if needs_form:
                    from nos.io_adapters.input_form_mapping import create_form_request_payload
                    workflow.prepare(initial_state)
                    state_vals = getattr(workflow, "state", None)
                    state_vals = state_vals.model_dump() if hasattr(state_vals, "model_dump") else (state_vals if isinstance(state_vals, dict) else {})
                    form_payload = create_form_request_payload(
                        state_schema=workflow.state_schema,
                        params_schema=None,
                        state_values=state_vals,
                        params_values={},
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        title=f"Configure initial state: {workflow.name}",
                    )
                    has_state_fields = (form_payload or {}).get("state", {}).get("fields", [])
                else:
                    has_state_fields = []

                if background and needs_form and has_state_fields:
                    channel.log("info", "📝 Waiting for initial state input...")
                    form_response = channel.request_and_wait(
                        event_type="form_input",
                        data=form_payload,
                        timeout=300.0,
                    )
                    if form_response and form_response.get("cancelled"):
                        socketio.emit("console_output", ConsoleOutput(
                            type="info", format="text", message="Workflow cancelled by user.", timestamp=time.time()
                        ).model_dump(), to=client_id)
                        return
                    if not form_response or not form_response.get("state"):
                        socketio.emit("console_output", ConsoleOutput(
                            type="warning", format="text", message="No initial state provided. Workflow not started.", timestamp=time.time()
                        ).model_dump(), to=client_id)
                        return
                    try:
                        validated = workflow.state_schema(**form_response["state"])
                        initial_state = validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)
                    except Exception as e:
                        socketio.emit("console_output", ConsoleOutput(
                            type="error", format="text", message=f"Form validation failed: {e}", timestamp=time.time()
                        ).model_dump(), to=client_id)
                        return
                    channel.log("info", "✓ Form submitted. Starting execution in background...")

                exec_id = engine.execute_background(
                    workflow=workflow,
                    initial_state=initial_state,
                    exec_log=channel,
                    callback=on_complete,
                    debug_mode=debug_mode,
                    output_format=output_format,
                    request=wf_request,
                )
                msg = "Execution running in background. See execution_logs for real-time output."
                socketio.emit("console_output", ConsoleOutput(type="info", format="text", message=msg, data={"execution_id": exec_id}, timestamp=time.time()).model_dump(), to=client_id)
            else:
                result = engine.execute_sync(
                    workflow=workflow,
                    initial_state=initial_state,
                    exec_log=channel,
                    debug_mode=debug_mode,
                    output_format=output_format,
                    request=wf_request,
                )
                on_complete(result)
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            error_output = ConsoleOutput(type="error", format="text", message=str(e), timestamp=time.time())
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_create_command(socketio, client_id, action: str, args: list):
        """
        Handle create commands (create_node, create_workflow).
        
        Creates a new plugin file with template code.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Create action type (create_node, create_workflow)
            args: Command arguments [id, --class ClassName, --path module.path, --name DisplayName]
        """
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: create <node|workflow> <id> --class ClassName --path <path> [--name DisplayName]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Parse arguments
        plugin_id = args[0]
        params = _parse_params(args[1:])
        
        # --class is REQUIRED for create
        class_name = params.get("class")
        if not class_name or not str(class_name).strip():
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing --class argument (required). Usage: create <node|workflow> <id> --class ClassName --path <path> [--name DisplayName]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        class_name = str(class_name).strip()
        name = params.get("name", plugin_id.replace("_", " ").title())
        
        try:
            if action == "create_node":
                _create_node_plugin(socketio, client_id, plugin_id, class_name, params.get("path"), name)
            elif action == "create_workflow":
                _create_workflow_plugin(socketio, client_id, plugin_id, class_name, params.get("path"), name)
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown create command: {action}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"Create command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _id_to_class_name(plugin_id: str) -> str:
        """Convert snake_case ID to PascalCase class name."""
        return "".join(word.capitalize() for word in plugin_id.split("_"))
    
    def _create_node_plugin(socketio, client_id, node_id: str, class_name: str, module_path: str = None, name: str = None):
        """
        Create a new node plugin file.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            node_id: Node identifier
            class_name: Python class name
            module_path: Full module path (REQUIRED)
            name: Display name
        """
        from ..services.plugin_code_service import create_node
        
        # module_path is required - no default folder
        if not module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing --path argument. Usage: create node <id> --path <path> (full or relative: nodes.<folder>.<module>)",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Creating node: {node_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Create the node
        result = create_node(
            node_id=node_id,
            class_name=class_name,
            module_path=module_path,
            name=name
        )
        
        if result.success:
            # Success - send result with code content for editor
            success_output = ConsoleOutput(
                type="success",
                format="json",
                message=result.message,
                data={
                    "action": "create_node",
                    "node_id": node_id,
                    "class_name": class_name,
                    "module_path": module_path,
                    "file_path": result.file_path,
                    "content": result.content,
                    "registration_status": result.registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _create_workflow_plugin(socketio, client_id, workflow_id: str, class_name: str, module_path: str = None, name: str = None):
        """
        Create a new workflow plugin file.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            workflow_id: Workflow identifier
            class_name: Python class name
            module_path: Full module path (REQUIRED)
            name: Display name
        """
        from ..services.plugin_code_service import create_workflow
        
        # module_path is required - no default folder
        if not module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing --path argument. Usage: create workflow <id> --path <path> (full or relative: workflows.<folder>.<module>)",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Creating workflow: {workflow_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Create the workflow
        result = create_workflow(
            workflow_id=workflow_id,
            class_name=class_name,
            module_path=module_path,
            name=name
        )
        
        if result.success:
            # Success - send result with code content for editor
            success_output = ConsoleOutput(
                type="success",
                format="json",
                message=result.message,
                data={
                    "action": "create_workflow",
                    "workflow_id": workflow_id,
                    "class_name": class_name,
                    "module_path": module_path,
                    "file_path": result.file_path,
                    "content": result.content,
                    "registration_status": result.registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _handle_open_command(socketio, client_id, action: str, args: list):
        """
        Handle open commands (open_node, open_workflow).
        
        Reads a plugin file and loads its content into the code editor.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Open action type (open_node, open_workflow)
            args: Command arguments [node_id|module_path]
        """
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID or module_path required. Usage: open <node|workflow> <id|module_path>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        identifier = args[0]
        
        # Determine if it's a module_path or plugin_id
        # Module path: contains ".", e.g. nos.plugins..., nodes..., workflows..., or dev_.my_node
        is_module_path = "." in identifier
        
        try:
            if action == "open_node":
                _open_node_plugin(socketio, client_id, identifier, is_module_path)
            elif action == "open_workflow":
                _open_workflow_plugin(socketio, client_id, identifier, is_module_path)
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown open command: {action}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"Open command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _open_node_plugin(socketio, client_id, identifier: str, is_module_path: bool):
        """
        Open a node plugin file and load it into the code editor.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            identifier: Full module path (required)
            is_module_path: True if identifier is a module path
        """
        from ..services.plugin_code_service import read_node_code
        
        # module_path is required - no default folder
        if not is_module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Module path required. Usage: open node <path> (full: nos.plugins.nodes.<folder>.<module> or relative: nodes.<folder>.<module>)",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Opening node: {identifier}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Read the node file
        result = read_node_code(module_path=identifier)
        node_id = identifier.split(".")[-1]  # Extract filename as node_id
        
        registration_status = None
        try:
            from nos.platform.services.sqlalchemy.node import repository as node_repo
            node = node_repo.get_by_id(node_id)
            if node:
                registration_status = getattr(node, "registration_status", None)
        except Exception:
            pass
        
        if result.success:
            # Success - send result with code content for editor
            success_output = ConsoleOutput(
                type="success",
                format="json",
                message=result.message,
                data={
                    "action": "open_node",
                    "node_id": node_id,
                    "module_path": identifier if is_module_path else None,
                    "file_path": result.file_path,
                    "content": result.content,
                    "registration_status": registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _open_workflow_plugin(socketio, client_id, identifier: str, is_module_path: bool):
        """
        Open a workflow plugin file and load it into the code editor.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            identifier: Full module path (required)
            is_module_path: True if identifier is a module path
        """
        from ..services.plugin_code_service import read_workflow_code
        
        # module_path is required - no default folder
        if not is_module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Module path required. Usage: open workflow <path> (full: nos.plugins.workflows.<folder>.<module> or relative: workflows.<folder>.<module>)",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Opening workflow: {identifier}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Read the workflow file
        result = read_workflow_code(module_path=identifier)
        workflow_id = identifier.split(".")[-1]  # Extract filename as workflow_id
        
        registration_status = None
        try:
            from ..services.sqlalchemy.workflow import repository as workflow_repo
            wf = workflow_repo.get_by_id(workflow_id)
            if wf:
                registration_status = getattr(wf, "registration_status", None)
        except Exception:
            pass
        
        if result.success:
            # Success - send result with code content for editor
            success_output = ConsoleOutput(
                type="success",
                format="json",
                message=result.message,
                data={
                    "action": "open_workflow",
                    "workflow_id": workflow_id,
                    "module_path": identifier if is_module_path else None,
                    "file_path": result.file_path,
                    "content": result.content,
                    "registration_status": registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _handle_save_command(socketio, client_id, request_data: dict):
        """
        Handle save command - write plugin code to file only (no registration).
        
        Saves the file to disk. Run via 'run node dev ...' or 'run workflow dev ...'.
        To register, use 'reg node <id> ...' or 'reg workflow <id> ...' separately.
        
        Expects request_data.save_payload with: content, module_path, node_id|workflow_id, class_name
        plugin_type: "node" or "workflow"
        """
        from ..services.plugin_code_service import save_node_code, save_workflow_code
        
        payload = request_data.get("save_payload") or {}
        content = payload.get("content", "")
        module_path = (payload.get("module_path") or "").strip()
        plugin_id = (payload.get("node_id") or payload.get("workflow_id") or "").strip()
        class_name = (payload.get("class_name") or "").strip()
        plugin_type = payload.get("plugin_type", "node")
        
        if not content or not module_path or not plugin_id or not class_name:
            error_output = ConsoleOutput(
                type="error",
                format="json",
                message="Missing required fields: content, module_path, node_id/workflow_id, class_name",
                data={"action": "save", "success": False},
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        try:
            if plugin_type == "workflow":
                result = save_workflow_code(
                    workflow_id=plugin_id,
                    class_name=class_name,
                    module_path=module_path,
                    content=content,
                )
            else:
                result = save_node_code(
                    node_id=plugin_id,
                    class_name=class_name,
                    module_path=module_path,
                    content=content,
                )
            if result.success:
                success_output = ConsoleOutput(
                    type="success",
                    format="json",
                    message=result.message,
                    data={
                        "action": "save",
                        "success": True,
                        "file_path": result.file_path,
                    },
                    timestamp=time.time()
                )
                socketio.emit("console_output", success_output.model_dump(), to=client_id)
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="json",
                    message=result.message,
                    data={"action": "save", "success": False},
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
        except Exception as e:
            logger.error(f"Save command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="json",
                message=f"Save failed: {str(e)}",
                data={"action": "save", "success": False},
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_reg_command(socketio, client_id, action: str, args: list):
        """
        Handle register commands (reg_node, reg_workflow).
        
        Registers a plugin (imports module, validates class, creates DB record).
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Register action type (reg_node, reg_workflow)
            args: Command arguments [id, class_name?, module_path?, name?]
        """
        if len(args) < 3:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing arguments. Usage: reg <node|workflow> <id> <class_name> <module_path> [name]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        class_name = args[1]
        module_path = args[2]
        name = args[3] if len(args) > 3 else None
        
        try:
            if action == "reg_node":
                _register_node_plugin(socketio, client_id, plugin_id, class_name, module_path, name)
            elif action == "reg_workflow":
                _register_workflow_plugin(socketio, client_id, plugin_id, class_name, module_path, name)
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown register command: {action}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"Register command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _register_node_plugin(socketio, client_id, node_id: str, class_name: str = None, module_path: str = None, name: str = None):
        """
        Register a node plugin.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            node_id: Node identifier
            class_name: Python class name (auto-generated if not provided)
            module_path: Full module path (REQUIRED)
            name: Display name (auto-generated if not provided)
        """
        from ..services.plugin_code_service import register_node
        
        # module_path is required - no default folder
        if not module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing module_path. Usage: reg node <id> <class_name> <module_path> [name]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Generate defaults for class_name and name if not provided
        if not class_name:
            class_name = _id_to_class_name(node_id)
        if not name:
            name = node_id.replace("_", " ").title()
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Registering node: {node_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Register the node
        result = register_node(node_id, class_name, module_path, name)
        
        if result.success:
            success_output = ConsoleOutput(
                type="success",
                format="text",
                message=result.message,
                data={
                    "action": "reg_node",
                    "node_id": node_id,
                    "registration_status": result.registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _register_workflow_plugin(socketio, client_id, workflow_id: str, class_name: str = None, module_path: str = None, name: str = None):
        """
        Register a workflow plugin.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            workflow_id: Workflow identifier
            class_name: Python class name (auto-generated if not provided)
            module_path: Full module path (REQUIRED)
            name: Display name (auto-generated if not provided)
        """
        from ..services.plugin_code_service import register_workflow
        
        # module_path is required - no default folder
        if not module_path:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing module_path. Usage: reg workflow <id> <class_name> <module_path> [name]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Generate defaults for class_name and name if not provided
        if not class_name:
            class_name = _id_to_class_name(workflow_id)
        if not name:
            name = workflow_id.replace("_", " ").title()
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Registering workflow: {workflow_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        # Register the workflow
        result = register_workflow(workflow_id, class_name, module_path, name)
        
        if result.success:
            success_output = ConsoleOutput(
                type="success",
                format="text",
                message=result.message,
                data={
                    "action": "reg_workflow",
                    "workflow_id": workflow_id,
                    "registration_status": result.registration_status,
                },
                timestamp=time.time()
            )
        else:
            success_output = ConsoleOutput(
                type="error",
                format="text",
                message=result.message,
                timestamp=time.time()
            )
        
        socketio.emit("console_output", success_output.model_dump(), to=client_id)
    
    def _handle_dir_command(socketio, client_id):
        """
        Handle dir command - show plugins directory structure.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
        """
        import os
        
        def build_tree(path: str, prefix: str = "", is_last: bool = True) -> list:
            """
            Build tree structure for a directory.
            
            Args:
                path: Directory path
                prefix: Current line prefix for indentation
                is_last: Whether this is the last item in parent
                
            Returns:
                List of tree lines
            """
            lines = []
            basename = os.path.basename(path)
            
            # Determine connector
            connector = "└── " if is_last else "├── "
            
            if os.path.isdir(path):
                lines.append(f"{prefix}{connector}📁 {basename}/")
                
                # Get children (directories first, then files)
                try:
                    children = sorted(os.listdir(path))
                    # Filter out __pycache__ and .pyc files
                    children = [c for c in children if c != "__pycache__" and not c.endswith(".pyc")]
                    # Sort: directories first, then files
                    dirs = [c for c in children if os.path.isdir(os.path.join(path, c))]
                    files = [c for c in children if os.path.isfile(os.path.join(path, c))]
                    children = dirs + files
                except PermissionError:
                    children = []
                
                # Calculate new prefix
                new_prefix = prefix + ("    " if is_last else "│   ")
                
                for i, child in enumerate(children):
                    child_path = os.path.join(path, child)
                    child_is_last = (i == len(children) - 1)
                    lines.extend(build_tree(child_path, new_prefix, child_is_last))
            else:
                # File
                icon = "🐍" if basename.endswith(".py") else "📄"
                lines.append(f"{prefix}{connector}{icon} {basename}")
            
            return lines
        
        try:
            # Get plugins directory path
            from ..services.plugin_code_service import _get_nos_pkg_dir
            nos_dir = _get_nos_pkg_dir()
            plugins_dir = os.path.join(nos_dir, "plugins")
            
            if not os.path.exists(plugins_dir):
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Plugins directory not found: {plugins_dir}",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            
            # Build tree
            lines = ["📁 plugins/"]
            
            # Get root children
            children = sorted(os.listdir(plugins_dir))
            children = [c for c in children if c != "__pycache__" and not c.endswith(".pyc")]
            dirs = [c for c in children if os.path.isdir(os.path.join(plugins_dir, c))]
            files = [c for c in children if os.path.isfile(os.path.join(plugins_dir, c))]
            children = dirs + files
            
            for i, child in enumerate(children):
                child_path = os.path.join(plugins_dir, child)
                child_is_last = (i == len(children) - 1)
                lines.extend(build_tree(child_path, "", child_is_last))
            
            tree_output = "\n".join(lines)
            
            output = ConsoleOutput(
                type="info",
                format="tree",
                message=tree_output,
                data={
                    "action": "dir",
                    "path": plugins_dir,
                    "item_count": len(children)
                },
                timestamp=time.time()
            )
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Dir command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_stop_command(socketio, client_id, args: list):
        """
        Handle stop command - stop a running node or workflow execution.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            args: [execution_id]
        """
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Usage: stop <execution_id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        execution_id = args[0]
        
        from nos.core.engine import get_shared_engine
        engine = get_shared_engine()
        
        # Try to stop the execution
        result = engine.stop_execution(execution_id)
        
        if result.get("stopped"):
            # No console_output on success: Ctrl+C already shows client-side ack; typed `stop` is
            # confirmed by execution_log (node_end / workflow_execution_result) and on_execution_complete
            # with the same Output-panel pattern as success/error.
            logger.info(
                "Stop acknowledged for %s %s (client %s)",
                result.get("execution_type", "execution"),
                execution_id,
                client_id,
            )
            return

        error_msg = result.get("error", f"Failed to stop execution: {execution_id}")
        output = ConsoleOutput(
            type="error",
            format="text",
            message=error_msg,
            data=None,
            timestamp=time.time()
        )
        socketio.emit("console_output", output.model_dump(), to=client_id)
    
    def _handle_ps_command(socketio, client_id):
        """
        Handle ps command - list all active executions.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
        """
        from nos.core.engine import get_shared_engine
        engine = get_shared_engine()
        
        # Get list of executions
        executions = engine.list_executions()
        
        if not executions:
            output = ConsoleOutput(
                type="info",
                format="text",
                message="No active executions",
                timestamp=time.time()
            )
        else:
            # Format as table
            lines = ["Active Executions:", ""]
            lines.append(f"{'ID':<40} {'Type':<10} {'Node/Workflow':<20} {'Status':<10}")
            lines.append("-" * 80)
            
            for exec_info in executions:
                exec_id = exec_info.get("execution_id", "")[:38]
                exec_type = exec_info.get("execution_type", "")
                name = exec_info.get("node_id") or exec_info.get("workflow_id") or ""
                status = "cancelled" if exec_info.get("cancelled") else ("running" if exec_info.get("running") else "done")
                lines.append(f"{exec_id:<40} {exec_type:<10} {name:<20} {status:<10}")
            
            output = ConsoleOutput(
                type="info",
                format="text",
                message="\n".join(lines),
                data={"executions": executions, "count": len(executions)},
                timestamp=time.time()
            )
        
        socketio.emit("console_output", output.model_dump(), to=client_id)
    
    def _handle_logs_command(socketio, client_id, args: list):
        """
        Handle logs command - retrieve execution logs from DB.
        
        Usage:
            logs <execution_id>       - Show logs for a specific execution
            logs                      - Show recent executions summary
            logs --limit N            - Show last N executions
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            args: [execution_id?] [--limit N]
        """
        from ..services.sqlalchemy.execution_log import repository as log_repo
        from datetime import datetime
        
        # Parse arguments
        execution_id = None
        limit = 50
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                if arg == "--limit" and i + 1 < len(args):
                    try:
                        limit = int(args[i + 1])
                    except ValueError:
                        limit = 50
                    i += 1
            else:
                execution_id = arg
            i += 1
        
        try:
            if execution_id:
                # Show logs for specific execution
                logs = log_repo.get_by_execution_id(execution_id)
                
                if not logs:
                    output = ConsoleOutput(
                        type="warning",
                        format="text",
                        message=f"No logs found for execution: {execution_id}",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", output.model_dump(), to=client_id)
                    return
                
                # Format logs
                lines = [f"Execution Logs: {execution_id}", ""]
                lines.append(f"{'Time':<24} {'Level':<8} {'Event':<25} {'Message'}")
                lines.append("-" * 100)
                
                for log in logs:
                    ts = datetime.fromtimestamp(log.start_timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    level = (log.level or "info").upper()[:7]
                    event = (log.event or "")[:24]
                    message = (log.message or "")[:50]
                    lines.append(f"{ts:<24} {level:<8} {event:<25} {message}")
                
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message="\n".join(lines),
                    data={
                        "execution_id": execution_id,
                        "logs": [l.to_dict() for l in logs],
                        "count": len(logs)
                    },
                    timestamp=time.time()
                )
            else:
                # Show recent executions summary
                executions = log_repo.get_unique_executions(limit=limit)
                
                if not executions:
                    output = ConsoleOutput(
                        type="info",
                        format="text",
                        message="No execution logs found in database",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", output.model_dump(), to=client_id)
                    return
                
                # Format execution summary
                lines = ["Recent Executions:", ""]
                lines.append(f"{'Execution ID':<50} {'Type':<10} {'Plugin':<20} {'Events'}")
                lines.append("-" * 90)
                
                for ex in executions:
                    exec_id = (ex.get("execution_id") or "")[:48]
                    exec_type = (ex.get("execution_type") or "")[:9]
                    plugin = (ex.get("plugin_id") or "")[:19]
                    count = ex.get("event_count", 0)
                    lines.append(f"{exec_id:<50} {exec_type:<10} {plugin:<20} {count}")
                
                lines.append("")
                lines.append("Use 'logs <execution_id>' to view detailed logs for an execution")
                
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message="\n".join(lines),
                    data={"executions": executions, "count": len(executions)},
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Logs command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error retrieving logs: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    # =========================================================================
    # Plugin Management Command Handlers
    # =========================================================================
    
    def _handle_unreg_command(socketio, client_id, action: str, args: list):
        """
        Handle unreg commands (unreg_node, unreg_workflow).
        
        Unregisters a plugin (deletes DB record and removes from registry).
        Cannot unregister published plugins.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Unreg action type (unreg_node, unreg_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import unregister_plugin
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: unreg <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "unreg_node" else "workflow"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Unregistering {plugin_type}: {plugin_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = unregister_plugin(plugin_type, plugin_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Unreg command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_pub_command(socketio, client_id, action: str, args: list):
        """
        Handle pub commands (pub_node, pub_workflow).
        
        Publishes a plugin (changes status from OK to Pub).
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Pub action type (pub_node, pub_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import publish_plugin
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: pub <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "pub_node" else "workflow"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Publishing {plugin_type}: {plugin_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = publish_plugin(plugin_type, plugin_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Pub command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_unpub_command(socketio, client_id, action: str, args: list):
        """
        Handle unpub commands (unpub_node, unpub_workflow).
        
        Unpublishes a plugin (changes status from Pub to OK).
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Unpub action type (unpub_node, unpub_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import unpublish_plugin
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: unpub <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "unpub_node" else "workflow"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Unpublishing {plugin_type}: {plugin_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = unpublish_plugin(plugin_type, plugin_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Unpub command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_update_command(socketio, client_id, action: str, args: list):
        """
        Handle update commands (update_node, update_workflow).
        
        Updates plugin fields in database.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Update action type (update_node, update_workflow)
            args: Command arguments [id, --field value, ...]
        """
        from ..services.plugin_management_service import update_plugin
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: update <node|workflow> <id> [--name value] [--class value] [--path value]",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "update_node" else "workflow"
        
        # Parse update fields
        params = _parse_params(args[1:])
        
        # Map params to field names
        fields = {}
        if "name" in params:
            fields["name"] = params["name"]
        if "class" in params:
            fields["class_name"] = params["class"]
        if "path" in params:
            fields["module_path"] = params["path"]
        
        if not fields:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="No fields to update. Use: --name, --class, or --path",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Updating {plugin_type}: {plugin_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = update_plugin(plugin_type, plugin_id, fields)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Update command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_info_command(socketio, client_id, action: str, args: list):
        """
        Handle info commands (info_node, info_workflow).
        
        Shows detailed plugin information.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Info action type (info_node, info_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import get_plugin_info
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: info <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "info_node" else "workflow"
        
        try:
            result = get_plugin_info(plugin_type, plugin_id)
            
            if result.success:
                # Format output nicely
                data = result.data
                lines = [f"Plugin Info: {plugin_type.upper()} '{plugin_id}'", ""]
                
                lines.append(f"  In Database:    {'Yes' if data.get('in_database') else 'No'}")
                lines.append(f"  In Registry:    {'Yes' if data.get('in_registry') else 'No'}")
                lines.append(f"  File Exists:    {'Yes' if data.get('file_exists') else 'No'}")
                
                if data.get("file_path"):
                    lines.append(f"  File Path:      {data['file_path']}")
                
                if data.get("db_record"):
                    db = data["db_record"]
                    lines.append("")
                    lines.append("  Database Record:")
                    lines.append(f"    Name:         {db.get('name', 'N/A')}")
                    lines.append(f"    Class:        {db.get('class_name', 'N/A')}")
                    lines.append(f"    Module Path:  {db.get('module_path', 'N/A')}")
                    lines.append(f"    Status:       {db.get('registration_status', 'N/A')}")
                    lines.append(f"    Created At:   {db.get('created_at', 'N/A')}")
                    lines.append(f"    Updated At:   {db.get('updated_at', 'N/A')}")
                
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message="\n".join(lines),
                    data=data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Info command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_reload_command(socketio, client_id, action: str, args: list):
        """
        Handle reload commands (reload_node, reload_workflow).
        
        Reloads a plugin (unregisters and re-registers from source).
        Useful after modifying plugin code.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Reload action type (reload_node, reload_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import reload_plugin
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: reload <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "reload_node" else "workflow"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Reloading {plugin_type}: {plugin_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = reload_plugin(plugin_type, plugin_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Reload command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_rm_command(socketio, client_id, action: str, args: list):
        """
        Handle rm commands (rm_node, rm_workflow).
        
        Deletes a plugin file and DB record permanently.
        Cannot delete published plugins.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Rm action type (rm_node, rm_workflow)
            args: Command arguments [id]
        """
        from ..services.plugin_management_service import delete_plugin_file
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing argument: ID required. Usage: rm <node|workflow> <id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        plugin_id = args[0]
        plugin_type = "node" if action == "rm_node" else "workflow"
        
        # Notify start with warning
        start_output = ConsoleOutput(
            type="warning",
            format="progress",
            message=f"Deleting {plugin_type}: {plugin_id} (this is permanent!)...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = delete_plugin_file(plugin_type, plugin_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Rm command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_mv_command(socketio, client_id, action: str, args: list):
        """
        Handle mv commands (mv_node, mv_workflow).
        
        Renames a plugin (file + DB record).
        Cannot rename published plugins.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Mv action type (mv_node, mv_workflow)
            args: Command arguments [old_id, new_id]
        """
        from ..services.plugin_management_service import rename_plugin
        
        if len(args) < 2:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing arguments. Usage: mv <node|workflow> <old_id> <new_id>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        old_id = args[0]
        new_id = args[1]
        plugin_type = "node" if action == "mv_node" else "workflow"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Renaming {plugin_type}: {old_id} -> {new_id}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = rename_plugin(plugin_type, old_id, new_id)
            
            if result.success:
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message=result.message,
                    data=result.data,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=result.message,
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Mv command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    # =========================================================================
    # SQL Command Handlers
    # =========================================================================
    
    def _handle_export_result(socketio, client_id, columns: list, rows: list, output_format: str, execution_time_ms: float):
        """
        Handle exporting query results to a file.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            columns: Column names
            rows: Query result rows
            output_format: Export format (csv, excel, json)
            execution_time_ms: Query execution time
        """
        from ..services.export_query_service import export_query_service
        
        # Export the results
        export_result = export_query_service.export_query_result(
            columns=columns,
            rows=rows,
            format=output_format
        )
        
        if export_result.success:
            # Return download format for rendering the link
            output = ConsoleOutput(
                type="success",
                format="download",
                message=f"Exported {len(rows)} rows to {output_format.upper()} ({execution_time_ms}ms)",
                data={
                    "url": export_result.download_url,
                    "filename": export_result.filename,
                    "format": export_result.format,
                    "size": export_result.file_size,
                    "row_count": len(rows)
                },
                timestamp=time.time()
            )
        else:
            output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Export failed: {export_result.error}",
                timestamp=time.time()
            )
        
        socketio.emit("console_output", output.model_dump(), to=client_id)
    
    def _extract_sql_from_raw(raw: str, prefix: str):
        """
        Extract SQL from raw command string, preserving quotes.
        shlex.split() strips quotes, so we extract from raw instead.
        
        Returns:
            (sql_string, opts) where opts = {limit, output_format, allow_write}
        """
        raw = raw.strip()
        m = re.match(r"^\s*" + re.escape(prefix) + r"\s+", raw, re.I)
        if not m:
            return "", {}
        rest = raw[m.end() :].strip()
        opts = {}
        while True:
            m = re.search(r"\s+--limit\s+(\d+)\s*$", rest, re.I)
            if m:
                opts["limit"] = int(m.group(1))
                rest = rest[: m.start()].rstrip()
                continue
            m = re.search(r"\s+--output_format\s+(csv|excel|json)\s*$", rest, re.I)
            if m:
                opts["output_format"] = m.group(1).lower()
                rest = rest[: m.start()].rstrip()
                continue
            if prefix.lower() == "sql":
                m = re.search(r"\s+--write\s*$", rest, re.I)
                if m:
                    opts["allow_write"] = True
                    rest = rest[: m.start()].rstrip()
                    continue
            break
        return rest.strip(), opts
    
    def _handle_sql_command(socketio, client_id, args: list, raw_command: str = ""):
        """
        Handle sql command - execute raw SQL queries.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            args: Command arguments (SQL query parts + optional --write, --output_format)
            raw_command: Raw command string - when present, used to preserve quotes in SQL
        """
        from ..services.sql_service import sql_service
        
        if raw_command:
            query, opts = _extract_sql_from_raw(raw_command, "sql")
            allow_write = opts.get("allow_write", False)
            output_format = opts.get("output_format")
        else:
            if not args:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message="Missing SQL query. Usage: sql <query> [--write] [--output_format csv|excel|json]",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            
            allow_write = False
            output_format = None
            filtered_args = []
            i = 0
            while i < len(args):
                arg_lower = args[i].lower()
                if arg_lower == "--write":
                    allow_write = True
                    i += 1
                elif arg_lower == "--output_format" and i + 1 < len(args):
                    output_format = args[i + 1].lower()
                    if output_format not in ['csv', 'excel', 'json']:
                        error_output = ConsoleOutput(
                            type="error",
                            format="text",
                            message=f"Invalid output format: {output_format}. Supported: csv, excel, json",
                            timestamp=time.time()
                        )
                        socketio.emit("console_output", error_output.model_dump(), to=client_id)
                        return
                    i += 2
                else:
                    filtered_args.append(args[i])
                    i += 1
            
            query = " ".join(filtered_args)
        
        if not query.strip():
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Empty SQL query",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Executing SQL ({sql_service.detect_query_type(query)})...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = sql_service.execute(query, allow_write=allow_write)
            
            if result.success:
                if result.rows:
                    # Check if export is requested
                    if output_format:
                        _handle_export_result(
                            socketio, client_id, 
                            result.columns, result.rows, 
                            output_format, result.execution_time_ms
                        )
                        return
                    
                    # Check if it's a SELECT query - use table format
                    is_select = result.query_type and result.query_type.upper() == "SELECT"
                    
                    output = ConsoleOutput(
                        type="success",
                        format="table" if is_select else "json",
                        message=f"Query executed ({result.row_count} rows, {result.execution_time_ms}ms)",
                        data={
                            "query_type": result.query_type,
                            "columns": result.columns,
                            "rows": result.rows,
                            "row_count": result.row_count,
                            "execution_time_ms": result.execution_time_ms
                        },
                        timestamp=time.time()
                    )
                elif result.affected_rows > 0:
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message=f"Query executed: {result.affected_rows} row(s) affected ({result.execution_time_ms}ms)",
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message=f"Query executed successfully ({result.execution_time_ms}ms)",
                        timestamp=time.time()
                    )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"SQL Error: {result.error}",
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"SQL command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_query_command(socketio, client_id, args: list, raw_command: str = ""):
        """
        Handle query command - execute SELECT queries only with table output.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            args: Command arguments (SELECT query parts + optional --limit N, --output_format)
            raw_command: Raw command string - when present, used to preserve quotes in SQL
        """
        from ..services.sql_service import sql_service
        
        if raw_command:
            query, opts = _extract_sql_from_raw(raw_command, "query")
            limit = opts.get("limit", 100)
            output_format = opts.get("output_format")
        else:
            if not args:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message="Missing SELECT query. Usage: query SELECT ... [--limit N] [--output_format csv|excel|json]",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                return
            
            limit = 100
            output_format = None
            filtered_args = []
            i = 0
            while i < len(args):
                arg_lower = args[i].lower()
                if arg_lower == "--limit" and i + 1 < len(args):
                    try:
                        limit = int(args[i + 1])
                        i += 2
                        continue
                    except ValueError:
                        pass
                elif arg_lower == "--output_format" and i + 1 < len(args):
                    output_format = args[i + 1].lower()
                    if output_format not in ['csv', 'excel', 'json']:
                        error_output = ConsoleOutput(
                            type="error",
                            format="text",
                            message=f"Invalid output format: {output_format}. Supported: csv, excel, json",
                            timestamp=time.time()
                        )
                        socketio.emit("console_output", error_output.model_dump(), to=client_id)
                        return
                    i += 2
                    continue
                filtered_args.append(args[i])
                i += 1
            
            query = " ".join(filtered_args).strip()
        
        if not query:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Empty query",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Validate that query starts with SELECT
        first_token = query.split()[0].upper() if query.split() else ""
        if first_token != "SELECT":
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"query command only supports SELECT statements. Got: {first_token}. Use 'sql' for other queries.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        # Add LIMIT if not already present
        query_upper = query.upper()
        if "LIMIT" not in query_upper:
            query = f"{query} LIMIT {limit}"
        
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Executing query (limit: {limit})...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            result = sql_service.execute(query, allow_write=False)
            
            if result.success:
                if result.rows:
                    # Check if export is requested
                    if output_format:
                        _handle_export_result(
                            socketio, client_id, 
                            result.columns, result.rows, 
                            output_format, result.execution_time_ms
                        )
                        return
                    
                    # Format as interactive table
                    output = ConsoleOutput(
                        type="success",
                        format="table",
                        message=f"Query completed: {result.row_count} row(s) ({result.execution_time_ms}ms)",
                        data={
                            "columns": result.columns,
                            "rows": result.rows,
                            "row_count": result.row_count,
                            "total_count": result.row_count,
                            "limit": limit,
                            "page": 1,
                            "page_size": limit,
                            "execution_time_ms": result.execution_time_ms
                        },
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="info",
                        format="text",
                        message=f"No rows returned ({result.execution_time_ms}ms)",
                        timestamp=time.time()
                    )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Query Error: {result.error}",
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Query command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_tables_command(socketio, client_id):
        """
        Handle tables command - list all database tables.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
        """
        from ..services.sql_service import sql_service
        
        try:
            tables = sql_service.get_tables()
            
            if tables:
                lines = ["Database tables:", ""]
                for table in tables:
                    count = sql_service.count_rows(table)
                    lines.append(f"  {table:30} ({count} rows)")
                
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message="\n".join(lines),
                    data={"tables": tables},
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message="No tables found in database",
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Tables command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_describe_command(socketio, client_id, args: list):
        """
        Handle describe command - show table structure.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            args: Command arguments [table_name]
        """
        from ..services.sql_service import sql_service
        
        if not args:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message="Missing table name. Usage: describe <table_name>",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
            return
        
        table_name = args[0]
        
        try:
            result = sql_service.describe_table(table_name)
            
            if result.success and result.rows:
                lines = [f"Table: {table_name}", ""]
                lines.append(f"{'Column':<25} {'Type':<15} {'Nullable':<10} {'PK':<5} {'Default'}")
                lines.append("-" * 70)
                
                for row in result.rows:
                    col_name = row.get("name", "")
                    col_type = row.get("type", "")
                    nullable = "NO" if row.get("notnull", 0) else "YES"
                    pk = "YES" if row.get("pk", 0) else ""
                    default = str(row.get("dflt_value", "")) if row.get("dflt_value") is not None else ""
                    lines.append(f"{col_name:<25} {col_type:<15} {nullable:<10} {pk:<5} {default}")
                
                output = ConsoleOutput(
                    type="success",
                    format="text",
                    message="\n".join(lines),
                    data=result.rows,
                    timestamp=time.time()
                )
            elif result.success:
                output = ConsoleOutput(
                    type="info",
                    format="text",
                    message=f"Table '{table_name}' has no columns or does not exist",
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Error: {result.error}",
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Describe command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    # =========================================================================
    # AI Command Handlers
    # =========================================================================
    
    def _handle_ai_command(socketio, client_id, action: str, args: list):
        """
        Handle ai commands (ai_providers, ai_models, ai_configs).
        
        Routes to specific handlers based on subcommand.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: AI action (ai_providers, ai_models, ai_configs)
            args: Command arguments
        """
        if action == "ai_providers":
            _handle_ai_providers_command(socketio, client_id, args)
        elif action == "ai_models":
            _handle_ai_models_command(socketio, client_id, args)
        elif action == "ai_configs":
            _handle_ai_configs_command(socketio, client_id, args)
        else:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown AI subcommand: {action}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_ai_providers_command(socketio, client_id, args: list):
        """
        Handle ai providers commands.
        
        Actions: list, add, update, delete, info
        """
        from ..services.sqlalchemy.ai import repository as ai_repo
        
        if not args:
            args = ["list"]  # Default action
        
        sub_action = args[0].lower()
        sub_args = args[1:]
        
        try:
            if sub_action == "list":
                providers = ai_repo.get_all_providers(active_only=False)
                
                if providers:
                    lines = ["AI Providers:", ""]
                    lines.append(f"{'ID':<20} {'Name':<25} {'Type':<12} {'Local':<6} {'Active':<8} {'Priority'}")
                    lines.append("-" * 85)
                    
                    for p in providers:
                        local_str = "Yes" if p.is_local else "No"
                        active_str = "Yes" if p.is_active else "No"
                        lines.append(f"{p.provider_id:<20} {p.name:<25} {p.provider_type:<12} {local_str:<6} {active_str:<8} {p.priority}")
                    
                    lines.append("")
                    lines.append(f"Total: {len(providers)} provider(s)")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=[p.to_dict() for p in providers],
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="info",
                        format="text",
                        message="No AI providers found",
                        timestamp=time.time()
                    )
                
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "add":
                # ai providers add <id> <name> <type> [url] [--local] [--env <VAR>]
                if len(sub_args) < 3:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai providers add <id> <name> <type> [url] [--local] [--env VAR]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider_id = sub_args[0]
                name = sub_args[1]
                provider_type = sub_args[2]
                
                # Parse optional args
                base_url = None
                is_local = False
                api_key_env = None
                
                i = 3
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--local":
                        is_local = True
                    elif arg == "--env" and i + 1 < len(sub_args):
                        i += 1
                        api_key_env = sub_args[i]
                    elif not arg.startswith("--"):
                        base_url = arg
                    i += 1
                
                # Check if exists
                existing = ai_repo.get_provider_by_id(provider_id)
                if existing:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Provider '{provider_id}' already exists",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider = ai_repo.create_provider(
                    provider_id=provider_id,
                    name=name,
                    provider_type=provider_type,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    is_local=is_local
                )
                
                output = ConsoleOutput(
                    type="success",
                    format="json",
                    message=f"Provider '{provider_id}' created successfully",
                    data=provider.to_dict(),
                    timestamp=time.time()
                )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "update":
                # ai providers update <id> [--name value] [--url value] [--active true/false]
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai providers update <id> [--name value] [--url value] [--active true/false]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider_id = sub_args[0]
                update_fields = {}
                
                i = 1
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--name" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["name"] = sub_args[i]
                    elif arg == "--url" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["base_url"] = sub_args[i]
                    elif arg == "--active" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["is_active"] = sub_args[i].lower() == "true"
                    elif arg == "--local" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["is_local"] = sub_args[i].lower() == "true"
                    elif arg == "--priority" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["priority"] = int(sub_args[i])
                    i += 1
                
                if not update_fields:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="No fields to update specified",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider = ai_repo.update_provider(provider_id, **update_fields)
                if provider:
                    output = ConsoleOutput(
                        type="success",
                        format="json",
                        message=f"Provider '{provider_id}' updated",
                        data=provider.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Provider '{provider_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "delete":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai providers delete <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider_id = sub_args[0]
                success, error = ai_repo.delete_provider(provider_id)
                
                if success:
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message=f"Provider '{provider_id}' deleted",
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=error,
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "info":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai providers info <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                provider_id = sub_args[0]
                provider = ai_repo.get_provider_by_id(provider_id)
                
                if provider:
                    models = ai_repo.get_models_by_provider(provider_id, active_only=False)
                    lines = [
                        f"Provider: {provider.name}",
                        f"  ID: {provider.provider_id}",
                        f"  Type: {provider.provider_type}",
                        f"  Base URL: {provider.base_url or '(not set)'}",
                        f"  API Key Env: {provider.api_key_env or '(not set)'}",
                        f"  Local: {'Yes' if provider.is_local else 'No'}",
                        f"  Active: {'Yes' if provider.is_active else 'No'}",
                        f"  Priority: {provider.priority}",
                        f"  Models: {len(models)}"
                    ]
                    if models:
                        lines.append("  Model list:")
                        for m in models:
                            lines.append(f"    - {m.model_id} ({m.model_name})")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=provider.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Provider '{provider_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown action '{sub_action}'. Use: list, add, update, delete, info",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"AI providers command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_ai_models_command(socketio, client_id, args: list):
        """
        Handle ai models commands.
        
        Actions: list, add, update, delete, info
        """
        from ..services.sqlalchemy.ai import repository as ai_repo
        
        if not args:
            args = ["list"]
        
        sub_action = args[0].lower()
        sub_args = args[1:]
        
        try:
            if sub_action == "list":
                # Check for --provider filter
                provider_filter = None
                for i, arg in enumerate(sub_args):
                    if arg == "--provider" and i + 1 < len(sub_args):
                        provider_filter = sub_args[i + 1]
                        break
                
                if provider_filter:
                    models = ai_repo.get_models_by_provider(provider_filter, active_only=False)
                else:
                    models = ai_repo.get_all_models(active_only=False)
                
                if models:
                    lines = ["AI Models:", ""]
                    lines.append(f"{'ID':<25} {'Name':<25} {'Model':<20} {'Provider':<15} {'Active'}")
                    lines.append("-" * 95)
                    
                    for m in models:
                        active_str = "Yes" if m.is_active else "No"
                        lines.append(f"{m.model_id:<25} {m.name:<25} {m.model_name:<20} {m.provider_id:<15} {active_str}")
                    
                    lines.append("")
                    lines.append(f"Total: {len(models)} model(s)")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=[m.to_dict() for m in models],
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="info",
                        format="text",
                        message="No AI models found",
                        timestamp=time.time()
                    )
                
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "add":
                # ai models add <id> <provider> <name> <model_name> [--context N] [--tools] [--vision]
                if len(sub_args) < 4:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai models add <id> <provider_id> <name> <model_name> [--context N] [--tools] [--vision]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model_id = sub_args[0]
                provider_id = sub_args[1]
                name = sub_args[2]
                model_name = sub_args[3]
                
                # Parse optional args
                context_length = None
                supports_tools = False
                supports_vision = False
                
                i = 4
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--context" and i + 1 < len(sub_args):
                        i += 1
                        context_length = int(sub_args[i])
                    elif arg == "--tools":
                        supports_tools = True
                    elif arg == "--vision":
                        supports_vision = True
                    i += 1
                
                # Check provider exists
                provider = ai_repo.get_provider_by_id(provider_id)
                if not provider:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Provider '{provider_id}' not found",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                # Check if model exists
                existing = ai_repo.get_model_by_id(model_id)
                if existing:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Model '{model_id}' already exists",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model = ai_repo.create_model(
                    model_id=model_id,
                    provider_id=provider_id,
                    name=name,
                    model_name=model_name,
                    context_length=context_length,
                    supports_tools=supports_tools,
                    supports_vision=supports_vision
                )
                
                output = ConsoleOutput(
                    type="success",
                    format="json",
                    message=f"Model '{model_id}' created successfully",
                    data=model.to_dict(),
                    timestamp=time.time()
                )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "update":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai models update <id> [--name value] [--active true/false] [--context N]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model_id = sub_args[0]
                update_fields = {}
                
                i = 1
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--name" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["name"] = sub_args[i]
                    elif arg == "--active" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["is_active"] = sub_args[i].lower() == "true"
                    elif arg == "--context" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["context_length"] = int(sub_args[i])
                    elif arg == "--tools" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["supports_tools"] = sub_args[i].lower() == "true"
                    elif arg == "--vision" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["supports_vision"] = sub_args[i].lower() == "true"
                    i += 1
                
                if not update_fields:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="No fields to update specified",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model = ai_repo.update_model(model_id, **update_fields)
                if model:
                    output = ConsoleOutput(
                        type="success",
                        format="json",
                        message=f"Model '{model_id}' updated",
                        data=model.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Model '{model_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "delete":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai models delete <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model_id = sub_args[0]
                success, error = ai_repo.delete_model(model_id)
                
                if success:
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message=f"Model '{model_id}' deleted",
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=error,
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "info":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai models info <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                model_id = sub_args[0]
                model = ai_repo.get_model_by_id(model_id)
                
                if model:
                    configs = ai_repo.get_configs_by_model(model_id, active_only=False)
                    lines = [
                        f"Model: {model.name}",
                        f"  ID: {model.model_id}",
                        f"  API Model: {model.model_name}",
                        f"  Provider: {model.provider_id}",
                        f"  Context Length: {model.context_length or '(not set)'}",
                        f"  Supports Tools: {'Yes' if model.supports_tools else 'No'}",
                        f"  Supports Vision: {'Yes' if model.supports_vision else 'No'}",
                        f"  Supports Streaming: {'Yes' if model.supports_streaming else 'No'}",
                        f"  Active: {'Yes' if model.is_active else 'No'}",
                        f"  Configurations: {len(configs)}"
                    ]
                    if configs:
                        lines.append("  Config list:")
                        for c in configs:
                            default_str = " (default)" if c.is_default else ""
                            lines.append(f"    - {c.config_id}: {c.name}{default_str}")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=model.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Model '{model_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown action '{sub_action}'. Use: list, add, update, delete, info",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"AI models command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_ai_configs_command(socketio, client_id, args: list):
        """
        Handle ai configs commands.
        
        Actions: list, add, update, delete, info
        """
        from ..services.sqlalchemy.ai import repository as ai_repo
        
        if not args:
            args = ["list"]
        
        sub_action = args[0].lower()
        sub_args = args[1:]
        
        try:
            if sub_action == "list":
                # Check for --model filter
                model_filter = None
                for i, arg in enumerate(sub_args):
                    if arg == "--model" and i + 1 < len(sub_args):
                        model_filter = sub_args[i + 1]
                        break
                
                if model_filter:
                    configs = ai_repo.get_configs_by_model(model_filter, active_only=False)
                else:
                    configs = ai_repo.get_all_configs(active_only=False)
                
                if configs:
                    lines = ["AI Model Configurations:", ""]
                    lines.append(f"{'ID':<25} {'Name':<25} {'Model':<20} {'Default':<8} {'Active'}")
                    lines.append("-" * 90)
                    
                    for c in configs:
                        default_str = "Yes" if c.is_default else "No"
                        active_str = "Yes" if c.is_active else "No"
                        lines.append(f"{c.config_id:<25} {c.name:<25} {c.model_id:<20} {default_str:<8} {active_str}")
                    
                    lines.append("")
                    lines.append(f"Total: {len(configs)} configuration(s)")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=[c.to_dict() for c in configs],
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="info",
                        format="text",
                        message="No AI configurations found",
                        timestamp=time.time()
                    )
                
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "add":
                # ai configs add <id> <model_id> <name> [--temp N] [--tokens N] [--system "prompt"] [--default]
                if len(sub_args) < 3:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai configs add <id> <model_id> <name> [--temp N] [--tokens N] [--system \"prompt\"] [--default]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config_id = sub_args[0]
                model_id = sub_args[1]
                name = sub_args[2]
                
                # Parse optional args
                params = {}
                is_default = False
                use_case = None
                description = None
                
                i = 3
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--temp" and i + 1 < len(sub_args):
                        i += 1
                        params["temperature"] = float(sub_args[i])
                    elif arg == "--tokens" and i + 1 < len(sub_args):
                        i += 1
                        params["max_tokens"] = int(sub_args[i])
                    elif arg == "--system" and i + 1 < len(sub_args):
                        i += 1
                        params["system_prompt"] = sub_args[i]
                    elif arg == "--default":
                        is_default = True
                    elif arg == "--use-case" and i + 1 < len(sub_args):
                        i += 1
                        use_case = sub_args[i]
                    elif arg == "--desc" and i + 1 < len(sub_args):
                        i += 1
                        description = sub_args[i]
                    i += 1
                
                # Check model exists
                model = ai_repo.get_model_by_id(model_id)
                if not model:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Model '{model_id}' not found",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                # Check if config exists
                existing = ai_repo.get_config_by_id(config_id)
                if existing:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Configuration '{config_id}' already exists",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config = ai_repo.create_config(
                    config_id=config_id,
                    model_id=model_id,
                    name=name,
                    params=params if params else None,
                    description=description,
                    is_default=is_default,
                    use_case=use_case
                )
                
                output = ConsoleOutput(
                    type="success",
                    format="json",
                    message=f"Configuration '{config_id}' created successfully",
                    data=config.to_dict(),
                    timestamp=time.time()
                )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "update":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai configs update <id> [--name value] [--temp N] [--tokens N] [--default] [--active true/false]",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config_id = sub_args[0]
                update_fields = {}
                params_update = {}
                
                i = 1
                while i < len(sub_args):
                    arg = sub_args[i]
                    if arg == "--name" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["name"] = sub_args[i]
                    elif arg == "--active" and i + 1 < len(sub_args):
                        i += 1
                        update_fields["is_active"] = sub_args[i].lower() == "true"
                    elif arg == "--default":
                        update_fields["is_default"] = True
                    elif arg == "--temp" and i + 1 < len(sub_args):
                        i += 1
                        params_update["temperature"] = float(sub_args[i])
                    elif arg == "--tokens" and i + 1 < len(sub_args):
                        i += 1
                        params_update["max_tokens"] = int(sub_args[i])
                    elif arg == "--system" and i + 1 < len(sub_args):
                        i += 1
                        params_update["system_prompt"] = sub_args[i]
                    i += 1
                
                # Merge params
                if params_update:
                    config = ai_repo.get_config_by_id(config_id)
                    if config:
                        existing_params = config.params.copy() if config.params else {}
                        existing_params.update(params_update)
                        update_fields["params"] = existing_params
                
                if not update_fields:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="No fields to update specified",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config = ai_repo.update_config(config_id, **update_fields)
                if config:
                    output = ConsoleOutput(
                        type="success",
                        format="json",
                        message=f"Configuration '{config_id}' updated",
                        data=config.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Configuration '{config_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "delete":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai configs delete <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config_id = sub_args[0]
                success, error = ai_repo.delete_config(config_id)
                
                if success:
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message=f"Configuration '{config_id}' deleted",
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=error,
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            elif sub_action == "info":
                if not sub_args:
                    error_output = ConsoleOutput(
                        type="error",
                        format="text",
                        message="Usage: ai configs info <id>",
                        timestamp=time.time()
                    )
                    socketio.emit("console_output", error_output.model_dump(), to=client_id)
                    return
                
                config_id = sub_args[0]
                config = ai_repo.get_config_by_id(config_id)
                
                if config:
                    params = config.params or {}
                    lines = [
                        f"Configuration: {config.name}",
                        f"  ID: {config.config_id}",
                        f"  Model: {config.model_id}",
                        f"  Description: {config.description or '(none)'}",
                        f"  Use Case: {config.use_case or '(none)'}",
                        f"  Default: {'Yes' if config.is_default else 'No'}",
                        f"  Active: {'Yes' if config.is_active else 'No'}",
                        "",
                        "  Parameters:",
                        f"    Temperature: {params.get('temperature', '(not set)')}",
                        f"    Max Tokens: {params.get('max_tokens', '(not set)')}",
                        f"    Top P: {params.get('top_p', '(not set)')}",
                    ]
                    if params.get('system_prompt'):
                        prompt = params['system_prompt'][:100] + "..." if len(params.get('system_prompt', '')) > 100 else params.get('system_prompt', '')
                        lines.append(f"    System Prompt: {prompt}")
                    
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data=config.to_dict(),
                        timestamp=time.time()
                    )
                else:
                    output = ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Configuration '{config_id}' not found",
                        timestamp=time.time()
                    )
                socketio.emit("console_output", output.model_dump(), to=client_id)
                return
            
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown action '{sub_action}'. Use: list, add, update, delete, info",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
                
        except Exception as e:
            logger.error(f"AI configs command error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    # =========================================================================
    # Ollama Command Handlers
    # =========================================================================
    
    def _handle_ollama_command(socketio, client_id, action: str, args: list):
        """
        Handle ollama commands (ollama_ping, ollama_models).
        
        Routes to specific handlers based on subcommand.
        Uses the centralized OllamaService.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            action: Ollama action (ollama_ping, ollama_models)
            args: Command arguments
        """
        from ..services.ai.ollama_service import ollama
        
        if action == "ollama_ping":
            _handle_ollama_ping(socketio, client_id, ollama)
        elif action == "ollama_models":
            _handle_ollama_models(socketio, client_id, ollama, args)
        else:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown Ollama subcommand: {action}. Use: ping, models",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_ollama_ping(socketio, client_id, ollama_service):
        """
        Handle ollama ping command - check server availability.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            ollama_service: OllamaService instance
        """
        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message=f"Pinging Ollama server at {ollama_service.base_url}...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            is_available = ollama_service.is_available()
            
            if is_available:
                output = ConsoleOutput(
                    type="success",
                    format="json",
                    message=f"Ollama server is available at {ollama_service.base_url}",
                    data={
                        "status": "online",
                        "base_url": ollama_service.base_url,
                        "default_model": ollama_service.default_model
                    },
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="json",
                    message=f"Ollama server is NOT available at {ollama_service.base_url}",
                    data={
                        "status": "offline",
                        "base_url": ollama_service.base_url,
                        "hint": "Make sure Ollama is running: ollama serve"
                    },
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Ollama ping error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error pinging Ollama: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)
    
    def _handle_ollama_models(socketio, client_id, ollama_service, args=None):
        """
        Handle ollama models command - list available models.
        
        Args:
            socketio: SocketIO instance
            client_id: Client session ID
            ollama_service: OllamaService instance
            args: Command args (e.g. ["--output_format", "table"])
        """
        args = args or []
        output_format = "table"
        i = 0
        while i < len(args):
            if args[i].lower() == "--output_format" and i + 1 < len(args):
                output_format = args[i + 1].lower().strip()
                if output_format not in ("table", "json", "text"):
                    output_format = "table"
                break
            elif args[i].lower() in ("table", "json", "text"):
                output_format = args[i].lower()
                break
            i += 1

        # Notify start
        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message="Fetching models from Ollama server...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)
        
        try:
            models = ollama_service.list_models()
            
            if models:
                columns = ["Name", "Size", "Modified", "Digest"]
                rows = []
                for m in models:
                    size_gb = m.size / (1024 ** 3)
                    if size_gb >= 1:
                        size_str = f"{size_gb:.1f} GB"
                    else:
                        size_mb = m.size / (1024 ** 2)
                        size_str = f"{size_mb:.0f} MB"
                    if m.modified_at:
                        if isinstance(m.modified_at, str):
                            modified = m.modified_at[:10]
                        elif hasattr(m.modified_at, 'strftime'):
                            modified = m.modified_at.strftime('%Y-%m-%d')
                        else:
                            modified = str(m.modified_at)[:10]
                    else:
                        modified = "N/A"
                    digest = (m.digest[:12] if m.digest else "") or ""
                    rows.append({"Name": m.name, "Size": size_str, "Modified": modified, "Digest": digest})
                
                if output_format == "table":
                    output = ConsoleOutput(
                        type="success",
                        format="table",
                        message=f"Ollama Models ({len(models)})",
                        data={"columns": columns, "rows": rows, "count": len(models)},
                        timestamp=time.time()
                    )
                elif output_format == "json":
                    output = ConsoleOutput(
                        type="success",
                        format="json",
                        message=f"Ollama Models ({len(models)})",
                        data={"models": [{"name": r["Name"], "size": r["Size"], "modified": r["Modified"]} for r in rows], "count": len(models)},
                        timestamp=time.time()
                    )
                else:
                    lines = ["Ollama Models:", ""]
                    lines.append(f"{'Name':<30} {'Size':<12} {'Modified'}")
                    lines.append("-" * 70)
                    for r in rows:
                        lines.append(f"{r['Name']:<30} {r['Size']:<12} {r['Modified']}")
                    lines.append("")
                    lines.append(f"Total: {len(models)} model(s)")
                    lines.append(f"Server: {ollama_service.base_url}")
                    output = ConsoleOutput(
                        type="success",
                        format="text",
                        message="\n".join(lines),
                        data={"models": rows, "count": len(models)},
                        timestamp=time.time()
                    )
            else:
                output = ConsoleOutput(
                    type="warning",
                    format="text",
                    message=f"No models found on Ollama server ({ollama_service.base_url}).\n\nUse 'ollama pull <model>' to download models.",
                    data={"models": [], "count": 0},
                    timestamp=time.time()
                )
            
            socketio.emit("console_output", output.model_dump(), to=client_id)
            
        except Exception as e:
            logger.error(f"Ollama models error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error fetching models: {str(e)}\n\nMake sure Ollama server is running.",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)

    # =========================================================================
    # Plugin scaffold / install (PLUGIN_PATH; pip uses server interpreter)
    # =========================================================================

    def _handle_plugin_command(socketio, client_id, action: str, args: list):
        """Handle ``plugin create`` and ``plugin install`` via :class:`PluginScaffoldService`."""
        from nos.platform.services.plugin_scaffold_service import (
            DEFAULT_PIP_INSTALL_TIMEOUT_SEC,
            PluginScaffoldService,
        )

        if not args:
            socketio.emit(
                "console_output",
                ConsoleOutput(
                    type="error",
                    format="text",
                    message="Missing arguments. Usage: plugin create <name>  |  plugin install <name>",
                    timestamp=time.time(),
                ).model_dump(),
                to=client_id,
            )
            return

        name = args[0].strip()
        if action == "plugin_create":
            start = ConsoleOutput(
                type="info",
                format="progress",
                message=f"Creating plugin package '{name}' under PLUGIN_PATH…",
                timestamp=time.time(),
            )
            socketio.emit("console_output", start.model_dump(), to=client_id)
            try:
                root = PluginScaffoldService.create_under_plugin_path(name)
            except FileExistsError as e:
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=str(e),
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            except ValueError as e:
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=str(e),
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            except Exception as e:
                logger.error("plugin create failed: %s", e, exc_info=True)
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Failed to create plugin: {e}",
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            socketio.emit(
                "console_output",
                ConsoleOutput(
                    type="success",
                    format="text",
                    message=(
                        f"Successfully created external plugin package at:\n{root}\n\n"
                        "Next: run `plugin install <name>` (pip targets PLATFORM_PATH/.venv when present), "
                        "then restart the server so PluginManager can register `nos.plugins` entry points."
                    ),
                    timestamp=time.time(),
                ).model_dump(),
                to=client_id,
            )
            return

        if action == "plugin_install":
            socketio.emit(
                "console_output",
                ConsoleOutput(
                    type="info",
                    format="progress",
                    message=(
                        f"Installing '{name}' in editable mode "
                        f"(timeout {DEFAULT_PIP_INSTALL_TIMEOUT_SEC}s)…"
                    ),
                    timestamp=time.time(),
                ).model_dump(),
                to=client_id,
            )
            try:
                for line in PluginScaffoldService.stream_pip_install_editable(name):
                    if line:
                        socketio.emit(
                            "console_output",
                            ConsoleOutput(
                                type="info",
                                format="text",
                                message=line,
                                timestamp=time.time(),
                            ).model_dump(),
                            to=client_id,
                        )
            except FileNotFoundError as e:
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=str(e),
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            except TimeoutError as e:
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=str(e),
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            except RuntimeError as e:
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=str(e),
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            except Exception as e:
                logger.error("plugin install failed: %s", e, exc_info=True)
                socketio.emit(
                    "console_output",
                    ConsoleOutput(
                        type="error",
                        format="text",
                        message=f"Install failed: {e}",
                        timestamp=time.time(),
                    ).model_dump(),
                    to=client_id,
                )
                return
            socketio.emit(
                "console_output",
                ConsoleOutput(
                    type="success",
                    format="text",
                    message=(
                        "Editable install completed successfully. "
                        "You can import and run the package in this environment; "
                        "restart the application process so PluginManager reloads entry points from metadata."
                    ),
                    timestamp=time.time(),
                ).model_dump(),
                to=client_id,
            )
            return

        socketio.emit(
            "console_output",
            ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown plugin action: {action}",
                timestamp=time.time(),
            ).model_dump(),
            to=client_id,
        )

    # =========================================================================
    # Vect (Vector DB) Command Handlers
    # =========================================================================

    def _handle_vect_command(socketio, client_id, action: str, args: list):
        """
        Handle vect commands (vect_chromadb connect, vect_chromadb collections).
        """
        if action == "vect_chromadb":
            sub = (args[0] if args else "connect").lower()
            if sub == "connect":
                _handle_vect_chromadb_connect(socketio, client_id)
            elif sub in ("collections", "coll"):
                _handle_vect_chromadb_collections(socketio, client_id)
            else:
                error_output = ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown vect chromadb subcommand: {sub}. Use: connect, collections (or coll)",
                    timestamp=time.time()
                )
                socketio.emit("console_output", error_output.model_dump(), to=client_id)
        else:
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Unknown vect subcommand. Use: vect chromadb connect",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)

    def _handle_vect_chromadb_connect(socketio, client_id):
        """Test ChromaDB connection."""
        from ..services.chromadb_service import chromadb_service

        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message="Connecting to ChromaDB...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)

        try:
            result = chromadb_service.connect()
            if result.get("success"):
                output = ConsoleOutput(
                    type="success",
                    format="json",
                    message="ChromaDB connected successfully",
                    data=result,
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="json",
                    message=f"ChromaDB connection failed: {result.get('error', 'Unknown error')}",
                    data=result,
                    timestamp=time.time()
                )
            socketio.emit("console_output", output.model_dump(), to=client_id)
        except Exception as e:
            logger.error(f"ChromaDB connect error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)

    def _handle_vect_chromadb_collections(socketio, client_id):
        """List ChromaDB collections."""
        from ..services.chromadb_service import chromadb_service

        start_output = ConsoleOutput(
            type="info",
            format="progress",
            message="Fetching ChromaDB collections...",
            timestamp=time.time()
        )
        socketio.emit("console_output", start_output.model_dump(), to=client_id)

        try:
            result = chromadb_service.get_collections()
            if result.get("success"):
                cols = result.get("collections", [])
                output = ConsoleOutput(
                    type="success",
                    format="table",
                    message=f"ChromaDB collections ({len(cols)})",
                    data={
                        "columns": ["collection"],
                        "rows": [{"collection": c} for c in cols],
                        "count": len(cols),
                    },
                    timestamp=time.time()
                )
            else:
                output = ConsoleOutput(
                    type="error",
                    format="json",
                    message=f"Failed: {result.get('error', 'Unknown error')}",
                    data=result,
                    timestamp=time.time()
                )
            socketio.emit("console_output", output.model_dump(), to=client_id)
        except Exception as e:
            logger.error(f"ChromaDB collections error: {e}", exc_info=True)
            error_output = ConsoleOutput(
                type="error",
                format="text",
                message=f"Error: {str(e)}",
                timestamp=time.time()
            )
            socketio.emit("console_output", error_output.model_dump(), to=client_id)