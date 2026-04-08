"""
Link base — routing between nodes (template method).

Concrete strategies: :class:`~nos.core.engine.link.always_link.AlwaysLink`,
:class:`~nos.core.engine.link.chain_link.ChainLink`.

Subclasses implement :meth:`_route_impl` only; :meth:`route` applies
:class:`OnNodeFailure` / :class:`OnRouteFailure` policies.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from .failure_policy import (
    OnNodeFailure,
    OnRouteFailure,
    node_execution_failed_for_routing,
)
if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class LinkResult:
    """Result from link routing logic."""
    next_node_id: Optional[str] = None
    should_continue: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class Link(ABC):
    """
    Base class for workflow links.

    Override :meth:`_route_impl` in subclasses. :meth:`route` applies failure policies
    (:class:`OnNodeFailure` from the workflow for the source node, :class:`OnRouteFailure` on this link).
    """

    def __init__(
        self,
        link_id: str,
        from_node_id: str,
        to_node_id: str,
        name: str = None,
        *,
        on_route_failure: OnRouteFailure = OnRouteFailure.TRY_NEXT_LINK,
    ):
        self.link_id = link_id
        self.from_node_id = from_node_id
        self.to_node_id = to_node_id
        self.name = name or link_id
        self.on_route_failure = on_route_failure
        self._exec_log = None
        #: Set by :meth:`nos.core.engine.workflow.workflow.Workflow.add_link` for policy lookup.
        self._workflow: Any = None

    def route(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """
        Apply :class:`OnNodeFailure`, then delegate to :meth:`_route_impl`, then handle routing exceptions
        per :attr:`on_route_failure`.

        ``last_output`` is normally a :class:`~nos.core.engine.node.node.NodeExecutionResult` from the
        previous ``node.run()`` (the workflow engine passes it through).
        """
        from_id = current_node_id if current_node_id is not None else self.from_node_id
        wf = getattr(self, "_workflow", None)
        if wf is not None and node_execution_failed_for_routing(last_output):
            pol = wf.get_on_node_failure(from_id)
            if pol == OnNodeFailure.ABORT_WORKFLOW:
                return LinkResult(
                    next_node_id=None,
                    should_continue=False,
                    metadata={
                        "policy": "on_node_failure",
                        "reason": "abort_workflow",
                    },
                )

        try:
            return self._route_impl(state, last_output, current_node_id)
        except Exception as e:
            logger.error("Link %s routing error: %s", self.link_id, e, exc_info=True)
            if self._exec_log:
                try:
                    self._exec_log.log(
                        "error",
                        f"Link {self.link_id} routing failed: {e}",
                        link_id=self.link_id,
                    )
                except Exception:
                    pass
            if self.on_route_failure == OnRouteFailure.ABORT_WORKFLOW:
                return LinkResult(
                    next_node_id=None,
                    should_continue=False,
                    metadata={
                        "policy": "on_route_failure",
                        "reason": "abort_workflow",
                        "error": str(e),
                    },
                )
            raise

    @abstractmethod
    def _route_impl(
        self,
        state: Dict[str, Any],
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        """Subclass routing logic (unconditional, conditional, chain hop, …)."""
        raise NotImplementedError

    def set_exec_log(self, exec_log):
        """Set the execution log sink for this link (same instance as the workflow)."""
        self._exec_log = exec_log

    def log(self, level: str, message: str, **kwargs):
        """Emit a log entry via the workflow exec log."""
        if self._exec_log:
            self._exec_log.log(level, message, link_id=self.link_id, **kwargs)
