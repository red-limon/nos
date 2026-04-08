"""Discover entry-point plugins, resolve dependencies, enable via sandboxed lifecycle hooks."""
from __future__ import annotations

import logging
from collections import defaultdict
from importlib.metadata import entry_points
from typing import Dict, List, Optional, Type

from flask import Flask

from nos.core.engine.base import Node, Workflow
from nos.platform.extensions import db
from nos.platform.services.sqlalchemy.plugin.enums import PluginRecordType
from nos.platform.services.sqlalchemy.plugin import repository as plugin_repo

from .dependency_graph import merge_requires_with_capabilities, topological_sort
from .plugin_base import EnginePluginAdapter, Plugin
from .plugin_context import PluginContext
from .sandbox import safe_call
from .service_container import ServiceContainer

logger = logging.getLogger(__name__)

ENTRY_GROUP = "nos.plugins"


def _requires_for_plugin(name: str, plugin: Plugin) -> List[str]:
    """Entry-point names that must load before ``name`` (direct ``requires`` on the class)."""
    tgt = getattr(plugin, "_target_cls", None)
    if tgt is not None:
        return list(getattr(tgt, "requires", []) or [])
    return list(plugin.__class__.requires or [])


def _requires_caps_for_plugin(plugin: Plugin) -> List[str]:
    return plugin.iter_requires_capabilities()


class PluginManager:
    """
    Loads ``nos.plugins`` entry points after app startup, registers engine classes, persists rows in
    the plugins bind (``plugins`` table), and keeps enabled :class:`Plugin` instances in :attr:`plugins`.
    """

    def __init__(self, app: Flask) -> None:
        self.app = app
        self.services = ServiceContainer()
        self.plugins: Dict[str, Plugin] = {}

    def load_and_enable_all(self) -> None:
        eps = list(entry_points(group=ENTRY_GROUP))
        if not eps:
            logger.info("PluginManager: no entry points in group %r", ENTRY_GROUP)
            return

        adapters: Dict[str, Plugin] = {}
        requires_map: Dict[str, List[str]] = {}

        for ep in eps:
            name = ep.name
            try:
                cls = ep.load()
            except Exception as exc:
                logger.exception("PluginManager: failed to load entry point %r", name)
                self._persist_load_failure(ep, name, exc)
                continue

            if not isinstance(cls, type):
                self._persist_type_error(name, ep, cls, "entry point does not refer to a class")
                continue

            try:
                if issubclass(cls, Workflow):
                    adapters[name] = EnginePluginAdapter(cls, name)
                    requires_map[name] = _requires_for_plugin(name, adapters[name])
                elif issubclass(cls, Node):
                    adapters[name] = EnginePluginAdapter(cls, name)
                    requires_map[name] = _requires_for_plugin(name, adapters[name])
                elif issubclass(cls, Plugin):
                    adapters[name] = cls()
                    requires_map[name] = _requires_for_plugin(name, adapters[name])
                else:
                    raise TypeError(f"{cls!r} must subclass Node, Workflow, or Plugin")
            except Exception as exc:
                logger.exception("PluginManager: failed to build plugin %r", name)
                self._persist_build_failure(ep, cls, exc)

        if not adapters:
            return

        capability_providers: Dict[str, List[str]] = defaultdict(list)
        for name, plugin in adapters.items():
            for cap in plugin.iter_capabilities():
                capability_providers[cap].append(name)

        requires_caps_map: Dict[str, List[str]] = {
            name: _requires_caps_for_plugin(plugin) for name, plugin in adapters.items()
        }

        try:
            merged = merge_requires_with_capabilities(
                requires_map, requires_caps_map, dict(capability_providers)
            )
            order = topological_sort(list(adapters.keys()), merged)
        except ValueError as exc:
            logger.error("PluginManager: dependency / capability resolution failed: %s", exc)
            return

        ctx = PluginContext(
            app=self.app,
            session=db.session,
            config=dict(self.app.config),
            services=self.services,
            plugins=self.plugins,
        )

        for name in order:
            plugin = adapters[name]
            _, err = safe_call(plugin.on_enable, ctx)
            if err is not None:
                db.session.rollback()
                self._persist_enable_failure(name, plugin, err)
                continue
            try:
                db.session.commit()
            except Exception as commit_exc:
                db.session.rollback()
                logger.exception("PluginManager: commit failed for %r", name)
                self._persist_enable_failure(name, plugin, commit_exc)
                continue
            self.plugins[name] = plugin
            logger.info("PluginManager: enabled entry point %r", name)

    # --- persistence helpers (errors must not take down the app) ---

    def _persist_load_failure(self, ep, name: str, exc: BaseException) -> None:
        mod, cls_name = self._split_ep(ep)
        try:
            plugin_repo.upsert_error(
                db.session,
                plugin_id=name,
                plugin_type=PluginRecordType.NODE,
                module_path=mod,
                class_name=cls_name,
                message=str(exc),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("PluginManager: could not persist load failure for %r", name)

    def _persist_type_error(self, name: str, ep, obj: object, message: str) -> None:
        mod, cls_name = self._split_ep(ep)
        try:
            plugin_repo.upsert_error(
                db.session,
                plugin_id=name,
                plugin_type=PluginRecordType.NODE,
                module_path=mod,
                class_name=cls_name,
                message=message,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("PluginManager: could not persist type error for %r", name)

    def _persist_build_failure(self, ep, cls: Type, exc: BaseException) -> None:
        name = ep.name
        mod = getattr(cls, "__module__", "")
        cls_name = getattr(cls, "__name__", "")
        try:
            plugin_repo.upsert_error(
                db.session,
                plugin_id=name,
                plugin_type=PluginRecordType.NODE,
                module_path=mod or self._split_ep(ep)[0],
                class_name=cls_name or self._split_ep(ep)[1],
                message=str(exc),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("PluginManager: could not persist build failure for %r", name)

    def _persist_enable_failure(self, name: str, plugin: Plugin, exc: BaseException) -> None:
        try:
            tgt = getattr(plugin, "_target_cls", None)
            if tgt is not None:
                plugin_id = getattr(tgt, "workflow_id", None) or getattr(tgt, "node_id", None) or name
                ptype = (
                    PluginRecordType.WORKFLOW
                    if issubclass(tgt, Workflow)
                    else PluginRecordType.NODE
                )
                mod = tgt.__module__
                cname = tgt.__name__
            else:
                plugin_id = name
                ptype = PluginRecordType.NODE
                mod = plugin.__class__.__module__
                cname = plugin.__class__.__name__

            plugin_repo.upsert_error(
                db.session,
                plugin_id=plugin_id,
                plugin_type=ptype,
                module_path=mod,
                class_name=cname,
                message=str(exc),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("PluginManager: could not persist enable failure for %r", name)

    @staticmethod
    def _split_ep(ep) -> tuple[str, str]:
        try:
            return ep.module, ep.attr  # type: ignore[attr-defined]
        except Exception:
            parts = str(ep.value).split(":", 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
            return "", ""
