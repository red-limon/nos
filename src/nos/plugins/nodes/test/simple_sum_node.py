"""
SimpleSumNode - Sums two numbers (a + b).

REFERENCE TEMPLATE: This module serves as the standard implementation pattern
for Hythera Node plugins. Use it as a few-shot prompt template for developer
agents when creating new nodes.

Pattern structure:
- Input state schema: workflow context (empty for standalone nodes)
- Input params schema: direct parameters from user/API/form
- Output schema: structure of the result
- Metadata schema: execution metadata (executed_by, node_id, etc.)

Module path: nos.plugins.nodes.dev_.simple_sum_node
Class name:  SimpleSumNode
Node ID:     simple_sum_node

To register:
    reg node simple_sum_node SimpleSumNode nos.plugins.nodes.dev_.simple_sum_node

To execute:
    run node db simple_sum_node --sync --debug --param a=5 --param b=3
"""

# Base Node class, NodeOutput and schema base classes
from typing import ClassVar

from nos.core.engine.base import Node, NodeOutput, NodeInputSchema, NodeStateSchema
# Pydantic for input/output validation schemas
from pydantic import BaseModel, Field


# =============================================================================
# Input/Output Schemas
# =============================================================================
#
# Each schema is a Pydantic BaseModel. The engine validates inputs against
# input_state_schema and input_params_schema before _do_execute; output and
# metadata are validated against output_schema and metadata_schema after.
#
# Field(..., description="...")     = required (no default)
# Field(default=..., description="") = optional with default.
# PATTERN: Use default values for params when running with --debug form,
#          so validation passes with empty {} before the user fills the form.
# =============================================================================

class SimpleSumInputState(NodeStateSchema):
    """Input state schema - workflow/context state. Empty when node has no state dependencies."""
    pass


class SimpleSumInputParams(NodeInputSchema):
    """Input params schema - direct parameters. Fields with default allow form debug mode."""
    # PATTERN: default=0 enables validation with empty params (form compatibility)
    a: float = Field(default=0, description="First number")
    b: float = Field(default=0, description="Second number")


class SimpleSumOutput(BaseModel):
    """Output schema - structure of the result returned by the node."""
    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    sum: float = Field(..., description="Result of a + b")
    status: str = Field(default="success", description="Execution status")


class SimpleSumMetadata(BaseModel):
    """Metadata schema - execution metadata (who ran it, which node, etc.)."""
    executed_by: str = Field(..., description="Node class name")
    node_id: str = Field(..., description="Node identifier")


# =============================================================================
# Node Implementation
# =============================================================================
#
# PATTERN: Node must define 4 schema properties and implement _do_execute.
# - input_state_schema, input_params_schema: validate incoming data
# - output_schema, metadata_schema: validate outgoing data
# - _do_execute(state_dict, params_dict) -> NodeOutput: main logic
# - self.exec_log: emit real-time logs/events to the console
# =============================================================================

class SimpleSumNode(Node):
    """
    SimpleSumNode - Sums two numbers a and b.
    
    Input state: empty
    Input params: a (float), b (float)
    
    Output: a, b, sum, status
    Metadata: executed_by, node_id
    """

    node_id: ClassVar[str] = "simple_sum_node"

    def __init__(self, node_id: str | None = None, name: str = None):
        # Base Node resolves node_id from class when omitted (same pattern as Workflow).
        super().__init__(node_id, name or "Simple Sum")
    
    @property
    def input_state_schema(self):
        """Return Pydantic model for workflow state validation."""
        return SimpleSumInputState
    
    @property
    def input_params_schema(self):
        """Return Pydantic model for direct params validation."""
        return SimpleSumInputParams
    
    @property
    def output_schema(self):
        """Return Pydantic model for output validation."""
        return SimpleSumOutput
    
    @property
    def metadata_schema(self):
        """Return Pydantic model for metadata validation."""
        return SimpleSumMetadata
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Orchestrator: coordinates node execution. Returns NodeOutput(output=..., metadata=...).

        Pattern note for agents: _do_execute is the central entry point. Keep it minimal.
        For complex logic, use private methods (e.g. _compute_result, _validate_input).
        This yields: (1) single responsibility per method, (2) more readable flow,
        (3) separated logic easier to maintain, (4) scalable node structure.
        """
        # PATTERN: params_dict is already validated; access keys directly
        a = params_dict["a"]
        b = params_dict["b"]
        
        # PATTERN: Use self.exec_log.log for real-time logs in the console
        self.exec_log.log("info",event="computing", message=f"Computing {a} + {b}")
        
        # Business logic
        result_sum = a + b
        
        self.exec_log.log("info",event="result", message=f"{result_sum}")
        
        # PATTERN: NodeOutput.output must be {"output_format": str, "data": Any}.
        # output_format tells the Output tab how to render data:
        #   "json"  → data is a dict/list  (default)
        #   "text"  → data is a string
        #   "html"  → data is an HTML string
        #   "table" → data is {"columns": [...], "rows": [[...]]}
        #   "code"  → data is a source-code string
        # CLI --output_format overrides this value; fallback is "json".
        return NodeOutput(
            output={
                "output_format": "code",
                "data": f"{a} + {b} = {result_sum}",
           },
            metadata={
                "executed_by": "SimpleSumNode",
                "node_id": self.node_id,
            },
        )

if __name__ == "__main__":
    node = SimpleSumNode()
    result = node.run(state={}, input_params={"a": 3, "b": 5})
    print("sum:", result.response.output.get("data", {}).get("sum"))
    print("metadata:", result.response.metadata)
    print("elapsed_time:", result.elapsed_time)
