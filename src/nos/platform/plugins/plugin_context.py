"""Controlled façade passed to plugin lifecycle hooks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from flask import Flask
    from sqlalchemy.orm import Session

    from .plugin_base import Plugin
    from .service_container import ServiceContainer


@dataclass
class PluginContext:
    """
    Intentionally narrow API for plugins: avoid importing internal ``nos.platform`` modules.

    - ``app``: Flask application instance
    - ``session``: SQLAlchemy scoped session; ORM writes route to the correct engine (core ``nos.db``
      vs plugins ``plugins.db``) via each model's ``__bind_key__``.
    - ``config``: Flask ``app.config`` mapping (read-only use recommended)
    - ``services``: :class:`ServiceContainer`
    - ``plugins``: mapping ``entry_point_name -> Plugin instance`` for already-enabled plugins
    """

    app: "Flask"
    session: "Session"
    config: Dict[str, Any]
    services: "ServiceContainer"
    plugins: Dict[str, "Plugin"] = field(default_factory=dict)
