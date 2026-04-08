"""
Example workflow: If-Then conditional workflow.

This workflow demonstrates:
- Two nodes (Start, Process)
- One conditional link (if condition is met, continue; else stop)
"""

from typing import Any, Optional

from pydantic import BaseModel
from nos.core.engine.base import Workflow, Node, Link, NodeOutput, LinkResult


# State schema
class IfThenState(BaseModel):
    """State schema for if-then workflow."""
    value: int = 0
    threshold: int = 10
    processed: bool = False


# Nodes
class StartNode(Node):
    """Start node - initializes value."""

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Initialize value in state."""
        value = state.get("value", 0)
        if value == 0:
            value = 5  # Default value
        
        state["value"] = value
        self.log("info", f"Initialized value: {value}")
        
        return NodeOutput(output={"value": value})


class ProcessNode(Node):
    """Process node - doubles the value."""

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Double the value."""
        value = state.get("value", 0)
        new_value = value * 2
        
        state["value"] = new_value
        state["processed"] = True
        
        self.log("info", f"Processed value: {value} -> {new_value}")
        
        return NodeOutput(output={"value": new_value, "processed": True})


# Links
class ConditionalLink(Link):
    """Conditional link - continues if value >= threshold."""
    
    def _route_impl(
        self,
        state: dict,
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """Route based on value threshold."""
        value = state.get("value", 0)
        threshold = state.get("threshold", 10)
        
        if value >= threshold:
            self.log("info", f"Condition met: {value} >= {threshold}, continuing")
            return LinkResult(
                next_node_id=self.to_node_id,
                should_continue=True,
                metadata={"condition": "met", "value": value, "threshold": threshold}
            )
        else:
            self.log("info", f"Condition not met: {value} < {threshold}, stopping")
            return LinkResult(
                next_node_id=None,
                should_continue=False,
                metadata={"condition": "not_met", "value": value, "threshold": threshold}
            )


# Workflow
class IfThenWorkflow(Workflow):
    """If-Then conditional workflow example."""
    
    workflow_id = "if_then_example"
    name = "If-Then Example Workflow"
    
    @property
    def state_schema(self):
        """Return state schema."""
        return IfThenState
    
    def define(self):
        """Define workflow structure."""
        # Create nodes
        start_node = StartNode(node_id="start", name="Start Node")
        process_node = ProcessNode(node_id="process", name="Process Node")
        
        # Add nodes
        self.add_node(start_node)
        self.add_node(process_node)
        
        # Create link
        conditional_link = ConditionalLink(
            link_id="check_threshold",
            from_node_id="start",
            to_node_id="process",
            name="Check Threshold"
        )
        
        # Add link
        self.add_link(conditional_link)
        
        # Set entry node
        self.set_entry_node("start")
