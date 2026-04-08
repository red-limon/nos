"""
Test workflow: ParallelNode + two PoliteScrapeNode branches (different seeds and depth).

Each scrape node is registered with ``default_input_params`` on :meth:`Workflow.add_node`
so the engine and :class:`ParallelNode` merge ``urls`` / ``deep`` (and throttle) when they
invoke the child.

**Risultati paralleli senza collisioni (dict annidato + ``combine``).**
Un dict annidato, es. ``parallel_scrape_results: { "scrape_a": {...}, "scrape_b": {...} }``,
così ogni figlio aggiorna solo la sua sottochiave → ``merge_strategy="combine"`` fa deep merge
del dict esterno e i rami non si pestano i piedi. :class:`PoliteScrapeParallelBranchNode`
è un sottile wrapper su :class:`PoliteScrapeNode` che copia il payload JSON dello scrape
(``output["data"]``) sotto quella sottochiave nello stato osservabile, così
:meth:`ParallelNode._merge_updates` unisce i delta in modo ricorsivo sulla chiave
``parallel_scrape_results``.

Workflow ID: ``parallel_polite_scrape_test``

Register::

    reg workflow parallel_polite_scrape_test ParallelPoliteScrapeTest \\
        nos.plugins.workflows.test.parallel_nodes_test

Run (example)::

    run workflow db parallel_polite_scrape_test
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import ParallelNode, Workflow
from nos.plugins.nodes.web_scraper.polite_scrape import PoliteScrapeNode


class PoliteScrapeParallelBranchNode(PoliteScrapeNode):
    """
    Wrapper: dopo lo scrape, copia ``output["data"]`` in
    ``state[parallel_results_state_key][result_slot_key]`` per un merge parallelo con
    ``combine`` (deep merge sul dict esterno).
    """

    def __init__(
        self,
        node_id: str = "polite_scrape",
        name: Optional[str] = None,
        *,
        parallel_results_state_key: str = "parallel_scrape_results",
        result_slot_key: Optional[str] = None,
    ) -> None:
        super().__init__(node_id=node_id, name=name)
        self._parallel_results_state_key = parallel_results_state_key
        self._result_slot_key = result_slot_key or node_id

    def _do_execute(self, state_dict: dict, params_dict: dict):
        out = super()._do_execute(state_dict, params_dict)
        raw = out.output if isinstance(out.output, dict) else {}
        inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        prev = state_dict.get(self._parallel_results_state_key)
        bucket: dict[str, Any] = dict(prev) if isinstance(prev, dict) else {}
        bucket[self._result_slot_key] = inner
        state_dict[self._parallel_results_state_key] = bucket
        return out


class ParallelPoliteScrapeTestState(BaseModel):
    """Shared state: merged nested scrape results (branch ids are fixed on ParallelNode via input defaults)."""

    parallel_scrape_results: dict[str, Any] = Field(
        default_factory=dict,
        description='Per-branch scrape payloads under e.g. {"scrape_a": {...}, "scrape_b": {...}}',
    )


class ParallelPoliteScrapeTest(Workflow):
    """
    Entry → ParallelNode runs two polite scrapes in parallel (different URLs and depth).

    - ``scrape_a``: ``https://example.com``, shallow (``deep`` = 1).
    - ``scrape_b``: ``https://example.org``, deeper BFS (``deep`` = 2).

    Uses ``merge_strategy="combine"`` so each branch only fills its slot inside
    ``parallel_scrape_results``. Child ids are passed via ``default_input_params``
    ``node_ids`` on the :class:`ParallelNode` (same idea as ``input_params`` in the
    :mod:`parallel_node` docstring); alternatively you could drive them from shared
    state keys ``node_ids`` / ``parallel_node_ids`` when you need a dynamic list.
    """

    workflow_id = "parallel_polite_scrape_test"
    name = "Test · Parallel PoliteScrape (2 branches)"

    @property
    def state_schema(self):
        return ParallelPoliteScrapeTestState

    def define(self) -> None:
        self.add_node(
            PoliteScrapeParallelBranchNode(node_id="scrape_a", name="Scrape example.com (deep=1)"),
            default_input_params={
                "urls": ["https://www.panthera.it"],
                "deep": 3,
                "min_interval_seconds": 2.0,
            },
        )
        self.add_node(
            PoliteScrapeParallelBranchNode(node_id="scrape_b", name="Scrape example.org (deep=2)"),
            default_input_params={
                "urls": ["https://www.inps.it"],
                "deep": 1,
                "min_interval_seconds": 2.0,
            },
        )

        self.add_node(
            ParallelNode(node_id="parallel", name="Parallel polite scrapes"),
            default_input_params={
                "node_ids": ["scrape_a", "scrape_b"],
                "merge_strategy": "combine",
            },
        )

        self.set_entry_node("parallel")
