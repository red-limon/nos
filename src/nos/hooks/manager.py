"""
Event Hook Manager - Core event system implementation.
"""

import logging
from typing import Callable, Any, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)


def _describe_event_data(data: Any) -> str:
    """Short summary for logs — never embed full payloads (HTML, etc.) at INFO."""
    if data is None:
        return "None"
    if isinstance(data, dict):
        keys = list(data.keys())
        head = keys[:16]
        extra = f", …+{len(keys) - 16} more" if len(keys) > 16 else ""
        return f"dict(n_keys={len(keys)}, keys={head!r}{extra})"
    if isinstance(data, (list, tuple)):
        return f"{type(data).__name__}(len={len(data)})"
    try:
        s = repr(data)
    except Exception:
        return f"<{type(data).__name__}>"
    if len(s) > 200:
        return f"{type(data).__name__}(~{len(s)} chars)"
    return s


def _event_type_key(event_type: Any) -> str:
    """Normalize hook keys so any :class:`enum.Enum` (e.g. scoped node run types) matches ``emit``/``register``."""
    if isinstance(event_type, Enum):
        v = event_type.value
        return v if isinstance(v, str) else str(v)
    return event_type


class EventType(str, Enum):
    """Domain-level event types."""
    
    # User events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    
    # State events
    STATE_CHANGED = "state.changed"
    
    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_ERROR = "workflow.error"
    WORKFLOW_STOPPED = "workflow.stopped"
    
    # Custom events can be added here
    CUSTOM = "custom"


class EventHookManager:
    """
    Manages domain-level event hooks.
    
    This is framework-agnostic and can be used from:
    - REST API endpoints
    - SocketIO handlers
    - Async jobs
    - Plugins
    - In-process code
    
    Future evolution: Can be replaced with message broker (Kafka/Redis)
    without breaking existing code.
    """
    
    def __init__(self):
        """Initialize the event hook manager."""
        self._hooks: Dict[str, List[Callable]] = {}
    
    def register(self, event_type: str | EventType, handler: Callable[[Any], None]):
        """
        Register an event handler.
        
        Args:
            event_type: Event type (string or EventType enum)
            handler: Callable that receives event data
        """
        event_str = _event_type_key(event_type)

        if event_str not in self._hooks:
            self._hooks[event_str] = []

        self._hooks[event_str].append(handler)
        logger.debug(f"Registered handler for event: {event_str}")
    
    def unregister(self, event_type: str | EventType, handler: Callable):
        """
        Unregister an event handler.
        
        Args:
            event_type: Event type
            handler: Handler to remove
        """
        event_str = _event_type_key(event_type)

        if event_str in self._hooks:
            try:
                self._hooks[event_str].remove(handler)
                logger.debug(f"Unregistered handler for event: {event_str}")
            except ValueError:
                logger.warning(f"Handler not found for event: {event_str}")
    
    def emit(self, event_type: str | EventType, data: Any = None):
        """
        Emit an event to all registered handlers.
        
        Args:
            event_type: Event type
            data: Event data (any type)
        """
        event_str = _event_type_key(event_type)

        if event_str not in self._hooks:
            logger.debug(f"No handlers registered for event: {event_str}")
            return

        n_handlers = len(self._hooks[event_str])
        logger.info(
            "Emitting event %s to %d handler(s); %s",
            event_str,
            n_handlers,
            _describe_event_data(data),
        )

        for i, handler in enumerate(self._hooks[event_str]):
            try:
                logger.debug(f"Calling handler {i+1}/{len(self._hooks[event_str])} for {event_str}")
                handler(data)
                logger.debug(f"Handler {i+1} completed successfully")
            except Exception as e:
                logger.error(f"Error in event handler {i+1} for {event_str}: {e}", exc_info=True)
    
    def clear(self, event_type: str | EventType | None = None):
        """
        Clear handlers for an event type, or all events.
        
        Args:
            event_type: Event type to clear. If None, clears all.
        """
        if event_type is None:
            self._hooks.clear()
            logger.debug("Cleared all event handlers")
        else:
            event_str = _event_type_key(event_type)
            if event_str in self._hooks:
                del self._hooks[event_str]
                logger.debug(f"Cleared handlers for event: {event_str}")


# Global event hook manager instance
event_hooks = EventHookManager()
