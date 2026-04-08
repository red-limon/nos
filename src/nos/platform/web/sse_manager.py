"""
SSE Manager - Handles Server-Sent Events connections with eventlet compatibility.
"""

import json
import time
import queue
import logging
from typing import Dict, Callable
from nos.hooks import event_hooks, EventType

logger = logging.getLogger(__name__)


class SSEManager:
    """
    Manages SSE connections with eventlet compatibility.
    Uses a dedicated queue system that works with eventlet's green threads.
    """
    
    def __init__(self):
        """Initialize SSE manager."""
        self._connections: Dict[str, queue.Queue] = {}
        self._callbacks: Dict[str, Callable] = {}
    
    def create_connection(self, connection_id: str) -> queue.Queue:
        """
        Create a new SSE connection.
        
        Args:
            connection_id: Unique connection identifier.
        
        Returns:
            Queue for this connection.
        """
        event_queue = queue.Queue()
        self._connections[connection_id] = event_queue
        
        # Create callbacks for each event type
        def create_event_callback(event_type: EventType):
            """Create a callback that adds event type to the data."""
            def event_callback(data):
                """Callback to capture events for this connection."""
                try:
                    # Ensure data is a dict and add event type
                    if isinstance(data, dict):
                        event_data = {**data, "type": event_type.value}
                    else:
                        event_data = {"type": event_type.value, "data": data}
                    
                    event_queue.put(event_data, block=False)
                    if isinstance(event_data, dict):
                        keys_preview = list(event_data.keys())[:20]
                        logger.debug(
                            "SSE event queued for %s: %s; keys=%s",
                            connection_id,
                            event_type.value,
                            keys_preview,
                        )
                    else:
                        logger.debug(
                            "SSE event queued for %s: %s; type=%s",
                            connection_id,
                            event_type.value,
                            type(event_data).__name__,
                        )
                except queue.Full:
                    logger.warning(f"SSE queue full for connection {connection_id}")
                except Exception as e:
                    logger.error(f"Error putting event in SSE queue: {e}")
            return event_callback
        
        # Register callbacks with event hooks
        state_callback = create_event_callback(EventType.STATE_CHANGED)
        user_created_callback = create_event_callback(EventType.USER_CREATED)
        user_updated_callback = create_event_callback(EventType.USER_UPDATED)
        user_deleted_callback = create_event_callback(EventType.USER_DELETED)
        custom_callback = create_event_callback(EventType.CUSTOM)
        
        self._callbacks[connection_id] = {
            EventType.STATE_CHANGED: state_callback,
            EventType.USER_CREATED: user_created_callback,
            EventType.USER_UPDATED: user_updated_callback,
            EventType.USER_DELETED: user_deleted_callback,
            EventType.CUSTOM: custom_callback,
        }
        
        event_hooks.register(EventType.STATE_CHANGED, state_callback)
        event_hooks.register(EventType.USER_CREATED, user_created_callback)
        event_hooks.register(EventType.USER_UPDATED, user_updated_callback)
        event_hooks.register(EventType.USER_DELETED, user_deleted_callback)
        event_hooks.register(EventType.CUSTOM, custom_callback)
        
        logger.info(f"Created SSE connection: {connection_id}")
        return event_queue
    
    def remove_connection(self, connection_id: str):
        """
        Remove an SSE connection and cleanup.
        
        Args:
            connection_id: Connection identifier to remove.
        """
        if connection_id in self._callbacks:
            callbacks = self._callbacks[connection_id]
            # Unregister all callbacks
            try:
                if isinstance(callbacks, dict):
                    # New format: dict of callbacks
                    event_hooks.unregister(EventType.STATE_CHANGED, callbacks.get(EventType.STATE_CHANGED))
                    event_hooks.unregister(EventType.USER_CREATED, callbacks.get(EventType.USER_CREATED))
                    event_hooks.unregister(EventType.USER_UPDATED, callbacks.get(EventType.USER_UPDATED))
                    event_hooks.unregister(EventType.USER_DELETED, callbacks.get(EventType.USER_DELETED))
                    event_hooks.unregister(EventType.CUSTOM, callbacks.get(EventType.CUSTOM))
                else:
                    # Old format: single callback (backward compatibility)
                    callback = callbacks
                    event_hooks.unregister(EventType.STATE_CHANGED, callback)
                    event_hooks.unregister(EventType.USER_CREATED, callback)
                    event_hooks.unregister(EventType.USER_UPDATED, callback)
                    event_hooks.unregister(EventType.USER_DELETED, callback)
                    event_hooks.unregister(EventType.CUSTOM, callback)
            except Exception as e:
                logger.warning(f"Error unregistering SSE callbacks: {e}")
            
            del self._callbacks[connection_id]
        
        if connection_id in self._connections:
            del self._connections[connection_id]
        
        logger.info(f"Removed SSE connection: {connection_id}")
    
    def get_connection(self, connection_id: str) -> queue.Queue | None:
        """
        Get queue for a connection.
        
        Args:
            connection_id: Connection identifier.
        
        Returns:
            Queue for the connection or None if not found.
        """
        return self._connections.get(connection_id)


# Global SSE manager instance
sse_manager = SSEManager()
