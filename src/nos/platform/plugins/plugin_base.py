"""Base class for optional custom platform plugins (beyond Node / Workflow entry points)."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, List

if TYPE_CHECKING:
    from .plugin_context import PluginContext


class Plugin:
    """
    Optional lifecycle hooks for advanced integrations.

    Entry points may target either:

    - a :class:`~nos.core.engine.base.Node` or :class:`~nos.core.engine.base.Workflow` subclass
      (handled by :class:`EnginePluginAdapter` inside :class:`PluginManager`), or
    - a subclass of this class for custom behaviour.

    ``requires`` lists **entry point names** (``importlib.metadata`` ``name``) that must load first.

    ``requires_capabilities`` lists **capability strings**; at least one other enabled plugin must
    advertise each capability via ``capabilities`` (see :meth:`iter_capabilities`).
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"
    requires: ClassVar[List[str]] = []
    requires_capabilities: ClassVar[List[str]] = []
    capabilities: ClassVar[List[str]] = []

    def iter_capabilities(self) -> List[str]:
        """Capabilities this plugin advertises (for dependency resolution)."""
        return list(self.__class__.capabilities or [])

    def iter_requires_capabilities(self) -> List[str]:
        """Capabilities that must be satisfied by other plugins before this one enables."""
        return list(self.__class__.requires_capabilities or [])

    def on_install(self, ctx: PluginContext) -> None:
        """Reserved for future package-install hooks."""

    def on_enable(self, ctx: PluginContext) -> None:
        """Override for custom enable logic (registry + DB are handled by the manager for engine classes)."""

    def on_disable(self, ctx: PluginContext) -> None:
        """Called when a plugin is disabled (future use)."""

    def on_uninstall(self, ctx: PluginContext) -> None:
        """Reserved for uninstall cleanup."""


class EnginePluginAdapter(Plugin):
    """
    Wraps a :class:`~nos.core.engine.base.Node` or :class:`~nos.core.engine.base.Workflow` class
    discovered via entry points so lifecycle flows through :meth:`on_enable`.
    """

    def __init__(self, target_cls: type, entry_point_name: str) -> None:
        self._target_cls = target_cls
        self._entry_point_name = entry_point_name
        self.name = entry_point_name or target_cls.__name__
        self.version = getattr(target_cls, "__version__", "0.0.0")

    def iter_capabilities(self) -> List[str]:
        return list(getattr(self._target_cls, "capabilities", []) or [])

    def iter_requires_capabilities(self) -> List[str]:
        return list(getattr(self._target_cls, "requires_capabilities", []) or [])

    def on_enable(self, ctx: PluginContext) -> None:
        from nos.core.engine.registry import workflow_registry
        from nos.core.engine.base import Node, Workflow

        from nos.platform.services.sqlalchemy.plugin.enums import PluginRecordType
        from nos.platform.services.sqlalchemy.plugin import repository as plugin_repo

        cls = self._target_cls
        session = ctx.session

        if issubclass(cls, Workflow):
            workflow_registry.register_workflow(cls)
            plugin_id = cls.workflow_id
            ptype = PluginRecordType.WORKFLOW
        elif issubclass(cls, Node):
            workflow_registry.register_node(cls)
            plugin_id = cls.node_id
            ptype = PluginRecordType.NODE
        else:
            raise TypeError(f"EnginePluginAdapter expects Node or Workflow, got {cls!r}")

        plugin_repo.upsert_registered(
            session,
            plugin_id=plugin_id,
            plugin_type=ptype,
            module_path=cls.__module__,
            class_name=cls.__name__,
        )
