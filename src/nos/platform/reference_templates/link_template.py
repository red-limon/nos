"""
Minimal example links: branch on ``state["condition"]``, or loop while ``iteration < max_iterations``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from nos.core.engine.base import Link, LinkResult
from nos.core.engine.link.failure_policy import OnRouteFailure


class ConditionalLink(Link):
    """If ``state["condition"]`` is truthy, go to ``to_node_id``; else go to ``else_id``."""

    def __init__(
        self,
        link_id: str,
        from_node_id: str,
        to_node_id: str,
        else_id: str,
        *,
        name: Optional[str] = None,
        on_route_failure: OnRouteFailure = OnRouteFailure.TRY_NEXT_LINK,
    ) -> None:
        super().__init__(link_id, from_node_id, to_node_id, name=name, on_route_failure=on_route_failure)
        self.else_id = else_id

    def _route_impl(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        if state.get("condition"):
            return LinkResult(next_node_id=self.to_node_id, should_continue=True, metadata={})
        return LinkResult(next_node_id=self.else_id, should_continue=True, metadata={})


class LoopLink(Link):
    """While ``state["iteration"] < max_iterations``, go to ``to_node_id``; otherwise stop (self-loop pattern)."""

    def __init__(
        self,
        link_id: str,
        from_node_id: str,
        to_node_id: str,
        max_iterations: int = 3,
        *,
        name: Optional[str] = None,
        on_route_failure: OnRouteFailure = OnRouteFailure.TRY_NEXT_LINK,
    ) -> None:
        super().__init__(link_id, from_node_id, to_node_id, name=name, on_route_failure=on_route_failure)
        self.max_iterations = max_iterations

    def _route_impl(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        i = int(state.get("iteration", 0))
        if i < self.max_iterations:
            return LinkResult(next_node_id=self.to_node_id, should_continue=True, metadata={})
        return LinkResult(next_node_id=None, should_continue=False, metadata={})
