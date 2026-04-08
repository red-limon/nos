"""
Config Service - Read configuration variables from .env file.

Provides functionality for listing environment variables loaded from .env.
Used by the console 'config list' command.

Usage:
    from nos.platform.services.config_service import config_service

    vars_list = config_service.list_env_vars()
    # Returns list of {"key": str, "value": str} (sensitive values masked)
"""

import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Substrings that indicate a key should have its value masked
_SENSITIVE_KEY_PATTERNS = (
    "PASSWORD", "SECRET", "TOKEN", "KEY", "AUTH", "CREDENTIAL", "PRIVATE",
    "API_KEY", "SECRET_KEY", "ACCESS_KEY",
)


def _is_sensitive_key(key: str) -> bool:
    """Return True if the key name suggests a sensitive value."""
    key_upper = key.upper()
    return any(p in key_upper for p in _SENSITIVE_KEY_PATTERNS)


def _mask_value(value: str) -> str:
    """Mask a sensitive value for display."""
    if not value or not value.strip():
        return "(empty)"
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:] if len(value) > 4 else "****"


class ConfigService:
    """
    Service for reading configuration from .env file.

    List environment variables from the loaded .env file (or from os.environ
    if .env is not found). Sensitive keys are masked in the output.
    """

    def list_env_vars(self) -> List[Dict[str, str]]:
        """
        List configuration variables from .env file.

        Reads the .env file via python-dotenv (find_dotenv + dotenv_values).
        Values for keys containing PASSWORD, SECRET, TOKEN, etc. are masked.

        Returns:
            List of {"key": str, "value": str} sorted by key.
            value is masked for sensitive keys.
        """
        result: List[Dict[str, str]] = []
        try:
            from dotenv import dotenv_values, find_dotenv

            env_path = find_dotenv(usecwd=True)
            if not env_path:
                # Fallback: try project root relative to package
                try:
                    pkg_dir = Path(__file__).resolve().parent
                    project_root = pkg_dir.parent.parent.parent
                    env_path = str(project_root / ".env")
                except Exception:
                    env_path = ".env"

            values = dotenv_values(dotenv_path=env_path)
            if not values:
                logger.debug("No .env file found or empty; using os.environ")
                import os
                values = dict(os.environ)

            for key in sorted(values.keys()):
                raw_value = values.get(key, "")
                display_value = (
                    _mask_value(str(raw_value)) if _is_sensitive_key(key) else str(raw_value)
                )
                result.append({"key": key, "value": display_value})

        except Exception as e:
            logger.warning("config_service list_env_vars failed: %s", e)
            result.append({"key": "(error)", "value": str(e)})

        return result


config_service = ConfigService()
