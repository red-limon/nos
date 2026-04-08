"""
Application state management service.
Framework-agnostic shared state.
"""

from typing import Set, Dict, Any


class AppState:
    """
    Application-wide state management.
    
    This is framework-agnostic and can be used from:
    - REST API endpoints
    - SocketIO handlers
    - Background jobs
    - Plugins
    
    Future evolution: Can be replaced with Redis or other distributed state
    without breaking existing code.
    """
    
    def __init__(self):
        """Initialize application state."""
        self.active_users: Set[str] = set()
        self.custom_data: Dict[str, Any] = {}
    
    def add_active_user(self, user_id: str):
        """Add an active user."""
        self.active_users.add(user_id)
    
    def remove_active_user(self, user_id: str):
        """Remove an active user."""
        self.active_users.discard(user_id)
    
    def get_active_users_count(self) -> int:
        """Get count of active users."""
        return len(self.active_users)
    
    def set_custom_data(self, key: str, value: Any):
        """Set custom data."""
        self.custom_data[key] = value
    
    def get_custom_data(self, key: str, default: Any = None) -> Any:
        """Get custom data."""
        return self.custom_data.get(key, default)
    
    def clear(self):
        """Clear all state."""
        self.active_users.clear()
        self.custom_data.clear()


# Global state instance
state = AppState()
