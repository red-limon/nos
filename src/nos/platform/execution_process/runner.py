"""Spawn OS worker processes and replay events into the parent execution log (EventLog or EventLogBuffer)."""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing import Process, get_context
from multiprocessing.queues import Queue
from typing import Any, Callable, Dict, Optional, Union

from nos.core.engine.base import Workflow, WorkflowExecutionResult, WorkflowResponseData
from nos.core.engine.workflow_engine import ExecutionContext, WorkflowEngine
from nos.core.execution_log import EventLogBuffer

from .serialization import deserialize_event
from .worker import node_worker_main, workflow_worker_main

logger = logging.getLogger(__name__)


def _workflow_result_from_dict(d: dict[str, Any]) -> WorkflowExecutionResult:
    resp_raw = d.get("response") or {}
    response = WorkflowResponseData(
        output=dict(resp_raw.get("output") or {}),
        metadata=dict(resp_raw.get("metadata") or {}),
    )
    return WorkflowExecutionResult(
        execution_id=str(d.get("execution_id", "")),
        workflow_id=str(d.get("workflow_id", "")),
        module_path=str(d.get("module_path", "")),
        class_name=str(d.get("class_name", "")),
        command=str(d.get("command", "")),
        status=str(d.get("status", "")),
        response=response,
        state=dict(d.get("state") or {}),
        state_changed=dict(d.get("state_changed") or {}),
        initial_state=dict(d.get("initial_state") or {}),
        started_at=str(d.get("started_at", "")),
        ended_at=str(d.get("ended_at", "")),
        message=d.get("message"),
        duration=float(d.get("duration") or 0.0),
        node_ids_executed=list(d.get("node_ids_executed") or []),
        event_logs=list(d.get("event_logs") or []),
    )


def _parent_request_and_wait(
    parent_log: Union[EventLogBuffer, Any],
    event_type: str,
    data: dict[str, Any],
    timeout: float,
) -> Any:
    fn = getattr(parent_log, "request_and_wait", None)
    if callable(fn):
        return fn(event_type, data, timeout=timeout)
    return None


def run_workflow_in_process_sync(
    engine: WorkflowEngine,
    workflow: Workflow,
    initial_state: Optional[Dict[str, Any]],
    parent_log: Union[EventLogBuffer, Any],
    debug_mode: str,
    output_format: str,
    request: Optional[Dict[str, Any]],
) -> WorkflowExecutionResult:
    """Run workflow in a child process; block until completion. Replays all events to ``parent_log``."""
    ctx = get_context("spawn")
    event_q: Queue = ctx.Queue()
    resp_q: Queue = ctx.Queue()
    stop_ev = ctx.Event()
    execution_id = parent_log.execution_id

    payload = {
        "workflow_id": workflow.workflow_id,
        "initial_state": dict(initial_state or {}),
        "execution_id": execution_id,
        "debug_mode": debug_mode,
        "output_format": output_format,
        "request": request,
    }

    proc = ctx.Process(
        target=workflow_worker_main,
        args=(event_q, resp_q, stop_ev, payload),
        name=f"nos-workflow-{execution_id}",
    )

    ectx = ExecutionContext(
        execution_id=execution_id,
        execution_type="workflow",
        started_at=time.time(),
        workflow_id=workflow.workflow_id,
        workflow=None,
        exec_log=parent_log,
        child_process=proc,
        mp_stop_event=stop_ev,
    )
    engine._execution_contexts[execution_id] = ectx

    proc.start()
    try:
        from nos.platform.services.sqlalchemy.execution_run import repository as run_repo

        try:
            run_repo.set_pid(execution_id, proc.pid)
        except Exception:
            pass
    except Exception:
        pass

    result_dict: Optional[dict[str, Any]] = None
    try:
        while True:
            if not proc.is_alive() and event_q.empty():
                time.sleep(0.05)
            try:
                msg = event_q.get(timeout=0.5)
            except Exception:
                if not proc.is_alive() and event_q.empty():
                    raise RuntimeError("Workflow worker process exited unexpectedly")
                continue
            if not msg:
                continue
            kind = msg[0]
            if kind == "emit":
                try:
                    parent_log._emit(deserialize_event(msg[1]))
                except Exception as exc:
                    logger.error("replay emit failed: %s", exc, exc_info=True)
            elif kind == "rpc_request":
                _, request_id, event_type, data = msg
                try:
                    resp = _parent_request_and_wait(parent_log, event_type, data, 300.0)
                    resp_q.put(("rpc_response", request_id, resp))
                except Exception as exc:
                    logger.error("rpc_request failed: %s", exc, exc_info=True)
                    resp_q.put(("rpc_response", request_id, None))
            elif kind == "done":
                result_dict = msg[1]
                break
            elif kind == "error":
                err = msg[1]
                tb = msg[2] if len(msg) > 2 else ""
                raise RuntimeError(f"{err}\n{tb}")
    finally:
        if proc.is_alive():
            proc.join(timeout=30.0)
        engine._execution_contexts.pop(execution_id, None)

    if result_dict is None:
        raise RuntimeError("Workflow worker finished without result")
    return _workflow_result_from_dict(result_dict)


def run_workflow_in_process_background(
    engine: WorkflowEngine,
    workflow: Workflow,
    initial_state: Optional[Dict[str, Any]],
    parent_log: Union[EventLogBuffer, Any],
    debug_mode: str,
    output_format: str,
    request: Optional[Dict[str, Any]],
    callback: Optional[Callable[[Any], None]],
) -> str:
    """Non-blocking: drain in a daemon thread; invoke ``callback`` when the worker exits."""
    execution_id = parent_log.execution_id

    def _drain():
        try:
            result = run_workflow_in_process_sync(
                engine,
                workflow,
                initial_state,
                parent_log,
                debug_mode,
                output_format,
                request,
            )
            if callback:
                callback(result)
        except Exception:
            logger.exception("Background workflow process failed")
            if callback:
                callback({"error": "Background workflow process failed"})

    threading.Thread(target=_drain, name=f"nos-wf-bg-{execution_id}", daemon=True).start()
    return execution_id


def run_node_in_process_sync(
    engine: WorkflowEngine,
    *,
    node_id: str,
    state: dict[str, Any],
    input_params: dict[str, Any],
    mode: str,
    module_path: Optional[str],
    class_name: Optional[str],
    parent_log: Union[EventLogBuffer, Any],
    debug_mode: str,
    command: Optional[str],
    user_id: str,
    run_request_extras: Optional[Dict[str, Any]],
    output_format: Optional[str],
) -> tuple[str, dict[str, Any]]:
    """Run node in child process; return (execution_id, result_dict)."""
    ctx = get_context("spawn")
    event_q: Queue = ctx.Queue()
    resp_q: Queue = ctx.Queue()
    stop_ev = ctx.Event()
    execution_id = parent_log.execution_id

    payload = {
        "node_id": node_id,
        "mode": mode,
        "module_path": module_path,
        "class_name": class_name,
        "state": state,
        "input_params": input_params,
        "execution_id": execution_id,
        "debug_mode": debug_mode,
        "output_format": output_format,
        "command": command,
        "user_id": user_id,
        "run_request_extras": run_request_extras,
    }

    proc = ctx.Process(
        target=node_worker_main,
        args=(event_q, resp_q, stop_ev, payload),
        name=f"nos-node-{execution_id}",
    )

    ectx = ExecutionContext(
        execution_id=execution_id,
        execution_type="node",
        started_at=time.time(),
        node_id=node_id,
        node=None,
        exec_log=parent_log,
        child_process=proc,
        mp_stop_event=stop_ev,
    )
    engine._execution_contexts[execution_id] = ectx

    proc.start()
    try:
        from nos.platform.services.sqlalchemy.execution_run import repository as run_repo

        try:
            run_repo.set_pid(execution_id, proc.pid)
        except Exception:
            pass
    except Exception:
        pass

    result_dict: Optional[dict[str, Any]] = None
    try:
        while True:
            if not proc.is_alive() and event_q.empty():
                time.sleep(0.05)
            try:
                msg = event_q.get(timeout=0.5)
            except Exception:
                if not proc.is_alive() and event_q.empty():
                    raise RuntimeError("Node worker process exited unexpectedly")
                continue
            if not msg:
                continue
            kind = msg[0]
            if kind == "emit":
                try:
                    parent_log._emit(deserialize_event(msg[1]))
                except Exception as exc:
                    logger.error("replay emit failed: %s", exc, exc_info=True)
            elif kind == "rpc_request":
                _, request_id, event_type, data = msg
                try:
                    resp = _parent_request_and_wait(parent_log, event_type, data, 300.0)
                    resp_q.put(("rpc_response", request_id, resp))
                except Exception as exc:
                    logger.error("rpc_request failed: %s", exc, exc_info=True)
                    resp_q.put(("rpc_response", request_id, None))
            elif kind == "done":
                result_dict = msg[1]
                break
            elif kind == "error":
                err = msg[1]
                tb = msg[2] if len(msg) > 2 else ""
                raise RuntimeError(f"{err}\n{tb}")
    finally:
        if proc.is_alive():
            proc.join(timeout=30.0)
        engine._execution_contexts.pop(execution_id, None)

    if result_dict is None:
        raise RuntimeError("Node worker finished without result")
    return execution_id, result_dict


def run_node_in_process_background(
    engine: WorkflowEngine,
    *,
    node_id: str,
    state: dict[str, Any],
    input_params: dict[str, Any],
    mode: str,
    module_path: Optional[str],
    class_name: Optional[str],
    parent_log: Union[EventLogBuffer, Any],
    debug_mode: str,
    command: Optional[str],
    user_id: str,
    run_request_extras: Optional[Dict[str, Any]],
    output_format: Optional[str],
    callback: Optional[Callable[[dict[str, Any]], None]],
) -> str:
    """Non-blocking node run in a child process; drain loop runs in a daemon thread."""
    execution_id = parent_log.execution_id

    def _drain():
        try:
            _, res = run_node_in_process_sync(
                engine,
                node_id=node_id,
                state=state,
                input_params=input_params,
                mode=mode,
                module_path=module_path,
                class_name=class_name,
                parent_log=parent_log,
                debug_mode=debug_mode,
                command=command,
                user_id=user_id,
                run_request_extras=run_request_extras,
                output_format=output_format,
            )
            if callback:
                callback(res)
        except Exception:
            logger.exception("Background node process failed")
            if callback:
                callback({"error": "Background node process failed"})

    threading.Thread(target=_drain, name=f"nos-node-bg-{execution_id}", daemon=True).start()
    return execution_id
