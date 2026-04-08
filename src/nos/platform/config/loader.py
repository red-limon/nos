"""
Configuration loader.
Loads environment-specific configuration.
"""

import os
from dotenv import load_dotenv


def load_config(env: str | None = None):
    """
    Load configuration based on environment.
    
    Args:
        env: Environment name (development, production, testing).
             If None, reads from FLASK_ENV environment variable.
    
    Returns:
        Configuration class instance.
    """
    # Load environment variables from .env file
    load_dotenv()
    
    # Determine environment
    env = env or os.getenv("FLASK_ENV", "development")
    env = env.lower()
    
    # Load appropriate config
    if env == "production":
        from .production import ProductionConfig
        return ProductionConfig
    
    if env == "testing":
        from .base import BaseConfig
        config = BaseConfig()
        config.TESTING = True
        config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        return config
    
    # Default to development
    from .development import DevelopmentConfig
    return DevelopmentConfig
