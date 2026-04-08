"""
Example standalone nodes that can be executed independently.

These nodes demonstrate:
- Nodes that can be executed outside of a workflow
- Simple processing nodes
- Nodes with input/output schemas
"""

from pydantic import BaseModel, Field
from nos.core.engine.base import Node, NodeOutput


# Input/Output schemas for standalone nodes
class MultiplyInput(BaseModel):
    """Input schema for MultiplyNode."""
    value: float = Field(..., description="Value to multiply")
    multiplier: float = Field(default=2.0, description="Multiplier")


class MultiplyOutput(BaseModel):
    """Output schema for MultiplyNode."""
    result: float = Field(..., description="Multiplication result")
    original_value: float = Field(..., description="Original input value")


class GreetInput(BaseModel):
    """Input schema for GreetNode."""
    name: str = Field(..., description="Name to greet")
    greeting: str = Field(default="Hello", description="Greeting message")


class GreetOutput(BaseModel):
    """Output schema for GreetNode."""
    message: str = Field(..., description="Greeting message")
    name: str = Field(..., description="Name that was greeted")


# Standalone Nodes
class MultiplyNode(Node):
    """
    Multiply node - multiplies a value by a multiplier.
    
    Can be executed standalone or in a workflow.
    """
    
    def __init__(self, node_id: str = "multiply", name: str = None):
        super().__init__(node_id, name or "Multiply Node")
    
    @property
    def input_schema(self):
        """Return input schema."""
        return MultiplyInput
    
    @property
    def output_schema(self):
        """Return output schema."""
        return MultiplyOutput
    
    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Multiply value by multiplier."""
        value = input_dict.get("value", state.get("value", 0))
        multiplier = input_dict.get("multiplier", state.get("multiplier", 2.0))
        
        result = value * multiplier
        
        # Update state
        state["value"] = result
        state["multiplier"] = multiplier
        
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


class GreetNode(Node):
    """
    Greet node - generates a greeting message.
    
    Can be executed standalone or in a workflow.
    """
    
    def __init__(self, node_id: str = "greet", name: str = None):
        super().__init__(node_id, name or "Greet Node")
    
    @property
    def input_schema(self):
        """Return input schema."""
        return GreetInput
    
    @property
    def output_schema(self):
        """Return output schema."""
        return GreetOutput
    
    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Generate greeting message."""
        name = input_dict.get("name", state.get("name", "World"))
        greeting = input_dict.get("greeting", state.get("greeting", "Hello"))
        
        message = f"{greeting}, {name}!"
        
        # Update state
        state["name"] = name
        state["greeting"] = greeting
        state["message"] = message
        
        self.log("info", f"Generated greeting: {message}")
        
        return NodeOutput(
            output={
                "message": message,
                "name": name
            },
            metadata={
                "greeting": greeting
            }
        )


class SumInput(BaseModel):
    """Input schema for SumNode."""
    a: float = Field(default=1.0, description="First value")
    b: float = Field(default=2.0, description="Second value")


class SumNode(Node):
    """
    Sum node - sums values from state or input.
    
    Can be executed standalone or in a workflow.
    """
    
    def __init__(self, node_id: str = "sum", name: str = None):
        super().__init__(node_id, name or "Sum Node")
    
    @property
    def input_schema(self):
        """Return input schema."""
        return SumInput
    
    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Sum values from state."""
        values = input_dict.get("values", [])
        if not values:
            a_raw = input_dict.get("a", 0)
            b_raw = input_dict.get("b", 0)
            try:
                a_val = float(a_raw) if a_raw not in (None, "") else 0.0
                b_val = float(b_raw) if b_raw not in (None, "") else 0.0
                values = [a_val, b_val]
            except (TypeError, ValueError):
                values = [0.0, 0.0]

        if isinstance(values, list):
            values = [float(v) if not isinstance(v, (int, float)) else v for v in values]
        result = sum(values) if isinstance(values, list) else 0
        
        # Update state
        state["sum"] = result
        state["values"] = values
        
        self.log("info", f"Summed values {values} = {result}")
        
        return NodeOutput(
            output={
                "result": result,
                "values": values
            },
            metadata={
                "count": len(values) if isinstance(values, list) else 0
            }
        )
