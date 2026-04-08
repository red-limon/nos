"""Workflow API routes. URL prefix: /workflows."""

import logging

from flask import jsonify, request, url_for

from ..routes import api_bp
from ..common import validate_payload, _call_callback_and_return, GRID_ACTION_HANDLERS
from ..data_grid_schema import DataGridResponseSchema
from ..form_wire import dump_grid_form_dict, form_envelope, form_schema_with_values
from ...services.sqlalchemy import WorkflowDbModel, RegistrationStatus
from ...services.sqlalchemy.workflow import repository as workflow_repo
from .schemas import (
    WorkflowCreateSchema,
    WorkflowDeleteSchema,
    WorkflowSaveCodeSchema,
    WorkflowStartSchema,
    WorkflowStatusSchema,
    WorkflowUpdateSchema,
)


def _build_workflow_form_schema():
    """Build form_schema dict and column names for workflow form (shared by form-schema and list endpoints)."""
    fields = [
        {
            "name": "workflow_id",
            "label": "Workflow ID",
            "type": "text",
            "placeholder": "e.g., my_workflow",
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
            "placeholder": "e.g., MyWorkflow",
            "required": True,
            "minLength": 1,
            "maxLength": 200,
        },
        {
            "name": "module_path",
            "label": "Module Path",
            "type": "text",
            "placeholder": "e.g., nos.plugins.workflows.my_workflow",
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
            "description": "OK if loaded in registry at startup, Error otherwise",
        },
    ]
    form_schema = form_envelope(
        form_id="workflow-form",
        title="Workflow Plugin",
        description="Add or edit a workflow plugin",
        fields=fields,
        submit_label="Save",
        cancel_label="Cancel",
        method="POST",
    )
    columns = [f["name"] for f in fields]
    return form_schema, columns


# --- Grid-to-action-dispatcher handlers (same pattern as test_datagrid, node) ---

def _execute_create_workflow(data):
    """Create a workflow from grid submit. data: dict with workflow_id, class_name, module_path, name, status, version, etc."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        from flask import session
        current_user = session.get("username", "system")
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            return jsonify({"error": "Bad Request", "message": "Field 'workflow_id' is required"}), 400
        from datetime import datetime
        from nos.core.engine.plugin_loader import try_register_workflow, get_workflow_node_ids, get_workflow_instance
        from nos.platform.loader_db import _register_node_from_db
        from nos.core.engine.registry import workflow_registry
        from ...services.sqlalchemy import NodeDbModel
        from ...extensions import db
        now = datetime.utcnow()
        ok, reg_error = try_register_workflow(
            data.get("module_path") or "",
            data.get("class_name") or "",
            workflow_id,
        )
        if not ok:
            logging.getLogger(__name__).info("Workflow create: registration failed for %s: %s", workflow_id, reg_error)
            workflow, err = workflow_repo.create(
                workflow_id=workflow_id,
                class_name=data.get("class_name") or "",
                module_path=data.get("module_path") or "",
                name=data.get("name"),
                created_by=current_user or data.get("created_by", "system"),
                updated_by=current_user or data.get("updated_by", "system"),
                registration_status=RegistrationStatus.ERROR.value,
                registration_date=now,
            )
            if err == "conflict":
                return jsonify({"error": "Conflict", "message": f"Workflow '{workflow_id}' already exists"}), 409
            if callback_response and isinstance(callback_response, str) and callback_response.strip():
                return _call_callback_and_return(callback_response)
            return jsonify(workflow.to_dict()), 201
        node_ids = get_workflow_node_ids(workflow_id)
        workflow_instance = get_workflow_instance(workflow_id)
        for nid in node_ids:
            node_row = NodeDbModel.query.get(nid)
            if node_row and node_row.registration_status != RegistrationStatus.OK.value:
                try:
                    _register_node_from_db(node_row)
                    node_row.registration_status = RegistrationStatus.OK.value
                    node_row.registration_date = now
                    db.session.commit()
                except Exception as e:
                    node_row.registration_status = RegistrationStatus.ERROR.value
                    node_row.registration_date = now
                    db.session.commit()
                    logging.getLogger(__name__).warning("Workflow create: node %s re-registration failed: %s", nid, e)
            elif not node_row and workflow_instance and nid in workflow_instance._nodes:
                cls = workflow_instance._nodes[nid].__class__
                class_name = cls.__name__
                module_path = cls.__module__
                name = getattr(cls, "name", None) or nid
                try:
                    workflow_registry.register_node(cls, nid)
                    reg_ok = True
                except Exception as e:
                    reg_ok = False
                    logging.getLogger(__name__).warning("Workflow create: node %s (not in DB) registration failed: %s", nid, e)
                status = RegistrationStatus.OK.value if reg_ok else RegistrationStatus.ERROR.value
                from ...services.sqlalchemy.node import repository as node_repo
                node_repo.create(
                    node_id=nid,
                    class_name=class_name,
                    module_path=module_path,
                    name=name,
                    created_by=current_user or "system",
                    updated_by=current_user or "system",
                    registration_status=status,
                    registration_date=now,
                )
                if reg_ok:
                    logging.getLogger(__name__).info("Workflow create: node %s (not in DB) registered and added to DB", nid)
        all_nodes_ok = all(
            (NodeDbModel.query.get(nid) and NodeDbModel.query.get(nid).registration_status == RegistrationStatus.OK.value)
            for nid in node_ids
        )
        if not all_nodes_ok:
            failed = [
                nid for nid in node_ids
                if not (NodeDbModel.query.get(nid) and NodeDbModel.query.get(nid).registration_status == RegistrationStatus.OK.value)
            ]
            logging.getLogger(__name__).warning(
                "Workflow create: workflow %s -> registration_status Error (nodes not OK: %s)",
                workflow_id, failed,
            )
            w_status = RegistrationStatus.ERROR.value
        else:
            w_status = RegistrationStatus.OK.value
        workflow, err = workflow_repo.create(
            workflow_id=workflow_id,
            class_name=data.get("class_name") or "",
            module_path=data.get("module_path") or "",
            name=data.get("name"),
            created_by=current_user or data.get("created_by", "system"),
            updated_by=current_user or data.get("updated_by", "system"),
            registration_status=w_status,
            registration_date=now,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Workflow '{workflow_id}' already exists"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(workflow.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error creating workflow: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_update_workflow(id_val, data):
    """Update a workflow from grid submit. id_val is workflow_id (string)."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        workflow_id = str(id_val) if id_val is not None else data.get("workflow_id")
        if not workflow_id:
            return jsonify({"error": "Bad Request", "message": "Update requires 'id' (workflow_id) in body or path"}), 400
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
        workflow, err = workflow_repo.update(workflow_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Workflow '{workflow_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Workflow conflict"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(workflow.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error updating workflow: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_delete_workflow(data):
    """Delete one or more workflows from grid submit. data must contain 'workflow_ids' or 'ids' (list of workflow_id strings)."""
    try:
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response")
        workflow_ids = data.get("workflow_ids") or data.get("ids", [])
        if not workflow_ids:
            return jsonify({"error": "Bad Request", "message": "Field 'workflow_ids' or 'ids' is required and must be a non-empty array"}), 400
        if not isinstance(workflow_ids, list):
            return jsonify({"error": "Bad Request", "message": "Field 'workflow_ids' must be an array"}), 400
        workflow_ids = [str(w) for w in workflow_ids]
        deleted_ids, not_found = workflow_repo.delete_many(workflow_ids)
        if not deleted_ids:
            return jsonify({"error": "Not Found", "message": "No workflows found with the provided workflow_ids"}), 404
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        result = {
            "message": f"{len(deleted_ids)} workflow(s) deleted",
            "deleted_workflow_ids": deleted_ids,
            "deleted_count": len(deleted_ids),
        }
        if not_found:
            result["not_found_workflow_ids"] = not_found
        return jsonify(result), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logging.getLogger(__name__).error("Error deleting workflows: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


GRID_ACTION_HANDLERS["workflow"] = {
    "create": _execute_create_workflow,
    "update": _execute_update_workflow,
    "delete": _execute_delete_workflow,
}


# --- Routes ---
@api_bp.get("/workflow/list")
@api_bp.get("/workflow/list/")
@api_bp.post("/workflow/list")
@api_bp.post("/workflow/list/")
def get_workflow_list():
    """List all available workflows, nodes, and links."""
    try:
        workflows = workflow_repo.get_all()
        data = [w.to_dict() for w in workflows]
        form_schema, columns = _build_workflow_form_schema()
        payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
        out = payload.model_dump()
        out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_workflow"))
        return jsonify(out)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Error listing workflows: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.get("/workflow/form-schema")
@api_bp.get("/workflow/form-schema/")
@api_bp.post("/workflow/form-schema")
@api_bp.post("/workflow/form-schema/")
@api_bp.get("/workflows/form-schema/")
def get_workflow_form_schema():
    """Get form_schema only (create mode). Used by wx-form-loader when no record id."""
    form_schema, _ = _build_workflow_form_schema()
    return jsonify(dump_grid_form_dict(form_schema, action=url_for("api.create_workflow")))


@api_bp.get("/workflow/list/registered")
@api_bp.get("/workflow/list/registered/")
@api_bp.post("/workflow/list/registered")
@api_bp.post("/workflow/list/registered/")
def get_registered_workflow_list():
    """Get list of all workflows for data-grid + form-loader (DataGridResponseSchema)."""
    try:
        workflows = workflow_repo.get_all_registered()
        data = [w.to_dict() for w in workflows]
        form_schema, columns = _build_workflow_form_schema()

        payload = DataGridResponseSchema(columns=columns, data=data, form_schema=form_schema)
        out = payload.model_dump()
        out["form_schema"] = dump_grid_form_dict(form_schema, action=url_for("api.create_workflow"))
        return jsonify(out)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Error listing workflows: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.get("/workflow/<workflow_id>")
@api_bp.get("/workflow/<workflow_id>/")
@api_bp.post("/workflow/<workflow_id>")
@api_bp.post("/workflow/<workflow_id>/")
def get_workflow_by_id(workflow_id: str):
    """Get a single workflow by ID. Returns form schema at root (for wx-form-loader), with fields filled."""
    try:
        form_schema, _ = _build_workflow_form_schema()
        workflow = workflow_repo.get_by_id(workflow_id)
        if not workflow:
            return jsonify({"error": "Not Found", "message": f"Workflow with ID '{workflow_id}' not found"}), 404
        workflow_dict = workflow.to_dict()
        form_schema_filled = form_schema_with_values(form_schema, workflow_dict)
        update_url = url_for("api.update_workflow", workflow_id=workflow_id)
        return jsonify(dump_grid_form_dict(form_schema_filled, action=update_url))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Error getting workflow by ID: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.post("/workflow/create")
@api_bp.post("/workflow/create/")
@validate_payload(WorkflowCreateSchema)
def create_workflow(data: WorkflowCreateSchema):
    """Create workflow: (1) register in registry, (2) ensure nodes OK, (3) set status and insert in DB."""
    try:
        from datetime import datetime
        from flask import session
        from nos.core.engine.plugin_loader import try_register_workflow, get_workflow_node_ids, get_workflow_instance
        from nos.platform.loader_db import _register_node_from_db
        from nos.core.engine.registry import workflow_registry
        from ...services.sqlalchemy import NodeDbModel
        from ...extensions import db
        current_user = session.get("username", "system")
        now = datetime.utcnow()
        ok, reg_error = try_register_workflow(data.module_path, data.class_name, data.workflow_id)
        if not ok:
            logging.getLogger(__name__).info("Workflow create: registration failed for %s: %s", data.workflow_id, reg_error)
            workflow, err = workflow_repo.create(
                workflow_id=data.workflow_id,
                class_name=data.class_name,
                module_path=data.module_path,
                name=data.name,
                created_by=current_user or data.created_by,
                updated_by=current_user or data.updated_by,
                registration_status=RegistrationStatus.ERROR.value,
                registration_date=now,
            )
            if err == "conflict":
                return jsonify({"error": "Conflict", "message": f"Workflow '{data.workflow_id}' already exists"}), 409
            return jsonify(workflow.to_dict()), 201
        node_ids = get_workflow_node_ids(data.workflow_id)
        workflow_instance = get_workflow_instance(data.workflow_id)
        for nid in node_ids:
            node_row = NodeDbModel.query.get(nid)
            if node_row and node_row.registration_status != RegistrationStatus.OK.value:
                try:
                    _register_node_from_db(node_row)
                    node_row.registration_status = RegistrationStatus.OK.value
                    node_row.registration_date = now
                    db.session.commit()
                except Exception as e:
                    node_row.registration_status = RegistrationStatus.ERROR.value
                    node_row.registration_date = now
                    db.session.commit()
                    logging.getLogger(__name__).warning("Workflow create: node %s re-registration failed: %s", nid, e)
            elif not node_row and workflow_instance and nid in workflow_instance._nodes:
                cls = workflow_instance._nodes[nid].__class__
                class_name = cls.__name__
                module_path = cls.__module__
                name = getattr(cls, "name", None) or nid
                try:
                    workflow_registry.register_node(cls, nid)
                    reg_ok = True
                except Exception as e:
                    reg_ok = False
                    logging.getLogger(__name__).warning("Workflow create: node %s (not in DB) registration failed: %s", nid, e)
                status = RegistrationStatus.OK.value if reg_ok else RegistrationStatus.ERROR.value
                from ...services.sqlalchemy.node import repository as node_repo
                node_repo.create(
                    node_id=nid,
                    class_name=class_name,
                    module_path=module_path,
                    name=name,
                    created_by=current_user or "system",
                    updated_by=current_user or "system",
                    registration_status=status,
                    registration_date=now,
                )
                if reg_ok:
                    logging.getLogger(__name__).info("Workflow create: node %s (not in DB) registered and added to DB", nid)
        all_nodes_ok = all(
            (NodeDbModel.query.get(nid) and NodeDbModel.query.get(nid).registration_status == RegistrationStatus.OK.value)
            for nid in node_ids
        )
        if not all_nodes_ok:
            failed = [
                nid for nid in node_ids
                if not (NodeDbModel.query.get(nid) and NodeDbModel.query.get(nid).registration_status == RegistrationStatus.OK.value)
            ]
            logging.getLogger(__name__).warning(
                "Workflow create: workflow %s -> registration_status Error (nodes not OK: %s)",
                data.workflow_id, failed,
            )
            w_status = RegistrationStatus.ERROR.value
        else:
            w_status = RegistrationStatus.OK.value
        workflow, err = workflow_repo.create(
            workflow_id=data.workflow_id,
            class_name=data.class_name,
            module_path=data.module_path,
            name=data.name,
            created_by=current_user or data.created_by,
            updated_by=current_user or data.updated_by,
            registration_status=w_status,
            registration_date=now,
        )
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Workflow '{data.workflow_id}' already exists"}), 409
        return jsonify(workflow.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        logger = logging.getLogger(__name__)
        logger.error("Error creating workflow: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.put("/workflow/update/<workflow_id>")
@api_bp.put("/workflow/update/<workflow_id>/")
@api_bp.post("/workflow/update/<workflow_id>")
@api_bp.post("/workflow/update/<workflow_id>/")
@validate_payload(WorkflowUpdateSchema)
def update_workflow(data: WorkflowUpdateSchema, workflow_id: str):
    """Update an existing workflow."""
    from flask import session

    try:
        current_user = session.get("username", "system")
        payload = data.model_dump(exclude_unset=True)
        if "updated_by" not in payload:
            payload["updated_by"] = current_user
        if "registration_status" in payload:
            valid = [s.value for s in RegistrationStatus]
            if payload["registration_status"] not in valid:
                return jsonify({"error": "Bad Request", "message": f"registration_status must be one of: {', '.join(valid)}"}), 400
        workflow, err = workflow_repo.update(workflow_id, payload)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Workflow '{workflow_id}' not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Workflow already exists"}), 409
        return jsonify(workflow.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error updating workflow: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.delete("/workflow/<workflow_id>")
@api_bp.delete("/workflow/<workflow_id>/")
@api_bp.post("/workflow/delete/<workflow_id>")
@api_bp.post("/workflow/delete/<workflow_id>/")
def delete_workflow_by_id(workflow_id: str):
    """Delete a single workflow by workflow_id (no request body)."""
    try:
        ok, err = workflow_repo.delete(workflow_id)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Workflow '{workflow_id}' not found"}), 404
        return jsonify({"message": f"Workflow '{workflow_id}' deleted"}), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error deleting workflow: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


@api_bp.post("/workflow/delete")
@api_bp.post("/workflow/delete/")
@api_bp.delete("/workflows")
@api_bp.delete("/workflows/")
@validate_payload(WorkflowDeleteSchema)
def delete_workflows(data: WorkflowDeleteSchema):
    """Delete one or more workflows from the database. Body: JSON with 'workflow_ids' (list of strings)."""
    try:
        deleted_ids, not_found_ids = workflow_repo.delete_many(data.workflow_ids)
        if not deleted_ids:
            return jsonify({"error": "Not Found", "message": "No workflows found with the provided workflow_ids"}), 404
        result = {
            "message": f"Successfully deleted {len(deleted_ids)} workflow(s)",
            "deleted_workflow_ids": deleted_ids,
            "deleted_count": len(deleted_ids),
        }
        if not_found_ids:
            result["not_found_workflow_ids"] = not_found_ids
            result["warning"] = f"Some workflow_ids were not found: {not_found_ids}"
        return jsonify(result), 200
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error("Error deleting workflows: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_start_workflow(data: WorkflowStartSchema, *, workflow=None):
    """Start a workflow execution. Shared by POST /workflow/start and POST /run (target=workflow).

    If ``workflow`` is None, resolve the class from the registry. Otherwise use the pre-loaded instance
    (e.g. :meth:`Workflow.load` dev).
    """
    import time
    from nos.core.engine.registry import workflow_registry
    from nos.core.engine import get_shared_engine
    from nos.core.execution_log import EventLogBuffer
    from nos.platform.execution_log import EventLog
    from nos.hooks import event_hooks, EventType

    if workflow is None:
        workflow_class = workflow_registry.get_workflow(data.workflow_id)
        if not workflow_class:
            return jsonify({"error": "Not Found", "message": f"Workflow '{data.workflow_id}' not found"}), 404
        workflow = workflow_registry.create_workflow_instance(data.workflow_id)
    engine = get_shared_engine()

    execution_id = f"{data.workflow_id}_{int(time.time())}"

    # Use EventLog for real-time, EventLogBuffer otherwise
    if data.enable_realtime_logs:
        channel = EventLog(
            execution_id=execution_id,
            workflow_id=data.workflow_id,
        )
    else:
        channel = EventLogBuffer(
            execution_id=execution_id,
            workflow_id=data.workflow_id,
        )

    event_hooks.emit(EventType.WORKFLOW_STARTED, {"workflow_id": data.workflow_id, "background": data.background})
    from nos.io_adapters.output_formats_schema import OUTPUT_FORMATS
    output_format = str(getattr(data, "output_format", "json") or "json").lower().strip()
    if output_format not in OUTPUT_FORMATS:
        return jsonify({"error": "Bad Request", "message": f"Invalid output_format. Allowed: {', '.join(OUTPUT_FORMATS)}"}), 400
    if data.background:
        execution_id = engine.execute_background(
            workflow=workflow,
            initial_state=data.initial_state,
            exec_log=channel,
            output_format=output_format,
            debug_mode=data.debug_mode,
            request=data.request,
        )
        return jsonify({
            "execution_id": execution_id,
            "workflow_id": data.workflow_id,
            "status": "running",
            "message": "Workflow started in background",
        }), 202
    try:
        result = engine.execute_sync(
            workflow=workflow,
            initial_state=data.initial_state,
            exec_log=channel,
            output_format=output_format,
            debug_mode=data.debug_mode,
            request=data.request,
        )
        event_hooks.emit(
            EventType.WORKFLOW_COMPLETED,
            {
                "workflow_id": data.workflow_id,
                "final_state": result.response.output.get("data"),
            },
        )
        payload = {
            "workflow_id": data.workflow_id,
            "status": "completed",
            "execution_id": result.execution_id,
            "module_path": result.module_path,
            "class_name": result.class_name,
            "response": {
                "output": dict(result.response.output),
                "metadata": dict(result.response.metadata),
            },
            "state": result.state,
            "initial_state": result.initial_state,
            "state_changed": result.state_changed,
            "event_logs": result.event_logs,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "duration": result.duration,
            "node_ids_executed": result.node_ids_executed,
            "message": result.message,
        }
        if result.status == "cancelled":
            payload["status"] = "cancelled"
        return jsonify(payload), 200
    except Exception as e:
        event_hooks.emit(EventType.WORKFLOW_ERROR, {"workflow_id": data.workflow_id, "error": str(e)})
        return jsonify({"error": "Workflow Execution Error", "message": str(e), "workflow_id": data.workflow_id}), 500


def dispatch_workflow_module_load(data: WorkflowStartSchema, module_path: str, class_name: str):
    """
    Load workflow via Workflow.load(dev, …) then run with the same engine path as POST /workflow/start.
    Shared by POST /api/run (target=workflow, load=module). Whitelist: nos.plugins.workflows / nos.plugins.old.
    """
    from nos.core.engine.workflow.workflow import Workflow

    file_path, ok = _workflow_module_path_to_file_path(module_path)
    if not ok or not file_path:
        return jsonify({
            "error": "Validation Error",
            "message": "module_path must be under nos.plugins.workflows or nos.plugins.old",
        }), 400
    try:
        workflow = Workflow.load(
            "dev",
            data.workflow_id,
            module_path=module_path.strip(),
            class_name=class_name.strip(),
        )
    except Exception as e:
        logging.getLogger(__name__).warning("Workflow.load(dev) failed: %s", e, exc_info=True)
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    return _execute_start_workflow(data, workflow=workflow)


@api_bp.post("/workflow/start")
@validate_payload(WorkflowStartSchema)
def start_workflow(data: WorkflowStartSchema):
    """Start a workflow execution."""
    return _execute_start_workflow(data)


@api_bp.get("/workflows/status/<execution_id>")
def get_workflow_status(execution_id: str):
    """Get status of a workflow execution."""
    from nos.core.engine import get_shared_engine
    engine = get_shared_engine()
    status = engine.get_execution_status(execution_id)
    if not status:
        return jsonify({"error": "Not Found", "message": f"Execution '{execution_id}' not found"}), 404
    return jsonify(WorkflowStatusSchema(**status).model_dump())


@api_bp.post("/workflows/stop/<execution_id>")
def stop_workflow(execution_id: str):
    """Stop a running workflow execution."""
    from nos.core.engine import get_shared_engine
    from nos.hooks import event_hooks, EventType
    engine = get_shared_engine()
    stopped = engine.stop_execution(execution_id)
    if not stopped:
        return jsonify({"error": "Not Found", "message": f"Execution '{execution_id}' not found or already completed"}), 404
    event_hooks.emit(EventType.WORKFLOW_STOPPED, {"execution_id": execution_id})
    return jsonify({"message": f"Workflow execution {execution_id} stopped"})


def _workflow_module_path_to_file_path(module_path: str):
    """Resolve workflow module path to .py file. Allowed: nos.plugins.workflows.* or nos.plugins.old.*.
    Returns (file_path, True) or (None, False).
    """
    import os
    try:
        import nos
        pkg_dir = os.path.dirname(os.path.abspath(nos.__file__))
    except Exception:
        return None, False
    parts = (module_path or "").strip().split(".")
    if not parts or parts[0] != "nos":
        return None, False
    rel_parts = parts[1:]
    if not rel_parts:
        return None, False
    plugins_dir = os.path.realpath(os.path.join(pkg_dir, "plugins"))
    allowed_subdirs = ("workflows", "old")
    file_path = os.path.realpath(os.path.join(pkg_dir, *rel_parts) + ".py")
    if not file_path.startswith(plugins_dir + os.sep):
        return None, False
    rel = os.path.relpath(os.path.dirname(file_path), plugins_dir)
    top = rel.split(os.sep)[0] if rel != "." else ""
    if top not in allowed_subdirs:
        return None, False
    return file_path, True


@api_bp.get("/workflow/load-code")
@api_bp.get("/workflow/load-code/")
def load_workflow_code():
    """Load Python source from workflow module file. Query params: workflow_id (optional), module_path (required)."""
    import os
    module_path = (request.args.get("module_path") or "").strip()
    workflow_id = (request.args.get("workflow_id") or "").strip()
    if not module_path:
        return jsonify({"error": "Validation Error", "message": "module_path is required"}), 400
    file_path, ok = _workflow_module_path_to_file_path(module_path)
    if not ok or not file_path:
        return jsonify({"error": "Validation Error", "message": "module_path must be under nos.plugins.workflows or nos.plugins.old"}), 400
    if not os.path.isfile(file_path):
        return jsonify({"error": "Not Found", "message": "File not found"}), 404
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content}), 200
    except OSError as e:
        logging.getLogger(__name__).error("load_workflow_code: read failed: %s", e)
        return jsonify({"error": "Read Error", "message": str(e)}), 500


@api_bp.post("/workflow/save-code")
@api_bp.post("/workflow/save-code/")
@validate_payload(WorkflowSaveCodeSchema)
def save_workflow_code(data: WorkflowSaveCodeSchema):
    """(1) Save Python source to file. (2) Try to register the workflow. (3) Update DB record with registration_status (OK/Error)."""
    import os
    from datetime import datetime
    from nos.core.engine.plugin_loader import try_register_workflow

    file_path, path_ok = _workflow_module_path_to_file_path(data.module_path)
    if not path_ok or not file_path:
        return jsonify({
            "error": "Validation Error",
            "message": "module_path must be under nos.plugins.workflows or nos.plugins.old",
        }), 400
    try:
        target_dir = os.path.dirname(file_path)
        os.makedirs(target_dir, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data.content)
    except OSError as e:
        logging.getLogger(__name__).error("save_workflow_code: write failed: %s", e)
        return jsonify({"error": "Write Error", "message": str(e)}), 500

    reg_error = None
    ok = False
    try:
        ok, reg_error = try_register_workflow(data.module_path, data.class_name, data.workflow_id)
        status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
    except Exception as e:
        logging.getLogger(__name__).error("save_workflow_code: register failed: %s", e)
        status = RegistrationStatus.ERROR.value
        reg_error = str(e)

    try:
        wf, err = workflow_repo.update(
            data.workflow_id,
            {
                "registration_status": status,
                "registration_date": datetime.utcnow(),
            },
        )
        if err == "not_found":
            logging.getLogger(__name__).warning("save_workflow_code: workflow %s not in DB, registration_status not persisted", data.workflow_id)
    except Exception as e:
        logging.getLogger(__name__).error("save_workflow_code: DB update failed: %s", e)
        return jsonify({"error": "DB Error", "message": str(e)}), 500

    return jsonify({
        "message": "File saved",
        "path": file_path,
        "registration_status": status,
        "registration_error": reg_error if not ok else None,
    }), 200
