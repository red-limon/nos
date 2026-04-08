"""Request/Response Pydantic schemas for Workflow API."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class WorkflowStartSchema(BaseModel):
    """Schema for starting a workflow."""

    workflow_id: str = Field(..., description="Workflow ID to execute")
    initial_state: dict = Field(default_factory=dict, description="Initial workflow state")
    background: bool = Field(default=False, description="Run in background (non-blocking)")
    enable_realtime_logs: bool = Field(default=False, description="Enable real-time logs via Socket.IO/SSE")
    realtime_mode: str = Field(default="socketio", description="Realtime mode: 'socketio', 'sse', or 'both'")
    output_format: str = Field(default="json", description="Output format for result: json, text, html, table, code, tree, chart, download")
    debug_mode: str = Field(
        default="trace",
        description="trace = no per-node interactive forms; debug = per-node forms on platform logs.",
    )
    request: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional caller context for Workflow.run(..., request=) (e.g. command, tracing); not initial_state.",
    )

    @field_validator("request", mode="before")
    @classmethod
    def _workflow_request_must_be_object(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("request must be a JSON object")
        return v

    @field_validator("debug_mode", mode="before")
    @classmethod
    def _normalize_debug_mode(cls, v):
        if v is None:
            return "trace"
        s = str(v).lower().strip()
        if s not in ("trace", "debug"):
            raise ValueError("debug_mode must be 'trace' or 'debug'")
        return s


class WorkflowStatusSchema(BaseModel):
    """Schema for a workflow execution status."""

    execution_id: str
    workflow_id: str
    status: str
    started_at: float
    running: bool = False
    result: Optional[dict] = None
    error: Optional[str] = None


class WorkflowListSchema(BaseModel):
    """Schema for listing available workflows."""

    workflows: list[str]
    nodes: list[str]
    links: list[str]


class WorkflowDeleteSchema(BaseModel):
    """Schema for deleting workflows."""

    workflow_ids: list[str] = Field(..., min_length=1, description="Workflow IDs to delete")


class WorkflowCreateSchema(BaseModel):
    """Schema for creating a workflow. registration_status/registration_date are set by server (register then insert)."""

    workflow_id: str = Field(..., min_length=3, max_length=100, pattern="^[a-z0-9_]+$", description="Unique workflow identifier")
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    module_path: str = Field(..., min_length=1, max_length=500, pattern="^[a-z0-9_.]+$", description="Python module path")
    name: Optional[str] = Field(None, max_length=200)
    created_by: str = Field(default="system", max_length=80)
    updated_by: str = Field(default="system", max_length=80)


class WorkflowUpdateSchema(BaseModel):
    """Schema for updating a workflow. registration_date is server-managed."""

    workflow_id: Optional[str] = Field(None, min_length=3, max_length=100, pattern="^[a-z0-9_]+$")
    class_name: Optional[str] = Field(None, min_length=1, max_length=200)
    module_path: Optional[str] = Field(None, min_length=1, max_length=500)
    name: Optional[str] = Field(None, max_length=200)
    updated_by: Optional[str] = Field(None, max_length=80)
    registration_status: Optional[str] = Field(None, max_length=20)


WORKFLOW_SAVE_CODE_CONTENT_MAX_LENGTH = 1_048_576


class WorkflowSaveCodeSchema(BaseModel):
    """Schema for saving workflow Python code to file (POST /workflow/save-code)."""

    module_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        pattern="^[a-z0-9_.]+$",
        description="Full Python module path (e.g. nos.plugins.old.if_then_workflow)",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=WORKFLOW_SAVE_CODE_CONTENT_MAX_LENGTH,
        description="Full Python source for the workflow module",
    )
    updated_by: str = Field(default="system", max_length=80)
