"""
Security utilities and helpers.
"""

import secrets
from functools import wraps
from flask import request, jsonify, current_app


def generate_secret_key() -> str:
    """
    Generate a secure random secret key.

    Returns:
        Random hex string suitable for Flask SECRET_KEY.
    """
    return secrets.token_hex(32)


def require_api_key(f):
    """
    Decorator to require API key authentication.
    Usage: @require_api_key
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        expected_key = current_app.config.get("API_KEY")

        if expected_key and api_key != expected_key:
            return jsonify({"error": "Unauthorized", "message": "Invalid API key"}), 401

        return f(*args, **kwargs)

    return decorated_function
