"""
AI Models page routes.
Registers /ai-models and related routes on the given blueprint.
"""

from flask import render_template


def register_routes(bp):
    """Register AI models routes on the given blueprint."""

    @bp.get("/ai-models")
    def ai_models():
        """AI Models management page."""
        return render_template("ai_models/models.html")
