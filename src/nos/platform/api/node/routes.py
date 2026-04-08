"""Node API routes. URL prefix: /nodes."""

import logging
from typing import Optional

from flask import jsonify, make_response, url_for

from ..routes import api_bp
from ..common import validate_payload, _call_callback_and_return, GRID_ACTION_HANDLERS
from ..data_grid_schema import DataGridResponseSchema
from ..form_wire import dump_grid_form_dict, form_envelope, form_schema_with_values
from ...services.sqlalchemy import NodeDbModel, RegistrationStatus
from ...services.sqlalchemy.node import repository as node_repo
from .schemas import (
    NodeCreateSchema,
    NodeDeleteSchema,
    NodeExecuteDirectSchema,
    NodeExecuteFromDbSchema,
    NodeExecuteSchema,
    NodeSaveCodeSchema,
    NodeUpdateSchema,
)


def _build_node_form_schema():
    """Build form_schema dict and column names for node form (shared by form-schema and list endpoints)."""
    fields = [
        {
            "name": "node_id",
            "label": "Node ID",
            "type": "text",
            "placeholder": "e.g., my_node",
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
            "placeholder": "e.g., MyNode",
            "required": True,
            "minLength": 1,
            "maxLength": 200,
        },
        {
            "name": "module_path",
            "label": "Module Path",
            "type": "text",
            "placeholder": "e.g., nos.plugins.nodes.my_node",
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
            "type": "text",
            "required": False,
            "readonly": True,
            "description": "OK if loaded in registry; Error if not; pub = published (regredire a ok dalla console)",
        },
    ]
    form_schema = form_envelope(
        form_id="node-form",
        title="Node Plugin",
        description="Add or edit a node plugin",
        fields=fields,
        submit_label="Save",
        cancel_label="Cancel",
        method="POST",
    )
    columns = [f["name"] for f in fields]
    return form_schema, columns


# --- Grid-to-action-dispatcher handlers (same pattern as test_datagrid) ---

def _execute_create_node(data):
    """Create a node from grid submit. data: dict with node_id, class_name, module_path, name, status, version, etc."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        from flask import session
        current_user = session.get("username", "system")
        node_id = data.get("node_id")
        if not node_id:
            return jsonify({"error": "Bad Request", "message": "Field 'node_id' is required"}), 400
        from nos.core.engine.plugin_loader import try_register_node
        ok, reg_error = try_register_node(
            data.get("module_path") or "",
            data.get("class_name") or "",
            node_id,
        )
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
        if not ok:
            logging.getLogger(__name__).info("Node create: registration failed for %s: %s", node_id, reg_error)
        node, err = node_repo.create(
            node_id=node_id,
            class_name=data.get("class_name") or "",
            module_path=data.get("module_path") or "",
            name=data.get("name"),
            created_by=current_user or data.get("created_by", "system"),
            updated_by=current_user or data.get("updated_by", "system"),
            registration_status=status,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Node '{node_id}' already exists"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(node.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error creating node: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_update_node(id_val, data):
    """Update a node from grid submit. id_val is node_id (string)."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        node_id = str(id_val) if id_val is not None else data.get("node_id")
        if not node_id:
            return jsonify({"error": "Bad Request", "message": "Update requires 'id' (node_id) in body or path"}), 400
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
        node, err = node_repo.update(node_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Node '{node_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Node conflict"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(node.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error updating node: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_delete_node(data):
    """Delete one or more nodes from grid submit. data must contain 'node_ids' (list) or 'ids' (list of node_id strings)."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        node_ids = data.get("node_ids") or data.get("ids", [])
        if not node_ids:
            return jsonify({"error": "Bad Request", "message": "Field 'node_ids' or 'ids' is required and must be a non-empty array"}), 400
        if not isinstance(node_ids, list):
            return jsonify({"error": "Bad Request", "message": "Field 'node_ids' must be an array"}), 400
        node_ids = [str(i) for i in node_ids]
        deleted_ids, not_found = node_repo.delete_many(node_ids)
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify({"message": f"{len(deleted_ids)} node(s) deleted", "deleted": deleted_ids}), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error deleting nodes: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


GRID_ACTION_HANDLERS["node"] = {
    "create": _execute_create_node,
    "update": _execute_update_node,
    "delete": _execute_delete_node,
}


# --- Routes ---
@api_bp.get("/node/form-schema")
@api_bp.get("/node/form-schema/")
@api_bp.post("/node/form-schema")
@api_bp.post("/node/form-schema/")
def get_node_form_schema():
    """Get form_schema for node to render in <form-loader> (create mode)."""
    form_schema, _ = _build_node_form_schema()
    return jsonify(dump_grid_form_dict(form_schema, action=url_for("api.create_node")))


@api_bp.get("/node/form-schema/<node_id>")
@api_bp.get("/node/form-schema/<node_id>/")
def get_node_form_schema_with_data(node_id: str):
    """Get form schema at root (title, fields with values) for node edit mode. Used by wx-form-loader."""
    form_schema, _ = _build_node_form_schema()
    node = node_repo.get_by_id(node_id)
    if not node:
        return jsonify({"error": "Not Found", "message": f"Node '{node_id}' not found"}), 404
    node_dict = node.to_dict()
    form_schema_filled = form_schema_with_values(form_schema, node_dict)
    return jsonify(dump_grid_form_dict(form_schema_filled, action=url_for("api.update_node_by_id")))


@api_bp.get("/node/list")
@api_bp.get("/node/list/")
@api_bp.post("/node/list")
@api_bp.post("/node/list/")
def get_node_list():
    """Get list of all nodes for data-grid + form-loader (DataGridResponseSchema)."""
    nodes = node_repo.get_all()
    data = [node.to_dict() for node in nodes]
    form_schema, columns = _build_node_form_schema()

    payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
    out = payload.model_dump()
    out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_node"))
    return jsonify(out)


@api_bp.get("/node")
@api_bp.get("/node/")
def get_node_form_schema_only():
    """Return form_schema only (create mode). Used by wx-form-loader when no record id."""
    form_schema, _ = _build_node_form_schema()
    return jsonify(dump_grid_form_dict(form_schema, action=url_for("api.create_node")))


@api_bp.get("/node/<node_id>")
@api_bp.get("/node/<node_id>/")
@api_bp.post("/node/<node_id>")
@api_bp.post("/node/<node_id>/")
def get_node_by_id(node_id: str):
    """Get a single node by node_id. Returns form schema at root (title, fields with values) for wx-form-loader."""
    node = node_repo.get_by_id(node_id)
    if not node:
        return jsonify({"error": "Not Found", "message": f"Node '{node_id}' not found"}), 404
    node_dict = node.to_dict()
    form_schema, _ = _build_node_form_schema()
    form_schema_filled = form_schema_with_values(form_schema, node_dict)
    return jsonify(dump_grid_form_dict(form_schema_filled, action=url_for("api.update_node_by_id")))


@api_bp.post("/node/create")
@api_bp.post("/node/create/")
@validate_payload(NodeCreateSchema)
def create_node(data: NodeCreateSchema):
    """Create a new node: (1) register in registry, (2) set registration_status OK/Error, (3) insert in DB."""
    try:
        from flask import session
        from nos.core.engine.plugin_loader import try_register_node
        current_user = session.get("username", "system")
        ok, reg_error = try_register_node(data.module_path, data.class_name, data.node_id)
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
        if not ok:
            import logging
            logging.getLogger(__name__).info("Node create: registration failed for %s: %s", data.node_id, reg_error)
        node, err = node_repo.create(
            node_id=data.node_id,
            class_name=data.class_name,
            module_path=data.module_path,
            name=data.name,
            created_by=current_user or data.created_by,
            updated_by=current_user or data.updated_by,
            registration_status=status,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Node '{data.node_id}' already exists"}), 409
        return jsonify(node.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error creating node: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500



@api_bp.post("/node/update")
@api_bp.post("/node/update/")
@validate_payload(NodeUpdateSchema)
def update_node_by_id(data: NodeUpdateSchema):
    """Update an existing node. node_id is taken from request body (data.node_id)."""
    try:
        node_id = data.node_id
        payload = data.model_dump(exclude_unset=True)
        payload.pop("node_id", None)  # do not pass node_id into update payload (it's the target id)
        node, err = node_repo.update(node_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Node '{node_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Node conflict"}), 409
        return jsonify(node.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error updating node: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.delete("/node")
@api_bp.delete("/node/")
@api_bp.post("/node/delete")
@api_bp.post("/node/delete/")
@validate_payload(NodeDeleteSchema)
def delete_nodes(data: NodeDeleteSchema):
    """Delete multiple nodes by node_id. Body: JSON with 'ids' (list of strings)."""
    try:
        deleted_ids, _ = node_repo.delete_many(data.ids)
        return jsonify({"message": f"{len(deleted_ids)} node(s) deleted"}), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error deleting nodes: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _node_run_request_extras(client_request: Optional[dict]) -> Optional[dict]:
    """Wrap client `request` under `context` so engine merge does not collide with node_id/state/input_params."""
    if not client_request:
        return None
    return {"context": client_request}


def _run_node_sync(
    node,
    state,
    input_params,
    node_id,
    channel,
    *,
    output_format=None,
    client_request=None,
):
    """
    Execute node with platform EventLog. Returns NodeExecutionResult.
    input_params is raw dict; Node.execute() validates state and params internally.
    """
    from nos.core.execution_log import ObservableStateDict
    from nos.core.engine.node import NodeExecutionResult

    node.set_exec_log(channel)

    # Observable state for tracking state changes (node._on_state_changed emits to channel)
    observable_state = ObservableStateDict(
        state.copy(),
        on_set=lambda k, o, n: node._on_state_changed(k, o, n),
    )
    
    run_request = {
        "node_id": node_id,
        "state": state.copy(),
        "input_params": input_params.copy(),
    }
    if output_format is not None:
        run_request["output_format"] = str(output_format).lower().strip()
    if client_request:
        run_request["context"] = client_request
    try:
        # node_start and node_end are emitted inside Node.run -> execute()
        result = node.run(
            observable_state,
            input_params,
            request=run_request,
            output_format=output_format,
        )
    except TypeError as e:
        if "not subscriptable" in str(e):
            raise TypeError(
                f"Node {node_id}: input_params is a Pydantic model instance, not a dict. "
                "Use params_dict = input_params.model_dump() if hasattr(input_params, 'model_dump') else (input_params or {}), "
                "then access keys via params_dict['key'] or params_dict.get('key', default). See docs/README.md."
            ) from e
        raise
    return result


def _execute_node_registry(data: NodeExecuteSchema):
    """
    Execute a single node from registry (standalone, outside of a workflow).
    Shared by POST /node/execute and POST /run (target=node).
    """
    engine = _get_shared_engine()

    state = data.state.copy() if data.state else {}
    input_params = data.input_params if data.input_params is not None else {}

    try:
        ret = engine.run_node(
            node_id=data.node_id,
            state=state,
            input_params=input_params,
            mode="prod",
            room=None,  # No real-time streaming for REST API
            background=data.background,
            output_format=data.output_format,
            run_request_extras=_node_run_request_extras(getattr(data, "request", None)),
        )

        if data.background:
            execution_id = ret
            return jsonify({
                "execution_id": execution_id,
                "node_id": data.node_id,
                "status": "running",
                "message": "Node started in background (use GET /node/execution/{id} to check status)",
            }), 202

        # Synchronous: engine returns (execution_id, result_dict)
        execution_id, result_dict = ret
        if result_dict.get("success"):
            return jsonify(result_dict.get("result", {})), 200
        else:
            return jsonify({
                "error": "Execution Error",
                "message": result_dict.get("error", "Unknown error"),
                "node_id": data.node_id
            }), 500

    except ValueError as e:
        return jsonify({
            "error": "Not Found",
            "message": str(e)
        }), 404
    except Exception as e:
        logging.getLogger(__name__).error(f"Error executing node {data.node_id}: {e}", exc_info=True)
        return jsonify({
            "error": "Execution Error",
            "message": str(e),
            "node_id": data.node_id
        }), 500


@api_bp.post("/node/execute")
@validate_payload(NodeExecuteSchema)
def execute_node(data: NodeExecuteSchema):
    """Execute a single node from registry. Uses WorkflowEngine for execution tracking and stop support."""
    return _execute_node_registry(data)


def _is_module_path_allowed(module_path: str) -> bool:
    """Check if module_path is under nos.plugins.nodes (whitelist for security)."""
    file_path, _ = _module_path_to_file_path(module_path)
    return file_path is not None


def _create_node_instance_dynamic(module_path: str, class_name: str, node_id: str, name: str | None):
    """
    Import module, get class, instantiate node. No registry/DB required.
    Returns (node, None) on success or (None, error_response) tuple (jsonify dict, status_code).
    """
    import importlib
    from nos.core.engine.base import Node

    if not _is_module_path_allowed(module_path):
        return None, ({"error": "Validation Error", "message": "module_path must be under nos.plugins.nodes"}, 400)
    try:
        module = importlib.import_module(module_path)
        node_class = getattr(module, class_name)
    except ImportError as e:
        return None, ({"error": "Import Error", "message": str(e)}, 400)
    except AttributeError as e:
        return None, ({"error": "Validation Error", "message": f"Class '{class_name}' not found in module: {e}"}, 400)
    if not isinstance(node_class, type) or not issubclass(node_class, Node):
        return None, ({"error": "Validation Error", "message": f"'{class_name}' is not a valid Node class"}, 400)
    try:
        node = node_class(node_id=node_id, name=name or node_id)
        return node, None
    except Exception as e:
        return None, ({"error": "Internal Error", "message": f"Failed to create node instance: {e}"}, 500)


def _run_node_execution_response(
    node,
    node_id: str,
    state: dict,
    input_params: dict,
    background: bool,
    channel,
    *,
    output_format=None,
):
    """Common execution logic for execute-direct and execute-from-db. Returns (jsonify_dict, status_code)."""
    import threading

    if background:
        def run_in_thread():
            try:
                _run_node_sync(
                    node,
                    state,
                    input_params,
                    node_id,
                    channel,
                    output_format=output_format,
                )
            except Exception as e:
                logging.getLogger(__name__).error(f"Background node {node_id} failed: {e}", exc_info=True)
                channel.log("error", str(e))
        t = threading.Thread(target=run_in_thread, daemon=True)
        t.start()
        return {"execution_id": channel.execution_id, "node_id": node_id, "status": "running", "message": "Node started in background"}, 202
    try:
        result = _run_node_sync(
            node,
            state,
            input_params,
            node_id,
            channel,
            output_format=output_format,
        )
        return result.model_dump(), 200
    except Exception as e:
        logging.getLogger(__name__).error(f"Error executing node {node_id}: {e}", exc_info=True)
        return {"error": "Execution Error", "message": str(e), "node_id": node_id}, 500


def dispatch_node_execute_direct(data: NodeExecuteDirectSchema):
    """
    Run a node by importing module_path/class_name (dev load) then engine.run_node.
    Shared by POST /node/execute-direct and POST /api/run (target=node, load=module).
    """
    if not _is_module_path_allowed(data.module_path):
        return jsonify({
            "error": "Validation Error",
            "message": "module_path must be under nos.plugins.nodes"
        }), 400

    engine = _get_shared_engine()
    state = data.state.copy() if data.state else {}
    input_params = data.input_params if data.input_params is not None else {}
    resolved_node_id = (data.node_id or "").strip() or "adhoc_direct"

    try:
        ret = engine.run_node(
            node_id=resolved_node_id,
            state=state,
            input_params=input_params,
            mode="dev",
            module_path=data.module_path,
            class_name=data.class_name,
            room=None,
            background=data.background,
            output_format=data.output_format,
            run_request_extras=_node_run_request_extras(getattr(data, "request", None)),
        )

        if data.background:
            execution_id = ret
            return jsonify({
                "execution_id": execution_id,
                "node_id": resolved_node_id,
                "status": "running",
                "message": "Node started in background (use GET /node/execution/{id} to check status)",
            }), 202

        execution_id, result_dict = ret
        if result_dict.get("success"):
            return jsonify(result_dict.get("result", {})), 200
        return jsonify({
            "error": "Execution Error",
            "message": result_dict.get("error", "Unknown error"),
            "node_id": resolved_node_id
        }), 500

    except ValueError as e:
        return jsonify({
            "error": "Validation Error",
            "message": str(e)
        }), 400
    except Exception as e:
        logging.getLogger(__name__).error(f"Error executing node direct: {e}", exc_info=True)
        return jsonify({
            "error": "Execution Error",
            "message": str(e),
        }), 500


def dispatch_node_execute_from_db(data: NodeExecuteFromDbSchema):
    """
    Run a node by resolving module_path/class_name from the node table (dev load).
    Shared by POST /node/execute-from-db.
    """
    from nos.platform.services.sqlalchemy.node import repository as node_repo

    engine = _get_shared_engine()
    state = data.state.copy() if data.state else {}
    input_params = data.input_params if data.input_params is not None else {}

    node_record = node_repo.get_by_id(data.node_id)
    if not node_record:
        return jsonify({"error": "Not Found", "message": f"Node '{data.node_id}' not found in database"}), 404

    try:
        ret = engine.run_node(
            node_id=data.node_id,
            state=state,
            input_params=input_params,
            mode="dev",
            module_path=node_record.module_path,
            class_name=node_record.class_name,
            room=None,
            background=data.background,
            output_format=data.output_format,
            run_request_extras=_node_run_request_extras(getattr(data, "request", None)),
        )

        if data.background:
            execution_id = ret
            return jsonify({
                "execution_id": execution_id,
                "node_id": data.node_id,
                "status": "running",
                "message": "Node started in background (use GET /node/execution/{id} to check status)",
            }), 202

        execution_id, result_dict = ret
        if result_dict.get("success"):
            return jsonify(result_dict.get("result", {})), 200
        return jsonify({
            "error": "Execution Error",
            "message": result_dict.get("error", "Unknown error"),
            "node_id": data.node_id
        }), 500

    except ValueError as e:
        return jsonify({
            "error": "Not Found",
            "message": str(e)
        }), 404
    except Exception as e:
        logging.getLogger(__name__).error(f"Error executing node from db: {e}", exc_info=True)
        return jsonify({
            "error": "Execution Error",
            "message": str(e),
            "node_id": data.node_id
        }), 500


@api_bp.post("/node/execute-direct")
@api_bp.post("/node/execute-direct/")
@validate_payload(NodeExecuteDirectSchema)
def execute_node_direct(data: NodeExecuteDirectSchema):
    """
    Execute a node by module_path and class_name (no registry/DB required).

    Uses WorkflowEngine for execution tracking and stop support.
    Whitelist: nos.plugins.nodes.
    """
    return dispatch_node_execute_direct(data)


@api_bp.post("/node/execute-from-db")
@api_bp.post("/node/execute-from-db/")
@validate_payload(NodeExecuteFromDbSchema)
def execute_node_from_db(data: NodeExecuteFromDbSchema):
    """
    Execute a node by node_id, loading module_path and class_name from DB.

    Uses WorkflowEngine for execution tracking and stop support.
    Whitelist: nos.plugins.nodes.
    """
    return dispatch_node_execute_from_db(data)


def _ensure_package_init(allowed_dir: str, target_dir: str) -> None:
    """Ensure every directory from allowed_dir to target_dir (inclusive) has __init__.py (Python package)."""
    import os
    allowed_real = os.path.realpath(allowed_dir)
    current = os.path.realpath(target_dir)
    if not current.startswith(allowed_real + os.sep) and current != allowed_real:
        return
    to_create = []
    while current and current != allowed_real and current != os.path.dirname(current):
        init_path = os.path.join(current, "__init__.py")
        if not os.path.isfile(init_path):
            to_create.append(init_path)
        current = os.path.dirname(current)
    for init_path in to_create:
        with open(init_path, "w", encoding="utf-8") as f:
            f.write("")

def _resolve_node_file_path(module_path: str, node_id: str):
    """Resolve module_path + node_id to absolute file path under plugins/nodes. Returns (file_path, allowed_dir, pkg_dir) or (None, None, None) on validation error."""
    import os
    try:
        import nos
        pkg_dir = os.path.dirname(os.path.abspath(nos.__file__))
    except Exception:
        return None, None, None
    parts = (module_path or "").strip().split(".")
    if not parts or parts[0] != "nos":
        return None, None, None
    rel_parts = parts[1:]
    if not rel_parts or not (node_id or "").strip():
        return None, None, None
    allowed_dir = os.path.realpath(os.path.join(pkg_dir, "plugins", "nodes"))
    # Primary: package dir = full module_path, file = node_id.py (e.g. .../request_node/request_ws.py)
    dir_path = os.path.join(pkg_dir, *rel_parts)
    file_path = os.path.realpath(os.path.join(dir_path, (node_id or "").strip() + ".py"))
    if not (file_path.startswith(allowed_dir + os.sep) or file_path == allowed_dir):
        return None, None, None
    return file_path, allowed_dir, pkg_dir


def _module_path_to_file_path(module_path: str):
    """Resolve module path to .py file path: dots become path segments, then add .py. Returns (file_path, allowed_dir) or (None, None)."""
    import os
    try:
        import nos
        pkg_dir = os.path.dirname(os.path.abspath(nos.__file__))
    except Exception:
        return None, None
    parts = (module_path or "").strip().split(".")
    if not parts or parts[0] != "nos":
        return None, None
    rel_parts = parts[1:]
    if not rel_parts:
        return None, None
    allowed_dir = os.path.realpath(os.path.join(pkg_dir, "plugins", "nodes"))
    file_path = os.path.realpath(os.path.join(pkg_dir, *rel_parts) + ".py")
    if not (file_path.startswith(allowed_dir + os.sep) or file_path == allowed_dir):
        return None, None
    return file_path, allowed_dir


@api_bp.get("/node/load-code")
@api_bp.get("/node/load-code/")
def load_node_code():
    """Load Python source from file. Query params: module_path (full module path). File = module_path with .py. Returns 404 if not found."""
    import os
    from flask import request
    module_path = (request.args.get("module_path") or "").strip()
    node_id = (request.args.get("node_id") or "").strip()  # optional, kept for backward compatibility
    if not module_path:
        return jsonify({"error": "Validation Error", "message": "module_path is required"}), 400
    file_path, _ = _module_path_to_file_path(module_path)
    if not file_path:
        return jsonify({"error": "Validation Error", "message": "module_path must be under nos.plugins.nodes"}), 400
    if not os.path.isfile(file_path):
        return jsonify({"error": "Not Found", "message": "File not found"}), 404
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content}), 200
    except OSError as e:
        logging.getLogger(__name__).error("load_node_code: read failed: %s", e)
        return jsonify({"error": "Read Error", "message": str(e)}), 500


# --- Execution Control ---

def _get_shared_engine():
    from nos.core.engine import get_shared_engine
    return get_shared_engine()


@api_bp.post("/node/stop/<execution_id>")
@api_bp.post("/node/stop/<execution_id>/")
def stop_node_execution(execution_id: str):
    """
    Stop a running node execution.
    
    Args:
        execution_id: Execution ID returned by execute endpoints
        
    Returns:
        JSON with stop result
    """
    engine = _get_shared_engine()
    result = engine.stop_execution(execution_id)
    
    if result.get("stopped"):
        return jsonify(result), 200
    else:
        return jsonify(result), 404


@api_bp.get("/node/executions")
@api_bp.get("/node/executions/")
def list_node_executions():
    """List all active node executions."""
    engine = _get_shared_engine()
    executions = engine.list_executions()
    # Filter to only show node executions
    node_executions = [e for e in executions if e.get("execution_type") == "node"]
    return jsonify({"executions": node_executions, "count": len(node_executions)}), 200


@api_bp.get("/node/execution/<execution_id>")
@api_bp.get("/node/execution/<execution_id>/")
def get_node_execution_status(execution_id: str):
    """Get status of a specific node execution."""
    engine = _get_shared_engine()
    status = engine.get_execution_status(execution_id)
    if not status:
        return jsonify({"error": "Not Found", "message": f"Execution '{execution_id}' not found"}), 404
    return jsonify(status), 200


# --- Execution Logs (from DB for background executions) ---

@api_bp.get("/execution/<execution_id>/logs")
@api_bp.get("/execution/<execution_id>/logs/")
def get_execution_logs(execution_id: str):
    """
    Get execution logs from database for a specific execution.
    
    Used to retrieve logs for background executions that were persisted to DB.
    
    Args:
        execution_id: Execution ID to retrieve logs for
        
    Query params:
        limit: Maximum number of log entries (default: 1000)
        offset: Skip first N entries for pagination
        
    Returns:
        JSON with logs array and count
    """
    from flask import request
    from ...services.sqlalchemy.execution_log import repository as log_repo
    
    limit = request.args.get("limit", 1000, type=int)
    offset = request.args.get("offset", 0, type=int)
    
    try:
        logs = log_repo.get_by_execution_id(execution_id, limit=limit, offset=offset)
        
        if not logs:
            return jsonify({
                "execution_id": execution_id,
                "logs": [],
                "count": 0,
                "message": "No logs found for this execution"
            }), 200
        
        return jsonify({
            "execution_id": execution_id,
            "logs": [l.to_dict() for l in logs],
            "count": len(logs),
        }), 200
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Error retrieving execution logs: {e}", exc_info=True)
        return jsonify({
            "error": "Internal Error",
            "message": str(e)
        }), 500


@api_bp.get("/execution/logs")
@api_bp.get("/execution/logs/")
def list_execution_logs():
    """
    List recent executions (summary with log counts).
    
    Query params:
        limit: Maximum number of executions (default: 50)
        type: Filter by execution type ("node" or "workflow")
        
    Returns:
        JSON with executions array (each with execution_id, type, plugin_id, event_count)
    """
    from flask import request
    from ...services.sqlalchemy.execution_log import repository as log_repo
    
    limit = request.args.get("limit", 50, type=int)
    execution_type = request.args.get("type")
    
    try:
        executions = log_repo.get_unique_executions(limit=limit, execution_type=execution_type)
        
        return jsonify({
            "executions": executions,
            "count": len(executions),
        }), 200
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Error listing execution logs: {e}", exc_info=True)
        return jsonify({
            "error": "Internal Error",
            "message": str(e)
        }), 500


@api_bp.delete("/execution/<execution_id>/logs")
@api_bp.delete("/execution/<execution_id>/logs/")
def delete_execution_logs(execution_id: str):
    """
    Delete logs for a specific execution.
    
    Args:
        execution_id: Execution ID to delete logs for
        
    Returns:
        JSON with deleted count
    """
    from ...services.sqlalchemy.execution_log import repository as log_repo
    
    try:
        count = log_repo.delete_by_execution_id(execution_id)
        return jsonify({
            "execution_id": execution_id,
            "deleted": count,
            "message": f"Deleted {count} log entries"
        }), 200
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Error deleting execution logs: {e}", exc_info=True)
        return jsonify({
            "error": "Internal Error",
            "message": str(e)
        }), 500


@api_bp.post("/node/save-code")
@api_bp.post("/node/save-code/")
@validate_payload(NodeSaveCodeSchema)
def save_node_code(data: NodeSaveCodeSchema):
    """
    (1) Save Python source to file. (2) Try to register the node. (3) Update DB record with registration_status (OK/Error).
    """
    import os
    from datetime import datetime
    from nos.core.engine.plugin_loader import try_register_node

    file_path, allowed_dir = _module_path_to_file_path(data.module_path)
    if not file_path:
        return jsonify({
            "error": "Validation Error",
            "message": "module_path must be under nos.plugins.nodes",
        }), 400
    try:
        target_dir = os.path.dirname(file_path)
        os.makedirs(target_dir, exist_ok=True)
        if target_dir != allowed_dir:
            _ensure_package_init(allowed_dir, target_dir)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data.content)
    except OSError as e:
        logging.getLogger(__name__).error("save_node_code: write failed: %s", e)
        return jsonify({"error": "Write Error", "message": str(e)}), 500

    reg_error = None
    ok = False
    try:
        ok, reg_error = try_register_node(data.module_path, data.class_name, data.node_id)
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
    except Exception as e:
        logging.getLogger(__name__).error("save_node_code: register failed: %s", e)
        status = RegistrationStatus.ERROR.value
        reg_error = str(e)

    try:
        node, err = node_repo.update(
            data.node_id,
            {
                "registration_status": status,
                "registration_date": datetime.utcnow(),
            },
        )
        if err == "not_found":
            logging.getLogger(__name__).warning("save_node_code: node %s not in DB, registration_status not persisted", data.node_id)
    except Exception as e:
        logging.getLogger(__name__).error("save_node_code: DB update failed: %s", e)
        return jsonify({"error": "DB Error", "message": str(e)}), 500

    return jsonify({
        "message": "File saved",
        "path": file_path,
        "registration_status": status,
        "registration_error": reg_error if not ok else None,
    }), 200
