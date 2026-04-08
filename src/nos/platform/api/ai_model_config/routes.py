"""
AI Model Config API routes.
Provides endpoints for managing AI providers, models, and configurations.
The list endpoint returns JOINed data from all 3 tables.
"""

import logging
from flask import jsonify, url_for

from ..routes import api_bp
from ..common import validate_payload, GRID_ACTION_HANDLERS
from ..data_grid_schema import DataGridResponseSchema
from ..form_wire import dump_grid_form_dict, form_envelope
from ...services.sqlalchemy.ai import AIProvider, AIModel, AIModelConfig
from ...services.sqlalchemy.ai import repository as ai_repo
from .schemas import (
    AIModelConfigCreateSchema,
    AIModelConfigUpdateSchema,
    AIModelConfigDeleteSchema,
)

logger = logging.getLogger(__name__)


def _get_model_options():
    """Get model options for select dropdown."""
    models = ai_repo.get_all_models(active_only=False)
    return [
        {"value": m.model_id, "label": f"{m.name} ({m.model_name})"}
        for m in models
    ]


def _build_ai_model_config_form_schema():
    """
    Build form_schema dict for AI model configurations (JOIN: config + model + provider).
    """
    model_options = _get_model_options()
    fields = [
        {
            "name": "config_id",
            "label": "Config ID",
            "type": "text",
            "placeholder": "e.g., gpt4_creative",
            "required": True,
            "pattern": "^[a-z0-9_-]+$",
            "minLength": 3,
            "maxLength": 100,
            "description": "Unique identifier (lowercase, alphanumeric, underscores, hyphens)",
        },
        {
            "name": "name",
            "label": "Configuration Name",
            "type": "text",
            "placeholder": "e.g., GPT-4 Creative",
            "required": True,
            "minLength": 1,
            "maxLength": 200,
        },
        {
            "name": "description",
            "label": "Description",
            "type": "textarea",
            "placeholder": "Describe this configuration...",
            "required": False,
            "maxLength": 500,
        },
        {
            "name": "model_id",
            "label": "Model",
            "type": "select",
            "options": model_options,
            "required": True,
            "description": "Select the AI model for this configuration",
        },
        {
            "name": "model_name",
            "label": "Model Name",
            "type": "text",
            "readonly": True,
            "required": False,
            "description": "API model name (from selected model)",
        },
        {
            "name": "provider_id",
            "label": "Provider",
            "type": "text",
            "readonly": True,
            "required": False,
            "description": "Provider (from selected model)",
        },
        {
            "name": "provider_name",
            "label": "Provider Name",
            "type": "text",
            "readonly": True,
            "required": False,
            "description": "Provider name (from selected model)",
        },
        {
            "name": "provider_type",
            "label": "Provider Type",
            "type": "text",
            "readonly": True,
            "required": False,
            "description": "Provider type (openai, ollama, etc.)",
        },
        {
            "name": "temperature",
            "label": "Temperature",
            "type": "number",
            "placeholder": "0.7",
            "required": False,
            "min": 0.0,
            "max": 2.0,
            "description": "Creativity level (0.0 = deterministic, 2.0 = very creative)",
        },
        {
            "name": "max_tokens",
            "label": "Max Tokens",
            "type": "number",
            "placeholder": "4096",
            "required": False,
            "min": 1,
            "max": 128000,
            "description": "Maximum response length in tokens",
        },
        {
            "name": "top_p",
            "label": "Top P",
            "type": "number",
            "placeholder": "1.0",
            "required": False,
            "min": 0.0,
            "max": 1.0,
            "description": "Nucleus sampling parameter",
        },
        {
            "name": "system_prompt",
            "label": "System Prompt",
            "type": "textarea",
            "placeholder": "You are a helpful assistant...",
            "required": False,
            "maxLength": 10000,
            "description": "Default system prompt for this configuration",
        },
        {
            "name": "use_case",
            "label": "Use Case",
            "type": "select",
            "options": [
                {"value": "general", "label": "General"},
                {"value": "coding", "label": "Coding"},
                {"value": "chat", "label": "Chat"},
                {"value": "analysis", "label": "Analysis"},
                {"value": "creative", "label": "Creative Writing"},
                {"value": "translation", "label": "Translation"},
            ],
            "required": False,
            "description": "Primary use case for this configuration",
        },
        {
            "name": "is_default",
            "label": "Default Config",
            "type": "checkbox",
            "required": False,
            "description": "Set as default configuration for this model",
        },
        {
            "name": "is_active",
            "label": "Active",
            "type": "checkbox",
            "value": True,
            "required": False,
            "description": "Enable/disable this configuration",
        },
        {
            "name": "context_length",
            "label": "Context Length",
            "type": "number",
            "readonly": True,
            "required": False,
            "description": "Model's max context window (from model)",
        },
        {
            "name": "supports_tools",
            "label": "Supports Tools",
            "type": "checkbox",
            "readonly": True,
            "required": False,
            "description": "Model supports function calling (from model)",
        },
        {
            "name": "supports_vision",
            "label": "Supports Vision",
            "type": "checkbox",
            "readonly": True,
            "required": False,
            "description": "Model supports image inputs (from model)",
        },
    ]
    form_schema = form_envelope(
        form_id="ai-model-config-form",
        title="AI Model Configuration",
        description="Configure AI model parameters and runtime settings",
        fields=fields,
        submit_label="Save",
        cancel_label="Cancel",
        method="POST",
    )
    columns = [f["name"] for f in fields]
    return form_schema, columns


def _get_all_configs_joined():
    """
    Get all AI model configs with JOINed model and provider data.
    Each row contains: config fields + model fields + provider fields.
    """
    from ...extensions import db
    
    configs = db.session.query(AIModelConfig).join(
        AIModel, AIModelConfig.model_id == AIModel.model_id
    ).join(
        AIProvider, AIModel.provider_id == AIProvider.provider_id
    ).order_by(AIModelConfig.name).all()
    
    result = []
    for config in configs:
        model = config.model
        provider = model.provider if model else None
        params = config.params or {}
        
        row = {
            "config_id": config.config_id,
            "name": config.name,
            "description": config.description,
            "model_id": config.model_id,
            "model_name": model.model_name if model else None,
            "provider_id": model.provider_id if model else None,
            "provider_name": provider.name if provider else None,
            "provider_type": provider.provider_type if provider else None,
            "temperature": params.get("temperature"),
            "max_tokens": params.get("max_tokens"),
            "top_p": params.get("top_p"),
            "system_prompt": params.get("system_prompt"),
            "use_case": config.use_case,
            "is_default": config.is_default,
            "is_active": config.is_active,
            "context_length": model.context_length if model else None,
            "supports_tools": model.supports_tools if model else False,
            "supports_vision": model.supports_vision if model else False,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }
        result.append(row)
    return result


# --- Grid action handlers ---

def _execute_create_config(data):
    """Create a new AI model configuration."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        
        config_id = data.get("config_id")
        model_id = data.get("model_id")
        name = data.get("name")
        
        if not config_id:
            return jsonify({"error": "Bad Request", "message": "Field 'config_id' is required"}), 400
        if not model_id:
            return jsonify({"error": "Bad Request", "message": "Field 'model_id' is required"}), 400
        if not name:
            return jsonify({"error": "Bad Request", "message": "Field 'name' is required"}), 400
        
        # Check if model exists
        model = ai_repo.get_model_by_id(model_id)
        if not model:
            return jsonify({"error": "Bad Request", "message": f"Model '{model_id}' not found"}), 400
        
        # Check if config already exists
        existing = ai_repo.get_config_by_id(config_id)
        if existing:
            return jsonify({"error": "Conflict", "message": f"Configuration '{config_id}' already exists"}), 409
        
        # Build params from individual fields
        params = {}
        if data.get("temperature") is not None:
            params["temperature"] = float(data.get("temperature"))
        if data.get("max_tokens") is not None:
            params["max_tokens"] = int(data.get("max_tokens"))
        if data.get("top_p") is not None:
            params["top_p"] = float(data.get("top_p"))
        if data.get("system_prompt"):
            params["system_prompt"] = data.get("system_prompt")
        
        from flask import session
        current_user = session.get("username", "system")
        
        config = ai_repo.create_config(
            config_id=config_id,
            model_id=model_id,
            name=name,
            description=data.get("description"),
            params=params if params else None,
            service=data.get("service"),
            is_default=data.get("is_default", False),
            use_case=data.get("use_case"),
            created_by=current_user,
        )
        
        return jsonify(config.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logger.error("Error creating AI config: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_update_config(id_val, data):
    """Update an AI model configuration."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        
        config_id = str(id_val) if id_val is not None else data.get("config_id")
        if not config_id:
            return jsonify({"error": "Bad Request", "message": "Update requires 'id' (config_id)"}), 400
        
        config = ai_repo.get_config_by_id(config_id)
        if not config:
            return jsonify({"error": "Not Found", "message": f"Configuration '{config_id}' not found"}), 404
        
        # Build params from individual fields, merging with existing
        params = config.params.copy() if config.params else {}
        if "temperature" in data and data.get("temperature") is not None:
            params["temperature"] = float(data.get("temperature"))
        if "max_tokens" in data and data.get("max_tokens") is not None:
            params["max_tokens"] = int(data.get("max_tokens"))
        if "top_p" in data and data.get("top_p") is not None:
            params["top_p"] = float(data.get("top_p"))
        if "system_prompt" in data:
            if data.get("system_prompt"):
                params["system_prompt"] = data.get("system_prompt")
            elif "system_prompt" in params:
                del params["system_prompt"]
        
        from flask import session
        current_user = session.get("username", "system")
        
        update_fields = {"updated_by": current_user}
        if "name" in data:
            update_fields["name"] = data.get("name")
        if "description" in data:
            update_fields["description"] = data.get("description")
        if "service" in data:
            update_fields["service"] = data.get("service")
        if "is_default" in data:
            update_fields["is_default"] = data.get("is_default")
        if "is_active" in data:
            update_fields["is_active"] = data.get("is_active")
        if "use_case" in data:
            update_fields["use_case"] = data.get("use_case")
        if params:
            update_fields["params"] = params
        
        updated = ai_repo.update_config(config_id, **update_fields)
        return jsonify(updated.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logger.error("Error updating AI config: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_delete_config(data):
    """Delete AI model configurations."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        
        ids = data.get("ids", [])
        if not ids:
            return jsonify({"error": "Bad Request", "message": "Field 'ids' is required"}), 400
        
        deleted_ids = []
        errors = []
        
        for config_id in ids:
            success, error = ai_repo.delete_config(config_id)
            if success:
                deleted_ids.append(config_id)
            else:
                errors.append(error)
        
        if errors and not deleted_ids:
            return jsonify({"error": "Delete Failed", "message": "; ".join(errors)}), 400
        
        return jsonify({
            "message": f"{len(deleted_ids)} configuration(s) deleted",
            "deleted": deleted_ids,
            "errors": errors if errors else None
        }), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logger.error("Error deleting AI configs: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


GRID_ACTION_HANDLERS["ai-model-config"] = {
    "create": _execute_create_config,
    "update": _execute_update_config,
    "delete": _execute_delete_config,
}


# --- Routes ---

@api_bp.get("/ai-model-config/form-schema")
@api_bp.get("/ai-model-config/form-schema/")
@api_bp.post("/ai-model-config/form-schema")
@api_bp.post("/ai-model-config/form-schema/")
def get_ai_model_config_form_schema():
    """Get form schema for AI model config."""
    form_schema, _ = _build_ai_model_config_form_schema()
    return jsonify(dump_grid_form_dict(form_schema, action=url_for("api.create_ai_model_config")))


@api_bp.get("/ai-model-config/list")
@api_bp.get("/ai-model-config/list/")
@api_bp.post("/ai-model-config/list")
@api_bp.post("/ai-model-config/list/")
def get_ai_model_config_list():
    """
    Get list of all AI model configs with JOINed model and provider data.
    Returns DataGridResponseSchema with columns and form_schema.
    """
    data = _get_all_configs_joined()
    form_schema, columns = _build_ai_model_config_form_schema()
    
    payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
    out = payload.model_dump()
    out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_ai_model_config"))
    return jsonify(out)


@api_bp.get("/ai-model-config/<config_id>")
@api_bp.get("/ai-model-config/<config_id>/")
def get_ai_model_config_by_id(config_id: str):
    """Get a single AI model config by ID."""
    config = ai_repo.get_config_by_id(config_id)
    if not config:
        return jsonify({"error": "Not Found", "message": f"Configuration '{config_id}' not found"}), 404
    return jsonify(config.to_dict())


@api_bp.post("/ai-model-config/create")
@api_bp.post("/ai-model-config/create/")
@validate_payload(AIModelConfigCreateSchema)
def create_ai_model_config(data: AIModelConfigCreateSchema):
    """Create a new AI model configuration."""
    return _execute_create_config(data.model_dump())


@api_bp.post("/ai-model-config/update")
@api_bp.post("/ai-model-config/update/")
@api_bp.put("/ai-model-config/update")
@api_bp.put("/ai-model-config/update/")
@validate_payload(AIModelConfigUpdateSchema)
def update_ai_model_config(data: AIModelConfigUpdateSchema):
    """Update an AI model configuration."""
    return _execute_update_config(data.config_id, data.model_dump(exclude_none=True))


@api_bp.post("/ai-model-config/delete")
@api_bp.post("/ai-model-config/delete/")
@api_bp.delete("/ai-model-config/delete")
@api_bp.delete("/ai-model-config/delete/")
@validate_payload(AIModelConfigDeleteSchema)
def delete_ai_model_config(data: AIModelConfigDeleteSchema):
    """Delete AI model configurations."""
    return _execute_delete_config(data.model_dump())


# --- Provider endpoints ---

@api_bp.get("/ai-provider/list")
@api_bp.get("/ai-provider/list/")
def get_ai_provider_list():
    """Get list of all AI providers."""
    providers = ai_repo.get_all_providers(active_only=False)
    return jsonify([p.to_dict() for p in providers])


# --- Model endpoints ---

@api_bp.get("/ai-model/list")
@api_bp.get("/ai-model/list/")
def get_ai_model_list():
    """Get list of all AI models."""
    models = ai_repo.get_all_models(active_only=False)
    return jsonify([m.to_dict() for m in models])


@api_bp.get("/ai-model/ready")
@api_bp.get("/ai-model/ready/")
def get_ready_ai_models():
    """Get list of all ready-to-use AI models (active model + active provider)."""
    supports_tools = None
    supports_vision = None
    provider_type = None
    local_only = False
    
    from flask import request
    if request.args.get("supports_tools"):
        supports_tools = request.args.get("supports_tools").lower() == "true"
    if request.args.get("supports_vision"):
        supports_vision = request.args.get("supports_vision").lower() == "true"
    if request.args.get("provider_type"):
        provider_type = request.args.get("provider_type")
    if request.args.get("local_only"):
        local_only = request.args.get("local_only").lower() == "true"
    
    models = ai_repo.get_ready_models(
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        provider_type=provider_type,
        local_only=local_only
    )
    return jsonify(models)
