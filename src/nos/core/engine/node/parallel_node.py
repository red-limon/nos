"""
Parallel execution of workflow child nodes
========================================

This module provides :class:`ParallelNode`, a composite :class:`~nos.core.engine.node.node.Node`
that runs **multiple sibling nodes** from the **same parent workflow** concurrently,
then merges their writes back into the workflow's shared state.

When to use it
--------------
Use ``ParallelNode`` when independent steps can share a snapshot of workflow state,
each update a disjoint (or mergeable) subset of keys, and you want wall-clock overlap
via a thread pool instead of strict sequential links.

Requirements
------------
* **Parent workflow** — The node must be registered on a workflow with
  :meth:`nos.core.engine.workflow.workflow.Workflow.add_node`. That call sets ``node._workflow``;
  without it, execution fails fast with a clear metadata error.
* **Registered targets** — ``node_ids`` must refer to nodes already added to that workflow
  (same ``workflow_id`` graph). Unknown ids respect :attr:`ParallelNodeInputParams.on_error`.
* **State mappings** — Each child uses the workflow's per-node
  ``StateMapping`` (or identity mapping) to project shared state into local input and to
  map observable state back to shared keys.
* **Per-child input params** — Pass ``default_input_params=`` to
  :meth:`~nos.core.engine.workflow.workflow.Workflow.add_node` so each branch gets its own
  ``urls``, ``deep``, etc.; the parallel runner passes those defaults as ``input_params`` and
  calls ``node.run(..., output_format="json")`` for each child.

Inputs
------
Runtime behaviour is driven by :class:`ParallelNodeInputParams` (the
``input_params_schema``):

* **node_ids** — List of workflow node ids to run. Resolved from ``input_params`` first;
  if missing, from shared state keys ``node_ids`` or ``parallel_node_ids``.
* **merge_strategy** — How to combine per-child state deltas:
  ``last_wins``, ``first_wins``, ``combine`` (recursive dict merge), or
  ``error_on_conflict`` (fail if the same key is written by more than one child).
* **on_error** — ``fail_fast`` aborts on the first child exception; ``continue_on_error``
  skips failed children when possible and records errors in metadata.

Execution model
---------------
For each child, the runner copies the current workflow state, maps it to the child's
view, invokes :meth:`~nos.core.engine.node.node.Node.run` in a worker thread, then maps the
child's observable state back to shared keys. Only keys that actually change relative to
the snapshot are kept as deltas, reducing accidental overwrites. Results are merged
according to ``merge_strategy``, and the **shared ``state`` dict passed into**
``_do_execute`` is **updated in place** so the outer engine sees the combined outcome.

Example
-------
Inside ``Workflow.define()`` (or any setup before ``prepare()`` / execution), every child
must be passed to :meth:`~nos.core.engine.workflow.workflow.Workflow.add_node` so it exists in
``workflow._nodes`` under its ``node_id``. The engine does **not** require a particular
call order among siblings—only that those ids are present before the parallel step runs.
**Recommended style:** add **child nodes first**, then **ParallelNode**, so the file reads
as “declare workers, then the step that fans out to them”.

Illustrative snippet (workflow class and concrete node types omitted)::

    from nos.core.engine.node.parallel_node import ParallelNode
    # from mypkg.nodes import FetchNodeA, FetchNodeB  # example concrete Node subclasses

    def define(self):
        # 1) Register each branch target (ids must match ParallelNode.node_ids later).
        self.add_node(
            FetchNodeA(node_id="http_a"),
            default_input_params={"timeout": 30},  # example; keys depend on each node's schema
        )
        self.add_node(
            FetchNodeB(node_id="http_b"),
            default_input_params={"limit": 100},
        )

        # 2) Register the composite; add_node sets ``_workflow`` on the instance.
        self.add_node(ParallelNode(node_id="parallel_fetch"))

        # 3) Wire links / entry as usual so execution reaches ``parallel_fetch``.

    # When ``parallel_fetch`` runs, pass the same ids via input_params or shared state:
    # input_params={
    #     "node_ids": ["http_a", "http_b"],
    #     "merge_strategy": "last_wins",
    #     "on_error": "fail_fast",
    # }
    # or set state keys ``node_ids`` / ``parallel_node_ids`` before that step.

See also :class:`ParallelNode`, :class:`ParallelNodeInputParams`, and
:meth:`nos.core.engine.workflow.workflow.Workflow.add_node`.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Literal, Union
from pydantic import BaseModel, Field

from .node import Node, NodeOutput
from ...execution_log.event_log_buffer import CancellationError, EventLogBuffer
from ...execution_log.logger_factory import build_event_log
from ..workflow.state_mapping import create_identity_mapping


MergeStrategy = Literal["last_wins", "first_wins", "combine", "error_on_conflict"]
OnErrorStrategy = Literal["fail_fast", "continue_on_error"]


class ParallelNodeInputParams(BaseModel):
    """Input params for ParallelNode."""

    node_ids: List[str] = Field(
        default_factory=list,
        description="List of workflow node IDs to run in parallel",
    )
    merge_strategy: MergeStrategy = Field(
        default="last_wins",
        description="How to merge state updates: last_wins, first_wins, combine, error_on_conflict",
    )
    on_error: OnErrorStrategy = Field(
        default="fail_fast",
        description="fail_fast: stop on first error. continue_on_error: collect errors and proceed",
    )


class ParallelNode(Node):
    """
    Composite node that runs N child nodes in parallel.

    Child nodes must belong to the same workflow. Uses ThreadPoolExecutor.
    Merge strategies: last_wins, first_wins, combine, error_on_conflict.
    """

    def __init__(
        self,
        node_id: str = "parallel",
        name: Optional[str] = None,
    ):
        super().__init__(node_id=node_id, name=name or "Parallel")

    @property
    def input_params_schema(self):
        return ParallelNodeInputParams

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        # node_ids can come from params (form/API) or from workflow state (StateMapping)
        node_ids: List[str] = (
            params_dict.get("node_ids")
            or state.get("node_ids")
            or state.get("parallel_node_ids")
            or []
        )
        merge_strategy: MergeStrategy = params_dict.get("merge_strategy", "last_wins")
        on_error: OnErrorStrategy = params_dict.get("on_error", "fail_fast")

        if not node_ids:
            return NodeOutput(
                output={},
                metadata={"error": "node_ids is required and must be non-empty"},
            )

        workflow = getattr(self, "_workflow", None)
        if workflow is None:
            return NodeOutput(
                output={},
                metadata={"error": "ParallelNode requires parent workflow (add via workflow.add_node)"},
            )

        # Resolve nodes and mappings
        nodes_to_run: List[tuple] = []
        for nid in node_ids:
            node = workflow.get_node(nid)
            if node is None:
                if on_error == "fail_fast":
                    return NodeOutput(
                        output={},
                        metadata={"error": f"Node '{nid}' not found in workflow"},
                    )
                continue
            mapping = workflow.get_node_mapping(nid) or create_identity_mapping()
            nodes_to_run.append((nid, node, mapping))

        if not nodes_to_run:
            return NodeOutput(
                output={},
                metadata={"error": "No valid nodes to run", "requested": node_ids},
            )

        parent_log = getattr(self, "_exec_log", None)
        shared_stop = getattr(parent_log, "_stop_event", None) if parent_log else None
        # Same fan-in as the engine uses for sequential nodes: workflow root buffer is
        # typically ``parent_log._append_to``, not this node's local ``_event_buffer``.
        parent_fanout = getattr(parent_log, "_append_to", None) if parent_log else None
        if parent_fanout is None and parent_log is not None:
            parent_fanout = getattr(parent_log, "_event_buffer", None)
        parent_room = getattr(parent_log, "_room", None) if parent_log else None
        execution_id = getattr(parent_log, "execution_id", "") if parent_log else ""

        def _child_exec_log(nid: str, node: Node, shared_state: dict) -> EventLogBuffer:
            mod = node.__class__.__module__
            cls_name = node.__class__.__name__
            try:
                return build_event_log(
                    execution_id=execution_id or "parallel_child",
                    node_id=nid,
                    workflow_id=workflow.workflow_id,
                    module_path=mod,
                    class_name=cls_name,
                    shared_state=dict(shared_state),
                    room=parent_room,
                    append_to=parent_fanout,
                    stop_event=shared_stop,
                )
            except RuntimeError:
                return EventLogBuffer(
                    execution_id=execution_id or "parallel_child",
                    node_id=nid,
                    workflow_id=workflow.workflow_id,
                    module_path=mod,
                    class_name=cls_name,
                    shared_state=dict(shared_state),
                    append_to=parent_fanout,
                    stop_event=shared_stop,
                )

        # Run in parallel
        results: Dict[str, Dict[str, Any]] = {}  # node_id -> state_updates
        errors: Dict[str, str] = {}  # node_id -> error_msg

        def run_one(nid: str, node: Node, mapping) -> tuple:
            try:
                initial_state = dict(workflow.state)
                node_input = mapping.map_to_node(initial_state)
                observable_state = dict(node_input)
                defaults = workflow.get_node_default_input_params(nid)
                input_params = {**defaults}
                run_request = {
                    "node_id": nid,
                    "state": dict(node_input),
                    "input_params": input_params,
                    "output_format": "json",
                }
                child_log = _child_exec_log(nid, node, initial_state)
                node.set_exec_log(child_log)
                try:
                    exec_result = node.run(
                        observable_state,
                        input_params,
                        request=run_request,
                        output_format="json",
                    )
                finally:
                    node.set_exec_log(None)
                if getattr(exec_result, "status", None) == "cancelled":
                    return (nid, {"updates": {}, "error": None, "cancelled": True})
                full_updates = mapping.map_to_shared(observable_state)
                # Only keep keys that actually changed (avoids one child overwriting another with empty)
                state_updates = {
                    k: v
                    for k, v in full_updates.items()
                    if initial_state.get(k) != v or k not in initial_state
                }
                return (nid, {"updates": state_updates, "error": None})
            except Exception as e:
                return (nid, {"updates": {}, "error": str(e)})

        with ThreadPoolExecutor(max_workers=len(nodes_to_run)) as executor:
            futures = {
                executor.submit(run_one, nid, node, mapping): nid
                for nid, node, mapping in nodes_to_run
            }
            for future in as_completed(futures):
                if parent_log is not None and parent_log.is_stop_requested():
                    for f in futures:
                        f.cancel()
                    raise CancellationError("ParallelNode stopped (execution cancel requested)")
                nid, data = future.result()
                if data.get("cancelled"):
                    for f in futures:
                        f.cancel()
                    raise CancellationError(
                        f"Parallel branch {nid!r} cancelled (cooperative stop)"
                    )
                if data["error"]:
                    errors[nid] = data["error"]
                    if on_error == "fail_fast":
                        # Cancel remaining and return
                        for f in futures:
                            f.cancel()
                        return NodeOutput(
                            output={},
                            metadata={"error": data["error"], "failed_node": nid},
                        )
                else:
                    results[nid] = data["updates"]

        # Merge state updates
        merged = self._merge_updates(
            [results[nid] for nid, _, _ in nodes_to_run if nid in results],
            merge_strategy,
        )
        if isinstance(merged, str):
            return NodeOutput(output={}, metadata={"error": merged})

        # Mutate state so engine's map_to_shared picks up the updates (do NOT call workflow.apply_state_updates)
        state.update(merged)

        return NodeOutput(
            output=merged,
            metadata={
                "node_ids": node_ids,
                "merge_strategy": merge_strategy,
                "ran": list(results.keys()),
                "errors": errors if errors else None,
            },
        )

    def _merge_updates(
        self,
        updates_list: List[Dict[str, Any]],
        strategy: MergeStrategy,
    ) -> Union[Dict[str, Any], str]:
        """Merge multiple state update dicts. Returns merged dict or error string."""
        if not updates_list:
            return {}

        if strategy == "last_wins":
            out = {}
            for u in updates_list:
                out.update(u)
            return out

        if strategy == "first_wins":
            out = {}
            for u in reversed(updates_list):
                for k, v in u.items():
                    if k not in out:
                        out[k] = v
            return out

        if strategy == "combine":
            out = {}
            for u in updates_list:
                out = self._deep_merge(out, u)
            return out

        if strategy == "error_on_conflict":
            all_keys: Dict[str, int] = {}
            for u in updates_list:
                for k in u:
                    all_keys[k] = all_keys.get(k, 0) + 1
            conflicts = [k for k, c in all_keys.items() if c > 1]
            if conflicts:
                return f"Conflict on keys: {conflicts}. Use merge_strategy other than error_on_conflict."
            out = {}
            for u in updates_list:
                out.update(u)
            return out

        return {}

    def _deep_merge(self, a: dict, b: dict) -> dict:
        """Recursively merge b into a. Values from b override a for non-dict values."""
        result = dict(a)
        for k, v in b.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result
