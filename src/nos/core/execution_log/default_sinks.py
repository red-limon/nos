"""
In-memory :class:`EventLogBuffer` factories for engine and :meth:`Node.run` / :meth:`Workflow.run`.

When ``exec_log`` is ``None``, use these helpers so buffer shape matches :meth:`WorkflowEngine.run_node`
(room-less, no DB) without duplicating ad-hoc constructors.
"""

from __future__ import annotations

import time
from typing import Any, Literal, TYPE_CHECKING

from .event_log_buffer import EventLogBuffer

if TYPE_CHECKING:
    pass

DebugMode = Literal["trace", "debug"]


def normalize_debug_mode(raw: str | None, *, default: DebugMode = "trace") -> DebugMode:
    """
    Normalize workflow/node ``debug_mode`` string flags (``trace`` | ``debug``).

    Non-interactive / batch runs use ``background=True`` on the engine instead of a separate mode value.
    """
    if raw is None:
        return default
    s = str(raw).lower().strip()
    if s not in ("trace", "debug"):
        raise ValueError(f"Invalid debug_mode {raw!r}. Use 'trace' or 'debug'.")
    return s  # type: ignore[return-value]


def create_default_workflow_exec_log(workflow_id: str) -> EventLogBuffer:
    execution_id = f"{workflow_id}_{int(time.time())}"
    return EventLogBuffer(execution_id=execution_id, workflow_id=workflow_id)


def create_default_node_exec_log(node: Any) -> EventLogBuffer:
    """Build a buffer for a standalone :class:`~nos.core.engine.node.node.Node` run (no workflow parent)."""
    execution_id = f"node_{node.node_id}_{int(time.time())}"
    return EventLogBuffer(
        execution_id=execution_id,
        node_id=node.node_id,
        workflow_id=None,
        module_path=node.__class__.__module__,
        class_name=node.__class__.__name__,
        shared_state={},
    )
