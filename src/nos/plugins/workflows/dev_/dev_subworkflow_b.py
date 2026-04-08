"""
Parent workflow: runs child workflow A via add_node_workflow, then enrich → save.

Composable flow (Option 3): B uses add_node_workflow("dev_subworkflow_a"),
then EnrichNode, then SaveNode. Links stay node-to-node.

Module path:  nos.plugins.workflows.dev_.dev_subworkflow_b
Class name:   DevSubworkflowB
Workflow ID:  dev_subworkflow_b

To register:
    reg workflow dev_subworkflow_b DevSubworkflowB nos.plugins.workflows.dev_.dev_subworkflow_b

Prerequisite: register dev_subworkflow_a first (child workflow).
"""

from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, Node, NodeOutput, AlwaysLink


# --- State schema (parent workflow) ---
class DevSubworkflowBState(BaseModel):
    """State for parent pipeline B (includes sub-workflow result)."""

    raw_data: str = Field(default="", description="From sub-workflow or input")
    validated_data: str = Field(default="", description="From sub-workflow A")
    enriched: str = Field(default="", description="After enrich node")
    saved: bool = Field(default=False, description="After save node")


# --- Enrich and Save (inline nodes for B) ---
class EnrichNode(Node):
    """Enriches validated_data (e.g. prefix)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        validated = state.get("validated_data", "")
        enriched = f"[enriched] {validated}"
        state["enriched"] = enriched
        return NodeOutput(output=dict(enriched=enriched))


class SaveNode(Node):
    """Marks as saved (demo)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["saved"] = True
        return NodeOutput(output=dict(saved=True))


# --- Workflow B ---
class DevSubworkflowB(Workflow):
    """Parent pipeline: sub_wf_A → enrich → save. Demonstrates composable workflows."""

    workflow_id = "dev_subworkflow_b"
    name = "Subworkflow B (A → enrich → save)"

    @property
    def state_schema(self):
        return DevSubworkflowBState

    def define(self):
        self.add_node_workflow(
            "dev_subworkflow_a",
            node_id="sub_wf_a",
            name="Run workflow A",
        )
        enrich = EnrichNode(node_id="enrich", name="Enrich")
        save = SaveNode(node_id="save", name="Save")

        self.add_node(enrich)
        self.add_node(save)

        self.add_link(
            AlwaysLink(
                link_id="sub_to_enrich",
                from_node_id="sub_wf_a",
                to_node_id="enrich",
                name="Sub A → Enrich",
            )
        )
        self.add_link(
            AlwaysLink(
                link_id="enrich_to_save",
                from_node_id="enrich",
                to_node_id="save",
                name="Enrich → Save",
            )
        )
        self.set_entry_node("sub_wf_a")
