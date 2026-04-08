"""
Workflow page routes.
Registers /workflow and related routes on the given blueprint.
"""

from flask import render_template, request, url_for


def register_routes(bp):
    """Register workflow routes on the given blueprint."""

    @bp.get("/workflow")
    def workflow():
        """Workflow management page."""
        return render_template("workflow/workflow.html")

    @bp.get("/workflow/panel")
    @bp.get("/workflow/panel/")
    @bp.get("/workflow/panel/<workflow_id>")
    @bp.get("/workflow/panel/<workflow_id>/")
    def workflow_form_panel(workflow_id=None):
        """Workflow form + console panel (unified plugin_form_panel with type=workflow)."""
        record_id = (workflow_id or request.args.get("row_key") or request.args.get("workflow_id") or "").strip()
        return render_template(
            "engine/plugin_form_panel.html",
            plugin_type="workflow",
            record_id=record_id,
            row_key="workflow_id",
            form_schema_only_url=url_for("api.get_workflow_form_schema"),
            api_base="/api/workflow",
            label_registry="Workflow registry",
            label_singular="Workflow",
        )
