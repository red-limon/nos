"""
Base configuration class.
All environment-specific configs inherit from this.
"""

import os
from datetime import timedelta


class BaseConfig:
    """Base configuration with common settings."""
    
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    DEBUG = False
    TESTING = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=31)
    
    # CORS (comma-separated origins; default allows localhost and nos on 8080/8081/8082)
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080,http://localhost:8081,http://127.0.0.1:8081,http://localhost:8082,http://127.0.0.1:8082,http://nos:8082",
    )
    
    # Database
    # Default will be overridden in app.py to use instance folder
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", 
        "sqlite:///nos.db"  # Will be overridden in app.py
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # SocketIO
    SOCKETIO_ASYNC_MODE = "gevent"  # Using gevent for better SSE support
    SOCKETIO_CORS_ALLOWED_ORIGINS = "*"
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
