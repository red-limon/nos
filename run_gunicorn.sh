#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
gunicorn --worker-class eventlet --workers 1 --bind 0.0.0.0:5000 --timeout 30 "hythera.app:create_app()"
