"""
Flask extensions initialization.
Centralized to avoid circular imports.
"""

from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

# SocketIO instance - initialized in app factory
# Using threading mode when using Waitress, gevent when running directly
socketio = SocketIO(
    async_mode="threading",  # Use threading with Waitress to avoid blocking
    logger=False,  # Reduce logging to prevent blocking
    engineio_logger=False,
    cors_allowed_origins="*",
    max_http_buffer_size=1e6,  # 1MB buffer
    ping_timeout=60,
    ping_interval=25,
    # Disable WebSocket upgrade when using Waitress (only polling)
    transports=['polling', 'websocket'],  # Allow both, but Waitress will use polling
)

# SQLAlchemy instance
db = SQLAlchemy()

# CORS instance - initialized in app factory
cors = CORS()
