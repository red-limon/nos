"""
Centralized logging configuration.
"""

import logging
import sys
from flask import Flask


def configure_logging(app: Flask):
    """
    Configure application-wide logging.

    Args:
        app: Flask application instance.
    """
    log_level = app.config.get("LOG_LEVEL", "INFO")
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Set Flask and Werkzeug loggers
    app.logger.setLevel(level)
    logging.getLogger("werkzeug").setLevel(level)

    # Suppress noisy loggers in production
    if not app.config.get("DEBUG", False):
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
