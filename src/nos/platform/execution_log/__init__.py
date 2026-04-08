"""
Web-oriented execution log: realtime :class:`EventLog` and interactive request registry.

Concrete class :class:`EventLog` extends :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer`.
The engine obtains instances via :func:`nos.core.execution_log.logger_factory.build_event_log`
after :func:`nos.platform.services.event_log_factory.register_default_event_log_factory`.
"""

from .event_log import EventLog
from .registry import EventLogRegistry, _event_log_registry

__all__ = ["EventLog", "EventLogRegistry", "_event_log_registry"]
