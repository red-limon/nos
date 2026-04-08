"""
ChainLink demo: single link for a linear path (node1 → node2 → node3).

Instead of 2 AlwaysLinks, one ChainLink defines the full sequence.

Module path:  nos.plugins.workflows.dev_.dev_chain_demo
Class name:   DevChainDemo
Workflow ID:  dev_chain_demo

To register:
    reg workflow dev_chain_demo DevChainDemo nos.plugins.workflows.dev_.dev_chain_demo
"""

from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, Node, NodeOutput, ChainLink


# --- State schema ---
class DevChainDemoState(BaseModel):
    """State for chain demo."""

    step1: str = Field(default="", description="Output from step 1")
    step2: str = Field(default="", description="Output from step 2")
    step3: str = Field(default="", description="Output from step 3")


# --- Inline nodes ---
class Step1Node(Node):
    """First step in the chain."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["step1"] = "done-1"
        return NodeOutput(output={"step1": "done-1"})


class Step2Node(Node):
    """Second step (via)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["step2"] = state.get("step1", "") + " → done-2"
        return NodeOutput(output={"step2": state["step2"]})


class Step3Node(Node):
    """Terminal step."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["step3"] = state.get("step2", "") + " → done-3"
        return NodeOutput(output={"step3": state["step3"]})


# --- Workflow ---
class DevChainDemo(Workflow):
    """Pipeline with ChainLink: step1 → step2 → step3 (1 link instead of 2)."""

    workflow_id = "dev_chain_demo"
    name = "ChainLink Demo (step1 → step2 → step3)"

    @property
    def state_schema(self):
        return DevChainDemoState

    def define(self):
        s1 = Step1Node(node_id="step1", name="Step 1")
        s2 = Step2Node(node_id="step2", name="Step 2")
        s3 = Step3Node(node_id="step3", name="Step 3")

        self.add_node(s1)
        self.add_node(s2)
        self.add_node(s3)

        # Single ChainLink replaces: AlwaysLink(step1→step2) + AlwaysLink(step2→step3)
        self.add_link(
            ChainLink(
                link_id="chain_1_to_3",
                from_node_id="step1",
                terminal_node_id="step3",
                via=["step2"],
                name="Step1 → Step2 → Step3",
            )
        )

        self.set_entry_node("step1")
