"""
Minimal reusable node template: scale a shared numeric state field by a per-node factor ``w``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput, NodeInputSchema, NodeStateSchema


class NodeTemplateState(NodeStateSchema):
    """
    State contract for :class:`NodeTemplate`: keys this node reads and updates.

    **Fields**
        result: Multiplied by ``w`` on each run; must exist in shared workflow state when the
        node executes inside a workflow whose :meth:`~nos.core.engine.workflow.workflow.Workflow.state_schema`
        includes the same field (see :class:`~reference_templates.workflow_template.WorkflowTemplateState`).
    """

    result: float = Field(
        default=1.0,
        description="Value this node scales by w (shared key with workflow state in this template).",
    )


class NodeTemplateParams(NodeInputSchema):
    """
    Direct parameters for :class:`NodeTemplate` (validated separately from workflow state).

    These values are merged from ``default_input_params`` on the workflow and runtime ``input_params``.
    """

    w: float = Field(
        default=1.0,
        description="Multiplier applied to shared state['result'] for this node instance.",
    )


class NodeTemplateOutput(BaseModel):
    """
    Shape of ``response.output['data']`` when ``output_format`` is ``json``.

    The engine validates the ``data`` payload against this model when :attr:`NodeTemplate.output_schema` is set.
    """

    node_id: str = Field(..., description="Identifier of this node instance in the workflow graph.")
    w: float = Field(..., description="Multiplier applied in this execution.")
    result: float = Field(..., description="Shared state value after scaling.")


class NodeTemplate(Node):
    """
    Multiply shared ``result`` by parameter ``w``.

    Computes ``result := result * w``, updates workflow state, and returns a small JSON payload
    whose structure matches :class:`NodeTemplateOutput`.
    """

    def __init__(self, node_id: str, name: str | None = None) -> None:
        """Wire this node into the graph with a stable id and optional display name."""
        super().__init__(node_id, name or "Template scale (result × w)")

    @property
    def input_state_schema(self):
        """Pydantic model for validating workflow/context state before :meth:`_do_execute` runs."""
        return NodeTemplateState

    @property
    def input_params_schema(self):
        """Pydantic model for validating direct node parameters (e.g. ``w``) before execution."""
        return NodeTemplateParams

    @property
    def output_schema(self):
        """Pydantic model validating ``NodeOutput.output['data']`` after execution (JSON branch)."""
        return NodeTemplateOutput

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        """
        Primary execution hook: main entry point where the node runs its logic and returns a :class:`~nos.core.engine.base.NodeOutput`.

        The engine invokes this after validating ``state`` and ``params_dict`` against
        :attr:`input_state_schema` and :attr:`input_params_schema`. Update ``state`` when participating
        in shared workflow state; confine side effects, I/O, and heavy work to this method or to private helpers it calls.
        """
        w = float(params_dict.get("w", 1.0))
        prev = float(state.get("result", 1.0))
        nxt = prev * w
        state["result"] = nxt
        return NodeOutput(
            output={
                "output_format": "json",
                "data": {"node_id": self.node_id, "w": w, "result": nxt},
            },
        )
