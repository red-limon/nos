"""
SimpleVecSumNode - Element-wise sum of two 2x2 matrices (vectors).

Based on simple_sum_node template. A and B are 2x2 matrices represented as
[[a00, a01], [a10, a11]]. Result C[i][j] = A[i][j] + B[i][j].

Pattern structure:
- Input state schema: empty
- Input params schema: a, b (2x2 matrices as list of lists)
- Output schema: a, b, sum (result matrix), status
- Metadata schema: executed_by, node_id

Module path: nos.plugins.nodes.dev_.simple_vec_sum_node
Class name:  SimpleVecSumNode
Node ID:     simple_vec_sum_node

To register:
    reg node simple_vec_sum_node SimpleVecSumNode nos.plugins.nodes.dev_.simple_vec_sum_node

To execute (params as JSON for nested structures):
    run node db simple_vec_sum_node --sync --debug --param 'a=[[1,2],[3,4]]' --param 'b=[[5,6],[7,8]]'
"""

# Base Node class and NodeOutput (typed return of _do_execute)
from nos.core.engine.base import Node, NodeOutput
# Pydantic for input/output validation schemas
from pydantic import BaseModel, Field
from typing import List


def _default_matrix_2x2() -> List[List[float]]:
    """Default 2x2 zero matrix for form compatibility (use factory to avoid mutable default)."""
    return [[0, 0], [0, 0]]


# =============================================================================
# Input/Output Schemas
# =============================================================================
#
# PATTERN: For nested structures (2x2 matrix), use List[List[float]] with
#          default_factory (avoids mutable default). Form/API can pass JSON: [[1,2],[3,4]]
# =============================================================================

class SimpleVecSumInputState(BaseModel):
    """Input state schema - workflow/context state. Empty when node has no state dependencies."""
    pass


class SimpleVecSumInputParams(BaseModel):
    """Input params schema - two 2x2 matrices to add element-wise."""
    # PATTERN: default enables validation with empty params (form compatibility)
    # 2x2 matrix as [[row0], [row1]] where each row is [col0, col1]
    a: List[List[float]] = Field(
        default_factory=_default_matrix_2x2,
        description="First 2x2 matrix [[a00,a01],[a10,a11]]"
    )
    b: List[List[float]] = Field(
        default_factory=_default_matrix_2x2,
        description="Second 2x2 matrix [[b00,b01],[b10,b11]]"
    )


class SimpleVecSumOutput(BaseModel):
    """Output schema - result of element-wise sum of two 2x2 matrices."""
    a: List[List[float]] = Field(..., description="First operand (2x2)")
    b: List[List[float]] = Field(..., description="Second operand (2x2)")
    sum: List[List[float]] = Field(..., description="Result of A + B (element-wise)")
    status: str = Field(default="success", description="Execution status")


class SimpleVecSumMetadata(BaseModel):
    """Metadata schema - execution metadata."""
    executed_by: str = Field(..., description="Node class name")
    node_id: str = Field(..., description="Node identifier")


# =============================================================================
# Node Implementation
# =============================================================================
#
# PATTERN: Node defines 4 schema properties and implements _do_execute.
# =============================================================================

def _add_matrices_2x2(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    """Element-wise sum of two 2x2 matrices."""
    return [
        [a[0][0] + b[0][0], a[0][1] + b[0][1]],
        [a[1][0] + b[1][0], a[1][1] + b[1][1]],
    ]


class SimpleVecSumNode(Node):
    """
    SimpleVecSumNode - Element-wise sum of two 2x2 matrices.
    
    Input state: empty
    Input params: a (2x2), b (2x2)
    
    Output: a, b, sum (2x2), status
    Metadata: executed_by, node_id
    """
    
    def __init__(self, node_id: str = "simple_vec_sum_node", name: str = None):
        # PATTERN: Always call super().__init__(node_id, name)
        super().__init__(node_id, name or "Simple Vec Sum")
    
    @property
    def input_state_schema(self):
        """Return Pydantic model for workflow state validation."""
        return SimpleVecSumInputState
    
    @property
    def input_params_schema(self):
        """Return Pydantic model for direct params validation."""
        return SimpleVecSumInputParams
    
    @property
    def output_schema(self):
        """Return Pydantic model for output validation."""
        return SimpleVecSumOutput
    
    @property
    def metadata_schema(self):
        """Return Pydantic model for metadata validation."""
        return SimpleVecSumMetadata
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Orchestrator: coordinates node execution. Element-wise sum of two 2x2 matrices.

        Pattern note for agents: _do_execute is the central entry point. Keep it minimal.
        For complex logic, use private methods (e.g. _compute_sum, _validate_matrices).
        This yields: (1) single responsibility per method, (2) more readable flow,
        (3) separated logic easier to maintain, (4) scalable node structure.
        """
        # PATTERN: params_dict is already validated; access keys directly
        a = params_dict["a"]
        b = params_dict["b"]
        
        # PATTERN: Use self.exec_log.log for real-time logs in the console
        self.exec_log.log("info", f"Computing A + B (element-wise)")
        self.exec_log.log("debug", f"A = {a}, B = {b}")
        
        # Business logic: element-wise matrix addition
        result_sum = _add_matrices_2x2(a, b)
        
        self.exec_log.log("info", f"Result: {result_sum}")
        
        # PATTERN: output and metadata must conform to output_schema and metadata_schema
        output = {
            "a": a,
            "b": b,
            "sum": result_sum,
            "status": "success",
        }
        metadata = {
            "executed_by": "SimpleVecSumNode",
            "node_id": self.node_id,
        }
        
        return NodeOutput(output=output, metadata=metadata)
