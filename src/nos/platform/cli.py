"""
CLI entry point for the application.

Requires optional dependency group ``web`` (``pip install 'nos[web]'``).
"""

import os
import platform
import signal
import sys
import threading


def _get_bind_host() -> str:
    """
    Get the host to bind. On Windows, 0.0.0.0 can cause issues with Waitress
    (hostname resolution, HOSTS file conflicts e.g. with Parallels).
    Use HOST env var to override; on Windows default to 127.0.0.1.
    """
    host = os.getenv("HOST", "").strip()
    if host:
        return host
    if platform.system() == "Windows":
        return "127.0.0.1"
    return "0.0.0.0"


def _shutdown_waitress_server(server) -> None:
    """
    Stop Waitress without relying on KeyboardInterrupt inside the asyncore loop.

    On Windows (and some IDE-integrated terminals), Ctrl+C may not interrupt
    select/poll promptly; closing the socket map makes the main loop exit.
    """
    from waitress.wasyncore import close_all

    # Request cooperative stop on in-flight workflow/node runs (shared stop_event),
    # then drain the engine thread pool so parallel scrapers exit at the next fetch boundary.
    try:
        from nos.core.engine import get_shared_engine

        get_shared_engine().shutdown()
    except Exception:
        pass

    try:
        server.task_dispatcher.shutdown()
    except Exception:
        pass
    sock_map = getattr(server, "map", None) or getattr(server, "_map", None)
    if sock_map is not None:
        try:
            close_all(sock_map)
        except Exception:
            pass


def _schedule_waitress_shutdown(server) -> None:
    """
    Queue shutdown on the wasyncore main-loop thread.

    Calling task_dispatcher.shutdown() from a signal handler can deadlock
    (handler runs with unpredictable timing; workers may hold locks). Waitress
    runs deferred work via trigger.pull_trigger(thunk) on that thread.
    """
    def _thunk():
        _shutdown_waitress_server(server)

    trigger = getattr(server, "trigger", None)
    if trigger is not None and hasattr(trigger, "pull_trigger"):
        try:
            trigger.pull_trigger(_thunk)
            return
        except Exception:
            pass
    # Multi-socket server or trigger failure: run outside the signal handler.
    threading.Timer(0.0, _thunk).start()


def _install_waitress_signal_handlers(server) -> None:
    """Register SIGINT/SIGTERM to tear down Waitress (main thread only)."""
    if threading.current_thread() is not threading.main_thread():
        return

    stop_once = threading.Event()

    def _handle(_signum, _frame):
        if stop_once.is_set():
            raise KeyboardInterrupt
        stop_once.set()
        print("\nStopping server…", flush=True)
        _schedule_waitress_shutdown(server)

    signal.signal(signal.SIGINT, _handle)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _handle)
        except (ValueError, OSError):
            pass


def main():
    """Main entry point for nos command."""
    if len(sys.argv) > 1 and sys.argv[1] == "plugin":
        from nos.platform.plugins.cli import main as plugin_main

        raise SystemExit(plugin_main(sys.argv[2:]))

    try:
        from .app import create_app
        from .extensions import socketio
    except ImportError as exc:
        print(
            "The 'nos' CLI requires the web platform dependencies.\n"
            "Install with:  pip install 'nos[web]'\n"
            "Or full stack: pip install 'nos[all]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    app = create_app()

    host = _get_bind_host()
    port = int(os.getenv("PORT", "8082"))

    # Use Waitress for HTTP/SSE, SocketIO handles WebSocket separately
    # This prevents blocking issues with gevent
    use_waitress = os.getenv("USE_WAITRESS", "true").lower() == "true"

    if use_waitress:
        try:
            from waitress import create_server
            threads = int(os.getenv("WAITRESS_THREADS", "12"))
            print("Starting with Waitress (HTTP/SSE) + Flask-SocketIO (WebSocket)...")
            print(f"Server running on http://{host}:{port}")
            print("Press Ctrl+C to stop.", flush=True)
            server = create_server(
                app,
                host=host,
                port=port,
                threads=threads,
                channel_timeout=120,
                cleanup_interval=30,
            )
            _install_waitress_signal_handlers(server)
            try:
                server.run()
            except KeyboardInterrupt:
                try:
                    from nos.core.engine import get_shared_engine

                    get_shared_engine().shutdown()
                except Exception:
                    pass
        except ImportError:
            print("Waitress not installed, falling back to SocketIO directly...")
            use_waitress = False

    if not use_waitress:
        # Fallback: Run with SocketIO directly
        print("Starting with Flask-SocketIO + Gevent (supports SSE + WebSocket)...")
        print(f"Server running on http://{host}:{port}")
        print("Press Ctrl+C to stop.", flush=True)
        try:
            socketio.run(
                app,
                host=host,
                port=port,
                debug=app.config.get("DEBUG", False),
                use_reloader=False,
            )
        except KeyboardInterrupt:
            try:
                from nos.core.engine import get_shared_engine

                get_shared_engine().shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    main()
