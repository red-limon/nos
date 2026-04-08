"""
Gunicorn configuration for nos.
Uses eventlet workers to support both HTTP (including SSE) and WebSocket.
"""

import multiprocessing

# Server socket
bind = "0.0.0.0:8082"
backlog = 2048

# Worker processes
workers = 1  # Use 1 worker with eventlet for SocketIO compatibility
worker_class = "eventlet"
worker_connections = 1000
timeout = 30
keepalive = 2

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"  # Log to stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "nos"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
# keyfile = None
# certfile = None
