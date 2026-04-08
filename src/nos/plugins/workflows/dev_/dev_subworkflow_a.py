"""
Child workflow for composable example (NodeWorkflow / add_node_workflow).

Workflow A: fetch_data → validate.
Used as sub-workflow by dev_subworkflow_b (workflow B runs A via add_node_workflow, then enrich → save).

Module path:  nos.plugins.workflows.dev_.dev_subworkflow_a
Class name:   DevSubworkflowA
Workflow ID:  dev_subworkflow_a

To register:
    reg workflow dev_subworkflow_a DevSubworkflowA nos.plugins.workflows.dev_.dev_subworkflow_a
"""

from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, Node, NodeOutput, AlwaysLink


# --- State schema (child workflow) ---
class DevSubworkflowAState(BaseModel):
    """State for child pipeline A."""

    raw_data: str = Field(default="", description="Fetched raw data")
    validated_data: str = Field(default="", description="Validated result")


# --- Inline nodes for workflow A ---
class FetchDataNode(Node):
    """Produces sample raw_data (for demo)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        raw = params_dict.get("sample") or state.get("raw_data") or "sample from A"
        state["raw_data"] = raw
        return NodeOutput(output=dict(raw_data=raw))


class ValidateNode(Node):
    """Validates raw_data and sets validated_data."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        raw = state.get("raw_data", "")
        validated = raw.strip() or "(empty)"
        state["validated_data"] = validated
        return NodeOutput(output=dict(validated_data=validated))


# --- Workflow A ---
class DevSubworkflowA(Workflow):
    """Child pipeline: Fetch → Validate. Used as sub-workflow by B."""

    workflow_id = "dev_subworkflow_a"
    name = "Subworkflow A (fetch → validate)"

    @property
    def state_schema(self):
        return DevSubworkflowAState

    def define(self):
        fetch = FetchDataNode(node_id="fetch_data", name="Fetch data")
        validate = ValidateNode(node_id="validate", name="Validate")

        self.add_node(fetch)
        self.add_node(validate)
        self.add_link(
            AlwaysLink(
                link_id="fetch_to_validate",
                from_node_id="fetch_data",
                to_node_id="validate",
                name="Fetch → Validate",
            )
        )
        self.set_entry_node("fetch_data")
