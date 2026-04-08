"""
FileUploadExampleNode - Example node for the 2-step form flow: file upload via HTTP, then form_data via Socket.IO.

Demonstrates:
1. input_params_schema with a file field (json_schema_extra: input_type="file", accept, multiple, max_size_mb)
2. Client uploads file(s) via POST /api/upload/temp, gets upload_id(s)
3. Client sends form_data via Socket.IO with upload_id(s) in params
4. Node receives params_dict["document"] = upload_id (or list of ids if multiple)
5. Node resolves upload_id to path via upload_service.get_path() and reads file info

Module path: nos.plugins.nodes.dev_.file_upload_example_node
Class name:  FileUploadExampleNode
Node ID:     file_upload_example

To test without registering:
    run node dev nos.plugins.nodes.dev_.file_upload_example_node FileUploadExampleNode --sync --debug

To register:
    reg node file_upload_example FileUploadExampleNode nos.plugins.nodes.dev_.file_upload_example_node

To execute (after registration):
    run node db file_upload_example --sync --debug
"""

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------

class FileUploadExampleInputParams(BaseModel):
    """Params: optional title + one file (upload_id after client upload)."""

    title: str = Field(
        default="",
        description="Optional title for this upload",
    )
    document: str = Field(
        default="",
        description="Upload a file (PDF, images, or text). Upload via form then Send.",
        json_schema_extra={
            "input_type": "file",
            "accept": ".pdf,.txt,image/*",
            "multiple": False,
            "max_size_mb": 10,
        },
    )


class FileUploadExampleOutput(BaseModel):
    """Output: file info and title."""

    title: str = Field(..., description="Title from params")
    upload_id: str = Field(..., description="Upload ID received")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    path: str = Field(..., description="Resolved server path (for debugging)")
    status: str = Field(default="ok", description="Status")


# -----------------------------------------------------------------------------
# Node
# -----------------------------------------------------------------------------

class FileUploadExampleNode(Node):
    """
    Example node that accepts a file upload param.
    Run from console: run node db file_upload_example --sync --debug
    Form will show: title (text) + document (file). Upload file via HTTP, then Send.
    """

    def __init__(self, node_id: str = "file_upload_example", name: str = None):
        super().__init__(node_id, name or "File Upload Example")

    @property
    def input_state_schema(self):
        return None

    @property
    def input_params_schema(self):
        return FileUploadExampleInputParams

    @property
    def output_schema(self):
        return FileUploadExampleOutput

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        title = (params_dict.get("title") or "").strip() or "(no title)"
        upload_id = (params_dict.get("document") or "").strip()

        if not upload_id:
            return NodeOutput(
                output={
                    "title": title,
                    "upload_id": "",
                    "filename": "",
                    "size": 0,
                    "path": "",
                    "status": "no_file",
                },
                metadata={"node_id": self.node_id},
            )

        from nos.platform.services.upload_service import upload_service
        # Resolve upload_id to path and read metadata
        info = upload_service.get_file_info(upload_id)
        if not info:
            return NodeOutput(
                output={
                    "title": title,
                    "upload_id": upload_id,
                    "filename": "",
                    "size": 0,
                    "path": "",
                    "status": "not_found",
                },
                metadata={"node_id": self.node_id},
            )

        return NodeOutput(
            output={
                "title": title,
                "upload_id": upload_id,
                "filename": info.get("filename", ""),
                "size": info.get("size", 0),
                "path": info.get("path", ""),
                "status": "ok",
            },
            metadata={"node_id": self.node_id},
        )
