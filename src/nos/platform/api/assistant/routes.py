"""Assistant API routes. URL prefix: /assistant, /assistants."""

import logging

from flask import jsonify, url_for

from ..routes import api_bp
from ..common import validate_payload, _call_callback_and_return, GRID_ACTION_HANDLERS
from ..data_grid_schema import DataGridResponseSchema
from ..form_wire import dump_grid_form_dict, form_envelope
from ...services.sqlalchemy import AssistantDbModel, RegistrationStatus
from ...services.sqlalchemy.assistant import repository as assistant_repo
from .schemas import (
    AssistantCreateSchema,
    AssistantDeleteSchema,
    AssistantUpdateSchema,
)


def _build_assistant_form_schema():
    """Build form_schema dict and column names for assistant form (shared by form-schema and list endpoints)."""
    fields = [
        {
            "name": "assistant_id",
            "label": "Assistant ID",
            "type": "text",
            "placeholder": "e.g., my_assistant",
            "required": True,
            "pattern": "^[a-z0-9_]+$",
            "minLength": 3,
            "maxLength": 100,
            "description": "Unique identifier (lowercase, alphanumeric, underscores only)",
        },
        {
            "name": "class_name",
            "label": "Class Name",
            "type": "text",
            "placeholder": "e.g., MyAssistant",
            "required": True,
            "minLength": 1,
            "maxLength": 200,
        },
        {
            "name": "module_path",
            "label": "Module Path",
            "type": "text",
            "placeholder": "e.g., nos.core.assistants.my_assistant",
            "required": True,
            "pattern": "^[a-z0-9_.]+$",
            "maxLength": 500,
            "description": "Python module path (dot-separated)",
        },
        {
            "name": "name",
            "label": "Display Name",
            "type": "text",
            "placeholder": "Human-readable name",
            "required": False,
            "maxLength": 200,
        },
        {
            "name": "registration_status",
            "label": "Registration status",
            "type": "hidden",
            "required": False,
            "description": "OK if loaded in registry at startup, Error otherwise",
        },
    ]
    form_schema = form_envelope(
        form_id="assistant-form",
        title="Assistant Plugin",
        description="Add or edit an assistant plugin",
        fields=fields,
        submit_label="Save",
        cancel_label="Cancel",
        method="POST",
    )
    columns = [f["name"] for f in fields]
    return form_schema, columns


# --- Grid-to-action-dispatcher handlers ---

def _execute_create_assistant(data):
    """Create an assistant from grid submit."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        from flask import session
        current_user = session.get("username", "system")
        assistant_id = data.get("assistant_id")
        if not assistant_id:
            return jsonify({"error": "Bad Request", "message": "Field 'assistant_id' is required"}), 400
        from nos.core.engine.plugin_loader import try_register_assistant
        ok, reg_error = try_register_assistant(
            data.get("module_path") or "",
            data.get("class_name") or "",
            assistant_id,
        )
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
        if not ok:
            logging.getLogger(__name__).info("Assistant create: registration failed for %s: %s", assistant_id, reg_error)
        assistant, err = assistant_repo.create(
            assistant_id=assistant_id,
            class_name=data.get("class_name") or "",
            module_path=data.get("module_path") or "",
            name=data.get("name"),
            created_by=current_user or data.get("created_by", "system"),
            updated_by=current_user or data.get("updated_by", "system"),
            registration_status=status,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Assistant '{assistant_id}' already exists"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(assistant.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error creating assistant: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_update_assistant(id_val, data):
    """Update an assistant from grid submit. id_val is assistant_id (string)."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        assistant_id = str(id_val) if id_val is not None else data.get("assistant_id")
        if not assistant_id:
            return jsonify({"error": "Bad Request", "message": "Update requires 'id' (assistant_id) in body or path"}), 400
        callback_response = data.get("callback_response")
        payload = {k: v for k, v in data.items() if k in ("class_name", "module_path", "name", "updated_by", "registration_status") and v is not None}
        from flask import session
        current_user = session.get("username", "system")
        if current_user:
            payload["updated_by"] = current_user
        if payload.get("registration_status"):
            valid = [s.value for s in RegistrationStatus]
            if payload["registration_status"] not in valid:
                return jsonify({"error": "Bad Request", "message": f"registration_status must be one of: {', '.join(valid)}"}), 400
        assistant, err = assistant_repo.update(assistant_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Assistant '{assistant_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Assistant conflict"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(assistant.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error updating assistant: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_delete_assistant(data):
    """Delete one or more assistants from grid submit."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        assistant_ids = data.get("assistant_ids") or data.get("ids", [])
        if not assistant_ids:
            return jsonify({"error": "Bad Request", "message": "Field 'assistant_ids' or 'ids' is required and must be a non-empty array"}), 400
        if not isinstance(assistant_ids, list):
            return jsonify({"error": "Bad Request", "message": "Field 'assistant_ids' must be an array"}), 400
        assistant_ids = [str(i) for i in assistant_ids]
        deleted_ids, _ = assistant_repo.delete_many(assistant_ids)
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify({"message": f"{len(deleted_ids)} assistant(s) deleted", "deleted": deleted_ids}), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error deleting assistants: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


GRID_ACTION_HANDLERS["assistant"] = {
    "create": _execute_create_assistant,
    "update": _execute_update_assistant,
    "delete": _execute_delete_assistant,
}


# --- Routes ---
@api_bp.get("/assistant/form-schema")
@api_bp.get("/assistant/form-schema/")
@api_bp.post("/assistant/form-schema")
@api_bp.post("/assistant/form-schema/")
def get_assistant_form_schema():
    """Get form_schema for assistant to render in <form-loader>."""
    form_schema, _ = _build_assistant_form_schema()
    return jsonify(dump_grid_form_dict(form_schema, action=url_for("api.create_assistant")))


@api_bp.get("/assistant/list")
@api_bp.get("/assistant/list/")
@api_bp.post("/assistant/list")
@api_bp.post("/assistant/list/")
def get_assistant_list():
    """Get list of all assistants for data-grid + form-loader (DataGridResponseSchema)."""
    assistants = assistant_repo.get_all()
    data = [a.to_dict() for a in assistants]
    form_schema, columns = _build_assistant_form_schema()

    payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
    out = payload.model_dump()
    out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_assistant"))
    return jsonify(out)


@api_bp.get("/assistant/list/published")
@api_bp.get("/assistant/list/published/")
@api_bp.post("/assistant/list/published")
@api_bp.post("/assistant/list/published/")
def get_assistant_list_published():
    """Get list of published assistants for data-grid (status = PUBLISHED)."""
    assistants = assistant_repo.get_all()
    published = [a for a in assistants if a.status == RegistrationStatus.PUBLISHED.value]
    data = [a.to_dict() for a in published]
    form_schema, columns = _build_assistant_form_schema()

    payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
    out = payload.model_dump()
    out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_assistant"))
    return jsonify(out)


@api_bp.get("/assistant/<assistant_id>")
@api_bp.get("/assistant/<assistant_id>/")
@api_bp.post("/assistant/<assistant_id>")
@api_bp.post("/assistant/<assistant_id>/")
def get_assistant_by_id(assistant_id: str):
    """Get a single assistant by assistant_id (no request body)."""
    assistant = assistant_repo.get_by_id(assistant_id)
    if not assistant:
        return jsonify({"error": "Not Found", "message": f"Assistant '{assistant_id}' not found"}), 404
    return jsonify(assistant.to_dict())


@api_bp.post("/assistant/create")
@api_bp.post("/assistant/create/")
@validate_payload(AssistantCreateSchema)
def create_assistant(data: AssistantCreateSchema):
    """Create a new assistant: (1) register in registry, (2) set registration_status OK/Error, (3) insert in DB."""
    try:
        from flask import session
        from nos.core.engine.plugin_loader import try_register_assistant
        current_user = session.get("username", "system")
        ok, reg_error = try_register_assistant(data.module_path, data.class_name, data.assistant_id)
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
        if not ok:
            import logging
            logging.getLogger(__name__).info("Assistant create: registration failed for %s: %s", data.assistant_id, reg_error)
        assistant, err = assistant_repo.create(
            assistant_id=data.assistant_id,
            class_name=data.class_name,
            module_path=data.module_path,
            name=data.name,
            created_by=current_user or data.created_by,
            updated_by=current_user or data.updated_by,
            registration_status=status,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Assistant '{data.assistant_id}' already exists"}), 409
        return jsonify(assistant.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error creating assistant: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.post("/assistant/update")
@api_bp.post("/assistant/update/")
@validate_payload(AssistantUpdateSchema)
def update_assistant_by_id(data: AssistantUpdateSchema):
    """Update an existing assistant. assistant_id is taken from request body (data.assistant_id)."""
    try:
        assistant_id = data.assistant_id
        payload = data.model_dump(exclude_unset=True)
        payload.pop("assistant_id", None)
        assistant, err = assistant_repo.update(assistant_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Assistant '{assistant_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Assistant conflict"}), 409
        return jsonify(assistant.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error updating assistant: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.delete("/assistant")
@api_bp.delete("/assistant/")
@api_bp.post("/assistant/delete")
@api_bp.post("/assistant/delete/")
@validate_payload(AssistantDeleteSchema)
def delete_assistants(data: AssistantDeleteSchema):
    """Delete multiple assistants by assistant_id. Body: JSON with 'ids' (list of strings)."""
    try:
        deleted_ids, _ = assistant_repo.delete_many(data.ids)
        return jsonify({"message": f"{len(deleted_ids)} assistant(s) deleted"}), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error deleting assistants: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500
