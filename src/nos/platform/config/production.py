"""
Production configuration.
"""

import os
from .base import BaseConfig


class ProductionConfig(BaseConfig):
    """Production-specific configuration."""
    
    DEBUG = False
    SQLALCHEMY_ECHO = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")
    
    # Security
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
