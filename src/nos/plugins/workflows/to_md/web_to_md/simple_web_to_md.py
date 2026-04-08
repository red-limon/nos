"""
SimpleWebToMD workflow — fetches content from URL (:class:`BaseRequestsNode`) and writes to file (:class:`FileWriteNode`).

Structure:
- State schema: url (required), response (from BaseRequestsNode), save_path, filename, size, content (from FileWriteNode)
- Node 1: BaseRequestsNode (``plugins/nodes/web_scraper/base_requests.py``)
- Node 2: FileWriteNode (``plugins/nodes/file_io/file_write_node.py``)
- Link: AlwaysLink (default)
"""

import os
from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, NodeOutput, AlwaysLink
from nos.core.engine.workflow.state_mapping import create_simple_mapping
from nos.plugins.nodes.web_scraper.base_requests import BaseRequestsNode
from nos.plugins.nodes.file_io.file_write_node import FileWriteNode


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------
# Defines the shared workflow state. All fields are exposed to callers and
# can be read after workflow completion. Node wrappers (below) write their
# outputs into state so map_to_shared can propagate them.


class SimpleWebToMDState(BaseModel):
    """Workflow state. url is required."""

    url: str = Field(..., description="URL to fetch (required)")
    response: str = Field(default="", description="Fetched content from BaseRequestsNode")
    save_path: str = Field(default="", description="Directory where file was saved (from FileWriteNode)")
    filename: str = Field(default="", description="Filename including extension (from FileWriteNode)")
    size: int = Field(default=0, description="Size in bytes of written content (from FileWriteNode)")
    content: str = Field(default="", description="Content that was written to file (from FileWriteNode)")


# ---------------------------------------------------------------------------
# Node wrappers (for state propagation)
# ---------------------------------------------------------------------------
# Base nodes return NodeOutput.output. map_to_shared reads from the node's
# state dict. These wrappers copy output into state so it flows to shared state.


class BaseRequestsNodeWithState(BaseRequestsNode):
    """BaseRequestsNode that writes ``response`` into node state for shared workflow state."""

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        out = super()._do_execute(state_dict, params_dict)
        state_dict["response"] = out.output.get("response", "")
        return out


class FileWriteNodeWithState(FileWriteNode):
    """FileWriteNode that writes output to state so it propagates to shared state."""

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        out = super()._do_execute(state_dict, params_dict)
        full_path = out.output.get("full_path") or ""
        state_dict["save_path"] = os.path.dirname(full_path) if full_path else ""
        state_dict["filename"] = out.output.get("filename", "")
        state_dict["size"] = out.output.get("bytes_written", 0)
        state_dict["content"] = state_dict.get("response", "")
        return out


# ---------------------------------------------------------------------------
# State mappings
# ---------------------------------------------------------------------------
# Input_fields: workflow state -> node input. Output_fields: node state -> workflow state.
# Used by map_to_shared to populate inputs and propagate outputs.


FETCH_MAPPING = create_simple_mapping(
    input_fields={"url": "url"},
    output_fields={"response": "response"},
    description="Map workflow url to BaseRequestsNode input; response to workflow state",
)

# FileWriteNode: workflow response -> node content; node full_path/filename/bytes_written -> workflow state
WRITE_FILE_MAPPING = create_simple_mapping(
    input_fields={"response": "content"},
    output_fields={
        "save_path": "save_path",
        "filename": "filename",
        "size": "size",
        "content": "content",
    },
    description="Map workflow response to FileWriteNode content; node output to workflow state",
)


# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------


class SimpleWebToMDWorkflow(Workflow):
    """
    Fetch a URL with :class:`BaseRequestsNode`, then write content with :class:`FileWriteNode`.
    Uses AlwaysLink between the two nodes.
    """

    workflow_id = "simple_web_to_md"
    name = "Simple Web to File"

    @property
    def state_schema(self):
        return SimpleWebToMDState

    def define(self):
        fetch_node = BaseRequestsNodeWithState(node_id="base_requests", name="Base requests")
        write_node = FileWriteNodeWithState(node_id="write_file", name="Write File")

        self.add_node(fetch_node, state_mapping=FETCH_MAPPING)
        self.add_node(write_node, state_mapping=WRITE_FILE_MAPPING)

        link = AlwaysLink(
            link_id="fetch_to_write",
            from_node_id="base_requests",
            to_node_id="write_file",
            name="Base requests → Write",
        )
        self.add_link(link)

        self.set_entry_node("base_requests")
