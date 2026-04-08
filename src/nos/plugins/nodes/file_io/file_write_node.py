"""
File Write Node - Saves content (text or binary) to the filesystem.

Uses FileWriteService. Path relative to NOS_TEMP_PATH (or deprecated ORKESTRO_TEMP_PATH).
Extension auto-detected from filename if present.

Module path:  nos.plugins.nodes.file_io.file_write_node
Class name:   FileWriteNode
Node ID:      file_write

To register:
    reg node file_write FileWriteNode nos.plugins.nodes.file_io.file_write_node

To execute:
    run node db file_write --sync --param content="Hello" --param filename="greeting" --param ext="txt"
"""

import base64
import logging
from typing import Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput

logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================

DEFAULT_CONTENT = """# Test Document

This is a **sample markdown** file for testing the FileWriteNode.

- Item 1
- Item 2
- Item 3

Created by Hythera FileWriteNode.
"""


class FileWriteInputParams(BaseModel):
    """Input params for FileWriteNode."""

    content: str = Field(default=DEFAULT_CONTENT, description="Text content to save")
    path: str = Field(default="", description="Subdirectory under base path")
    filename: str = Field(default="output", description="Filename (extension in name or use ext)")
    ext: Optional[str] = Field(default=None, description="Extension if not in filename (e.g. txt, json)")
    binary: bool = Field(default=False, description="If true, content is base64-encoded binary")


class FileWriteOutput(BaseModel):
    """Output schema for FileWriteNode."""

    success: bool = Field(..., description="Write success")
    full_path: Optional[str] = Field(default=None, description="Absolute path of saved file")
    filename: Optional[str] = Field(default=None, description="Saved filename")
    bytes_written: int = Field(default=0, description="Bytes written")
    error: Optional[str] = Field(default=None, description="Error message on failure")


# =============================================================================
# Node Implementation
# =============================================================================

class FileWriteNode(Node):
    """
    File Write Node - saves content to the filesystem.

    Input params: content, path, filename, ext, binary
    Output: success, full_path, filename, bytes_written
    """

    def __init__(self, node_id: str = "file_write", name: Optional[str] = None):
        super().__init__(node_id, name or "File Write")

    @property
    def input_state_schema(self):
        return None

    @property
    def input_params_schema(self):
        return FileWriteInputParams

    @property
    def output_schema(self):
        return FileWriteOutput

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        from nos.platform.services.file_write_service import file_write_service

        content = params_dict.get("content", "")
        path = params_dict.get("path", "")
        filename = params_dict.get("filename", "output")
        ext = params_dict.get("ext")
        binary = params_dict.get("binary", False)

        if binary and content:
            try:
                content = base64.b64decode(content)
            except Exception as e:
                return NodeOutput(
                    output={"success": False, "error": f"Invalid base64: {e}"},
                    metadata={"node_id": self.node_id},
                )

        result = file_write_service.save(
            content=content,
            path=path,
            filename=filename,
            extension=ext,
        )

        if result.success:
            return NodeOutput(
                output={
                    "success": True,
                    "full_path": result.full_path,
                    "filename": result.filename,
                    "bytes_written": result.bytes_written,
                },
                metadata={"node_id": self.node_id},
            )
        else:
            return NodeOutput(
                output={"success": False, "error": result.error},
                metadata={"node_id": self.node_id},
            )
