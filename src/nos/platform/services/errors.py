"""
Centralized error handling.
"""

import logging
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


def register_error_handlers(app: Flask):
    """
    Register global error handlers.

    Args:
        app: Flask application instance.
    """

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        """Handle HTTP exceptions."""
        # API routes return JSON
        if request.path.startswith("/api"):
            return jsonify({
                "error": e.name,
                "message": e.description,
                "code": e.code
            }), e.code

        # Web routes return HTML
        return render_template("error.html", error=e), e.code

    @app.errorhandler(404)
    def handle_not_found(e):
        """Handle 404 errors."""
        if request.path.startswith("/api"):
            return jsonify({
                "error": "Not Found",
                "message": "The requested resource was not found.",
                "code": 404
            }), 404
        return render_template("error.html", error=e), 404

    @app.errorhandler(500)
    def handle_internal_error(e):
        """Handle 500 errors."""
        logger.exception("Internal server error")

        if request.path.startswith("/api"):
            return jsonify({
                "error": "Internal Server Error",
                "message": "An unexpected error occurred.",
                "code": 500
            }), 500

        return render_template("error.html", error=e), 500

    @app.errorhandler(Exception)
    def handle_generic_exception(e: Exception):
        """Handle unhandled exceptions."""
        logger.exception("Unhandled exception")

        if request.path.startswith("/api"):
            return jsonify({
                "error": "Internal Server Error",
                "message": str(e) if app.config.get("DEBUG") else "An unexpected error occurred.",
                "code": 500
            }), 500

        return render_template("error.html", error=e), 500
