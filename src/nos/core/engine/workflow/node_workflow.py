"""
NodeWorkflow - Node that runs a child workflow by ID.

Subclass of Node whose _do_execute loads a workflow from the registry (or via
module_path/class_name as fallback), runs it with the parent state as
initial_state, and merges the child output back (via map_to_node / map_to_shared).
"""

import importlib
from typing import Optional

from ..node import Node, NodeOutput


class NodeWorkflow(Node):
    """
    Node that executes a child workflow by workflow_id.

    Resolution order:
    1. Try registry: workflow_registry.create_workflow_instance(workflow_id)
    2. If not found and module_path + class_name provided: import and instantiate (direct)
    3. Else: error

    By default passes the parent workflow's state to the child and merges
    the child output back. Uses the same map_to_node / map_to_shared flow
    as any other node.

    Args:
        workflow_id: ID of the child workflow to run (required).
        node_id: Unique identifier for this node. Default: sub_{workflow_id}
        name: Human-readable name. Default: workflow_id
        module_path: Optional Python module path for direct resolution (fallback).
        class_name: Optional class name for direct resolution (required with module_path).
    """

    def __init__(
        self,
        workflow_id: str,
        node_id: Optional[str] = None,
        name: Optional[str] = None,
        module_path: Optional[str] = None,
        class_name: Optional[str] = None,
    ):
        _node_id = node_id or f"sub_{workflow_id}"
        _name = name or workflow_id
        super().__init__(node_id=_node_id, name=_name)
        self._workflow_id = workflow_id
        self._module_path = module_path
        self._class_name = class_name

    def _resolve_workflow(self, workflow_id: str, params_dict: dict) -> tuple:
        """
        Resolve child workflow: registry first, then direct (module_path + class_name).
        Returns (workflow, error_message). workflow is None on failure.
        """
        from ..registry import workflow_registry

        workflow = workflow_registry.create_workflow_instance(workflow_id)
        if workflow is not None:
            return workflow, None

        module_path = params_dict.get("module_path") or self._module_path
        class_name = params_dict.get("class_name") or self._class_name
        if module_path and class_name:
            try:
                module = importlib.import_module(module_path)
                workflow_class = getattr(module, class_name)
                return workflow_class(), None
            except (ImportError, AttributeError) as e:
                return None, f"Direct resolution failed ({module_path}.{class_name}): {e}"
        return None, (
            f"Workflow '{workflow_id}' not found. Register it or pass "
            "module_path and class_name for direct resolution."
        )

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        workflow_id = params_dict.get("workflow_id") or self._workflow_id
        from ..workflow_engine import get_shared_engine

        workflow, error_msg = self._resolve_workflow(workflow_id, params_dict)
        if workflow is None:
            return NodeOutput(output={}, metadata={"error": error_msg})

        engine = get_shared_engine()
        initial = dict(state)
        try:
            nested_mode = "debug" if getattr(self, "_debug_mode", False) else "trace"
            out = engine.execute_sync(
                workflow,
                initial_state=initial,
                exec_log=self._exec_log,
                debug_mode=nested_mode,
            )
        except Exception as e:
            return NodeOutput(
                output={},
                metadata={"error": str(e), "workflow_id": workflow_id},
            )

        raw = out.response.output or {}
        data = raw.get("data")
        if isinstance(data, dict):
            state.update(data)
        fmt = str(raw.get("output_format") or "json")
        return NodeOutput(
            output={"output_format": fmt, "data": data},
            metadata={"workflow_id": workflow_id, "state_changed": out.state_changed},
        )
