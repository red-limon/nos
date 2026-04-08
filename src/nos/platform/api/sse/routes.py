"""
SSE streaming endpoint.

GET /api/sse/stream
    Opens a persistent ``text/event-stream`` connection for the current user.

    - Each connected browser tab gets its own :class:`queue.Queue` via
      :class:`~nos.platform.services.sse.manager.SseManager`.
    - A heartbeat comment (``": heartbeat"``) is sent every 25 seconds to
      keep the connection alive through proxies that close idle connections.
    - The generator cleans up the queue on any exit path (client disconnect,
      server shutdown, or stop sentinel).

SSE frame format (standard W3C EventSource protocol)::

    event: <event_name>\\n
    data: <json_payload>\\n
    \\n

Security note
-------------
The endpoint is served under the existing Flask session / auth context.
``user_id`` is read from ``flask.session`` so only the correct events
are delivered to each user.
"""

from __future__ import annotations

import json
import logging
import queue

from flask import Response, session, stream_with_context

from ...services.sse.manager import sse_manager

logger = logging.getLogger(__name__)


def register_routes(api_bp) -> None:
    """Register all SSE routes on *api_bp* (the shared Flask Blueprint)."""

    @api_bp.get("/sse/stream")
    def sse_stream() -> Response:
        """Open a persistent Server-Sent Events stream for the current user.

        The client (browser ``EventSource``) connects here once and receives
        push notifications without polling.  The connection is kept alive via
        25-second heartbeat comments that are invisible to the EventSource API
        but prevent proxy timeouts.

        Returns:
            A streaming ``text/event-stream`` :class:`flask.Response`.
        """
        user_id: str = session.get("username", "developer")
        q: queue.Queue = sse_manager.subscribe(user_id)

        def _frame(event: str, data: dict) -> str:
            """Serialise one SSE message according to the W3C EventSource spec."""
            try:
                payload = json.dumps(data, default=str)
            except (TypeError, ValueError) as exc:
                logger.warning("SSE frame serialisation error: %s", exc)
                payload = json.dumps({"error": "serialisation_error"})
            return f"event: {event}\ndata: {payload}\n\n"

        def generate():
            # Announce successful subscription
            yield _frame("connected", {"user_id": user_id})

            try:
                while True:
                    try:
                        # Block until an event arrives; yield green thread while waiting.
                        # With eventlet monkey-patching, queue.Queue is patched and this
                        # call cooperates with the event loop (does NOT block other requests).
                        item = q.get(timeout=25)

                    except queue.Empty:
                        # No event within 25 s → send a heartbeat comment.
                        # Comments start with ": " and are ignored by EventSource clients
                        # but keep the connection alive through HTTP proxies.
                        yield ": heartbeat\n\n"
                        continue

                    # Stop sentinel: server-side shutdown request
                    if sse_manager.is_stop(item):
                        yield _frame("disconnected", {"reason": "server_stop"})
                        return

                    try:
                        yield _frame(item["event"], item["data"])
                    except (KeyError, TypeError) as exc:
                        logger.warning("SSE malformed queue item: %s — item=%r", exc, item)

            except GeneratorExit:
                # Browser navigated away, tab closed, or explicit EventSource.close()
                logger.debug("SSE generator exit (client disconnected): user=%s", user_id)

            except Exception as exc:
                logger.error(
                    "SSE generator unexpected error: user=%s  error=%s",
                    user_id,
                    exc,
                    exc_info=True,
                )

            finally:
                # Always clean up; safe to call even if already unsubscribed
                sse_manager.unsubscribe(user_id, q)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                # Tell nginx (and nginx-like reverse proxies) not to buffer the response.
                # Transfer-Encoding is intentionally omitted: it is a hop-by-hop header
                # forbidden by PEP 3333 in WSGI applications (Waitress raises AssertionError).
                "X-Accel-Buffering": "no",
            },
        )

    @api_bp.get("/sse/status")
    def sse_status() -> dict:
        """Return diagnostic information about active SSE connections (developer endpoint).

        Returns:
            JSON with ``connected_users`` count and ``connection_count``.
        """
        return {
            "connected_users": len(sse_manager.connected_users()),
            "connection_count": sse_manager.connection_count(),
        }
