"""Unified POST /run — load + run for node or workflow."""

from ..routes import api_bp
from ..common import validate_payload
from ..node.routes import _execute_node_registry, dispatch_node_execute_direct
from ..node.schemas import NodeExecuteDirectSchema, NodeExecuteSchema
from ..workflow.routes import _execute_start_workflow, dispatch_workflow_module_load
from ..workflow.schemas import WorkflowStartSchema
from .schemas import UnifiedRunSchema


@api_bp.post("/run")
@api_bp.post("/run/")
@validate_payload(UnifiedRunSchema)
def unified_run(data: UnifiedRunSchema):
    """
    Single entry point: resolve plugin (registry or module) then run.

    Node: registry → POST /node/execute; module → POST /node/execute-direct style (WorkflowEngine.run_node dev).
    Workflow: registry → POST /workflow/start; module → Workflow.load(dev) then same engine as /workflow/start.
    """
    if data.target == "workflow":
        wf_data = WorkflowStartSchema(
            workflow_id=(data.id or "").strip(),
            initial_state=data.state,
            background=data.background,
            enable_realtime_logs=False,
            realtime_mode="socketio",
            output_format=(data.output_format or "json"),
            debug_mode="trace",
            request=data.request,
        )
        if data.load == "registry":
            return _execute_start_workflow(wf_data)
        return dispatch_workflow_module_load(
            wf_data,
            (data.module_path or "").strip(),
            (data.class_name or "").strip(),
        )

    if data.load == "registry":
        return _execute_node_registry(
            NodeExecuteSchema(
                node_id=(data.id or "").strip(),
                state=data.state,
                input_params=data.input_params,
                background=data.background,
                output_format=data.output_format,
                request=data.request,
            )
        )

    nid = (data.id or "").strip() or None
    return dispatch_node_execute_direct(
        NodeExecuteDirectSchema(
            module_path=(data.module_path or "").strip(),
            class_name=(data.class_name or "").strip(),
            state=data.state,
            input_params=data.input_params,
            background=data.background,
            output_format=data.output_format,
            node_id=nid,
            request=data.request,
        )
    )
