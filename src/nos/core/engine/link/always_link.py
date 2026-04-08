"""AlwaysLink — unconditional routing to the target node."""

from typing import Any, Dict, Optional

from .link import Link, LinkResult


class AlwaysLink(Link):
    """
    Link that always routes to the target node (returns True).

    Use this for simple sequential workflows where no conditional logic is needed.
    """

    def _route_impl(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """Always continue to the next node."""
        return LinkResult(
            next_node_id=self.to_node_id,
            should_continue=True,
            metadata={"link_type": "always"},
        )
