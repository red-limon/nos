"""SSE (Server-Sent Events) service package.

Exports the module-level :data:`sse_manager` singleton used by both the
Flask streaming endpoint and platform EventLog to fan-out execution
completion events to connected browser tabs.
"""

from .manager import SseManager, sse_manager

__all__ = ["SseManager", "sse_manager"]
