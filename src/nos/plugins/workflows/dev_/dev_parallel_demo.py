"""
Workflow demo: ParallelNode runs fetch_a and fetch_b in parallel, then format_results.

Shows:
- How to define child nodes (fetch_a, fetch_b) and pass their IDs to ParallelNode
- How parallel_node_ids in initial_state tells ParallelNode which nodes to run
- FormatResultsNode as the next step after the parallel block

Module path:  nos.plugins.workflows.dev_.dev_parallel_demo
Class name:   DevParallelDemo
Workflow ID:  dev_parallel_demo

To register:
    reg workflow dev_parallel_demo DevParallelDemo nos.plugins.workflows.dev_.dev_parallel_demo

To run:
    run workflow db dev_parallel_demo
"""

from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, Node, NodeOutput, ParallelNode, AlwaysLink


# --- State schema ---
class DevParallelDemoState(BaseModel):
    """State for parallel demo workflow."""

    parallel_node_ids: list[str] = Field(
        default_factory=lambda: ["fetch_a", "fetch_b"],
        description="Node IDs for ParallelNode to run in parallel",
    )
    result_a: str = Field(default="", description="Output from fetch_a")
    result_b: str = Field(default="", description="Output from fetch_b")
    merged: str = Field(default="", description="Combined result from format_results")


# --- Child nodes (run by ParallelNode) ---
class FetchANode(Node):
    """Produces result_a (simulates fetch from source A)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["result_a"] = "data from A"
        return NodeOutput(output={"result_a": "data from A"})


class FetchBNode(Node):
    """Produces result_b (simulates fetch from source B)."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        state["result_b"] = "data from B"
        return NodeOutput(output={"result_b": "data from B"})


# --- Post-parallel node ---
class FormatResultsNode(Node):
    """Runs after ParallelNode. Combines result_a and result_b into merged."""

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        a = state.get("result_a", "")
        b = state.get("result_b", "")
        merged = f"{a} | {b}"
        state["merged"] = merged
        return NodeOutput(output={"merged": merged})


# --- Workflow ---
class DevParallelDemo(Workflow):
    """
    Parallel demo: parallel (fetch_a + fetch_b) → format_results.

    - fetch_a and fetch_b are added as normal nodes but have no incoming links
    - ParallelNode runs them in parallel when it executes
    - parallel_node_ids in state tells ParallelNode which node IDs to run
    """

    workflow_id = "dev_parallel_demo"
    name = "Parallel Demo (fetch_a + fetch_b → format)"

    @property
    def state_schema(self):
        return DevParallelDemoState

    def define(self):
        # 1. Child nodes (run BY ParallelNode, not by the engine directly)
        self.add_node(FetchANode(node_id="fetch_a", name="Fetch A"))
        self.add_node(FetchBNode(node_id="fetch_b", name="Fetch B"))

        # 2. ParallelNode: runs fetch_a and fetch_b; reads node_ids from state.parallel_node_ids
        self.add_node(ParallelNode(node_id="parallel", name="Run in parallel"))

        # 3. Post-parallel node
        self.add_node(FormatResultsNode(node_id="format_results", name="Format results"))

        # 4. Links: engine runs parallel → format_results (fetch_a and fetch_b are never
        #    reached by the engine; ParallelNode invokes them internally)
        self.add_link(
            AlwaysLink(
                link_id="parallel_to_format",
                from_node_id="parallel",
                to_node_id="format_results",
                name="Parallel → Format",
            )
        )

        self.set_entry_node("parallel")
