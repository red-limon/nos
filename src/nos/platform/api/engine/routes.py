"""Engine API: unified list of registered nodes, workflows, assistants."""

from flask import jsonify, request
from pydantic import ValidationError

from ..routes import api_bp
from ..common import validate_payload
from ..data_grid_schema import DataGridResponseSchema
from ..form_wire import form_envelope
from ...services.sqlalchemy import RegistrationStatus
from ...services.sqlalchemy.node import repository as node_repo
from ...services.sqlalchemy.workflow import repository as workflow_repo
from ...services.sqlalchemy.assistant import repository as assistant_repo

from .schemas import EngineGetRecordSchema, EngineValidateCommandSchema, ENGINE_COMMANDS


def _engine_form_schema():
    """Minimal form schema for engine grid (read-only; client may ignore)."""
    return form_envelope(form_id="engine-grid", title="Engine", fields=[], submit_label="Submit")


@api_bp.get("/engine/list")
@api_bp.get("/engine/list/")
@api_bp.post("/engine/list")
@api_bp.post("/engine/list/")
def get_engine_list():
    """
    List all nodes, workflows and assistants with registration_status OK.
    Returns DataGridResponseSchema: columns type, id, name; minimal form_schema.
    """
    ok = RegistrationStatus.OK.value
    data = []

    for node in node_repo.get_all():
        if node.registration_status != ok:
            continue
        data.append({
            "row_id": f"nd:{node.node_id}",
            "type": "nd",
            "id": node.node_id,
            "name": node.name or "",
        })

    for wf in workflow_repo.get_all_registered():
        data.append({
            "row_id": f"wk:{wf.workflow_id}",
            "type": "wk",
            "id": wf.workflow_id,
            "name": wf.name or "",
        })

    for ass in assistant_repo.get_all():
        if ass.registration_status != ok:
            continue
        data.append({
            "row_id": f"ass:{ass.assistant_id}",
            "type": "ass",
            "id": ass.assistant_id,
            "name": ass.name or "",
        })

    columns = ["type", "id", "name"]
    form_schema = _engine_form_schema()
    payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
    return jsonify(payload.model_dump())


def _get_engine_record_response(data: EngineGetRecordSchema):
    """Look up record by type and id; return (json_response, status_code) or (tuple for 404/400)."""
    record = None
    if data.type == "nd":
        record = node_repo.get_by_id(data.id)
    elif data.type == "wk":
        record = workflow_repo.get_by_id(data.id)
    elif data.type == "ass":
        record = assistant_repo.get_by_id(data.id)

    if record is None:
        return jsonify({"error": "Not Found", "message": f"Record not found: type={data.type}, id={data.id}"}), 404
    return jsonify(record.to_dict()), 200


@api_bp.get("/engine/record")
@api_bp.get("/engine/record/")
def get_engine_record_get():
    """Get record by type and id (query params: type, id). Returns record JSON only."""
    try:
        data = EngineGetRecordSchema(type=request.args.get("type"), id=request.args.get("id"))
    except ValidationError as e:
        return jsonify({"error": "Validation Error", "message": "Invalid query params", "details": e.errors()}), 400
    return _get_engine_record_response(data)


@api_bp.post("/engine/record")
@api_bp.post("/engine/record/")
@validate_payload(EngineGetRecordSchema)
def get_engine_record_post(data: EngineGetRecordSchema):
    """Get record by type and id (body: type, id). Returns record JSON only."""
    return _get_engine_record_response(data)


@api_bp.post("/engine/validate-command")
@api_bp.post("/engine/validate-command/")
@validate_payload(EngineValidateCommandSchema)
def validate_engine_command(data: EngineValidateCommandSchema):
    """
    Validate and parse an engine command.
    Returns { valid: true, help: true, commands: {...} } for help command.
    Returns { valid: true, execute: true, background: bool, debug_mode: str } for run commands.
    Returns { valid: true, publish: true, type, id } for pub command.
    Returns { valid: true, unpublish: true, type, id } for unpub command.
    Returns { valid: true, exit: true } for exit command.
    Returns { valid: false, error: str } for invalid commands.
    """
    cmd = data.command.strip().lower()
    tokens = cmd.split()
    if not tokens:
        return jsonify({"valid": False, "error": "Empty command"}), 400

    token1 = tokens[0]
    extra_tokens = tokens[1:]

    # Help command
    if token1 == "help":
        commands_structured = {
            "sections": [
                {
                    "title": "Token 1: Primary Command",
                    "commands": [
                        {"name": "help", "description": "Show available commands"},
                        {"name": "pub", "description": "Publish plugin (update status from OK to Published)"},
                        {"name": "unpub", "description": "Unpublish plugin (update status from Published to OK)"},
                        {"name": "run", "description": "Execute plugin (Token 2 & 3 optional, default: --sync debug)"},
                        {"name": "exec", "description": "Alias for run"},
                        {"name": "exit", "description": "Close this console tab"},
                    ],
                },
                {
                    "title": "Token 2: Execution Mode (optional, default: --sync)",
                    "commands": [
                        {"name": "--background", "description": "Run in background (non-blocking)"},
                        {"name": "--sync", "description": "Run synchronously (blocking, interactive)"},
                    ],
                },
                {
                    "title": "Token 3: Debug mode (optional, default: debug)",
                    "commands": [
                        {"name": "trace", "description": "Logs and init form; no intermediate node forms"},
                        {"name": "debug", "description": "All forms and logs (interactive step-by-step)"},
                    ],
                },
            ],
            "examples": [
                {"name": "run", "description": "Quick run (default: --sync debug)"},
                {"name": "run --sync debug", "description": "Interactive execution with all forms and logs"},
                {"name": "run --background", "description": "Background execution (non-interactive); use trace internally"},
            ],
        }
        return jsonify({"valid": True, "help": True, "commands": commands_structured})

    # Pub command
    if token1 == "pub":
        if extra_tokens:
            return jsonify({
                "valid": True,
                "publish": True,
                "type": data.type,
                "id": data.id,
                "warning": "Extra tokens ignored for 'pub' command",
            })
        return jsonify({"valid": True, "publish": True, "type": data.type, "id": data.id})

    # Unpub command
    if token1 == "unpub":
        if extra_tokens:
            return jsonify({
                "valid": True,
                "unpublish": True,
                "type": data.type,
                "id": data.id,
                "warning": "Extra tokens ignored for 'unpub' command",
            })
        return jsonify({"valid": True, "unpublish": True, "type": data.type, "id": data.id})

    # Exit command
    if token1 == "exit":
        if extra_tokens:
            return jsonify({
                "valid": True,
                "exit": True,
                "warning": "Extra tokens ignored for 'exit' command",
            })
        return jsonify({"valid": True, "exit": True})

    # Run command (accept "run" or "exec")
    if token1 in ("run", "exec"):
        mode_token = extra_tokens[0] if len(extra_tokens) >= 1 else "--sync"
        output_token = extra_tokens[1] if len(extra_tokens) >= 2 else "debug"

        if mode_token not in ("--background", "--sync"):
            return jsonify({
                "valid": False,
                "error": f"Invalid mode '{mode_token}'. Use '--background' or '--sync'",
            }), 400

        if output_token not in ("trace", "debug"):
            return jsonify({
                "valid": False,
                "error": f"Invalid debug mode '{output_token}'. Use 'trace' or 'debug'",
            }), 400

        background = mode_token == "--background"
        return jsonify({
            "valid": True,
            "execute": True,
            "background": background,
            "debug_mode": output_token,
        })

    # Unknown command
    return jsonify({
        "valid": False,
        "error": f"Unknown command '{token1}'. Use 'help', 'run', 'exec', 'pub', 'unpub', or 'exit'",
    }), 400


@api_bp.post("/engine/publish")
@api_bp.post("/engine/publish/")
def publish_record():
    """Publish a record (update status from OK to Published)."""
    data = request.get_json()
    rec_type = data.get("type")
    rec_id = data.get("id")
    
    if not rec_type or not rec_id:
        return jsonify({"success": False, "error": "Missing type or id"}), 400
    
    repo = {"nd": node_repo, "wk": workflow_repo, "ass": assistant_repo}.get(rec_type)
    if not repo:
        return jsonify({"success": False, "error": f"Invalid type: {rec_type}"}), 400
    
    record = repo.get_by_id(rec_id)
    if not record:
        return jsonify({"success": False, "error": f"Record not found: {rec_id}"}), 404
    
    if getattr(record, "registration_status", None) == RegistrationStatus.PUBLISHED.value:
        return jsonify({"success": False, "error": f"Record '{rec_id}' is already published"}), 400
    
    if getattr(record, "registration_status", None) != RegistrationStatus.OK.value:
        return jsonify({"success": False, "error": f"Cannot publish: status is '{getattr(record, 'registration_status', '')}', must be 'OK'"}), 400
    
    repo.update(rec_id, {"registration_status": RegistrationStatus.PUBLISHED.value})
    type_label = {"nd": "Node", "wk": "Workflow", "ass": "Assistant"}.get(rec_type, "Record")
    return jsonify({"success": True, "message": f"{type_label} '{rec_id}' published successfully"})


@api_bp.post("/engine/unpublish")
@api_bp.post("/engine/unpublish/")
def unpublish_record():
    """Unpublish a record (update status from Published to OK)."""
    data = request.get_json()
    rec_type = data.get("type")
    rec_id = data.get("id")
    
    if not rec_type or not rec_id:
        return jsonify({"success": False, "error": "Missing type or id"}), 400
    
    repo = {"nd": node_repo, "wk": workflow_repo, "ass": assistant_repo}.get(rec_type)
    if not repo:
        return jsonify({"success": False, "error": f"Invalid type: {rec_type}"}), 400
    
    record = repo.get_by_id(rec_id)
    if not record:
        return jsonify({"success": False, "error": f"Record not found: {rec_id}"}), 404
    
    if getattr(record, "registration_status", None) != RegistrationStatus.PUBLISHED.value:
        return jsonify({"success": False, "error": f"Record '{rec_id}' is not published (status: {getattr(record, 'registration_status', '')})"}), 400
    
    repo.update(rec_id, {"registration_status": RegistrationStatus.OK.value})
    type_label = {"nd": "Node", "wk": "Workflow", "ass": "Assistant"}.get(rec_type, "Record")
    return jsonify({"success": True, "message": f"{type_label} '{rec_id}' unpublished successfully"})
