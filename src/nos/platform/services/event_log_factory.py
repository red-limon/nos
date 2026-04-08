"""
Register the default :class:`~nos.platform.execution_log.event_log.EventLog` factory.

Call :func:`register_default_event_log_factory` once from :func:`nos.platform.app.create_app`
so :func:`nos.core.execution_log.logger_factory.build_event_log` resolves for engine paths
that need audit and/or Socket.IO (see :mod:`nos.core.execution_log.logger_factory`).
"""

from __future__ import annotations

from typing import Any


def _default_event_log_factory(**kwargs: Any):
    from nos.platform.execution_log.event_log import EventLog

    return EventLog(**kwargs)


def register_default_event_log_factory() -> None:
    """Wire the platform default :class:`~nos.platform.execution_log.event_log.EventLog` builder into ``nos.core``.

    Call once per ``create_app()`` so every app instance registers the same constructor.
    """
    from nos.core.execution_log.logger_factory import register_event_log_factory

    register_event_log_factory(_default_event_log_factory)
