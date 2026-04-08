"""
Web routes - HTML pages and Server-Sent Events (SSE).
"""

import os
from flask import Blueprint, render_template, Response, stream_with_context, request, redirect, url_for, session, abort
from ...services.state_service import state
import json
import time
import uuid
import logging
from ..sse_manager import sse_manager

logger = logging.getLogger(__name__)

web_bp = Blueprint("web", __name__)


@web_bp.get("/redlimon")
def redlimon():
    """RedLemon landing page."""
    return render_template("redlimon.html")


@web_bp.get("/redlimon/app")
@web_bp.get("/redlimon/app.html")
def redlimon_app():
    """RedLimon App page – plug&play digital assistants from the marketplace."""
    return render_template("redlimon/app.html")


@web_bp.get("/redlimon/download")
def redlimon_download():
    """RedLimon Download page."""
    return render_template("redlimon/download.html")


@web_bp.get("/redlimon/blog")
def redlimon_blog():
    """RedLimon Blog page."""
    return render_template("redlimon/blog.html")


@web_bp.get("/redlimon/community")
def redlimon_community():
    """RedLimon Community page – waiting list signup."""
    return render_template("redlimon/community.html")

@web_bp.get("/")
def index():
    """nOS landing page (index.html). Public root — no duplicate /nos path."""
    return render_template("index.html")


@web_bp.get("/nos")
@web_bp.get("/nos/")
def removed_nos_path():
    """Legacy marketing URL removed: same as any unknown page (404 + error.html)."""
    abort(404)


@web_bp.get("/showcase")
def showcase():
    """Public digital assistants showcase - run nodes via Socket.IO like the console."""
    return render_template("assistants_showcase.html")


@web_bp.get("/logout")
def logout():
    """Clear session and redirect to landing page."""
    session.clear()
    return redirect(url_for("web.index"))


@web_bp.get("/login")
def login_page():
    """Login page (form). Redirect to home if already logged in."""
    if session.get("username"):
        return redirect(url_for("web.home"))
    return render_template("login.html")


@web_bp.post("/login")
def login():
    """Handle login. Credentials from .env: LOGIN_USER, LOGIN_PASSWORD."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    remember_me = request.form.get("remember_me") == "1"
    expected_user = os.getenv("LOGIN_USER", "developer").strip()
    expected_password = os.getenv("LOGIN_PASSWORD", "").strip()
    if (
        expected_user
        and expected_password
        and username == expected_user
        and password == expected_password
    ):
        session["username"] = username
        session.permanent = remember_me
        return redirect(url_for("web.home"))
    return render_template(
        "login.html",
        error="Username and/or password not recognized.",
    )


@web_bp.get("/home")
def home():
    """Home page (playground UI) with iframes."""
    if not session.get("username"):
        session["username"] = os.getenv("LOGIN_USER", "developer").strip() or "developer"
    return render_template("home.html")


@web_bp.get("/navbar")
def navbar():
    """Navbar iframe."""
    return render_template("navbar.html")


@web_bp.get("/home-content")
def home_content():
    """Default content for home iframe."""
    return render_template("home_content.html")


@web_bp.get("/engine")
def engine():
    """Engine page."""
    return render_template("engine/plugins_console.html")


@web_bp.get("/engine/run")
def engine_run():
    """Engine run page (old version). Uses engine_form_data / engine_request_run.
    UI moved to engine/console_old/run.html. Current console: /engine/console uses engine_console.html."""
    return render_template("engine/console_old/run.html")


@web_bp.get("/engine/console")
def engine_console():
    """Engine console page."""
    if not session.get("username"):
        session["username"] = os.getenv("LOGIN_USER", "developer").strip() or "developer"
    return render_template("engine/engine_console.html")


@web_bp.get("/engine/console/compact")
def engine_console_compact():
    """Engine console - compact/mobile UI (same features, touch-friendly)."""
    return render_template("engine/engine_console_compact.html")


@web_bp.get("/engine/console/v2")
def engine_console_v2():
    """Engine console - IDE-style split layout (same features as engine_console.html)."""
    if not session.get("username"):
        session["username"] = os.getenv("LOGIN_USER", "developer").strip() or "developer"
    return render_template("engine/engine_console_v2.html")


@web_bp.get("/engine/console/bak-2026-03-27")
def engine_console_backup_2026_03_27():
    """Frozen snapshot of the console UI (see templates/engine/engine_console.html.2026-03-27.bak). Remove when obsolete."""
    return render_template("engine/engine_console.html.2026-03-27.bak")


def _serialize_command(cmd):
    """Serialize a CommandDefinition for the help template (no handler)."""
    subcommands = getattr(cmd, "subcommands", None) or {}
    return {
        "name": getattr(cmd, "name", ""),
        "description": getattr(cmd, "description", ""),
        "usage": (getattr(cmd, "usage", "") or "").strip(),
        "aliases": list(getattr(cmd, "aliases", None) or []),
        "subcommands": [_serialize_command(sc) for sc in subcommands.values()],
    }


@web_bp.get("/engine/help")
def engine_help():
    """Console commands help page - full reference with description, usage, examples."""
    from nos.platform.console import command_registry
    commands = [_serialize_command(c) for c in command_registry.get_all()]
    return render_template("engine/help.html", commands=commands)


@web_bp.get("/plugin-console/embed")
def plugin_console_embed():
    """Embeddable plugin console - command line only, for end users or iframes.
    Query param: theme=light|dark (default: dark)."""
    theme = request.args.get("theme", "dark")
    if theme not in ("light", "dark"):
        theme = "dark"
    return render_template("plugin_console_embed.html", theme=theme)


@web_bp.get("/test")
def test():
    """Test page (old index.html)."""
    return render_template("old/test.html", users=[], active_users_count=state.get_active_users_count())


@web_bp.get("/docs")
def docs():
    """Legacy documentation (templates/docs/docs.html). Not the API 101 reference."""
    return render_template("docs/docs.html")


@web_bp.get("/docs/101")
@web_bp.get("/docs/docs_101.html")
def docs_101():
    """Official API reference (nOS 1.0.1) — templates/docs/docs_101.html (sidebar TOC + PAGES)."""
    return render_template("docs/docs_101.html")


@web_bp.get("/docs/101/bak-2026-03-27")
def docs_101_backup_2026_03_27():
    """Temporary: backup snapshot of docs_101. Uses render_template so Jinja resolves `url_for(static, ...)`. Remove when obsolete."""
    return render_template("docs/docs_101.html.2026-03-27.bak")


@web_bp.get("/app")
@web_bp.get("/app.html")
@web_bp.get("/apps.html")
def app_page():
    """Apps page – use cases and workflow examples (placeholder)."""
    return render_template("apps.html")


@web_bp.get("/download")
def download_page():
    """Download page – get nOS from PyPI."""
    return render_template("download.html")


@web_bp.get("/form-example")
def form_example():
    """Form schema renderer example page."""
    return render_template("old/form_example.html")


@web_bp.get("/vibe-coding")
def vibe_coding():
    """Vibe coding page (beta) - AI-assisted plugin development."""
    return render_template("engine/vibe_coding.html")


@web_bp.get("/cron-jobs")
def cron_jobs():
    """Cron jobs management page."""
    return render_template("engine/cron_jobs.html")


@web_bp.get("/logger")
def logger_page():
    """Logger page."""
    return render_template("engine/logger.html")


@web_bp.get("/webhooks")
def webhooks():
    """Webhooks management page."""
    return render_template("engine/webhooks.html")


@web_bp.get("/console")
def console():
    """Real-time execution console - Socket.IO event viewer."""
    return render_template("engine/engine_console.html")


@web_bp.get("/events-test")
def test_events():
    """Simple test endpoint to verify routing works."""
    from flask import jsonify
    logger.info("Test endpoint /events-test called")
    return jsonify({"status": "ok", "message": "Events endpoint is reachable"}), 200


@web_bp.get("/events")
def stream_events():
    """
    Server-Sent Events (SSE) endpoint.
    Streams domain events to clients.
    
    Compatible with both Waitress (threading) and gevent.
    """
    try:
        # Log that endpoint was called
        logger.info("SSE endpoint /events called")
        print(f"[SSE] Endpoint /events called")
        
        # Generate unique connection ID
        connection_id = str(uuid.uuid4())
        logger.info(f"Creating SSE connection with ID: {connection_id}")
        print(f"[SSE] Creating connection: {connection_id}")
        
        event_queue = sse_manager.create_connection(connection_id)
        
        def event_stream():
            """
            Generator function for SSE stream.
            Optimized for one-shot unidirectional messages (no polling needed).
            """
            try:
                logger.debug("SSE event_stream generator started for %s", connection_id)
                
                # Send initial connection message immediately
                initial_data = {'type': 'connected', 'message': 'SSE stream connected'}
                initial_msg = f"data: {json.dumps(initial_data)}\n\n"
                yield initial_msg
                logger.info(f"SSE initial message sent for {connection_id}")
                
                # Send keep-alive comment to establish connection
                yield ": keepalive\n\n"
                
                last_keepalive = time.time()
                keepalive_interval = 15  # Send keep-alive comment every 15 seconds
                
                # Main event loop - optimized for one-shot messages
                while True:
                    try:
                        import queue as queue_module
                        # Wait for events with timeout for keep-alive
                        try:
                            event_data = event_queue.get(timeout=1.0)
                            # Format SSE message: "data: {json}\n\n"
                            msg = f"data: {json.dumps(event_data)}\n\n"
                            yield msg
                            logger.info(f"SSE sent event to {connection_id}: {event_data.get('type', 'unknown')}")
                        except queue_module.Empty:
                            # No events - check if we need keep-alive
                            current_time = time.time()
                            if current_time - last_keepalive >= keepalive_interval:
                                # Send keep-alive comment (not data, just a comment)
                                yield ": keepalive\n\n"
                                last_keepalive = current_time
                                logger.debug(f"SSE keep-alive sent to {connection_id}")
                    except Exception as e:
                        logger.warning(f"SSE queue error for {connection_id}: {e}", exc_info=True)
                        # Continue loop on error - use regular sleep (works with both threading and gevent)
                        time.sleep(0.5)
            
            except GeneratorExit:
                logger.info(f"SSE connection {connection_id} closed by client (GeneratorExit)")
            except Exception as e:
                logger.error(f"SSE generator error for {connection_id}: {e}", exc_info=True)
            finally:
                # Cleanup
                try:
                    sse_manager.remove_connection(connection_id)
                    logger.info(f"SSE connection {connection_id} cleaned up")
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up SSE connection {connection_id}: {cleanup_error}")
        
        # Create response with proper headers for SSE
        # Using stream_with_context to maintain Flask context during streaming
        response = Response(
            stream_with_context(event_stream()),
            mimetype="text/event-stream",
        )
        
        # Set headers for SSE compatibility
        # Note: "Connection" header is not allowed in WSGI (PEP 3333) - Waitress handles it automatically
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
        
        return response
    
    except Exception as e:
        logger.error(f"SSE endpoint error: {e}", exc_info=True)
        # Return error as SSE message format so client can receive it
        def error_stream():
            try:
                error_data = {
                    'type': 'error',
                    'message': 'SSE connection error',
                    'error': str(e)
                }
                yield f"data: {json.dumps(error_data)}\n\n"
            except:
                # Fallback if JSON encoding fails
                yield f"data: {{\"type\":\"error\",\"message\":\"SSE connection error\"}}\n\n"
        
        response = Response(
            stream_with_context(error_stream()),
            mimetype="text/event-stream",
            status=200,  # Keep 200 so client receives the error message
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
        return response


# Register routes from node, workflow, assistant and ai_models submodules
from .node import register_routes as register_node_routes
from .workflow import register_routes as register_workflow_routes
from .assistant import register_routes as register_assistant_routes
from .ai_models import register_routes as register_ai_models_routes
register_node_routes(web_bp)
register_workflow_routes(web_bp)
register_assistant_routes(web_bp)
register_ai_models_routes(web_bp)