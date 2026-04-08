"""Minimal service locator used by :class:`PluginContext`."""
from __future__ import annotations

from typing import Any, Dict, Optional


class ServiceContainer:
    """Simple ``register`` / ``get`` container for platform services exposed to plugins."""

    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str) -> Optional[Any]:
        return self._services.get(name)

    def require(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"Service {name!r} is not registered")
        return self._services[name]
