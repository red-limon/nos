"""
Development configuration.
"""

import os

from .base import BaseConfig


class DevelopmentConfig(BaseConfig):
    """Development-specific configuration."""

    DEBUG = True
    SQLALCHEMY_ECHO = True
    LOG_LEVEL = "DEBUG"
    # In dev allow any origin (override with CORS_ORIGINS env to restrict)
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")