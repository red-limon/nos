"""Request/Response Pydantic schemas for Node API."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class NodeExecuteSchema(BaseModel):
    """Schema for executing a single node (POST /node/execute)."""

    node_id: str = Field(..., min_length=1, max_length=100, description="Node ID to execute")
    state: dict = Field(default_factory=dict, description="Initial state for node execution")
    input_params: Optional[dict] = Field(default=None, description="Input parameters for the node (separate from state)")
    output_format: Optional[str] = Field(
        default=None,
        description="Rendering format (json, text, …); not part of input_params_schema",
    )
    background: bool = Field(default=False, description="Run in background (non-blocking)")
    request: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional caller context for hooks/telemetry; forwarded under `context` in Node.run(..., request=).",
    )

    @field_validator("request", mode="before")
    @classmethod
    def _request_must_be_object(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("request must be a JSON object")
        return v


class NodeExecuteDirectSchema(BaseModel):
    """Schema for direct node execution by module_path and class_name (POST /node/execute-direct)."""

    module_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        pattern="^[a-z0-9_.]+$",
        description="Python module path (e.g. nos.plugins.nodes.messengers.whatsapp_messenger.whatsapp_messenger_node)",
    )
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    node_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Instance id for this run; defaults to adhoc_direct when omitted",
    )
    state: dict = Field(default_factory=dict, description="Initial state for node execution")
    input_params: Optional[dict] = Field(default=None, description="Input parameters for the node (separate from state)")
    output_format: Optional[str] = Field(
        default=None,
        description="Rendering format (json, text, …); not part of input_params_schema",
    )
    background: bool = Field(default=False, description="Run in background (non-blocking)")
    request: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional caller context for hooks/telemetry; forwarded under `context` in Node.run(..., request=).",
    )

    @field_validator("request", mode="before")
    @classmethod
    def _request_must_be_object_execute_direct(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("request must be a JSON object")
        return v


class NodeExecuteFromDbSchema(BaseModel):
    """Schema for node execution by node_id, loading module_path and class_name from DB (POST /node/execute-from-db)."""

    node_id: str = Field(..., min_length=1, max_length=100, description="Node ID (must exist in node table)")
    state: dict = Field(default_factory=dict, description="Initial state for node execution")
    input_params: Optional[dict] = Field(default=None, description="Input parameters for the node (separate from state)")
    output_format: Optional[str] = Field(
        default=None,
        description="Rendering format (json, text, …); not part of input_params_schema",
    )
    background: bool = Field(default=False, description="Run in background (non-blocking)")
    request: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional caller context for hooks/telemetry; forwarded under `context` in Node.run(..., request=).",
    )

    @field_validator("request", mode="before")
    @classmethod
    def _request_must_be_object_from_db(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("request must be a JSON object")
        return v


class NodeCreateSchema(BaseModel):
    """Schema for creating a node. registration_status/registration_date are set by server (register then insert)."""

    node_id: str = Field(..., min_length=3, max_length=100, pattern="^[a-z0-9_]+$", description="Unique node identifier")
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    module_path: str = Field(..., min_length=1, max_length=500, pattern="^[a-z0-9_.]+$", description="Python module path")
    name: str = Field(..., max_length=200, description="Display name")


class NodeUpdateSchema(BaseModel):
    """Schema for updating a node. All updatable table fields required. registration_date is server-managed."""

    node_id: str = Field(..., min_length=1, max_length=100, description="Node ID to update")
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    module_path: str = Field(..., min_length=1, max_length=500, pattern="^[a-z0-9_.]+$", description="Python module path")
    name: str = Field(..., max_length=200)
    registration_status: str = Field(..., max_length=20, description="OK or Error")


class NodeDeleteSchema(BaseModel):
    """Schema for deleting multiple nodes."""

    ids: list[str] = Field(..., min_length=1, description="List of node_id to delete")


# Max size for node source code (1 MiB) to avoid oversized payloads and document the limit.
NODE_SAVE_CODE_CONTENT_MAX_LENGTH = 1_048_576


class NodeSaveCodeSchema(BaseModel):
    """Schema for saving node Python code to file (POST /node/save-code)."""

    module_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        pattern="^[a-z0-9_.]+$",
        description="Package or full module path (e.g. nos.plugins.nodes.developer or .file_io.write_file)",
    )
    content: str = Field(
        ...,
        max_length=NODE_SAVE_CODE_CONTENT_MAX_LENGTH,
        description="Python source code to write (max 1 MiB)",
    )
    node_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern="^[a-z0-9_]+$",
        description="Node ID; used as filename (<node_id>.py) inside the package from module_path.",
    )
    class_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Class name for registration after save.",
    )
