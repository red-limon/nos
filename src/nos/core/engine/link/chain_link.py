"""ChainLink — linear path from → via… → terminal."""

from typing import Any, Dict, List, Optional

from .failure_policy import OnRouteFailure
from .link import Link, LinkResult


class ChainLink(Link):
    """
    Link that defines a linear path: from → via[0] → ... → via[n] → terminal.

    A single ChainLink replaces multiple AlwaysLinks for sequential pipelines.
    The engine routes hop-by-hop until the terminal node.
    """

    def __init__(
        self,
        link_id: str,
        from_node_id: str,
        terminal_node_id: str,
        via: Optional[List[str]] = None,
        name: str = None,
        *,
        on_route_failure: OnRouteFailure = OnRouteFailure.TRY_NEXT_LINK,
    ):
        """
        Initialize chain link.

        Args:
            link_id: Unique identifier for this link
            from_node_id: First node in the chain
            terminal_node_id: Last node (destination)
            via: Optional list of intermediate node IDs (in order)
            name: Human-readable name (defaults to link_id)
        """
        # Base Link expects to_node_id; for ChainLink we use first hop
        via_list = via or []
        path = [from_node_id] + via_list + [terminal_node_id]
        first_hop = path[1] if len(path) > 1 else terminal_node_id
        super().__init__(
            link_id=link_id,
            from_node_id=from_node_id,
            to_node_id=first_hop,
            name=name or link_id,
            on_route_failure=on_route_failure,
        )
        self.terminal_node_id = terminal_node_id
        self.via = via_list
        self._path = path

    @property
    def path(self) -> List[str]:
        """Full path: [from, via..., terminal]."""
        return self._path

    def _route_impl(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """Route to next node in the chain based on current position."""
        if not current_node_id or current_node_id not in self._path:
            return LinkResult(
                next_node_id=None,
                should_continue=False,
                metadata={"link_type": "chain", "reason": "current_node_not_in_path"},
            )
        idx = self._path.index(current_node_id)
        if idx + 1 >= len(self._path):
            return LinkResult(
                next_node_id=None,
                should_continue=False,
                metadata={"link_type": "chain", "reason": "at_terminal"},
            )
        next_id = self._path[idx + 1]
        return LinkResult(
            next_node_id=next_id,
            should_continue=True,
            metadata={"link_type": "chain", "path": self._path},
        )
