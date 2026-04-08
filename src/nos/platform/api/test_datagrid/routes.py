"""Test DataGrid API routes. URL prefix: /test-datagrid. Registers grid-to-action handlers in common."""

from flask import jsonify, request, make_response

from ..routes import api_bp
from ..common import _call_callback_and_return, GRID_ACTION_HANDLERS
from ..test_datagrid_form import get_test_datagrid_form_schema
from ...services.sqlalchemy import TestDataGridDbModel
from ...services.sqlalchemy.test_datagrid import repository as test_datagrid_repo


def _execute_create_test_datagrid(data):
    try:
        if not data:
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response") if isinstance(data, dict) else None
        record, err = test_datagrid_repo.create(data)
        if err == "bad_request":
            return jsonify({"error": "Bad Request", "message": "Required fields missing: nome, cognome, email"}), 400
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": f"Record with email '{data.get('email', '')}' already exists"}), 409
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(record.to_dict()), 201
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error creating test_datagrid record: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_update_test_datagrid(id_val, data):
    try:
        if not data:
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        try:
            id_int = int(id_val)
        except (TypeError, ValueError):
            return jsonify({"error": "Bad Request", "message": "'id' must be an integer for test_datagrid"}), 400
        callback_response = data.get("callback_response") if isinstance(data, dict) else None
        record, err = test_datagrid_repo.update(id_int, data)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": f"Record with ID {id_int} not found"}), 404
        if err == "conflict":
            return jsonify({"error": "Conflict", "message": "Record with that email already exists"}), 409
        if err == "bad_request":
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return jsonify(record.to_dict())
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error updating test_datagrid record: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


def _execute_delete_test_datagrid(data):
    try:
        if not data:
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON"}), 400
        callback_response = data.get("callback_response") if isinstance(data, dict) else None
        record_ids = data.get("ids", [])
        if not record_ids:
            return jsonify({"error": "Bad Request", "message": "Field 'ids' is required and must be a non-empty array"}), 400
        if not isinstance(record_ids, list):
            return jsonify({"error": "Bad Request", "message": "Field 'ids' must be an array"}), 400
        try:
            record_ids = [int(i) for i in record_ids]
        except (ValueError, TypeError):
            return jsonify({"error": "Bad Request", "message": "All IDs must be integers"}), 400
        deleted, err = test_datagrid_repo.delete_by_ids(record_ids)
        if err == "not_found":
            return jsonify({"error": "Not Found", "message": "No records found with the provided IDs"}), 404
        if err == "bad_request":
            return jsonify({"error": "Bad Request", "message": "Invalid ids"}), 400
        if callback_response and isinstance(callback_response, str) and callback_response.strip():
            return _call_callback_and_return(callback_response)
        return make_response("", 204)
    except Exception as e:
        from ...extensions import db
        db.session.rollback()
        import logging
        logging.getLogger(__name__).error(f"Error deleting test_datagrid records: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500


# Register handlers for grid-to-action-dispatcher (used by common.register_grid_routes)
GRID_ACTION_HANDLERS["test_datagrid"] = {
    "create": _execute_create_test_datagrid,
    "update": _execute_update_test_datagrid,
    "delete": _execute_delete_test_datagrid,
}


@api_bp.get("/test-datagrid")
@api_bp.get("/test-datagrid/")
@api_bp.post("/test-datagrid")
@api_bp.post("/test-datagrid/")
def get_test_datagrid():
    """Get list of all test_datagrid records for data grid with form_schema."""
    records = test_datagrid_repo.get_all()
    form_schema = get_test_datagrid_form_schema()
    columns = [c.key for c in TestDataGridDbModel.__table__.columns]
    records_as_dicts = [r.to_dict() for r in records]
    data = [[row.get(col) for col in columns] for row in records_as_dicts]
    return jsonify({
        "columns": columns,
        "data": data,
        "form_schema": form_schema,
    })


@api_bp.get("/test-datagrid/<int:id>")
@api_bp.get("/test-datagrid/<int:id>/")
def get_test_datagrid_by_id(id: int):
    """Get a single test_datagrid record by id. Query: action=create|update (default update)."""
    action = request.args.get('action', 'update').lower()
    if action == 'create':
        form_schema = dict(get_test_datagrid_form_schema())
        form_schema["method"] = "POST"
        form_schema["title"] = "Nuovo Cliente"
        form_schema["description"] = "Aggiungi un nuovo cliente"
        return jsonify({"form_schema": form_schema})

    record = test_datagrid_repo.get_by_id(id)
    if not record:
        return jsonify({"error": "Not Found", "message": f"Record with ID '{id}' not found"}), 404
    form_schema = get_test_datagrid_form_schema(record)
    form_data = record.to_dict()
    return jsonify({"form_schema": form_schema, "form_data": form_data})


@api_bp.post("/test-datagrid/add")
def create_test_datagrid():
    """Create a new test_datagrid record."""
    data = request.get_json()
    return _execute_create_test_datagrid(data)


@api_bp.post("/test-datagrid/update/<int:id>")
@api_bp.post("/test-datagrid/update/<int:id>/")
def update_test_datagrid(id: int):
    """Update an existing test_datagrid record via POST."""
    data = request.get_json()
    return _execute_update_test_datagrid(id, data)


@api_bp.post("/test-datagrid/delete")
def delete_test_datagrid():
    """Delete one or more test_datagrid records."""
    data = request.get_json()
    return _execute_delete_test_datagrid(data)
