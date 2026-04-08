"""Serialize/deserialize execution log events for cross-process bridge."""

from __future__ import annotations

import importlib
from typing import Any

from nos.core.execution_log.events import BaseEvent, CustomEvent

_EVENTS_MODULE = importlib.import_module("nos.core.execution_log.events")


def serialize_event(event: BaseEvent) -> dict[str, Any]:
    """Pickle-friendly dict for multiprocessing queue."""
    name = event.__class__.__name__
    data = event.model_dump()
    return {"__event_class__": name, "payload": data}


def deserialize_event(obj: dict[str, Any]) -> BaseEvent:
    """Rebuild a Pydantic event instance from :func:`serialize_event` output."""
    name = obj.get("__event_class__", "CustomEvent")
    payload = dict(obj.get("payload") or {})
    cls = getattr(_EVENTS_MODULE, name, None)
    if cls is None:
        return CustomEvent.model_validate(payload)
    return cls.model_validate(payload)
