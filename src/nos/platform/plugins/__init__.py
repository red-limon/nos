"""
Flask-side plugin loader: ``nos.plugins`` entry points, dependency / capability ordering,
``plugins`` database table (isolated bind), registry bridge for :class:`~nos.core.engine.base.Node`
and :class:`~nos.core.engine.base.Workflow` classes.
"""

from .dependency_graph import merge_requires_with_capabilities, topological_sort
from .plugin_manager import ENTRY_GROUP, PluginManager
from .plugin_base import EnginePluginAdapter, Plugin
from .plugin_context import PluginContext
from .service_container import ServiceContainer

__all__ = [
    "ENTRY_GROUP",
    "EnginePluginAdapter",
    "Plugin",
    "PluginContext",
    "PluginManager",
    "ServiceContainer",
    "merge_requires_with_capabilities",
    "topological_sort",
]
