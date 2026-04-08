from pydantic import BaseModel, Field
from nos.core.engine.base import Node, NodeOutput

class MyFirstNodeInput(BaseModel):
    name: str = Field(default="World", description="Name to greet")

class MyFirstNodeOutput(BaseModel):
    message: str = Field(default="Hello, World!", description="Greeting message")

class MyFirstNode(Node):
    def __init__(self, node_id: str = "my_first_node", name: str = None):
        super().__init__(node_id, name)

    @property
    def input_schema(self):
        """Return input schema."""
        return MyFirstNodeInput
    
    @property
    def output_schema(self):
        """Return output schema."""
        return MyFirstNodeOutput
    
    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """Execute the node."""
        name = input_dict.get("name", "World")
        self.log("debug", f"Hello, {name}!", input_name=name)
        return NodeOutput(output={"message": f"Hello, {name}!"}, metadata={"name": name})