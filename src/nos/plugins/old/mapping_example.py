"""
Example workflow demonstrating state mapping for node isolation.

This example shows:
- How to define default state mapping at node level
- How to override mapping when adding node to workflow
- How nodes can be reused in different workflows with different mappings
"""

from pydantic import BaseModel, Field
from nos.core.engine.base import Workflow, Node, Link, NodeOutput, LinkResult
from nos.core.engine.workflow.state_mapping import (
    StateMapping,
    create_simple_mapping,
    create_namespace_mapping,
    create_identity_mapping,
)


# State schema
class MappingExampleState(BaseModel):
    """State schema for mapping example workflow."""
    # Workflow uses prefixed keys
    multiply_input_value: float = 0
    multiply_input_mult: float = 2.0
    multiply_output_result: float = 0
    final_result: float = 0


# Node with default mapping
class IsolatedMultiplyNode(Node):
    """
    Multiply node with isolated state.
    
    This node expects input keys: "value", "multiplier"
    and outputs: "result", "original_value"
    
    But workflow state uses: "multiply_input_value", "multiply_input_mult", etc.
    """
    
    def __init__(self, node_id: str = "isolated_multiply", name: str = None):
        super().__init__(node_id, name or "Isolated Multiply Node")
        # Set default mapping: simple field-to-field mapping
        from nos.core.engine.workflow.state_mapping import create_simple_mapping
        default_mapping = create_simple_mapping(
            input_fields={
                "multiply_input_value": "value",
                "multiply_input_mult": "multiplier"
            },
            output_fields={
                "result": "multiply_output_result",
                "original_value": "multiply_input_value"  # Update input value
            },
            description="Default mapping for isolated multiply node"
        )
        self.set_default_state_mapping(default_mapping)
    
    @property
    def input_schema(self):
        """Input schema expects value and multiplier."""
        class MultiplyInput(BaseModel):
            value: float = Field(..., description="Value to multiply")
            multiplier: float = Field(default=2.0, description="Multiplier")
        return MultiplyInput
    
    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """
        Execute multiplication.

        Note: state here is the isolated/mapped state, not workflow state.
        """
        value = input_dict.get("value", 0)
        multiplier = input_dict.get("multiplier", 2.0)
        
        result = value * multiplier
        
        # Update isolated state (this will be mapped back to workflow state)
        state["result"] = result
        state["original_value"] = value
        
        self.log("info", f"Multiplied {value} by {multiplier} = {result}")
        
        return NodeOutput(
            output={
                "result": result,
                "original_value": value
            },
            metadata={
                "multiplier": multiplier,
                "operation": "multiply"
            }
        )


# Example workflow using mapping
class MappingExampleWorkflow(Workflow):
    """
    Example workflow demonstrating state mapping.
    
    This workflow shows how the same node can be used with different
    state mappings in different contexts.
    """
    
    workflow_id = "mapping_example"
    name = "State Mapping Example Workflow"
    
    @property
    def state_schema(self):
        """Return state schema."""
        return MappingExampleState
    
    def define(self):
        """Define workflow structure."""
        # Create node
        multiply_node = IsolatedMultiplyNode(node_id="multiply1")
        
        # Option 1: Use node's default mapping (already set)
        # self.add_node(multiply_node)
        
        # Option 2: Override with namespace mapping
        custom_mapping = create_namespace_mapping(
            namespace="multiply",
            description="Namespace mapping for multiply node in this workflow"
        )
        self.add_node(multiply_node, state_mapping=custom_mapping)
        
        # Option 3: Use simple custom mapping
        # custom_mapping = create_simple_mapping(
        #     input_fields={
        #         "workflow_value": "value",
        #         "workflow_mult": "multiplier"
        #     },
        #     output_fields={
        #         "result": "workflow_result"
        #     }
        # )
        # self.add_node(multiply_node, state_mapping=custom_mapping)
        
        # Create a simple link that always continues
        class SimpleLink(Link):
            def _route_impl(
                self,
                state: dict,
                last_output,
                current_node_id=None,
            ) -> LinkResult:
                return LinkResult(
                    next_node_id=None,
                    should_continue=False,
                    metadata={"reason": "workflow_complete"}
                )
        
        # No links needed - single node workflow
        self.set_entry_node("multiply1")
