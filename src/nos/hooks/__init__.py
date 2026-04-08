"""
Event Hook System - Domain-level events, framework-agnostic.

This module provides an event hook system that:
- Works at domain level, not HTTP level
- Has no Flask dependencies
- Can be used from REST, SocketIO, async jobs, plugins
- Can evolve to message broker (Kafka/Redis) without breaking code
"""

from .manager import EventHookManager, event_hooks, EventType
from .registrations import register_app_event_listeners

__all__ = ["EventHookManager", "event_hooks", "EventType", "register_app_event_listeners"]
