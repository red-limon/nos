"""Enums for the unified ``plugins`` registry table (entry-point plugins)."""
from enum import Enum


class PluginRecordType(str, Enum):
    """Engine component type stored in ``plugins.plugin_type``."""

    NODE = "node"
    WORKFLOW = "workflow"


class PluginRecordStatus(str, Enum):
    """Lifecycle status for entry-point plugin rows."""

    REGISTERED = "registered"
    PUBLISHED = "published"
    ERROR = "error"
