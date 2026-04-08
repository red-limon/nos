"""
SimpleDotNode - Multiplies two numbers (a * b).

Based on simple_sum_node template. Demonstrates scalar product (dot product of two scalars).

Pattern structure:
- Input state schema: empty
- Input params schema: a, b (floats)
- Output schema: a, b, product, status
- Metadata schema: executed_by, node_id

Module path: nos.plugins.nodes.dev_.simple_dot_node
Class name:  SimpleDotNode
Node ID:     simple_dot_node

To register:
    reg node simple_dot_node SimpleDotNode nos.plugins.nodes.dev_.simple_dot_node

To execute:
    run node db simple_dot_node --sync --debug --param a=5 --param b=3
"""

# Base Node class and NodeOutput (typed return of _do_execute)
from nos.core.engine.base import Node, NodeOutput
# Pydantic for input/output validation schemas
from pydantic import BaseModel, Field


# =============================================================================
# Input/Output Schemas
# =============================================================================
#
# PATTERN: Use default values for params when running with --debug form,
#          so validation passes with empty {} before the user fills the form.
# =============================================================================

class SimpleDotInputState(BaseModel):
    """Input state schema - workflow/context state. Empty when node has no state dependencies."""
    pass


class SimpleDotInputParams(BaseModel):
    """Input params schema - two scalars to multiply."""
    # PATTERN: default=0 enables validation with empty params (form compatibility)
    a: float = Field(default=0, description="First number")
    b: float = Field(default=0, description="Second number")


class SimpleDotOutput(BaseModel):
    """Output schema - structure of the result (product of a and b)."""
    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    product: float = Field(..., description="Result of a * b")
    status: str = Field(default="success", description="Execution status")


class SimpleDotMetadata(BaseModel):
    """Metadata schema - execution metadata."""
    executed_by: str = Field(..., description="Node class name")
    node_id: str = Field(..., description="Node identifier")


# =============================================================================
# Node Implementation
# =============================================================================
#
# PATTERN: Node defines 4 schema properties and implements _do_execute.
# =============================================================================

class SimpleDotNode(Node):
    """
    SimpleDotNode - Multiplies two numbers a and b.
    
    Input state: empty
    Input params: a (float), b (float)
    
    Output: a, b, product, status
    Metadata: executed_by, node_id
    """
    
    def __init__(self, node_id: str = "simple_dot_node", name: str = None):
        # PATTERN: Always call super().__init__(node_id, name)
        super().__init__(node_id, name or "Simple Dot")
    
    @property
    def input_state_schema(self):
        """Return Pydantic model for workflow state validation."""
        return SimpleDotInputState
    
    @property
    def input_params_schema(self):
        """Return Pydantic model for direct params validation."""
        return SimpleDotInputParams
    
    @property
    def output_schema(self):
        """Return Pydantic model for output validation."""
        return SimpleDotOutput
    
    @property
    def metadata_schema(self):
        """Return Pydantic model for metadata validation."""
        return SimpleDotMetadata
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Orchestrator: coordinates node execution. Multiplies a * b.

        Pattern note for agents: _do_execute is the central entry point. Keep it minimal.
        For complex logic, use private methods (e.g. _compute_product, _validate_input).
        This yields: (1) single responsibility per method, (2) more readable flow,
        (3) separated logic easier to maintain, (4) scalable node structure.
        """
        # PATTERN: params_dict is already validated; access keys directly
        a = params_dict["a"]
        b = params_dict["b"]
        
        # PATTERN: Use self.exec_log.log for real-time logs in the console
        self.exec_log.log("info", f"Computing {a} * {b}")
        
        # Business logic: scalar product
        product = a * b
        
        self.exec_log.log("info", f"Result: {product}")
        
        return NodeOutput(
            output={
                "output_format": "json",
                "data": {"a": a, "b": b, "product": product, "status": "success"},
            },
            metadata={
                "executed_by": "SimpleDotNode",
                "node_id": self.node_id,
            },
        )
