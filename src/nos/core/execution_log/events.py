"""
Pydantic event schemas for structured execution log payloads (buffer / platform EventLog).

All events inherit from BaseEvent which provides common fields.
"""

from typing import Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
import time


class BaseEvent(BaseModel):
    """Base Pydantic model for all channel events."""

    model_config = ConfigDict(extra="allow")

    # Identifiers
    event: str = Field(..., description="Event type (node_start, node_end, etc.)")
    execution_id: str = Field(..., description="Execution identifier")
    
    # Time
    started_at: str = Field(default="", description="ISO 8601 execution start time (constant across all events of the same execution)")
    datetime: str = Field(default="", description="ISO 8601 datetime when this event was emitted")
    
    # Context
    level: str = Field(default="info", description="Log level")
    message: str = Field(default="", description="Human-readable message")
    
    # Optional identifiers
    node_id: Optional[str] = Field(default=None)
    workflow_id: Optional[str] = Field(default=None)
    link_id: Optional[str] = Field(default=None)

    def __init__(self, **data):
        # Auto-fill datetime if not provided
        if "datetime" not in data or not data["datetime"]:
            data["datetime"] = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()
        super().__init__(**data)

    def to_dict(self) -> dict:
        """Convert to dict, removing None values."""
        d = self.model_dump()
        return {k: v for k, v in d.items() if v is not None}


# --- Node events ---


class NodeExecuteEvent(BaseEvent):
    """node_execute event - emitted when node is about to run _do_execute (after init)."""

    event: str = Field(default="starting execution")
    message: str = Field(default="Node is starting execution...")
    
    module_path: str = Field(default="")
    class_name: str = Field(default="")
    state: dict = Field(default_factory=dict)
    shared_state: dict = Field(default_factory=dict)
    input_params: dict = Field(default_factory=dict)

class NodeRequestEvent(BaseEvent):
    """node_request event - emitted when node request is received from client."""

    event: str = Field(default="request received")
    message: str = Field(default="Client connected. Serving node module/class.")

    module_path: str = Field(default="")
    class_name: str = Field(default="")
    request: dict = Field(default_factory=dict)

class NodeExecutionRequestEvent(BaseEvent):
    """
    node_start event - emitted from Node._on_start when execution is requested (before init/validation).
    Top-level: execution_id, node_id, module_path, class_name, command (no request, no timestamp).
    """

    event: str = Field(default="preparing")
    message: str = Field(default="Preparing node for execution...")

    module_path: str = Field(default="")
    class_name: str = Field(default="")
    command: str = Field(default="", description="Full command string that triggered the execution")


class NodeInitEvent(BaseEvent):
    """node_init event - emitted when node init is about to run (before validation)."""

    event: str = Field(default="initializing")
    message: str = Field(default="Node is initializing...")

    module_path: str = Field(default="")
    class_name: str = Field(default="")
    shared_state: dict = Field(default_factory=dict)
    state: dict = Field(default_factory=dict)
    input_params: dict = Field(default_factory=dict)


class NodeInitCompletedEvent(BaseEvent):
    """node_init_completed event - emitted when _on_init succeeded."""

    event: str = Field(default="initialization completed")
    message: str = Field(default="Node initialized. Ready for execution...")

    module_path: str = Field(default="")
    class_name: str = Field(default="")
    shared_state: dict = Field(default_factory=dict)
    state: dict = Field(default_factory=dict)
    input_params: dict = Field(default_factory=dict)
    command: str = Field(default="", description="Full command reconstructed with defaults applied after _on_init")


class NodeStateChangedEvent(BaseEvent):
    """node_state_changed event - emitted on each state mutation."""

    event: str = Field(default="node state changed")
    
    state_key: str = Field(default="")
    old_value: Any = None
    new_value: Any = None

    def __init__(self, **data):
        if "message" not in data or not data["message"]:
            data["message"] = f"Node state changed: {data.get('state_key', '')}"
        super().__init__(**data)


class NodeOutputEvent(BaseEvent):
    """node_output event - emitted with NodeOutput (output + metadata) when node finishes."""

    event: str = Field(default="node output")
    message: str = Field(default="Node output is ready...")

    output: dict = Field(default_factory=dict, description="Node output dict")
    metadata: dict = Field(default_factory=dict, description="Node metadata dict")


class NodeEndEvent(BaseEvent):
    """node_end event - emitted when node execution completes. Carries the full NodeExecutionResult payload."""

    event: str = Field(default="Node end")
    message: str = Field(default="Node execution completed")

    # NodeExecutionResult fields (mirrors node.NodeExecutionResult)
    # output_format lives inside response.output['output_format'] — not a top-level field
    status: str = Field(default="")
    module_path: str = Field(default="")
    class_name: str = Field(default="")
    command: str = Field(default="")
    response: dict = Field(default_factory=dict, description="output + metadata from the node")
    initial_state: dict = Field(default_factory=dict)
    input_params: dict = Field(default_factory=dict)
    final_state: dict = Field(default_factory=dict)
    ended_at: str = Field(default="")
    elapsed_time: str = Field(default="0s")
    event_logs: list = Field(default_factory=list)


class NodeStopEvent(BaseEvent):
    """Cooperative stop: user/engine requested cancellation; raised via :exc:`CancellationError` and handled before ``node_end``."""

    event: str = Field(default="cooperative stop")
    level: str = Field(default="warning")
    message: str = Field(default="Execution stopped by user request")
    reason: str = Field(default="", description="Optional detail from cancelled result payload")


# --- Workflow events ---


class WorkflowStartEvent(BaseEvent):
    """workflow_start event - emitted when workflow execution begins."""

    event: str = Field(default="workflow_start")
    message: str = Field(default="Workflow execution started")
    
    initial_state: dict = Field(default_factory=dict)
    state_mapping: Optional[str] = None


class WorkflowInitEvent(BaseEvent):
    """workflow_init — before shared state schema validation (mirrors :class:`NodeInitEvent`)."""

    event: str = Field(default="workflow_init")
    message: str = Field(default="Preparing workflow shared state...")
    initial_state: dict = Field(default_factory=dict)


class WorkflowInitCompletedEvent(BaseEvent):
    """workflow_init_completed — after shared state validated in :meth:`Workflow._initialize_state` (mirrors :class:`NodeInitCompletedEvent`)."""

    event: str = Field(default="workflow_init_completed")
    message: str = Field(default="Workflow shared state validated. Ready to start...")
    state: dict = Field(default_factory=dict)


class WorkflowFormResponseReceivedEvent(BaseEvent):
    """workflow_form_response_received — when the initial shared-state HTML form returns (mirrors :class:`NodeFormResponseReceivedEvent`)."""

    event: str = Field(default="workflow_form_response")
    message: str = Field(default="Workflow initial state form response received from client...")
    form_response: dict = Field(default_factory=dict, description="Client form response (state, cancelled, etc.)")


class WorkflowSharedStateChangedEvent(BaseEvent):
    """shared_state_changed event - emitted when shared state is updated by a node."""

    event: str = Field(default="shared_state_changed")
    
    state_updates: dict = Field(default_factory=dict)
    old_values: dict = Field(default_factory=dict)

    def __init__(self, **data):
        if "message" not in data or not data["message"]:
            node_id = data.get("node_id", "unknown")
            data["message"] = f"Shared state updated by node {node_id}"
        super().__init__(**data)


class WorkflowExecutionResultEvent(BaseEvent):
    """Emitted when workflow execution completes (final state summary in log stream)."""

    event: str = Field(default="workflow_execution_result")
    message: str = Field(default="Workflow execution completed")
    
    initial_state: dict = Field(default_factory=dict)
    final_state: dict = Field(default_factory=dict)
    state_changed: dict = Field(default_factory=dict)


class LinkDecisionEvent(BaseEvent):
    """link_decision event - emitted when a link makes a routing decision."""

    event: str = Field(default="link_decision")
    
    decision: str = Field(default="")
    next_node_id: Optional[str] = None

    def __init__(self, **data):
        if "message" not in data or not data["message"]:
            link_id = data.get("link_id", "unknown")
            decision = data.get("decision", "")
            next_node = data.get("next_node_id") or "STOP"
            data["message"] = f"Link {link_id} routing: {decision} -> {next_node}"
        super().__init__(**data)


# --- Generic events ---


class NodeFormResponseReceivedEvent(BaseEvent):
    """node_form_response_received event - emitted when form response is received from client."""

    event: str = Field(default="Form response")
    message: str = Field(default="Form response received from client...")

    module_path: str = Field(default="")
    class_name: str = Field(default="")
    form_response: dict = Field(default_factory=dict, description="Client form response (state, params, cancelled, etc.)")


class FormSchemaSentEvent(BaseEvent):
    """form_schema_sent event - emitted when form schema is sent to client."""

    event: str = Field(default="form_schema_sent")
    message: str = Field(default="Form schema sent")
    
    form_schema: dict = Field(default_factory=dict)


class FormDataReceivedEvent(BaseEvent):
    """form_data_received event - emitted when form data is received from client."""

    event: str = Field(default="form_data_received")
    message: str = Field(default="Form data received")
    
    form_data: dict = Field(default_factory=dict)


class NodeErrorEvent(BaseEvent):
    """System error event - emitted on framework-level errors (validation, bad_request, etc.)."""

    event: str = Field(default="error")
    level: str = Field(default="error")
    error_type: str = Field(default="", description="Error category: validation_error, bad_request, output_validation_error, form_validation_error, internal_error")
    detail: str = Field(default="", description="Full technical error message")


class CustomEvent(BaseEvent):
    """Custom event for arbitrary logging."""

    event: str = Field(default="Logging event")
