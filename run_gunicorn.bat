@echo off
cd /d %~dp0
.venv\Scripts\Activate.ps1
gunicorn --worker-class eventlet --workers 1 --bind 0.0.0.0:5000 --timeout 30 "hythera.app:create_app()"
