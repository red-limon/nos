"""
Workflow - Container for nodes and links with lifecycle control.
"""

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Type, Union, overload
from pydantic import BaseModel, ValidationError as PydanticValidationError

from ...execution_log.workflow_run_hooks import WorkflowRunEventType, attach_workflow_run_hooks_bus

from ..node import Node
from ..reserved_keys import validate_reserved_keys
from .node_workflow import NodeWorkflow
from ..link import ChainLink, Link
from ..link.failure_policy import OnNodeFailure

logger = logging.getLogger(__name__)

# Import StateMapping for workflow node mappings
try:
    from .state_mapping import StateMapping
except ImportError:
    StateMapping = None


class _NullWorkflowExecLog:
    """
    No-op sink for standalone/CLI workflow execution when no buffer is attached.
    Prevents AttributeError on ``self.exec_log.log()``. Logs a one-time warning on first use.
    """
    _warned: bool = False

    def _warn_once(self):
        if not _NullWorkflowExecLog._warned:
            _NullWorkflowExecLog._warned = True
            logger.warning(
                "Channel is None (standalone/CLI execution). "
                "exec_log.log() is no-op. For full interaction, run via Console."
            )

    def log_custom(
        self,
        level: str,
        message: str,
        *,
        event: str = "Logging event",
        include_base_fields: bool = True,
        **kwargs,
    ):
        self._warn_once()

    def log(
        self,
        level: str,
        message: str,
        *,
        event: str = "Logging event",
        include_base_fields: bool = True,
        **kwargs,
    ):
        self.log_custom(
            level,
            message,
            event=event,
            include_base_fields=include_base_fields,
            **kwargs,
        )


_NULL_WORKFLOW_EXEC_LOG = _NullWorkflowExecLog()


class WorkflowExecLog:
    """
    Public execution-log API exposed to Workflow subclasses.

    Use :meth:`log` for custom lines; the engine and base :class:`Workflow` hooks use the same
    :meth:`log` API on the raw sink (no separate ``log_*`` helpers on the buffer for orchestration).

    Use ``self.exec_log`` inside Workflow subclass methods.
    """

    def __init__(self, sink):
        self._inner = sink

    def log(
        self,
        level: str,
        message: str,
        *,
        event: str = "Logging event",
        include_base_fields: bool = True,
        **kwargs,
    ):
        """
        Write a custom execution-log line from within a workflow (same contract as :class:`~nos.core.engine.node.node.NodeExecLog.log`).

        Args:
            level: Log level (``debug``, ``info``, ``warning``, ``error``).
            message: Log message.
            event: Logical event type on :class:`~nos.core.execution_log.events.CustomEvent`.
            include_base_fields: If True (default), payload includes execution context.
            **kwargs: Additional fields on the event payload.
        """
        self._inner.log(
            level,
            message,
            event=event,
            include_base_fields=include_base_fields,
            **kwargs,
        )


class WorkflowStatus(str, Enum):
    """Workflow execution status."""
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    PAUSED = "paused"


@dataclass
class WorkflowOutput:
    """
    Renderable output from a workflow (mirrors :class:`~nos.core.engine.node.node.NodeOutput`).

    Use this shape when a workflow (or the engine) exposes only the primary payload:

    - ``output``: dict with keys ``output_format`` (str) and ``data`` (Any), same contract as nodes.
    - ``metadata``: optional workflow-level extras, validated by ``metadata_schema`` when set.
    """

    output: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResponseData:
    """
    Nested under :class:`WorkflowExecutionResult` (mirrors :class:`~nos.core.engine.node.node.NodeResponseData`).

    - ``output``: ``{'output_format': str, 'data': Any}`` — effective format and renderable content.
    - ``metadata``: validated workflow metadata from :meth:`Workflow.get_metadata`.
    """

    output: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecutionResult:
    """
    Full result of a workflow run (mirrors :class:`~nos.core.engine.node.node.NodeExecutionResult`).

    Primary renderable content lives in ``response.output`` (``output_format`` + ``data``).
    ``state`` is the final raw shared state; ``initial_state`` is the snapshot before the run.
    """

    execution_id: str
    workflow_id: str
    module_path: str
    class_name: str
    command: str
    status: str  # "success" | "error" | "cancelled"
    response: WorkflowResponseData
    state: Dict[str, Any]
    state_changed: Dict[str, Dict[str, Any]]
    initial_state: Dict[str, Any]
    started_at: str
    ended_at: str
    message: Optional[str] = None
    duration: float = 0.0
    node_ids_executed: List[str] = field(default_factory=list)
    event_logs: list = field(default_factory=list)


class Workflow(ABC):
    """
    Abstract base class for workflows.

    A workflow defines:
    - Sequence of nodes
    - Links between nodes
    - Shared mutable state
    - State schema (for validation)
    - Lifecycle hooks :meth:`_on_start` (before :meth:`prepare`, raw ``initial_state`` like :meth:`~nos.core.engine.node.node.Node._on_start` + ``request``), then :meth:`_on_init` via :meth:`prepare`; when the platform shows the **initial shared-state** form, :meth:`_on_input` runs after :meth:`exec_log.request_and_wait` returns (same role as :meth:`~nos.core.engine.node.node.Node._on_input` for the node debug form); during the graph, :meth:`_on_state_changed`, :meth:`_on_link_decision`, :meth:`_on_link_error`; terminal completion mirrors :class:`~nos.core.engine.node.node.Node`: :meth:`_on_error` emits ``workflow.error`` then :meth:`_on_end` with ``level="error"``; :meth:`_on_end` alone closes successful or cancelled runs (``workflow.end`` → ``workflow_execution_result`` on the sink); then :meth:`_on_stop` for engine teardown where applicable; …
    - Structured lifecycle for the workflow run goes through a scoped per-run hook bus (see :meth:`set_exec_log`), like :class:`~nos.core.engine.node.node.Node`; adapters forward to the execution sink.

    Resolve a canonical instance with :meth:`load` (registry or module), then run the graph with :meth:`run`
    (delegates to the shared :class:`~nos.core.engine.workflow_engine.WorkflowEngine`) or call
    :meth:`~nos.core.engine.workflow_engine.WorkflowEngine.execute_sync` when you need a platform log.
    :meth:`prepare` and workflow lifecycle hooks are normally invoked inside the engine.
    """

    def __init__(self, workflow_id: str = None, name: str = None):
        """
        Initialize workflow.

        Args:
            workflow_id: Unique identifier for this workflow. If None, read from
                         class attribute workflow_id (required on subclass).
            name: Human-readable name (defaults to workflow_id or class attribute name)
        """
        if workflow_id is None:
            if not hasattr(self.__class__, "workflow_id"):
                raise TypeError(
                    f"{self.__class__.__name__} must define workflow_id as a class attribute, "
                    "or pass workflow_id to __init__"
                )
            workflow_id = self.__class__.workflow_id
        self.workflow_id = workflow_id
        self.name = name or getattr(self.__class__, "name", None) or workflow_id
        self._nodes: Dict[str, Node] = {}
        self._node_mappings: Dict[str, Optional['StateMapping']] = {}  # Override mappings per node
        self._node_default_input_params: Dict[str, Dict[str, Any]] = {}
        #: Per-node policy when the node run finishes with an error status (see :class:`~nos.core.engine.link.failure_policy.OnNodeFailure`).
        self._node_on_node_failure: Dict[str, OnNodeFailure] = {}
        self._links: Dict[str, Link] = {}
        #: Set when :meth:`_on_error` runs so outer handlers (e.g. background thread) skip duplicate teardown.
        self._workflow_error_already_handled: bool = False
        self._entry_node_id: Optional[str] = None
        self._status = WorkflowStatus.IDLE
        self._state: Dict[str, Any] = {}
        self._exec_log: Optional[Any] = None  # EventLogBuffer or platform EventLog (like Node)
        self._run_event_hook = None  # EventHookManager: per run when exec_log is set; cleared on unset
        self._load_spec: Optional[Dict[str, Any]] = None  # Set by :meth:`load`

    @classmethod
    def load(
        cls,
        mode: Literal["dev", "prod"],
        workflow_id: str,
        *,
        module_path: Optional[str] = None,
        class_name: Optional[str] = None,
        **kwargs: Any,
    ) -> "Workflow":
        """
        Resolve a workflow from the registry (``prod``) or from a Python module (``dev``).

        ``workflow_id`` is always required: in ``prod`` it is the registry lookup key; in ``dev`` it is passed
        to the workflow constructor (with the usual class-attribute fallback in :meth:`__init__` if omitted there).

        In ``prod``, ``module_path`` and ``class_name`` are ignored (warning if set).
        In ``dev``, ``module_path`` and ``class_name`` are required.
        """
        from ..registry import workflow_registry

        if not workflow_id or not str(workflow_id).strip():
            raise ValueError("Workflow.load: workflow_id is required and cannot be empty.")

        if mode == "prod":
            if module_path or class_name:
                logger.warning(
                    "Workflow.load(prod): module_path and class_name are ignored when loading from the registry."
                )
            wf = workflow_registry.create_workflow_instance(workflow_id, **kwargs)
            if wf is None:
                raise ValueError(f"Workflow.load(prod): no workflow registered for workflow_id={workflow_id!r}.")
            if not isinstance(wf, cls):
                raise TypeError(
                    f"Workflow.load: registry workflow {workflow_id!r} is {type(wf).__name__}, expected instance of {cls.__name__}."
                )
            wf._load_spec = {"mode": "prod", "workflow_id": workflow_id}
            return wf

        if mode == "dev":
            if not module_path or not str(module_path).strip():
                raise ValueError("Workflow.load(dev): module_path is required.")
            if not class_name or not str(class_name).strip():
                raise ValueError("Workflow.load(dev): class_name is required.")
            try:
                module = importlib.import_module(module_path)
                wf_class = getattr(module, class_name)
            except (ImportError, AttributeError) as e:
                raise ValueError(
                    f"Workflow.load(dev): failed to load {module_path!r}.{class_name!r}: {e}"
                ) from e
            if not isinstance(wf_class, type) or not issubclass(wf_class, Workflow):
                raise TypeError(
                    f"Workflow.load(dev): {module_path}.{class_name} must be a Workflow subclass, got {wf_class!r}."
                )
            if not issubclass(wf_class, cls):
                raise TypeError(
                    f"Workflow.load(dev): loaded class {wf_class.__name__} is not a subclass of {cls.__name__}."
                )
            wf = wf_class(workflow_id=workflow_id, **kwargs)
            wf._load_spec = {
                "mode": "dev",
                "workflow_id": workflow_id,
                "module_path": module_path,
                "class_name": class_name,
            }
            return wf

        raise ValueError(f"Workflow.load: invalid mode={mode!r}; use 'dev' or 'prod'.")

    @property
    def exec_log(self) -> WorkflowExecLog:
        """
        Public execution-log API for Workflow subclasses (prefer :meth:`WorkflowExecLog.log`).
        When unset (standalone/CLI), returns a no-op wrapper that logs a one-time warning on first use.
        """
        return WorkflowExecLog(self._exec_log if self._exec_log is not None else _NULL_WORKFLOW_EXEC_LOG)

    @property
    def state_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define state schema (Pydantic model) for input/output state validation.

        Returns:
            Pydantic model class or None if no validation needed
        """
        return None

    @property
    def output_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define output schema (Pydantic model) for workflow output validation.

        Use only when the output structure differs from the state (e.g. subset,
        transformation, or a different shape). In most cases output equals final state,
        so validation uses state_schema when output_schema is not defined.

        Default: None. validate_output uses output_schema if defined, otherwise
        state_schema. If neither is defined, returns data as-is (no validation).

        Returns:
            Pydantic model class or None
        """
        return None

    @property
    def metadata_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define metadata schema (Pydantic model) for workflow output metadata validation.

        Override to validate the metadata dict returned by get_metadata() before
        the engine builds :class:`WorkflowExecutionResult`. Returns None to use raw dict (no validation).

        Returns:
            Pydantic model class or None
        """
        return None

    def get_metadata(
        self,
        final_state: Dict[str, Any],
        state_changed: Dict[str, Dict[str, Any]],
        node_ids_executed: List[str],
        status: str = "success",
    ) -> Dict[str, Any]:
        """
        Return metadata for :class:`WorkflowExecutionResult`. Override in subclasses to provide custom
        metadata (e.g. counts, summary, workflow-specific context). The engine validates
        the result against metadata_schema if defined.

        Args:
            final_state: Final workflow state
            state_changed: Keys changed with {"old": ..., "new": ...}
            node_ids_executed: List of node IDs executed in order
            status: Execution status ("success", "error", "cancelled")

        Returns:
            Metadata dict (validated by metadata_schema if defined)
        """
        return {}

    def validate_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate metadata dict against metadata_schema if defined.
        Returns validated dict or metadata as-is when no schema.

        Called by the engine before building :class:`WorkflowExecutionResult` (on success).
        """
        if self.metadata_schema is None:
            return metadata or {}
        validated = self.metadata_schema(**metadata)
        return validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)

    def validate_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate output data. Uses output_schema if defined, otherwise state_schema.
        If neither is defined, returns data as-is.

        Called by the engine before building :class:`WorkflowExecutionResult`.

        Args:
            data: Final state (dict) to validate

        Returns:
            Validated data dict

        Raises:
            PydanticValidationError: When data does not comply with the schema
        """
        schema = self.output_schema if self.output_schema is not None else self.state_schema
        if schema is None:
            return data
        validated = schema(**data)
        return validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)

    @abstractmethod
    def define(self):
        """
        Define workflow structure.

        This method should:
        - Create nodes using self.add_node()
        - Create links using self.add_link()
        - Set entry node using self.set_entry_node()
        """
        pass

    def prepare(self, initial_state: Dict[str, Any] = None):
        """
        Prepare workflow for execution.

        Called by the engine (or by callers in pure Python) **after** :meth:`_on_start` and before graph execution.

        Flow: :meth:`define` → :meth:`_initialize_state` (copy/validate shared state, then :meth:`_on_init`).
        The engine invokes :meth:`_on_start` **before** this method. Callers do not call
        :meth:`_initialize_state` directly.
        """
        self.define()
        self._initialize_state(initial_state)

    @overload
    def run(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        *,
        output_format: str = "json",
        request: Optional[Dict[str, Any]] = None,
        background: Literal[False] = False,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        debug_mode: Literal["trace", "debug"] = "trace",
        exec_log: Any = None,
    ) -> "WorkflowExecutionResult": ...

    @overload
    def run(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        *,
        output_format: str = "json",
        request: Optional[Dict[str, Any]] = None,
        background: Literal[True],
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        debug_mode: Literal["trace", "debug"] = "trace",
        exec_log: Any = None,
    ) -> str: ...

    def run(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        *,
        output_format: str = "json",
        request: Optional[Dict[str, Any]] = None,
        background: bool = False,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        debug_mode: Literal["trace", "debug"] = "trace",
        exec_log: Any = None,
    ) -> Union["WorkflowExecutionResult", str]:
        """
        Public entry for workflow execution (symmetric to :meth:`~nos.core.engine.node.node.Node.run`).

        Delegates to :func:`~nos.core.engine.workflow_engine.get_shared_engine`.

        - ``background=False`` (default): :meth:`~nos.core.engine.workflow_engine.WorkflowEngine.execute_sync`.
          If ``exec_log`` is ``None``, the engine uses an in-memory
          :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` (no Socket.IO).

        - ``background=True``: :meth:`~nos.core.engine.workflow_engine.WorkflowEngine.execute_background` —
          returns ``execution_id`` (``str``); optional ``callback`` and ``debug_mode`` match the engine.

        Args:
            initial_state: Initial shared state; optional.
            output_format: Result rendering format (json, text, html, table, …).
            request: Optional caller context. Each node's ``run(..., request=...)`` includes it under
                ``workflow_run_request``. If ``request`` contains a string ``command``, sync results expose it as
                ``WorkflowExecutionResult.command``.
            background: If ``True``, non-blocking submission via the shared engine's thread pool.
            callback: Passed to ``execute_background`` when ``background=True``.
            debug_mode: ``trace`` (no per-node forms) or ``debug`` (per-node forms on platform logs). Initial-state
                form is shown when the sink supports it and ``state_schema`` is set.
            exec_log: Optional buffer or platform log; ``None`` lets the engine create a default buffer.

        Example::

            result = wf.run(
                initial_state={"x": 1},
                request={"command": "run workflow my_wf", "tenant_id": "acme"},
            )
            assert result.command == "run workflow my_wf"

            eid = wf.run(initial_state={"x": 1}, background=True, request={"command": "run wf"})
        """
        from ..workflow_engine import get_shared_engine

        engine = get_shared_engine()
        if background:
            return engine.execute_background(
                self,
                initial_state=initial_state,
                exec_log=exec_log,
                callback=callback,
                debug_mode=debug_mode,
                output_format=output_format,
                request=request,
            )
        return engine.execute_sync(
            self,
            initial_state=initial_state,
            exec_log=exec_log,
            debug_mode=debug_mode,
            output_format=output_format,
            request=request,
        )

    def add_node(
        self,
        node: Node,
        state_mapping: Optional['StateMapping'] = None,
        *,
        default_input_params: Optional[Dict[str, Any]] = None,
        on_node_failure: Optional[OnNodeFailure] = None,
    ):
        """
        Add a node to the workflow.

        Args:
            node: Node instance to add
            state_mapping: Optional state mapping override. If None, uses node's default mapping.
                         This allows the same node to be used differently in different workflows.
            default_input_params: Optional dict of **node** parameters (validated against the node's
                ``input_params_schema`` on each run). Stored per ``node_id``; the workflow engine
                (and :class:`~nos.core.engine.node.parallel_node.ParallelNode` for children) merges
                these into the ``input_params`` passed to ``node.run()``. The workflow run's
                ``output_format`` (from :meth:`run` or the engine) is passed as the keyword argument
                ``output_format=`` to ``node.run``, not mixed into ``default_input_params``. Use plain
                JSON-serializable values (e.g. ``model_dump()`` from Pydantic).
            on_node_failure: When the node run fails (non-success status), whether to still evaluate
                outgoing links (:class:`~nos.core.engine.link.failure_policy.OnNodeFailure`).
                Default: ``CONTINUE_ROUTING``.
        """
        self._nodes[node.node_id] = node
        self._node_mappings[node.node_id] = state_mapping
        self._node_default_input_params[node.node_id] = (
            dict(default_input_params) if default_input_params else {}
        )
        self._node_on_node_failure[node.node_id] = (
            on_node_failure if on_node_failure is not None else OnNodeFailure.CONTINUE_ROUTING
        )
        node._workflow = self  # Give node access to parent workflow (e.g. ParallelNode)
        # Nodes receive NodeLogger at execution time from engine (not WorkflowLogger)

    def add_node_workflow(
        self,
        workflow_id: str,
        node_id: Optional[str] = None,
        name: Optional[str] = None,
        module_path: Optional[str] = None,
        class_name: Optional[str] = None,
        state_mapping: Optional['StateMapping'] = None,
    ) -> str:
        """
        Add a node that runs a child workflow by ID.

        Creates a NodeWorkflow instance and adds it. The child workflow receives
        the parent state as initial_state and its output is merged back (same
        map_to_node / map_to_shared flow as any node).

        Resolution: registry first, then direct (module_path + class_name) if provided.

        Args:
            workflow_id: ID of the child workflow to run.
            node_id: Optional node ID. Default: sub_{workflow_id}
            name: Optional display name. Default: workflow_id
            module_path: Optional Python module path for direct resolution (fallback when
                not in registry). Requires class_name.
            class_name: Optional class name for direct resolution. Requires module_path.
            state_mapping: Optional state mapping for this node.

        Returns:
            The node_id of the added node (for use in add_link, set_entry_node).
        """
        node = NodeWorkflow(
            workflow_id=workflow_id,
            node_id=node_id,
            name=name,
            module_path=module_path,
            class_name=class_name,
        )
        self.add_node(node, state_mapping=state_mapping)
        return node.node_id

    def get_node_mapping(self, node_id: str) -> Optional['StateMapping']:
        """
        Get state mapping for a node.

        Returns workflow-specific mapping if set, otherwise node's default mapping.

        Args:
            node_id: Node identifier

        Returns:
            StateMapping instance or None (identity mapping)
        """
        # Check for workflow-specific override
        if node_id in self._node_mappings and self._node_mappings[node_id] is not None:
            return self._node_mappings[node_id]

        # Use node's default mapping
        node = self._nodes.get(node_id)
        if node:
            return node.default_state_mapping

        return None

    def add_link(self, link: Link):
        """Add a link to the workflow."""
        self._links[link.link_id] = link
        link._workflow = self
        if self._exec_log:
            link.set_exec_log(self._exec_log)

    def get_on_node_failure(self, node_id: str) -> OnNodeFailure:
        """Return :class:`~nos.core.engine.link.failure_policy.OnNodeFailure` for ``node_id`` (default: continue routing)."""
        return self._node_on_node_failure.get(node_id, OnNodeFailure.CONTINUE_ROUTING)

    def set_entry_node(self, node_id: str):
        """Set the entry node (where execution starts)."""
        if node_id not in self._nodes:
            raise ValueError(f"Entry node {node_id} not found in workflow nodes")
        self._entry_node_id = node_id

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    def get_node_default_input_params(self, node_id: str) -> Dict[str, Any]:
        """
        Copy of default input parameters registered for ``node_id`` via :meth:`add_node`.

        Used by the workflow engine and by :class:`~nos.core.engine.node.parallel_node.ParallelNode`
        when invoking child nodes. Empty dict if none were set.
        """
        raw = self._node_default_input_params.get(node_id)
        return dict(raw) if raw else {}

    def get_link(self, link_id: str) -> Optional[Link]:
        """Get a link by ID."""
        return self._links.get(link_id)

    def get_links_from_node(self, node_id: str) -> list:
        """Get all links originating from a node.

        Includes:
        - Standard links where from_node_id == node_id
        - ChainLinks where node_id is in the path and not the terminal
        """
        result = []
        for link in self._links.values():
            if link.from_node_id == node_id:
                result.append(link)
            elif isinstance(link, ChainLink):
                if node_id in link.path and node_id != link.path[-1]:
                    result.append(link)
        return result

    @property
    def status(self) -> WorkflowStatus:
        """Get current workflow status."""
        return self._status

    @property
    def state(self) -> Dict[str, Any]:
        """Get current workflow state (read-only copy)."""
        return self._state.copy()

    def set_state(self, key: str, value: Any):
        """Update workflow state."""
        old_value = self._state.get(key)
        self._state[key] = value

    def apply_state_updates(self, updates: Dict[str, Any]):
        """
        Apply multiple state updates without logging.
        Used by engine after map_to_shared; :meth:`_on_state_changed` is called separately before this.
        """
        self._state.update(updates)

    def update_state(self, updates: Dict[str, Any]):
        """Update multiple state keys at once."""
        for key, value in updates.items():
            self.set_state(key, value)

    def set_exec_log(self, exec_log):
        """
        Set the execution log sink for workflow and link messaging (engine, before execution).
        When non-``None``, attaches a scoped per-run hook bus (adapters forward lifecycle events to this sink).
        Pass ``None`` to clear the sink and the bus. Per-node sinks are attached when each node runs.
        """
        self._exec_log = exec_log
        for link in self._links.values():
            link.set_exec_log(exec_log)
        if exec_log is None:
            self._run_event_hook = None
        else:
            attach_workflow_run_hooks_bus(self, exec_log)

    def set_run_event_hook(self, hook) -> None:
        """Internal: scoped :class:`~nos.hooks.manager.EventHookManager` from :meth:`set_exec_log`."""
        self._run_event_hook = hook

    # --- Lifecycle hooks (override in subclasses; engine calls these — same pattern as Node._on_*) ---

    def _on_start(self, initial_state: Optional[Dict[str, Any]] = None) -> None:
        """
        Pre-prepare hook: engine calls this **after** :meth:`set_exec_log` and **before** :meth:`prepare`
        (same phase as :meth:`~nos.core.engine.node.node.Node._on_start` before :meth:`~nos.core.engine.node.node.Node.execute`).

        ``initial_state`` is the **raw** dict passed into the run (not yet validated by ``state_schema``).
        Use it for early logic or async fetch that mutates state before :meth:`prepare` runs; to mirror the node,
        mutate a dict you own and pass that same reference as ``initial_state`` into :meth:`run` / ``execute_sync``.

        Base implementation:

        - Sets :attr:`status` to :attr:`WorkflowStatus.RUNNING`.
        - Emits :class:`WorkflowRunEventType.WORKFLOW_START` with the given ``initial_state`` snapshot.

        When no execution log was attached, only the status transition runs (no bus, no sink).
        """
        self._status = WorkflowStatus.RUNNING
        raw = dict(initial_state) if initial_state else {}
        if self._run_event_hook:
            self._run_event_hook.emit(
                WorkflowRunEventType.WORKFLOW_START,
                {
                    "initial_state": raw,
                    "state_mapping_desc": "per-node StateMapping",
                    "workflow_id": self.workflow_id,
                },
            )

    def _on_stop(self):
        """Lifecycle hook: workflow stopped. Sets status to STOPPED; override to add custom logic."""
        if self._status == WorkflowStatus.ERROR:
            return
        self._status = WorkflowStatus.STOPPED
        if self._exec_log:
            self._exec_log.log("info", f"Workflow {self.workflow_id} stopped")

    def _on_error(self, result: "WorkflowExecutionResult") -> None:
        """
        Lifecycle hook: workflow run failed with a structured result (mirrors :meth:`Node._on_error`).

        Emits ``workflow.error`` on the scoped bus (adapter → structured log) then :meth:`_on_end`
        with ``level=\"error\"`` so observers always get a terminal ``workflow_execution_result``.
        """
        self._workflow_error_already_handled = True
        self._status = WorkflowStatus.ERROR
        if self._run_event_hook:
            self._run_event_hook.emit(WorkflowRunEventType.WORKFLOW_ERROR, {"result": result})
        self._on_end(result, level="error", message="Workflow execution completed with error")

    def _on_state_changed(
        self,
        node_id: str,
        state_updates: Dict[str, Any],
        old_values: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Lifecycle hook: a node merged output into shared state (before :meth:`apply_state_updates`).

        Base implementation logs a ``shared_state_changed`` line via :meth:`exec_log.log`. Override
        for custom logic; call ``super()._on_state_changed(node_id, state_updates, old_values)`` to
        keep the same event shape on the channel.

        This is **workflow** shared state (not :meth:`~nos.core.engine.node.node.Node._on_state_changed`,
        which fires per key on the node’s observable state dict).
        """
        if self._exec_log:
            self._exec_log.log(
                "info",
                f"Shared state updated by node {node_id}",
                event="shared_state_changed",
                node_id=node_id,
                state_updates=dict(state_updates) if state_updates else {},
                old_values=dict(old_values) if old_values else {},
            )

    def _on_end(
        self,
        result: "WorkflowExecutionResult",
        *,
        level: str = "info",
        message: str = "Workflow execution completed",
    ) -> None:
        """
        Terminal hook for every finished workflow run (mirrors :meth:`Node._on_end`).

        Emits ``workflow.end`` on the scoped bus; adapters write ``workflow_execution_result`` to the sink.
        On error paths the engine calls :meth:`_on_error` first, which delegates here with ``level=\"error\"``.
        """
        if self._status == WorkflowStatus.RUNNING:
            self._status = WorkflowStatus.STOPPED
        if self._run_event_hook:
            self._run_event_hook.emit(
                WorkflowRunEventType.WORKFLOW_END,
                {"result": result, "level": level, "message": message},
            )

    def _on_link_decision(
        self,
        link_id: str,
        decision: str,
        next_node_id: Optional[str] = None,
    ) -> None:
        """
        Lifecycle hook: engine chose a routing outcome after evaluating a link (orchestration-level).

        Base implementation logs ``link_decision`` on the execution sink. Override for custom logic;
        call ``super()._on_link_decision(...)`` to keep the same event shape.
        """
        if self._exec_log:
            next_str = next_node_id if next_node_id is not None else "STOP"
            self._exec_log.log(
                "info",
                f"Link {link_id} routing: {decision} -> {next_str}",
                event="link_decision",
                link_id=link_id,
                decision=decision,
                next_node_id=next_node_id,
            )

    def _on_link_error(self, link_id: str, error: Exception) -> None:
        """
        Lifecycle hook: ``route()`` raised while the engine was evaluating this link.

        Base implementation logs an error line with ``link_id``. The engine may try the next link.
        """
        if self._exec_log:
            self._exec_log.log(
                "error",
                f"Link {link_id} error: {error}",
                link_id=link_id,
            )

    def validate_state(self) -> bool:
        """Validate current state against state_schema."""
        if self.state_schema is None:
            return True

        try:
            self.state_schema(**self._state)
            return True
        except Exception as e:
            logger.error(f"State validation failed for workflow {self.workflow_id}: {e}")
            return False

    def validate_state_or_raise(self, node_id: Optional[str] = None):
        """
        Validate current state against state_schema. Raises on failure.
        Used after map_to_shared/apply_state_updates to fail fast before link routing.

        Args:
            node_id: Optional node ID (for error message context).

        Raises:
            PydanticValidationError: When state does not comply with state_schema.
        """
        if self.state_schema is None:
            return
        try:
            self.state_schema(**self._state)
        except PydanticValidationError as e:
            node_ctx = f" after node {node_id}" if node_id else ""
            raise ValueError(
                f"Workflow {self.workflow_id} state invalid{node_ctx}. "
                "Node output does not comply with workflow.state_schema. "
                f"Details: {e}"
            ) from e

    def _initialize_state(self, initial_state: Dict[str, Any] = None):
        """
        Initialize workflow shared state (internal; use :meth:`prepare`).

        Emits ``workflow.init`` on the scoped bus (raw snapshot), validates reserved keys and
        ``state_schema``, then calls :meth:`_on_init` for ``workflow_init_completed`` + logging.
        """
        raw_snapshot = dict(initial_state) if initial_state else {}
        logger.info(f"Preparing workflow shared state for {self.workflow_id}: {raw_snapshot}")
        if self._run_event_hook:
            self._run_event_hook.emit(
                WorkflowRunEventType.WORKFLOW_INIT,
                {"initial_state": raw_snapshot, "workflow_id": self.workflow_id},
            )

        if initial_state:
            self._state = initial_state.copy()
        else:
            self._state = {}

        logger.info("Validating workflow shared state (reserved keys)")
        validate_reserved_keys(
            self._state,
            schema_field_names=(
                set(self.state_schema.model_fields.keys()) if self.state_schema is not None else None
            ),
            context_label=f"workflow {self.workflow_id} initial state",
        )

        if self.state_schema:
            logger.info("Validating workflow shared state with state_schema")
            try:
                validated = self.state_schema(**self._state)
                self._state = validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)
                logger.info(f"Workflow shared state validated: {self._state}")
            except Exception as e:
                logger.warning(f"Initial state validation failed for {self.workflow_id}: {e}")
                # Continue with unvalidated state

        self._on_init()

    def _on_init(self) -> None:
        """
        Telemetry hook **after** initial shared-state validation — validation runs **before** this
        method, inside :meth:`_initialize_state`, not here.

        **Order:** :meth:`prepare` calls :meth:`define` then :meth:`_initialize_state`. In
        ``_initialize_state``, reserved keys and ``state_schema`` (if any) are applied first; only
        then is ``_on_init`` called. So ``prepare`` is the public entry point, but the validation
        step lives in ``_initialize_state``.

        Emits ``workflow.init_completed`` on the scoped per-run bus (mirrors
        :meth:`~nos.core.engine.node.node.Node` after ``_on_init`` succeeds). Override for custom
        logic; call ``super()._on_init()`` to keep channel behaviour.
        """
        if self._run_event_hook:
            self._run_event_hook.emit(
                WorkflowRunEventType.WORKFLOW_INIT_COMPLETED,
                {"state": self._state.copy(), "workflow_id": self.workflow_id},
            )

    def _on_input(self, form_response: Dict[str, Any]) -> None:
        """
        Hook when the **initial shared-state** HTML form response is received (platform ``EventLog`` +
        :meth:`state_schema` with at least one field). The engine calls this immediately after
        :meth:`~nos.core.execution_log.event_log_buffer.EventLogBuffer.request_and_wait` returns — same
        position as :meth:`~nos.core.engine.node.node.Node._on_input` relative to the node debug form.

        **Order:** :meth:`prepare` runs first (``define`` → :meth:`_initialize_state` → :meth:`_on_init`), so
        shared state is already validated once. The optional form then lets the operator adjust values;
        :meth:`_on_input` receives the **raw** client payload; the engine re-validates with ``state_schema``
        and assigns :attr:`_state` before graph execution.

        Override for custom handling; call ``super()._on_input(form_response)`` to emit
        ``workflow.form_response`` on the scoped bus and structured log entries.
        """
        if self._run_event_hook:
            self._run_event_hook.emit(
                WorkflowRunEventType.WORKFLOW_FORM_RESPONSE,
                {"form_response": form_response},
            )
