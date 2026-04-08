"""
Examples of how to attach ``form_schema`` (plain dict) to API responses, SocketIO, SSE.

Uses :mod:`nos.platform.api.form_wire` — same shape as engine run and grid APIs.
"""

import json
from typing import Any, Dict, List

from .form_wire import add_form_schema_to_response, form_envelope


def example_user_form_schema() -> Dict[str, Any]:
    """Example form for user registration."""
    fields: List[Dict[str, Any]] = [
        {
            "name": "username",
            "label": "Username",
            "type": "text",
            "placeholder": "Enter username",
            "required": True,
            "minLength": 3,
            "maxLength": 20,
            "pattern": "^[a-zA-Z0-9_]+$",
            "description": "Only letters, numbers, and underscores",
        },
        {
            "name": "email",
            "label": "Email",
            "type": "email",
            "placeholder": "user@example.com",
            "required": True,
        },
        {
            "name": "password",
            "label": "Password",
            "type": "password",
            "placeholder": "Enter password",
            "required": True,
            "minLength": 8,
            "description": "At least 8 characters",
        },
        {
            "name": "age",
            "label": "Age",
            "type": "number",
            "placeholder": "25",
            "required": False,
            "min": 18,
            "max": 120,
        },
        {
            "name": "newsletter",
            "label": "Subscribe to newsletter",
            "type": "checkbox",
            "required": False,
        },
    ]
    return form_envelope(
        form_id="user-registration",
        title="User Registration",
        description="Create a new account",
        fields=fields,
        submit_label="Register",
        cancel_label="Cancel",
        method="POST",
    )


def example_workflow_form_schema() -> Dict[str, Any]:
    """Example workflow configuration form."""
    fields: List[Dict[str, Any]] = [
        {
            "name": "workflow_name",
            "label": "Workflow Name",
            "type": "text",
            "placeholder": "My Workflow",
            "required": True,
            "maxLength": 100,
        },
        {
            "name": "description",
            "label": "Description",
            "type": "textarea",
            "placeholder": "Describe your workflow",
            "required": False,
            "maxLength": 500,
        },
        {
            "name": "priority",
            "label": "Priority",
            "type": "select",
            "required": True,
            "options": [
                {"value": "low", "label": "Low"},
                {"value": "medium", "label": "Medium"},
                {"value": "high", "label": "High"},
            ],
        },
        {
            "name": "enabled",
            "label": "Enabled",
            "type": "checkbox",
            "value": True,
            "required": False,
        },
    ]
    return form_envelope(
        form_id="workflow-config",
        title="Workflow Configuration",
        fields=fields,
        submit_label="Save",
        method="POST",
    )


def example_api_response_with_form_schema():
    """Example: JSON response that includes ``form_schema``."""
    response_data = {
        "status": "success",
        "message": "Data loaded",
        "data": {"users": []},
    }
    return add_form_schema_to_response(response_data, example_user_form_schema())


def example_socketio_event_with_form_schema(socketio):
    """Example: emit SocketIO event with ``form_schema``."""

    @socketio.on("request_form")
    def handle_request_form():
        event_data = {"type": "form_available", "form_id": "workflow-config", "data": {}}
        event_data = add_form_schema_to_response(event_data, example_workflow_form_schema())
        return event_data


def example_sse_event_with_form_schema():
    """Example: SSE payload including ``form_schema``."""
    event_data = {"type": "update", "timestamp": "2024-01-01T00:00:00Z"}
    event_data = add_form_schema_to_response(event_data, example_user_form_schema())
    return f"data: {json.dumps(event_data)}\n\n"


def create_form_schema_from_model_stub(model_class) -> Dict[str, Any]:
    """
    Placeholder: map an ORM/SQLAlchemy model to wire fields (implement per project).
    """
    return form_envelope(
        form_id=f"{model_class.__name__.lower()}-form",
        title=model_class.__name__,
        fields=[],
        submit_label="Submit",
    )
