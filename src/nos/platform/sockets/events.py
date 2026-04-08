"""
SocketIO event handlers.
Handles WebSocket connections and events.
"""

import logging
from flask_socketio import emit, join_room, leave_room
from flask import request
from ..services.state_service import state
from nos.hooks import event_hooks, EventType
from .engine_events import register_engine_socket_events
from .console_events import register_console_socket_events

logger = logging.getLogger(__name__)


def register_socket_events(socketio):
    """
    Register all SocketIO event handlers.
    
    Args:
        socketio: SocketIO instance.
    """
    
    @socketio.on("connect")
    def handle_connect(auth=None):
        """Handle client connection."""
        client_id = request.sid
        logger.info(f"Client connected: {client_id}")
        
        # Add to active users
        state.add_active_user(client_id)
        
        # Emit connection status
        emit("status", {"msg": "Connected", "client_id": client_id})
        
        # Emit domain event
        event_hooks.emit(EventType.STATE_CHANGED, {
            "type": "user_connected",
            "client_id": client_id,
            "active_users_count": state.get_active_users_count(),
        })
    
    @socketio.on("disconnect")
    def handle_disconnect():
        """Handle client disconnection."""
        client_id = request.sid
        logger.info(f"Client disconnected: {client_id}")
        
        # Remove from active users
        state.remove_active_user(client_id)
        
        # Emit domain event
        event_hooks.emit(EventType.STATE_CHANGED, {
            "type": "user_disconnected",
            "client_id": client_id,
            "active_users_count": state.get_active_users_count(),
        })
    
    @socketio.on("message")
    def handle_message(data):
        """
        Handle generic message event.
        
        Args:
            data: Message data (dict or string).
        """
        client_id = request.sid
        logger.info(f"Message from {client_id}: {data}")
        
        # Broadcast to all clients
        emit("message", {
            "from": client_id,
            "data": data,
        }, broadcast=True)
    
    @socketio.on("join")
    def handle_join(data):
        """
        Handle room join event.
        
        Args:
            data: Dict with 'room' key.
        """
        room = data.get("room", "default")
        client_id = request.sid
        join_room(room)
        logger.info(f"Client {client_id} joined room: {room}")
        emit("status", {"msg": f"Joined room: {room}"}, room=room)
    
    @socketio.on("leave")
    def handle_leave(data):
        """
        Handle room leave event.
        
        Args:
            data: Dict with 'room' key.
        """
        room = data.get("room", "default")
        client_id = request.sid
        leave_room(room)
        logger.info(f"Client {client_id} left room: {room}")
        emit("status", {"msg": f"Left room: {room}"})
    
    @socketio.on("user_event")
    def handle_user_event(data):
        """
        Handle custom user event.
        
        Args:
            data: Event data.
        """
        client_id = request.sid
        logger.info(f"User event from {client_id}: {data}")
        
        # Emit domain event
        event_hooks.emit(EventType.CUSTOM, {
            "type": "socket_user_event",
            "client_id": client_id,
            "data": data,
        })
        
        # Broadcast to all clients
        emit("user_event", {
            "from": client_id,
            "data": data,
        }, broadcast=True)
    
    # Handle execution_response from client (Phase 2: bidirectional communication)
    @socketio.on("execution_response")
    def handle_execution_response(data):
        """
        Handle response from client to an execution_request.
        
        Args:
            data: Dict with 'request_id' and 'response' keys.
        """
        request_id = data.get("request_id")
        response_data = data.get("response", {})
        
        if not request_id:
            logger.warning("Received execution_response without request_id")
            return
        
        logger.info(f"Received execution_response for request_id: {request_id}")
        
        # Find and notify the waiting event log via global registry
        from nos.platform.execution_log import _event_log_registry

        event_log = _event_log_registry.get_for_request(request_id)
        if event_log:
            event_log.handle_response(request_id, response_data)
        else:
            logger.warning(f"No event log waiting for request_id: {request_id}")
    
    # Register engine socket events (engine_request_run, engine_form_data, etc.)
    register_engine_socket_events(socketio)
    
    # Register console socket events (console_command, console_output)
    register_console_socket_events(socketio)