from nos.core.engine.base import Node, NodeOutput
from pydantic import BaseModel, Field

class ReverseInputParams(BaseModel):
  text: str = Field(default="", description="Text to reverse")

class ReverseOutput(BaseModel):
  original: str = Field(..., description="Original text")
  reversed: str = Field(..., description="Reversed text")

class ReverseNode(Node):

  def __init__(self, node_id: str = "reverse", name: str = None):
    super().__init__(node_id, name or "Reverse String")

  @property
  def input_state_schema(self): return None

  @property
  def input_params_schema(self): return ReverseInputParams

  @property
  def output_schema(self): return ReverseOutput
  def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
    text = params_dict.get("text", "")
    return NodeOutput(
        output={"original": text, "reversed": text[::-1]},
        metadata={"executed_by": "ReverseNode"}
    )