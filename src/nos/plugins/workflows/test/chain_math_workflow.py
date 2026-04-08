"""
Two-node workflow for tests: shared state field ``result``.

1. **sum_ab** — reads input params ``a`` and ``b``, writes ``result = a + b`` into shared state.
2. **mul_w** — reads shared ``result`` and param ``w``, writes ``result = result * w``.

State schema: a single numeric ``result`` (final value after both steps).

Module path: ``nos.plugins.workflows.test.chain_math_workflow``
Class: ``ChainMathWorkflow``
Workflow ID: ``test_chain_math``

Register (optional)::

    reg workflow test_chain_math ChainMathWorkflow nos.plugins.workflows.test.chain_math_workflow

Run module directly::

    python -m nos.plugins.workflows.test.chain_math_workflow

**Execution log.** When you call :meth:`~nos.core.engine.base.Workflow.run` without ``exec_log``, the engine
creates an in-memory :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` inside
:meth:`~nos.core.engine.workflow_engine.WorkflowEngine.execute_sync` (see
``create_default_workflow_exec_log``). That buffer records events and mirrors them to Python
:mod:`logging` at **INFO** for ``nos.core.execution_log.event_log_buffer``. If the process has no
logging configuration, the interpreter only prints **WARNING** and above, so those INFO lines do
not appear on the terminal—use ``logging.basicConfig(level=logging.INFO)`` (as in ``main`` below)
or inspect ``result.event_logs``.
"""

from __future__ import annotations

import logging

from pydantic import Field

from nos.core.engine.base import AlwaysLink, Node, NodeOutput, NodeStateSchema, Workflow
from nos.core.engine.base import NodeInputSchema


class ChainMathState(NodeStateSchema):
    """Shared workflow state: one numeric result field."""

    result: float = Field(default=0.0, description="Intermediate / final numeric result")


class SumABParams(NodeInputSchema):
    a: float = Field(default=0.0, description="Summand a")
    b: float = Field(default=0.0, description="Summand b")


class MulWParams(NodeInputSchema):
    w: float = Field(default=1.0, description="Multiplier applied to shared result")


class SumABNode(Node):
    """Writes ``result = a + b`` into shared state."""

    def __init__(self, node_id: str = "sum_ab", name: str | None = None):
        super().__init__(node_id, name or "Sum a + b")

    @property
    def input_state_schema(self):
        return ChainMathState

    @property
    def input_params_schema(self):
        return SumABParams

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        a = float(params_dict.get("a", 0.0))
        b = float(params_dict.get("b", 0.0))
        s = a + b
        self.exec_log.log("info", event="result", message=f"{s}")
        state_dict["result"] = s
        return NodeOutput(
            output={"output_format": "json", "data": {"step": "sum", "a": a, "b": b, "result": s}},
        )


class MulWNode(Node):
    """Writes ``result = result * w`` into shared state."""

    def __init__(self, node_id: str = "mul_w", name: str | None = None):
        super().__init__(node_id, name or "Multiply by w")

    @property
    def input_state_schema(self):
        return ChainMathState

    @property
    def input_params_schema(self):
        return MulWParams

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        w = float(params_dict.get("w", 1.0))
        prev = float(state_dict.get("result", 0.0))
        out = prev * w
        state_dict["result"] = out
        return NodeOutput(
            output={"output_format": "json", "data": {"step": "mul", "w": w, "result": out}},
        )


class ChainMathWorkflow(Workflow):
    """Linear workflow: sum then multiply (defaults a=10, b=3, w=2 → result 26)."""

    workflow_id = "test_chain_math"
    name = "Test chain math"

    @property
    def state_schema(self):
        return ChainMathState

    def define(self) -> None:
        sum_n = SumABNode(node_id="sum_ab", name="Sum a+b")
        mul_n = MulWNode(node_id="mul_w", name="Times w")
        self.add_node(sum_n, default_input_params={"a": 10.0, "b": 3.0})
        self.add_node(mul_n, default_input_params={"w": 2.0})
        self.add_link(
            AlwaysLink(
                link_id="sum_to_mul",
                from_node_id="sum_ab",
                to_node_id="mul_w",
                name="sum → mul",
            )
        )
        self.set_entry_node("sum_ab")


def main() -> None:
    # EventLogBuffer mirrors execution lines to logging at INFO; without a handler, Python’s root
    # default is WARNING-only, so nothing appears on the terminal.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Use base Workflow.load so ``python -m this.module`` works: import_module loads a distinct
    # module object from __main__, and ChainMathWorkflow.load would compare unequal class identities.
    wf = Workflow.load(
        "dev",
        workflow_id="test_chain_math",
        module_path="nos.plugins.workflows.test.chain_math_workflow",
        class_name="ChainMathWorkflow",
    )
    run_request = {
        "invocation": "module_entrypoint",
        "correlation_id": "chain-math-demo-01",
        "tenant": "local-dev",
    }
    result = wf.run(
        initial_state={},
        debug_mode="trace",
        request=run_request,
    )
    print("status:", result.status)
    print("correlation_id (from request):", run_request.get("correlation_id"))
    print("event_logs (structured events in result):", len(result.event_logs))
    print("final shared state:", result.state)
    print("output data:", (result.response.output or {}).get("data"))


if __name__ == "__main__":
    main()
