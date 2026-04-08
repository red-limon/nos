"""
Minimal two-node workflow template: sequential :class:`~reference_templates.node_template.NodeTemplate`
steps linked by :class:`~nos.core.engine.base.AlwaysLink`.
"""

from __future__ import annotations

from pydantic import Field

from nos.core.engine.base import AlwaysLink, NodeStateSchema, Workflow

from reference_templates.node_template import NodeTemplate


class WorkflowTemplateState(NodeStateSchema):
    """
    Aggregate shared state for :class:`WorkflowTemplate`.

    This is the workflow’s :meth:`~nos.core.engine.workflow.workflow.Workflow.state_schema`;
    it describes the full state object passed between nodes. Individual nodes declare their own
    :class:`~reference_templates.node_template.NodeTemplateState` for validation of the slice
    they consume; here both use the same ``result`` key so they stay consistent.
    """

    result: float = Field(
        default=1.0,
        description="Numeric accumulator flowing through the workflow (scaled by each NodeTemplate).",
    )


class WorkflowTemplate(Workflow):
    """
    Reference linear workflow: two :class:`~reference_templates.node_template.NodeTemplate`
    instances with distinct ``w`` and an :class:`~nos.core.engine.base.AlwaysLink` between them.

    **Graph**
        ``scale_a`` (``w=2.0``) → ``scale_b`` (``w=3.0``); entry is ``scale_a``.

    **State**  
    :class:`WorkflowTemplateState` with ``result`` defaulting to ``1.0`` before the first node runs.
    """

    workflow_id = "workflow_template"
    name = "Workflow template (two scale nodes)"

    @property
    def state_schema(self):
        return WorkflowTemplateState

    def define(self) -> None:
        scale_a = NodeTemplate(node_id="scale_a", name="Scale × w₁")
        scale_b = NodeTemplate(node_id="scale_b", name="Scale × w₂")

        self.add_node(scale_a, default_input_params={"w": 2.0})
        self.add_node(scale_b, default_input_params={"w": 3.0})

        self.add_link(
            AlwaysLink(
                link_id="scale_a_to_scale_b",
                from_node_id="scale_a",
                to_node_id="scale_b",
                name="scale_a → scale_b",
            )
        )
        self.set_entry_node("scale_a")
