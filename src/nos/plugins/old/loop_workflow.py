"""
Example workflow: Loop workflow.

This workflow demonstrates:
- Two nodes (Counter, Increment)
- One loop link (loops until condition is met)
"""

from typing import Any, Optional

from pydantic import BaseModel
from nos.core.engine.base import Workflow, Node, Link, NodeOutput, LinkResult


# State schema
class LoopState(BaseModel):
    """State schema for loop workflow."""
    counter: int = 0
    max_iterations: int = 5
    completed: bool = False


# Nodes
class CounterNode(Node):
    """Counter node - initializes or reads counter."""

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Initialize or read counter."""
        counter = state.get("counter", 0)
        
        self.log("info", f"Counter value: {counter}")
        
        return NodeOutput(output={"counter": counter})


class IncrementNode(Node):
    """Increment node - increments counter."""

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Increment counter."""
        counter = state.get("counter", 0)
        new_counter = counter + 1
        
        state["counter"] = new_counter
        
        self.log("info", f"Incremented counter: {counter} -> {new_counter}")
        
        return NodeOutput(output={"counter": new_counter})


# Links
class LoopLink(Link):
    """Loop link - loops until counter >= max_iterations."""
    
    def _route_impl(
        self,
        state: dict,
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """Route based on loop condition."""
        counter = state.get("counter", 0)
        max_iterations = state.get("max_iterations", 5)
        
        if counter < max_iterations:
            # Continue loop - go back to increment
            self.log("info", f"Looping: {counter} < {max_iterations}, continuing")
            return LinkResult(
                next_node_id=self.to_node_id,
                should_continue=True,
                metadata={"loop": True, "counter": counter, "max": max_iterations}
            )
        else:
            # Loop complete - stop
            state["completed"] = True
            self.log("info", f"Loop complete: {counter} >= {max_iterations}, stopping")
            return LinkResult(
                next_node_id=None,
                should_continue=False,
                metadata={"loop": False, "counter": counter, "max": max_iterations}
            )


# Workflow
class LoopWorkflow(Workflow):
    """Loop workflow example."""
    
    workflow_id = "loop_example"
    name = "Loop Example Workflow"
    
    @property
    def state_schema(self):
        """Return state schema."""
        return LoopState
    
    def define(self):
        """Define workflow structure."""
        # Create nodes
        counter_node = CounterNode(node_id="counter", name="Counter Node")
        increment_node = IncrementNode(node_id="increment", name="Increment Node")
        
        # Add nodes
        self.add_node(counter_node)
        self.add_node(increment_node)
        
        # Create links
        # Link from counter to increment (first iteration)
        start_link = LoopLink(
            link_id="start_loop",
            from_node_id="counter",
            to_node_id="increment",
            name="Start Loop"
        )
        
        # Link from increment back to increment (loop)
        loop_link = LoopLink(
            link_id="continue_loop",
            from_node_id="increment",
            to_node_id="increment",
            name="Continue Loop"
        )
        
        # Add links
        self.add_link(start_link)
        self.add_link(loop_link)
        
        # Set entry node
        self.set_entry_node("counter")
