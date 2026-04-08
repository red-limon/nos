"""
Node page routes.
Registers /nodes and related routes on the given blueprint.
"""

from flask import render_template, request, url_for


def register_routes(bp):
    """Register node routes on the given blueprint."""

    @bp.get("/nodes")
    def nodes():
        """Nodes management page."""
        return render_template("node/node.html")

    @bp.get("/nodes/panel")
    @bp.get("/nodes/panel/")
    @bp.get("/nodes/panel/<node_id>")
    @bp.get("/nodes/panel/<node_id>/")
    def node_form_panel(node_id=None):
        """Node form + developer console panel (unified plugin_form_panel with type=node)."""
        record_id = (node_id or request.args.get("row_key") or request.args.get("node_id") or "").strip()
        return render_template(
            "engine/plugin_form_panel.html",
            plugin_type="node",
            record_id=record_id,
            row_key="node_id",
            form_schema_only_url=url_for("api.get_node_form_schema_only"),
            api_base="/api/node",
            label_registry="Node registry",
            label_singular="Node",
        )
