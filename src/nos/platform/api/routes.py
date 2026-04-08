"""
REST API blueprint. Route handlers are registered in:
- workflow (URL prefix: /workflow, /workflows)
- node (URL prefix: /node, /nodes)
- test_datagrid (URL prefix: /test-datagrid)

Shared: common.validate_payload, common._call_callback_and_return, common.grid_to_action_dispatcher (via register_grid_routes).
"""

from flask import Blueprint, jsonify

from .common import validate_payload

api_bp = Blueprint("api", __name__)


@api_bp.get("/health")
def health_check():
    """Liveness probe for load balancers and tests (GET /api/health)."""
    return jsonify({"status": "healthy"}), 200

# Re-export for backward compatibility (e.g. @validate_payload(WorkflowDeleteSchema))
__all__ = ["api_bp", "validate_payload"]
