"""
Shared API utilities: payload validation, callback response, grid-to-action dispatcher.
"""

from flask import jsonify, request, make_response
from pydantic import ValidationError


def validate_payload(schema_class):
    """
    Decorator to validate request payload with Pydantic schema.
            ...
    """
    def decorator(f):
        def wrapper(*args, **kwargs):
            try:
                json_data = request.get_json()
                if json_data is None:
                    return jsonify({
                        "error": "Invalid Request",
                        "message": "Request body must be JSON"
                    }), 400
                validated_data = schema_class(**json_data)
                return f(validated_data, *args, **kwargs)
            except ValidationError as e:
                details = e.errors()
                message = "Invalid request payload"
                for err in details:
                    loc = err.get("loc") or ()
                    loc_list = list(loc) if not isinstance(loc, list) else loc
                    err_type = str(err.get("type", "")).lower()
                    if "content" in loc_list and ("max_length" in err_type or "too_long" in err_type):
                        message = "Il codice supera la dimensione massima consentita (1 MB)."
                        break
                return jsonify({
                    "error": "Validation Error",
                    "message": message,
                    "details": details,
                }), 400
            except Exception as e:
                return jsonify({
                    "error": "Internal Server Error",
                    "message": str(e)
                }), 500
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator


def _call_callback_and_return(callback_response):
    """If callback_response is a non-empty URL string, GET that URL and return its response; otherwise return 204 No Content.
    If callback_response starts with '/', it is treated as a path and resolved against the current request host (e.g. /api/node/list/ -> http://localhost:8082/api/node/list/)."""
    if not callback_response or not isinstance(callback_response, str) or not callback_response.strip():
        from flask import make_response
        return make_response("", 204)
    from flask import request
    # Path-relative callbacks (e.g. /api/node/list/) need to be turned into absolute URLs for urllib
    if callback_response.strip().startswith("/"):
        callback_url = request.host_url.rstrip("/") + callback_response.strip()
    else:
        callback_url = callback_response
    import urllib.request
    try:
        with urllib.request.urlopen(callback_url, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            from flask import make_response
            r = make_response(body, resp.status)
            # Do not copy hop-by-hop headers (PEP 3333: WSGI app must not set e.g. Connection)
            skip_headers = {"transfer-encoding", "content-encoding", "connection", "keep-alive", "te", "trailer", "upgrade"}
            for k, v in resp.headers.items():
                if k.lower() not in skip_headers:
                    r.headers[k] = v
            return r
    except Exception as e:
        return jsonify({"error": "Callback Error", "message": str(e)}), 502


# ---------------------------------------------------------------------------
# Grid-to-Action Dispatcher
# ---------------------------------------------------------------------------
# Single POST endpoint that routes create/update/delete requests to the
# correct handler based on JSON body fields:
#
#   - resource (optional): name of the "resource", e.g. "test_datagrid".
#     Default: "test_datagrid". Used to look up handlers in GRID_ACTION_HANDLERS.
#   - form-submit-action (required): "create" | "update" | "delete".
#   - id (required for update): record id (integer) when form-submit-action is "update".
#   - callback_response (optional): URL string. If present and non-empty, the handler may
#     perform a GET to that URL and return its response instead of the default JSON/204.
#   - Plus any resource-specific fields (e.g. nome, cognome, email for test_datagrid;
#     ids[] for delete).
#
# Handlers are registered per resource in GRID_ACTION_HANDLERS. Each entry is:
#   {"create": callable(data), "update": callable(id, data), "delete": callable(data)}
# Callables receive the request body (and id for update) and return a Flask response.
# See docs/GRID_ACTION_DISPATCHER.md for full documentation.
# ---------------------------------------------------------------------------

GRID_ACTION_HANDLERS = {}


def register_grid_routes(api_bp):
    """Register the grid-to-action-dispatcher route on the given blueprint.
    Expects handlers to be registered in GRID_ACTION_HANDLERS by resource modules
    (e.g. api.test_datagrid.routes)."""
    # OPTIONS handlers so CORS preflight returns 200.
    # URL id segment: <string:id> accepts both string ids (e.g. test_01) and numeric (e.g. 42, received as "42").
    @api_bp.route("/grid-to-action-dispatcher", methods=["OPTIONS"])
    @api_bp.route("/grid-to-action-dispatcher/", methods=["OPTIONS"])
    @api_bp.route("/grid-to-action-dispatcher/<string:id>", methods=["OPTIONS"])
    @api_bp.route("/grid-to-action-dispatcher/<string:id>/", methods=["OPTIONS"])
    def grid_to_action_dispatcher_options(id=None):
        return make_response("", 200)

    @api_bp.post("/grid-to-action-dispatcher")
    @api_bp.post("/grid-to-action-dispatcher/")
    @api_bp.post("/grid-to-action-dispatcher/<string:id>")
    @api_bp.post("/grid-to-action-dispatcher/<string:id>/")
    def grid_to_action_dispatcher(id=None):
        """Dispatch by JSON 'form-submit-action' and optional 'resource'.
        Body: form-submit-action (create|update|delete), resource (default test_datagrid), id (for update), plus payload fields."""
        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Bad Request", "message": "Request body must be JSON with 'form-submit-action' (create|update|delete)"}), 400
        resource = data.get("resource", "test_datagrid")
        handlers = GRID_ACTION_HANDLERS.get(resource)
        if not handlers:
            return jsonify({"error": "Bad Request", "message": f"Unknown resource: {resource}"}), 400
        action = data.get("form-submit-action")
        if action == "update":
            id_key = data.get("rowKey") or "id"
            id_val = data.get(id_key)
            if id_val is None:
                return jsonify({"error": "Bad Request", "message": f"form-submit-action=update requires '{id_key}' (or 'id') in body"}), 400
            # Pass id as-is; handler may interpret as int (test_datagrid) or string (node)
            return handlers["update"](id_val, data)
        if action == "create":
            return handlers["create"](data)
        if action == "delete":
            return handlers["delete"](data)
        return jsonify({"error": "Bad Request", "message": "form-submit-action must be 'create', 'update' or 'delete'"}), 400
