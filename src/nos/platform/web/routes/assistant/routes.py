"""
Assistant page routes.
Registers /assistant and related routes on the given blueprint.
"""

from flask import render_template


def register_routes(bp):
    """Register assistant routes on the given blueprint."""

    @bp.get("/assistant")
    def assistant():
        """Assistant management page."""
        return render_template("assistant/assistant.html")

    @bp.get("/assistants/published")
    def assistants_published():
        """Public assistants registry - shows assistants with PUBLISHED status."""
        return render_template("assistant/published.html")
