"""Child-process entrypoints: run workflow or node with WorkerQueueLog → parent queue."""

from __future__ import annotations

import dataclasses
import logging
import os
import time
import traceback
from multiprocessing import Event as MpEvent
from multiprocessing import Queue
from typing import Any, Optional

logger = logging.getLogger(__name__)


def workflow_worker_main(
    event_q: Queue,
    resp_q: Queue,
    stop_ev: MpEvent,
    payload: dict[str, Any],
) -> None:
    """
    Execute one workflow in this OS process.

    ``payload`` must be picklable: workflow_id, initial_state, execution_id, debug_mode,
    output_format, request (optional).
    """
    os.environ["NOS_EXECUTION_WORKER"] = "1"
    from nos.core.engine import WorkflowEngine
    from nos.core.engine.registry import workflow_registry
    from .worker_log import WorkerProxyInteractiveLog, start_resource_metrics_thread

    wf_id = payload["workflow_id"]
    initial_state = payload.get("initial_state") or {}
    execution_id = payload["execution_id"]
    debug_mode = payload.get("debug_mode") or "trace"
    output_format = payload.get("output_format") or "json"
    request = payload.get("request")

    exec_log = WorkerProxyInteractiveLog(
        event_q,
        resp_q,
        stop_ev,
        execution_id=execution_id,
        workflow_id=wf_id,
        module_path="",
        class_name="",
        shared_state={},
    )
    m_stop, _m_thread = start_resource_metrics_thread(exec_log)

    try:
        workflow = workflow_registry.create_workflow_instance(wf_id)
        if workflow is None:
            event_q.put(("error", f"Workflow '{wf_id}' not found", ""))
            return

        engine = WorkflowEngine()
        result = engine._execute_sync_inner(
            workflow,
            initial_state,
            exec_log,
            debug_mode,
            output_format,
        )
        event_q.put(("done", dataclasses.asdict(result)))
    except Exception as e:
        logger.exception("workflow_worker_main failed")
        event_q.put(("error", str(e), traceback.format_exc()))
    finally:
        m_stop.set()


def node_worker_main(
    event_q: Queue,
    resp_q: Queue,
    stop_ev: MpEvent,
    payload: dict[str, Any],
) -> None:
    """Execute one node in this OS process."""
    os.environ["NOS_EXECUTION_WORKER"] = "1"
    import importlib
    import sys

    from nos.core.engine import WorkflowEngine
    from nos.core.engine.registry import workflow_registry
    from nos.core.engine.workflow_engine import ExecutionContext

    from .worker_log import WorkerProxyInteractiveLog, start_resource_metrics_thread

    node_id = payload["node_id"]
    mode = payload.get("mode") or "prod"
    module_path = payload.get("module_path")
    class_name = payload.get("class_name")
    state = payload.get("state") or {}
    input_params = payload.get("input_params") or {}
    execution_id = payload["execution_id"]
    debug_mode = payload.get("debug_mode") or "debug"
    output_format = payload.get("output_format")
    command = payload.get("command")
    run_request_extras = payload.get("run_request_extras")

    actual_module_path = module_path
    actual_class_name = class_name

    if mode == "dev":
        if not module_path or not class_name:
            event_q.put(("error", "mode='dev' requires module_path and class_name", ""))
            return
        try:
            importlib.invalidate_caches()
            module = importlib.import_module(module_path)
            node_class = getattr(module, class_name)
            node = node_class(node_id=node_id)
            actual_module_path = module_path
            actual_class_name = class_name
        except (ImportError, AttributeError) as e:
            event_q.put(
                (
                    "error",
                    (
                        f"Failed to load {module_path}.{class_name}: {e}\n"
                        f"Interpreter: {sys.executable}"
                    ),
                    traceback.format_exc(),
                )
            )
            return
    else:
        node = workflow_registry.create_node_instance(node_id)
        if not node:
            event_q.put(("error", f"Node '{node_id}' not found in registry", ""))
            return
        actual_module_path = node.__class__.__module__
        actual_class_name = node.__class__.__name__

    exec_log = WorkerProxyInteractiveLog(
        event_q,
        resp_q,
        stop_ev,
        execution_id=execution_id,
        node_id=node_id,
        module_path=actual_module_path or "",
        class_name=actual_class_name or "",
        shared_state=dict(state),
    )
    m_stop, _m_thread = start_resource_metrics_thread(exec_log)

    engine = WorkflowEngine()
    context = ExecutionContext(
        execution_id=execution_id,
        execution_type="node",
        started_at=time.time(),
        node_id=node_id,
        node=node,
        exec_log=exec_log,
    )
    engine._execution_contexts[execution_id] = context

    try:
        node.set_exec_log(exec_log)
        exec_log.set_execution_flags(background=False, debug_mode=debug_mode)
        result_dict = engine._run_node_sync_impl(
            execution_id=execution_id,
            node_id=node_id,
            node=node,
            exec_log=exec_log,
            state=state,
            input_params=input_params,
            mode=mode,
            room=None,
            debug_mode=debug_mode,
            command=command,
            run_request_extras=run_request_extras,
            output_format=output_format,
            context=context,
            callback=None,
        )
        event_q.put(("done", result_dict))
    except Exception as e:
        logger.exception("node_worker_main failed")
        event_q.put(("error", str(e), traceback.format_exc()))
    finally:
        m_stop.set()
        engine._execution_contexts.pop(execution_id, None)
