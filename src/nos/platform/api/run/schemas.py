"""Unified run API schema (POST /run)."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class UnifiedRunSchema(BaseModel):
    """
    Single HTTP shape for *load + run*: resolve a node or workflow, then execute.

    - ``load=registry``: ``id`` is the registry plugin id (node or workflow).
    - ``load=module``: ``module_path`` + ``class_name`` are **required** (with ``id`` as instance id:
      node_id or workflow_id passed to ``Node`` / ``Workflow`` — same as :meth:`Node.load` / :meth:`Workflow.load` in dev).

    Node module paths must live under ``nos.plugins.nodes`` (validated when executing).
    Workflow module paths must live under ``nos.plugins.workflows`` or ``nos.plugins.old`` (validated when executing).

    Realtime / interactive options are fixed server-side for non-interactive HTTP (see ``unified_run``).
    """

    model_config = {"extra": "ignore"}

    target: Literal["node", "workflow"] = Field(..., description="node | workflow")
    load: Literal["registry", "module"] = Field(
        default="registry",
        description="registry: lookup in memory; module: import module_path.class_name (dev load)",
    )
    id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Registry id, or required workflow_id / optional node_id when load=module (see Workflow.load / Node)",
    )
    module_path: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Required when load=module: Python module (nodes: nos.plugins.nodes…; workflows: nos.plugins.workflows…)",
    )
    class_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Required when load=module: Node or Workflow subclass name",
    )
    state: dict = Field(default_factory=dict, description="Node state or workflow initial_state")
    input_params: Optional[dict] = Field(
        default=None,
        description="Node only: parameters for input_params_schema (ignored for workflow)",
    )
    background: bool = Field(default=False, description="Non-blocking execution when True")
    output_format: Optional[str] = Field(
        default=None,
        description="Rendering hint (json, text, …). Defaults to json for workflow when omitted.",
    )
    request: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional caller context for hooks/telemetry only — not validated as node state or input_params. "
            "Forwarded under the `context` key in the dict passed to Node.run(..., request=...) / workflow run."
        ),
    )

    @field_validator("request", mode="before")
    @classmethod
    def _request_must_be_object(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("request must be a JSON object")
        return v

    @model_validator(mode="after")
    def _validate_load(self):
        if self.load == "registry":
            if not (self.id or "").strip():
                raise ValueError("id is required when load=registry.")
            return self
        # load == module
        if not (self.module_path or "").strip() or not (self.class_name or "").strip():
            raise ValueError("module_path and class_name are required when load=module.")
        if self.target == "workflow" and not (self.id or "").strip():
            raise ValueError("id (workflow_id) is required when load=module for a workflow.")
        return self
