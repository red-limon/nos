"""
SocketIO namespaces for organized event handling.
Can be extended for different namespaces (e.g., /admin, /public).
"""

from flask_socketio import Namespace, emit


class PublicNamespace(Namespace):
    """Public namespace for general events."""
    
    def on_connect(self, auth):
        """Handle connection to public namespace."""
        emit("status", {"msg": "Connected to public namespace"})
    
    def on_disconnect(self):
        """Handle disconnection from public namespace."""
        pass
    
    def on_message(self, data):
        """Handle message in public namespace."""
        emit("message", data, broadcast=True)


# Example: Register namespace
# socketio.on_namespace(PublicNamespace('/public'))
