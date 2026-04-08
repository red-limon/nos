"""
Failure policies for workflow graph routing (:class:`~nos.core.engine.link.link.Link`).

- :class:`OnNodeFailure` — when the **previous node** ended with a non-success status, whether to
  still evaluate link routing or stop the workflow immediately.
- :class:`OnRouteFailure` — when :meth:`~nos.core.engine.link.link.Link.route` / ``_route_impl`` raises,
  whether to try the next outgoing link or stop the workflow.
"""

from __future__ import annotations

from enum import Enum


class OnNodeFailure(str, Enum):
    """
    Policy for outgoing links when the node that just ran did not complete successfully.

    Configured per node on :meth:`nos.core.engine.workflow.workflow.Workflow.add_node`.
    """

    CONTINUE_ROUTING = "continue_routing"
    """Evaluate :meth:`~nos.core.engine.link.link.Link.route` so links can branch to recovery or stop explicitly."""

    ABORT_WORKFLOW = "abort_workflow"
    """Skip routing; workflow stops at this node (no ``next_node_id``)."""


class OnRouteFailure(str, Enum):
    """
    Policy when link routing raises an exception.

    Set on each :class:`~nos.core.engine.link.link.Link` instance (constructor or subclass).
    """

    TRY_NEXT_LINK = "try_next_link"
    """Log and attempt the next outgoing link from the same node (legacy engine behaviour)."""

    ABORT_WORKFLOW = "abort_workflow"
    """Stop the workflow; routing returns no next node."""


def node_execution_failed_for_routing(result: object) -> bool:
    """
    True if *result* (typically :class:`~nos.core.engine.node.node.NodeExecutionResult`) indicates
    a failed node run for routing purposes.

    ``cancelled`` is **not** treated as failure here (the workflow engine handles cancel before links).
    """
    if result is None:
        return True
    status = getattr(result, "status", None)
    if status is None:
        return True
    if status == "completed":
        return False
    if status == "cancelled":
        return False
    return True
