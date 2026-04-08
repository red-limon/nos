"""
Node — unit of work with input/output schemas (:class:`Node`).

**Inputs**

- ``input_state_schema`` — validates workflow/context state (``None`` → :class:`_FlatInputSchema`, any keys).
- ``input_params_schema`` — validates direct parameters (``None`` → flat schema).

**Outputs**

- Subclasses return :class:`NodeOutput` from :meth:`Node._do_execute`; the framework builds
  :class:`NodeExecutionResult` with ``response.output`` / ``response.metadata``.

**Communication**

- **Console:** standard library ``logging``.
- **Runtime / UI:** :attr:`Node.exec_log` (:class:`NodeExecLog`) for :meth:`~NodeExecLog.log`, errors,
  cooperative cancel, and :meth:`~Node.request_and_wait` / forms.
- **Cooperative stop:** :meth:`Node.request_cooperative_stop` (optional ``execution_id``).
- **Lifecycle telemetry:** scoped per-run bus from :meth:`Node.set_exec_log` (see
  :mod:`nos.core.execution_log.node_run_hooks`); adapters mirror events to the sink. Subclasses must not call
  ``log_node_*`` directly — hooks emit via the bus; custom lines use :meth:`NodeExecLog.log`.

**Extension**

Subclass :class:`Node`, implement schema properties and :meth:`Node._do_execute`, optionally override
``_on_*`` hooks. See the official API reference (``docs_101.html``, Node) for signatures and patterns.
"""

import importlib
import logging
import time
import warnings
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, Literal, Optional, Type, TYPE_CHECKING, Union, overload
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError as PydanticValidationError

# Import StateMapping for node isolation
try:
    from ..workflow.state_mapping import StateMapping, create_identity_mapping
except ImportError:
    StateMapping = None
    create_identity_mapping = None

if TYPE_CHECKING:
    from ...execution_log.event_log_buffer import EventLogBuffer

# Import CancellationError for transparent cooperative stop support.
# Raised by exec_log.log() on the buffer when stop is requested; caught in execute().
from ...execution_log.default_sinks import create_default_node_exec_log, normalize_debug_mode
from ...execution_log.event_log_buffer import CancellationError
from ...execution_log.node_run_hooks import NodeRunEventType
from ..reserved_keys import validate_reserved_keys

logger = logging.getLogger(__name__)


class NodeRunStatus(str, Enum):
    """
    Lifecycle state for a node instance.

    Typical flow: ``IDLE`` → ``RUNNING`` (after :meth:`Node._on_start`) → ``STOPPED`` or ``ERROR`` at end.
    """

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


def _format_elapsed(seconds: float) -> str:
    """Format a duration as a human-readable string.

    Under 60 s → ``"5.1s"``
    60 s or more → ``"1m 05s"``
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m {s:02d}s"


class NodeExecLog:
    """
    Public execution-log API exposed to Node subclasses.

    Use :meth:`log` for custom messages from node code.

    System events (``log_node_init``, ``log_node_end``, ``log_error``, etc. on the raw sink) are reserved for the
    Node base class and not accessible from subclasses.

    Use ``self.exec_log`` inside Node subclass methods.
    """

    def __init__(self, sink: "EventLogBuffer"):
        """
        Args:
            sink: :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` or platform ``EventLog``
                (same object attached via :meth:`Node.set_exec_log`, or created lazily by :attr:`Node.exec_log`).
        """
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
        Write a custom execution-log line/event from within a node's ``_do_execute`` (or similar).

        Same behavior as :meth:`EventLogBuffer.log_custom` / :meth:`EventLogBuffer.log` on the
        underlying sink (buffer, cooperative cancellation, optional realtime delivery).

        Args:
            level: Log level (``debug``, ``info``, ``warning``, ``error``).
            message: Log message.
            event: Logical event type on :class:`~nos.core.execution_log.events.CustomEvent`
                (default ``Logging event``).
            include_base_fields: If True (default), payload includes execution context
                (execution_id, started_at, node_id, etc.). If False, payload is only level,
                message, and kwargs.
            **kwargs: Additional fields to include in the event payload.
        """
        self._inner.log(level, message, event=event, include_base_fields=include_base_fields, **kwargs)

    def is_stop_requested(self) -> bool:
        """True if cooperative cancellation was requested (shared with workflow / parallel children)."""
        inner = self._inner
        return bool(getattr(inner, "is_stop_requested", lambda: False)())


class _FlatInputSchema(BaseModel):
    """Default flat schema: accepts any extra key-value pairs."""

    model_config = ConfigDict(extra="allow")


class NodeInputSchema(BaseModel):
    """
    Base class for node input params schemas.

    Enforces strict field validation: any parameter not declared in the schema
    raises a ValidationError. Use this as the base for all input_params_schema
    definitions in Node subclasses.

    Example::

        class MyNodeInputParams(NodeInputSchema):
            a: float = Field(default=0, description="First number")
            b: float = Field(default=0, description="Second number")
    """

    model_config = ConfigDict(extra="forbid")


class NodeStateSchema(BaseModel):
    """
    Base class for node input state schemas.

    Enforces strict field validation on workflow state keys that this node
    declares as dependencies. Use this as the base for all input_state_schema
    definitions in Node subclasses.

    Example::

        class MyNodeInputState(NodeStateSchema):
            user_id: str = Field(..., description="Current user ID from workflow state")
    """

    model_config = ConfigDict(extra="forbid")


class NodeOutputData(BaseModel):
    """
    Structured output returned by _do_execute (documented convention, not enforced at Pydantic level).

    Nodes set this structure inside NodeOutput.output so that the Output tab knows how to render.

    Fields:
      output_format : str   — rendering format ('json', 'html', 'text', 'table', 'code', 'tree').
      data          : Any   — the primary renderable content, shaped for the chosen format:
                              'json'  → any dict / list / scalar
                              'html'  → HTML string
                              'text'  → plain-text string
                              'table' → {'columns': [...], 'rows': [[...]]}
                              'code'  → source-code string
                              'tree'  → nested dict

    The framework resolves the effective output_format in this priority order:
      1. --output_format from CLI (validated against node's allowed_output_formats)
      2. output_format returned by the node in NodeOutput.output['output_format']
      3. Fallback: 'json' (with a backend warning)
    """

    output_format: str = Field(default="json")
    data: Any = Field(default=None)


class NodeResponseData(BaseModel):
    """
    Response payload stored in NodeExecutionResult.

    output  : dict with keys 'output_format' (str) and 'data' (Any).
              output_format is the effective rendering format resolved by the framework.
              data is the primary renderable content for that format.
    metadata: Free-form supplementary info (validated by metadata_schema if defined).
    """

    output: dict = Field(default_factory=dict, description="{'output_format': str, 'data': Any} — see NodeOutputData")
    metadata: dict = Field(default_factory=dict, description="Extra info (validated by metadata_schema if defined)")


class NodeExecutionResult(BaseModel):
    """
    Full execution result produced by :meth:`Node.execute` / :meth:`Node.run`.

    Plugin code in :meth:`Node._do_execute` returns only :class:`NodeOutput`; the framework fills identity,
    timestamps, ``status``, and ``response``.

    **status** (common values): ``completed``, ``cancelled``, ``validation_error``, ``internal_error``,
    ``bad_request``, and others as defined by the execution paths.
    """

    execution_id: str = Field(..., description="Unique execution identifier (UUID)")
    node_id: str = Field(..., description="Node identifier")
    module_path: str = Field(default="", description="Python module path of the node class")
    class_name: str = Field(default="", description="Node class name")
    command: str = Field(default="", description="Command string that triggered this execution")
    status: str = Field(..., description="Execution status (e.g. completed)")
    response: NodeResponseData = Field(..., description="Output and metadata from the node. response.output = {'output_format': str, 'data': Any}")
    initial_state: dict = Field(default_factory=dict, description="State at start")
    input_params: dict = Field(default_factory=dict, description="Input parameters used")
    final_state: dict = Field(default_factory=dict, description="State after execution")
    started_at: str = Field(..., description="Execution start timestamp (ISO 8601)")
    ended_at: str = Field(..., description="Execution end timestamp (ISO 8601)")
    elapsed_time: str = Field(..., description="Execution time (e.g. '1.3s', '1m 05s')")
    event_logs: list = Field(default_factory=list, description="Events emitted during execution")


@dataclass
class NodeOutput:
    """
    Output from _do_execute. Returned by the node's _do_execute method.

    Fields:
      - output:   Must be a dict with keys ``output_format`` (str) and ``data`` (Any).
                  ``output_format`` is the node's natural rendering format.
                  ``data`` is the primary renderable content shaped for that format.
                  The framework may override ``output_format`` with the CLI --output_format value.
                  ``data`` is validated by ``output_schema`` when defined: ``dict`` payloads
                  use field validation; scalar/list roots use a :class:`pydantic.RootModel` schema.
      - metadata: Optional supplementary info (counts, timing, debug values…). Free-form dict.
                  Validated by node.metadata_schema if defined.

    Output format / data shape contract:
      'json'  → data: any dict / list / scalar
      'html'  → data: HTML string
      'text'  → data: plain-text string
      'table' → data: {'columns': [...], 'rows': [[...]]}
      'code'  → data: source-code string
      'tree'  → data: nested dict

    Examples:
        # Render sum result as JSON (default):
        return NodeOutput(
            output={"output_format": "json", "data": {"a": 1, "b": 2, "sum": 3}},
        )

        # Render fetched page as HTML:
        return NodeOutput(
            output={"output_format": "html", "data": "<html>...</html>"},
            metadata={"url": "https://example.com", "elapsed_time": 0.42},
        )

        # Render summary as plain text:
        return NodeOutput(
            output={"output_format": "text", "data": "Sum: 3"},
        )
    """
    output: Any
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _InitResult:
    """
    Internal bundle returned by :meth:`Node._on_init` (protected API).

    Carries validated state/params, timing, and the resolved rendering format for the rest of :meth:`execute`.
    """
    execution_id: str
    started_at: datetime
    t0: float
    state_dict: Dict[str, Any]
    params_dict: Any  # MappingProxyType after _on_init — read-only; mutable dict only during form re-validation
    initial_state: Dict[str, Any]
    state_for_node: Any  # Passed to _do_execute (may be ObservableStateDict in workflow engine)
    original_state: Any
    requested_output_format: Optional[str]  # None when CLI/output_format not provided


# Output formats supported for rendering NodeExecutionResult (shared with workflows)
from nos.io_adapters.output_formats_schema import NODE_OUTPUT_FORMATS


class Node(ABC):
    """
    Abstract base class for workflow nodes.

    **Implementation pattern**

    1. Subclass ``Node`` and implement :meth:`_do_execute` (required).

    2. Override schema properties as needed:

       - :attr:`input_state_schema`, :attr:`input_params_schema` — return ``None`` for a **flat** schema
         (any dict; see :class:`_FlatInputSchema`), or a strict :class:`NodeStateSchema` / :class:`NodeInputSchema` subclass.
       - :attr:`output_schema`, :attr:`metadata_schema` — optional validation for rendered ``data`` and ``metadata``.

    3. Optionally override :attr:`ALLOWED_OUTPUT_FORMATS` to restrict CLI/UI formats (default: all
       :data:`NODE_OUTPUT_FORMATS`).

    **Lifecycle** (override with care; call ``super()`` where documented)

    Base hooks drive :attr:`status` and emit on the scoped bus from :meth:`set_exec_log`: ``_on_start``,
    ``_on_init``, ``_on_input``, ``_on_state_changed``, ``_on_end``, ``_on_error``, ``_on_stop``.

    **Public entry points**

    - :meth:`load` — classmethod: resolve an instance (registry ``prod`` or import ``dev``).
    - :meth:`run` — attach log, ``_on_start``, then :meth:`execute` (or delegate to engine if ``background=True``).

    **Communication**

    - Console: ``logging``.
    - Runtime / UI: :attr:`exec_log` (:meth:`NodeExecLog.log`), :meth:`request_and_wait` / :meth:`request_form_input`.
      Do not call ``log_node_*`` on the raw sink from subclasses.
    """

    ALLOWED_OUTPUT_FORMATS: list = None  # None = all formats from NODE_OUTPUT_FORMATS

    def __init__(self, node_id: Optional[str] = None, name: Optional[str] = None):
        """
        Initialize node.

        Args:
            node_id: Unique identifier for this node. If None, read from
                class attribute ``node_id`` (required on subclass).
            name: Human-readable name (defaults to ``node_id`` or class attribute ``name``).
        """
        if node_id is None:
            if not hasattr(self.__class__, "node_id"):
                raise TypeError(
                    f"{self.__class__.__name__} must define node_id as a class attribute, "
                    "or pass node_id to __init__"
                )
            node_id = self.__class__.node_id
        self.node_id = node_id
        self.name = name or getattr(self.__class__, "name", None) or node_id
        self._exec_log: Optional["EventLogBuffer"] = None
        # Mirrors init_result.execution_id for the body of execute() (after successful _on_init);
        # cleared in execute() finally. Used by request_cooperative_stop() when no log is attached.
        self._active_run_execution_id: Optional[str] = None
        self._run_event_hook = None  # EventHookManager: per-run only; cleared in run() finally
        self._default_state_mapping = None
        self._debug_mode: bool = False  # If True, show interactive form before execution
        # Set by :meth:`load` so :meth:`run` (background) can replay the same resolution via the engine.
        self._load_spec: Optional[Dict[str, Any]] = None
        self._status = NodeRunStatus.IDLE

    @property
    def status(self) -> NodeRunStatus:
        """Lifecycle status (same semantics as :attr:`~nos.core.engine.workflow.workflow.Workflow.status`)."""
        return self._status

    @classmethod
    def load(
        cls,
        mode: Literal["dev", "prod"],
        node_id: str,
        *,
        module_path: Optional[str] = None,
        class_name: Optional[str] = None,
        **kwargs: Any,
    ) -> "Node":
        """
        Resolve a node from the registry (``prod``) or from a Python module (``dev``).

        ``node_id`` is always required: in ``prod`` it selects the registry entry; in ``dev`` it is the
        ``node_id`` passed to the constructor and used for labels / logs / commands.

        In ``prod``, ``module_path`` and ``class_name`` are ignored (a warning is logged if they are set).
        In ``dev``, ``module_path`` and ``class_name`` are required.

        Returns an instance of the loaded class (must be a subclass of ``cls`` when ``cls`` is a concrete plugin type).
        """
        from ..registry import workflow_registry

        if not node_id or not str(node_id).strip():
            raise ValueError("Node.load: node_id is required and cannot be empty.")

        if mode == "prod":
            if module_path or class_name:
                logger.warning(
                    "Node.load(prod): module_path and class_name are ignored when loading from the registry."
                )
            node = workflow_registry.create_node_instance(node_id, **kwargs)
            if node is None:
                raise ValueError(f"Node.load(prod): no node registered for node_id={node_id!r}.")
            if not isinstance(node, cls):
                raise TypeError(
                    f"Node.load: registry node {node_id!r} is {type(node).__name__}, expected instance of {cls.__name__}."
                )
            node._load_spec = {"mode": "prod", "node_id": node_id}
            return node

        if mode == "dev":
            if not module_path or not str(module_path).strip():
                raise ValueError("Node.load(dev): module_path is required.")
            if not class_name or not str(class_name).strip():
                raise ValueError("Node.load(dev): class_name is required.")
            try:
                module = importlib.import_module(module_path)
                node_class = getattr(module, class_name)
            except (ImportError, AttributeError) as e:
                raise ValueError(
                    f"Node.load(dev): failed to load {module_path!r}.{class_name!r}: {e}"
                ) from e
            if not isinstance(node_class, type) or not issubclass(node_class, Node):
                raise TypeError(
                    f"Node.load(dev): {module_path}.{class_name} must be a Node subclass, got {node_class!r}."
                )
            if not issubclass(node_class, cls):
                raise TypeError(
                    f"Node.load(dev): loaded class {node_class.__name__} is not a subclass of {cls.__name__}."
                )
            node = node_class(node_id=node_id, **kwargs)
            node._load_spec = {
                "mode": "dev",
                "node_id": node_id,
                "module_path": module_path,
                "class_name": class_name,
            }
            return node

        raise ValueError(f"Node.load: invalid mode={mode!r}; use 'dev' or 'prod'.")

    def _node_identity(self) -> dict:
        """Return execution_id (from :attr:`_exec_log`), module_path, class_name, command for NodeExecutionResult.

        ``execution_id`` is the authoritative id set by the engine when it attaches the execution log
        (via :meth:`set_exec_log`). Empty string when no log is set (standalone/CLI — no engine).
        ``command`` is the effective command (with defaults) persisted after ``log_node_init_completed``.
        """
        log = self._exec_log
        return {
            "execution_id": log.execution_id if log else "",
            "module_path": self.__class__.__module__,
            "class_name": self.__class__.__name__,
            "command": getattr(log, "_command", "") if log else "",
        }

    def allowed_output_formats(self) -> list:
        """Return list of allowed output formats. Override ALLOWED_OUTPUT_FORMATS to restrict."""
        if self.ALLOWED_OUTPUT_FORMATS is not None:
            return list(self.ALLOWED_OUTPUT_FORMATS)
        return list(NODE_OUTPUT_FORMATS)

    @property
    def default_output_format(self) -> str:
        """Default output format when not specified. Override in subclasses (e.g. return 'code')."""
        return "json"

    @property
    def exec_log(self) -> "NodeExecLog":
        """
        Public execution-log API for Node subclasses (:meth:`NodeExecLog.log`).

        If no sink is attached yet (e.g. before :meth:`run` or after ``set_exec_log(None)``), a default
        in-memory :class:`~nos.core.execution_log.event_log_buffer.EventLogBuffer` is created and the
        scoped run hook bus is attached (same as :meth:`set_exec_log`).
        """
        if self._exec_log is None:
            self.set_exec_log(create_default_node_exec_log(self))
        return NodeExecLog(self._exec_log)

    @property
    def input_state_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define schema for workflow/context state validation.
        Returns None to use flat schema (accept any dict).
        """
        return None

    @property
    def input_params_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define schema for direct input parameters validation.
        Returns None to use flat schema (accept any dict).
        """
        return None

    @property
    def output_schema(self) -> Optional[Type[BaseModel]]:
        """
        Schema for ``response.output["data"]`` after format resolution.

        * ``BaseModel`` — validate when ``data`` is a ``dict`` (``schema(**data)``).
        * :class:`pydantic.RootModel` — validate non-dict ``data`` (e.g. ``RootModel[str]`` for HTML/text);
          the validated root value replaces ``data``.
        * ``None`` — no validation.
        """
        return None

    @property
    def metadata_schema(self) -> Optional[Type[BaseModel]]:
        """
        Define metadata schema for response.metadata. Returns None to use raw dict.
        """
        return None

    def _to_dict(self, val: Any) -> Dict[str, Any]:
        """Convert to dict. Handles Pydantic model or dict."""
        if hasattr(val, "model_dump"):
            return val.model_dump()
        if isinstance(val, dict):
            return val
        return {}

    def _validate_with_schema(
        self, schema: Optional[Type[BaseModel]], raw: Dict[str, Any], default: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate raw dict with schema. Returns validated dict. Uses _FlatInputSchema if schema is None."""
        s = schema if schema is not None else _FlatInputSchema
        d = raw if raw is not None else default
        try:
            validated = s(**d)
        except Exception:
            # When empty input, try schema() to use defaults (form pre-fill in debug mode)
            if not d and schema is not None:
                validated = schema()
            else:
                raise
        return validated.model_dump() if hasattr(validated, "model_dump") else dict(validated)

    def _get_form_timeout_seconds(self, state_dict: Dict[str, Any]) -> float:
        """Override to use workflow state (e.g. idle_timeout_minutes). Default 5 min."""
        return 300.0

    def _generate_execution_id(self) -> str:
        """Generate unique execution ID. Override in subclass if needed."""
        return str(uuid.uuid4())

    def _on_init(
        self,
        state: Dict[str, Any],
        input_params: Any,
        *,
        requested_output_format: Optional[str] = None,
    ) -> _InitResult:
        """
        Initialize execution: validate inputs, prepare state and params.
        Override in subclasses to add custom init logic; always call super()._on_init(...).

        ``requested_output_format`` is the caller/engine rendering hint (CLI ``--output_format``,
        ``Node.run(..., output_format=...)``, etc.). It is **not** read from ``input_params``. If your
        node's ``input_params_schema`` defines a field also named ``output_format``, that field is
        domain data only and does not set the framework rendering format unless you wire it yourself
        in ``_do_execute``.

        For subclass use only (leading underscore = protected).
        """
        execution_id = (
            self._exec_log.execution_id if self._exec_log else self._generate_execution_id()
        )
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        logger.info(f"[{execution_id}] Node {self.node_id} starting execution")
        logger.info("Preparing and validating inputs")
        logger.info(f"State: {state}")
        logger.info(f"Input params: {input_params}")

        raw_state = self._to_dict(state) if state else {}
        raw_params = self._to_dict(input_params) if input_params is not None else {}

        if self._run_event_hook:
            self._run_event_hook.emit(
                NodeRunEventType.NODE_INIT,
                {"initial_state": raw_state, "initial_params": raw_params},
            )

        # Rendering format: only from explicit requested_output_format (never from input_params dict).
        _cli_fmt = requested_output_format
        if _cli_fmt is not None:
            _cli_fmt = str(_cli_fmt).lower().strip()
            if _cli_fmt not in self.allowed_output_formats():
                allowed = ", ".join(self.allowed_output_formats())
                raise ValueError(
                    f"Invalid output_format '{_cli_fmt}'. Allowed for this node: {allowed}"
                )
        requested_fmt: Optional[str] = _cli_fmt

        logger.info(f"Raw state: {raw_state}")
        logger.info(f"Raw input params: {raw_params}")
        logger.info("Checking for overlapping keys between state and input_params")

        common_keys = set(raw_state.keys()) & set(raw_params.keys())
        if common_keys:
            logger.error(f"State and input_params have overlapping keys: {common_keys}. ")
            raise ValueError(
                f"state and input_params have overlapping keys: {common_keys}. "
                f"When this occurs, rename the workflow state keys (or use StateMapping) so they do not collide "
                f"with input_params of node '{self.node_id}'. Use state for workflow context, input_params for direct parameters."
            )

        validate_reserved_keys(
            raw_state,
            schema_field_names=(
                set(self.input_state_schema.model_fields.keys())
                if self.input_state_schema is not None
                else None
            ),
            context_label=f"node {self.node_id} state",
        )
        validate_reserved_keys(
            raw_params,
            schema_field_names=(
                set(self.input_params_schema.model_fields.keys())
                if self.input_params_schema is not None
                else None
            ),
            context_label=f"node {self.node_id} input_params",
        )

        logger.info("Validating state with schema")
        state_dict = self._validate_with_schema(self.input_state_schema, raw_state, {})
        logger.info(f"State validated: {state_dict}")

        logger.info("Validating input params with schema")
        if self.input_params_schema is not None:
            known_fields = set(self.input_params_schema.model_fields.keys())
            unknown = set(raw_params.keys()) - known_fields
            if unknown:
                valid_list = ", ".join(f"--param {k}=<value>" for k in sorted(known_fields)) or "(none)"
                raise ValueError(
                    f"Unknown parameter(s) for {self.__class__.__name__}: {', '.join(sorted(unknown))}. "
                    f"Valid params: {valid_list}"
                )
        params_dict = MappingProxyType(self._validate_with_schema(self.input_params_schema, raw_params, {}))
        logger.info(f"Input params validated: {params_dict}")

        logger.info("Creating initial state")
        initial_state = dict(state_dict)
        state_for_node = state if state is not None else state_dict
        logger.info(f"Initial state: {initial_state}")
        logger.info(f"Validated params: {params_dict}")

        return _InitResult(
            execution_id=execution_id,
            started_at=started_at,
            t0=t0,
            state_dict=state_dict,
            params_dict=params_dict,
            initial_state=initial_state,
            state_for_node=state_for_node,
            original_state=state,
            requested_output_format=requested_fmt,
        )

    def _on_start(self, request: Dict[str, Any]) -> Optional[bool]:
        """
        Pre-initialization hook: called by run() before execute().
        Base implementation emits ``node.start`` on the scoped run bus (see :meth:`set_exec_log`).
        Return True to proceed with execute(); return False or None to stop execution
        (run() returns a cancelled NodeExecutionResult).
        Override in subclasses to add custom logic (e.g. logging, validation, rejection).
        Subclasses must call super()._on_start(request) if overriding.

        Example (stop execution with custom message via :attr:`exec_log`):
            def _on_start(self, request):
                super()._on_start(request)
                if some_reject_condition:
                    if self._exec_log:
                        self._exec_log.log("warning", "Execution rejected: reason X")
                    return False
                return True

        For subclass use only.
        """
        self._status = NodeRunStatus.RUNNING
        if self._run_event_hook:
            self._run_event_hook.emit(NodeRunEventType.NODE_START, {"request": request})
        return True

    def _on_input(self, form_response: Dict[str, Any]) -> None:
        """
        Hook called when form response is received from client (debug mode).
        Override in subclasses to add custom logic; call super()._on_input(form_response).
        Base implementation emits ``node.form_response`` on the scoped run bus.
        For subclass use only.
        """
        if self._run_event_hook:
            self._run_event_hook.emit(
                NodeRunEventType.NODE_FORM_RESPONSE, {"form_response": form_response}
            )

    def _on_state_changed(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        Hook called when state_dict is mutated (each state_dict[key] = value).
        Override in subclasses to add custom logic; call super()._on_state_changed(key, old_value, new_value).
        Base implementation emits ``node.state_changed`` on the scoped run bus. Called by the engine's
        ObservableStateDict callback; the node receives (key, old_value, new_value).
        For subclass use only.
        """
        if self._run_event_hook:
            self._run_event_hook.emit(
                NodeRunEventType.NODE_STATE_CHANGED,
                {"key": key, "old_value": old_value, "new_value": new_value},
            )

    def _on_end(self, result: "NodeExecutionResult", level: str = "info", message: str = "Node execution completed") -> None:
        """
        Hook called when node execution ends (any outcome). Override in subclasses to add
        custom logic; call super()._on_end(result, level, message) if extending.
        """
        if self._status == NodeRunStatus.RUNNING:
            self._status = NodeRunStatus.STOPPED
        if self._run_event_hook:
            self._run_event_hook.emit(
                NodeRunEventType.NODE_END,
                {"result": result, "level": level, "message": message},
            )

    def _on_error(self, result: "NodeExecutionResult") -> None:
        """
        Hook called when node execution terminates with an error.
        Emits ``node.error`` on the scoped bus (adapter → ``log_node_error``) then calls _on_end with level='error'.
        Replaces the old pattern of log_node_output + _on_end in error paths.
        Override in subclasses to add custom error handling; call super()._on_error(result).
        """
        self._status = NodeRunStatus.ERROR
        if self._run_event_hook:
            self._run_event_hook.emit(NodeRunEventType.NODE_ERROR, {"result": result})
        self._on_end(result, level="error", message="Node execution completed with error")

    def _on_stop(
        self,
        result: "NodeExecutionResult",
        message: str = "Execution cancelled by user",
    ) -> None:
        """
        Hook for cooperative cancellation (:exc:`CancellationError` from ``exec_log.log`` / ``log_custom``).

        Base behaviour: emits ``node.stop`` on the scoped run bus (adapter → :meth:`~nos.core.execution_log.event_log_buffer.EventLogBuffer.log_node_stop`),
        then :meth:`_on_end` with ``level="warning"`` so the usual ``node_end`` event still carries the full
        ``NodeExecutionResult`` (``status="cancelled"``).

        Override in subclasses for extra teardown; call ``super()._on_stop(result, message)`` to keep telemetry.
        """
        if self._run_event_hook:
            self._run_event_hook.emit(
                NodeRunEventType.NODE_STOP,
                {"result": result, "message": message},
            )
        self._on_end(result, level="warning", message=message)

    @overload
    def run(
        self,
        state: Dict[str, Any],
        input_params: Any = None,
        request: Optional[Dict[str, Any]] = None,
        *,
        background: Literal[False] = False,
        room: Optional[str] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        persist_to_db: bool = True,
        debug_mode: str = "debug",
        command: Optional[str] = None,
        user_id: str = "anonymous",
        exec_log: Any = None,
        output_format: Optional[str] = None,
    ) -> "NodeExecutionResult": ...

    @overload
    def run(
        self,
        state: Dict[str, Any],
        input_params: Any = None,
        request: Optional[Dict[str, Any]] = None,
        *,
        background: Literal[True],
        room: Optional[str] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        persist_to_db: bool = True,
        debug_mode: str = "debug",
        command: Optional[str] = None,
        user_id: str = "anonymous",
        exec_log: Any = None,
        output_format: Optional[str] = None,
    ) -> str: ...

    def run(
        self,
        state: Dict[str, Any],
        input_params: Any = None,
        request: Optional[Dict[str, Any]] = None,
        *,
        background: bool = False,
        room: Optional[str] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        persist_to_db: bool = True,
        debug_mode: str = "debug",
        command: Optional[str] = None,
        user_id: str = "anonymous",
        exec_log: Any = None,
        output_format: Optional[str] = None,
    ) -> Union["NodeExecutionResult", str]:
        """
        Execute this node instance. Prefer obtaining the instance via :meth:`load` so resolution matches execution.

        With ``background=False`` (default), runs synchronously: ensures a default exec log if none is set,
        runs ``_on_start``, then :meth:`execute`.

        With ``background=True``, returns an execution id string and submits via :meth:`WorkflowEngine.run_node`.
        If the instance was created with :meth:`load`, ``mode`` / ``module_path`` / ``class_name`` are replayed;
        otherwise ``prod`` and registry lookup by ``self.node_id`` are used. ``exec_log`` is ignored when
        ``background=True`` (engine owns the sink).

        Args:
            state: Workflow/context state dict.
            input_params: Parameters dict or compatible mapping.
            request: Optional dict merged into the run request (e.g. tracing, ``workflow_engine_debug_mode``).
            background: If True, non-blocking engine execution.
            room: Socket.IO room / client id for realtime logs (background path).
            callback: Optional callback when background completes.
            persist_to_db: Persist execution logs (background).
            debug_mode: ``trace`` | ``debug`` (normalized); affects interactive forms when the execution log supports ``request_and_wait``.
            command: CLI/command string for audit.
            user_id: Audit user id.
            exec_log: Explicit sink for synchronous runs; ignored when ``background=True``.
            output_format: Rendering hint (``json``, ``html``, …); validated against :meth:`allowed_output_formats`.

        Returns:
            :class:`NodeExecutionResult` when ``background=False``; execution id ``str`` when ``background=True``.
        """
        if background:
            from ..workflow_engine import get_shared_engine

            spec = getattr(self, "_load_spec", None) or {}
            mode = spec.get("mode", "prod")
            module_path = spec.get("module_path")
            class_name = spec.get("class_name")
            params_dict = self._to_dict(input_params) if input_params is not None else {}
            if exec_log is not None:
                warnings.warn(
                    "exec_log is ignored when background=True; the engine builds the sink for run_node.",
                    UserWarning,
                    stacklevel=2,
                )
            return get_shared_engine().run_node(
                node_id=self.node_id,
                state=state,
                input_params=params_dict,
                mode=mode,
                module_path=module_path,
                class_name=class_name,
                room=room,
                background=True,
                persist_to_db=persist_to_db,
                callback=callback,
                debug_mode=normalize_debug_mode(debug_mode, default="debug"),
                command=command,
                user_id=user_id,
                run_request_extras=request,
                output_format=output_format,
            )

        engine_mode = None
        if request is not None and isinstance(request, dict):
            engine_mode = request.get("workflow_engine_debug_mode")

        prev_log = self._exec_log
        if exec_log is not None:
            self.set_exec_log(exec_log)
        elif prev_log is None:
            self.set_exec_log(create_default_node_exec_log(self))

        prev_debug_standalone: Optional[bool] = None
        if engine_mode is None:
            dm = normalize_debug_mode(debug_mode, default="debug")
            prev_debug_standalone = self._debug_mode
            self.set_debug_mode(
                dm == "debug"
                and callable(getattr(self._exec_log, "request_and_wait", None))
            )
        else:
            normalize_debug_mode(engine_mode)

        req_of: Optional[str] = None
        if output_format is not None:
            req_of = str(output_format).lower().strip()

        try:
            try:

                if self._run_event_hook:
                    self._run_event_hook.emit(NodeRunEventType.NODE_RUN, {"request": request})

                req = request if request is not None else {
                    "state": self._to_dict(state) if state else {},
                    "input_params": self._to_dict(input_params) if input_params is not None else {},
                }
                proceed = self._on_start(req)
            except (ValueError, PydanticValidationError) as e:
                err_msg = str(e)
                logger.warning("Bad request in _on_start: %s", e)
                execution_id = self._generate_execution_id()
                started_at = datetime.now(timezone.utc)
                ended_at = datetime.now(timezone.utc)
                raw_state = self._to_dict(state) if state else {}
                raw_params = self._to_dict(input_params) if input_params is not None else {}
                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="bad_request",
                    response=NodeResponseData(
                        output={"output_format": "json", "data": {"bad_request": True, "detail": err_msg}},
                        metadata={},
                    ),
                    initial_state=raw_state,
                    input_params=raw_params,
                    final_state={},
                    started_at=started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time="0s",
                    event_logs=[],
                )
                if self._exec_log:
                    self._exec_log.log_error(f"Bad request in _on_start: {err_msg}", error_type="bad_request", detail=err_msg)
                    result.event_logs = self._exec_log.get_events()
                    self._on_error(result)
                return result
            except Exception as e:
                err_msg = str(e)
                logger.exception("Unhandled error in Node.run (_on_start): %s", e)
                execution_id = self._generate_execution_id()
                started_at = datetime.now(timezone.utc)
                ended_at = datetime.now(timezone.utc)
                raw_state = self._to_dict(state) if state else {}
                raw_params = self._to_dict(input_params) if input_params is not None else {}
                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="internal_error",
                    response=NodeResponseData(
                        output={"output_format": "json", "data": {"internal_error": True, "detail": err_msg, "stage": "run"}},
                        metadata={},
                    ),
                    initial_state=raw_state,
                    input_params=raw_params,
                    final_state={},
                    started_at=started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time="0s",
                    event_logs=[],
                )
                if self._exec_log:
                    self._exec_log.log_error(f"Unhandled error in run(): {err_msg}", error_type="internal_error", detail=err_msg)
                    result.event_logs = self._exec_log.get_events()
                    self._on_error(result)
                return result

            if proceed is not True:
                execution_id = self._generate_execution_id()
                started_at = datetime.now(timezone.utc)
                ended_at = datetime.now(timezone.utc)
                raw_state = self._to_dict(state) if state else {}
                raw_params = self._to_dict(input_params) if input_params is not None else {}
                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="cancelled",
                    response=NodeResponseData(
                        output={"output_format": "json", "data": {"cancelled": True, "reason": "Execution stopped by _on_start"}},
                        metadata={},
                    ),
                    initial_state=raw_state,
                    input_params=raw_params,
                    final_state={},
                    started_at=started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time="0s",
                    event_logs=[],
                )
                if self._exec_log:
                    self._exec_log.log("warning", "Execution stopped by _on_start")
                    result.event_logs = self._exec_log.get_events()
                    self._on_end(result)
                return result
            return self.execute(state, input_params, requested_output_format=req_of)
        finally:
            if engine_mode is None and prev_debug_standalone is not None:
                self.set_debug_mode(prev_debug_standalone)
            if exec_log is not None:
                self.set_exec_log(prev_log)
            elif prev_log is None:
                self.set_exec_log(None)
            self.set_run_event_hook(None)

    def execute(
        self,
        state: Dict[str, Any],
        input_params: Any = None,
        *,
        requested_output_format: Optional[str] = None,
    ) -> NodeExecutionResult:
        """
        Run validation, optional debug form, :meth:`_do_execute`, output/metadata validation, and lifecycle hooks.

        Prefer :meth:`run` for public calls (it sets up exec log and ``_on_start``). The engine calls
        :meth:`execute` when the node is already wired.

        Args:
            state: Workflow/context state.
            input_params: Direct parameters (dict or mapping).
            requested_output_format: CLI/UI rendering format; must be in :meth:`allowed_output_formats` if set.

        Returns:
            :class:`NodeExecutionResult` with ``status``, ``response``, timestamps, and ``event_logs``.

        **Errors**

        After a successful :meth:`_on_init`, unexpected :exc:`Exception` in the main phase is turned into
        ``status="internal_error"`` (not re-raised) for symmetry with :meth:`WorkflowEngine.run_node`.
        :exc:`CancellationError` is handled separately (cooperative stop → ``cancelled``). Other
        :exc:`BaseException` subclasses are not caught.
        """
        if self._status == NodeRunStatus.IDLE:
            self._status = NodeRunStatus.RUNNING
        # Initialize and validate inputs via _on_init. init_result holds execution_id, timestamps,
        # validated state_dict/params_dict, initial_state, and state_for_node for the rest of execute.
        # If _on_init raises ValueError or Pydantic ValidationError, we catch it here, notify the
        # client via exec_log (log + terminal hooks), and return a NodeExecutionResult with
        # status="validation_error" instead of re-raising.
        try:
            init_result = self._on_init(
                state,
                input_params,
                requested_output_format=requested_output_format,
            )
            if self._run_event_hook:
                self._run_event_hook.emit(
                    NodeRunEventType.NODE_INIT_COMPLETED,
                    {
                        "state": dict(init_result.state_dict),
                        "input_params": dict(init_result.params_dict),
                        "output_format": init_result.requested_output_format,
                    },
                )

        except (ValueError, PydanticValidationError) as init_err:
            err_msg = str(init_err)
            logger.warning("Init/validation failed: %s", init_err)
            if self._exec_log:
                self._exec_log.log_error(f"Init/validation failed: {err_msg}", error_type="validation_error", detail=err_msg)
            execution_id = self._generate_execution_id()
            started_at = datetime.now(timezone.utc)
            ended_at = datetime.now(timezone.utc)
            raw_state = self._to_dict(state) if state else {}
            raw_params = self._to_dict(input_params) if input_params is not None else {}
            result = NodeExecutionResult(
                **self._node_identity(),
                node_id=self.node_id,
                status="validation_error",
                response=NodeResponseData(
                    output={"output_format": "json", "data": {"validation_error": True, "detail": err_msg}},
                    metadata={},
                ),
                initial_state=raw_state,
                input_params=raw_params,
                final_state={},
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
                elapsed_time="0s",
                event_logs=[],
            )
            if self._exec_log:
                result.event_logs = self._exec_log.get_events()
                self._on_error(result)
            return result

        self._active_run_execution_id = init_result.execution_id
        try:
            # _on_init completed successfully; execution continues with the validated context
            # (debug form if enabled, then _do_execute).
            # log_node_execute sends to exec_log (and Python logging via _log_to_console); no separate logger call
            # if self._exec_log:
            #     self._exec_log.log_node_execute(state=init_result.initial_state, input_params=init_result.params_dict)
            # TODO: uncomment when we want node_execute events in the buffer
            # In debug mode, show interactive form with VALIDATED values (defaults applied)
            if self._debug_mode and self._exec_log:
                try:
                    from nos.io_adapters.input_form_mapping import create_form_request_payload

                    # Build form payload using VALIDATED values (with defaults applied)
                    form_payload = create_form_request_payload(
                        state_schema=self.input_state_schema,
                        params_schema=self.input_params_schema,
                        state_values=init_result.state_dict,
                        params_values=init_result.params_dict,
                        node_id=self.node_id,
                        title=self.__class__.__name__,
                    )

                    # Only show form if there are fields to edit
                    has_state_fields = form_payload.get("state", {}).get("fields", [])
                    has_params_fields = form_payload.get("params", {}).get("fields", [])
                
                    if has_state_fields or has_params_fields:
                        timeout_sec = self._get_form_timeout_seconds(init_result.state_dict)
                        self._exec_log.log("info", "📝 Waiting for state/params input...")
                        # Form request + "waiting" + response routing: all handled by request_and_wait
                        # (execution_log + execution_request with form_payload as data).
                        form_response = self.request_and_wait(
                            event_type="Form input",
                            data=form_payload,
                            timeout=timeout_sec,
                        )
                    
                        if form_response:
                            # Lifecycle hook: subclasses can override _on_input to customize handling.
                            self._on_input(form_response)
                            if form_response.get("cancelled"):
                                self._exec_log.log("warning", "Execution cancelled by user")
                                ended_at = datetime.now(timezone.utc)
                                elapsed_time = time.perf_counter() - init_result.t0

                                result = NodeExecutionResult(
                                    **self._node_identity(),
                                    node_id=self.node_id,
                                    status="cancelled",
                                    response=NodeResponseData(
                                        output={"output_format": "json", "data": {"cancelled": True, "reason": "User cancelled form input"}},
                                        metadata={},
                                    ),
                                    initial_state=init_result.initial_state,
                                    input_params=dict(init_result.params_dict),
                                    final_state=init_result.state_dict,
                                    started_at=init_result.started_at,
                                    ended_at=ended_at,
                                    elapsed_time=_format_elapsed(elapsed_time),
                                    event_logs=[],
                                )
                            
                                if self._exec_log:
                                    result.event_logs = self._exec_log.get_events()
                                    self._on_end(result)

                                return result
                        
                            # Update values with user modifications from form
                            if "state" in form_response and form_response["state"]:
                                init_result.state_dict.update(form_response["state"])
                            if "params" in form_response and form_response["params"]:
                                mutable_params = dict(init_result.params_dict)
                                mutable_params.update(form_response["params"])
                                init_result.params_dict = MappingProxyType(mutable_params)

                            # Re-validate form data against schemas (client data must not be trusted)
                            # Note: output_format is a framework-level parameter — it is NOT a form field
                            # and must NOT be read from form_response. It stays as resolved in _on_init.
                            try:
                                init_result.state_dict = self._validate_with_schema(
                                    self.input_state_schema, init_result.state_dict, {}
                                )
                                init_result.params_dict = MappingProxyType(self._validate_with_schema(
                                    self.input_params_schema, dict(init_result.params_dict), {}
                                ))
                                # Mutate original state (ObservableStateDict) in place so engine's map_to_shared
                                # picks up updates. Do not replace state_for_node with a new dict.
                                if init_result.original_state is not None:
                                    init_result.original_state.clear()
                                    init_result.original_state.update(init_result.state_dict)
                                    init_result.state_for_node = init_result.original_state
                                else:
                                    init_result.state_for_node = init_result.state_dict
                                init_result.initial_state = dict(init_result.state_dict)
                            except Exception as val_err:
                                err_msg = str(val_err)
                                logger.warning("Form re-validation failed: %s", val_err)
                                if self._exec_log:
                                    self._exec_log.log_error(
                                        f"Form validation failed: {err_msg}",
                                        error_type="form_validation_error",
                                        detail=err_msg,
                                    )
                                ended_at = datetime.now(timezone.utc)
                                elapsed_time = time.perf_counter() - init_result.t0
                                try:
                                    result = NodeExecutionResult(
                                        **self._node_identity(),
                                        node_id=self.node_id,
                                        status="validation_error",
                                        response=NodeResponseData(
                                            output={"output_format": "json", "data": {"validation_error": True, "detail": err_msg}},
                                            metadata={},
                                        ),
                                        initial_state=init_result.initial_state,
                                        input_params=dict(init_result.params_dict),
                                        final_state=init_result.state_dict,
                                        started_at=init_result.started_at,
                                        ended_at=ended_at,
                                        elapsed_time=_format_elapsed(elapsed_time),
                                        event_logs=[],
                                    )
                                    if self._exec_log:
                                        result.event_logs = self._exec_log.get_events()
                                        self._on_error(result)
                                    return result
                                except Exception:
                                    raise val_err

                         #   self._exec_log.log("info", "Form submitted, continuing execution...")
                        else:
                            self._exec_log.log("warning", "Form timeout, using validated values")

                except CancellationError:
                    raise  # bubble up to outer CancellationError handler (stop during form wait)
                except Exception as form_error:
                    err_msg = str(form_error)
                    logger.warning("Form request failed: %s", form_error)
                    if self._exec_log:
                        self._exec_log.log_error(
                            f"Form request failed: {err_msg}",
                            error_type="form_validation_error",
                            detail=err_msg,
                        )
                    ended_at = datetime.now(timezone.utc)
                    elapsed_time = time.perf_counter() - init_result.t0
                    result = NodeExecutionResult(
                        **self._node_identity(),
                        node_id=self.node_id,
                        status="form_validation_error",
                        response=NodeResponseData(
                            output={"output_format": "json", "data": {"form_error": True, "detail": err_msg}},
                            metadata={},
                        ),
                        initial_state=init_result.initial_state,
                        input_params=dict(init_result.params_dict),
                        final_state=init_result.state_dict,
                        started_at=init_result.started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        elapsed_time=_format_elapsed(elapsed_time),
                        event_logs=[],
                    )
                    if self._exec_log:
                        result.event_logs = self._exec_log.get_events()
                        self._on_error(result)
                    return result

            # ── Cancellable phase: pre-execute log + _do_execute + output validation ──
            #
            # try / except CancellationError: cooperative stop (log when stop requested).
            # except Exception: safety net for any other failure after init (e.g. TypeError during
            # output_schema access, bugs post-_do_execute) — returns internal_error NodeExecutionResult
            # so direct node.run/execute callers get a structured result like engine.run_node.
            try:
                if self._exec_log:
                    self._exec_log.log(
                        "info",
                        event="starting execution",
                        message=f"{self.node_id} starting execution...",
                        state=dict(init_result.state_dict),
                        input_params=dict(init_result.params_dict),
                    )

                # Execute the node logic with (possibly user-modified) validated values
                try:
                    output = self._do_execute(init_result.state_for_node, init_result.params_dict)
                except CancellationError:
                    raise  # bubble up to outer CancellationError handler
                except Exception as do_exec_err:
                    err_msg = str(do_exec_err)
                    logger.exception("Unhandled error in _do_execute: %s", do_exec_err)
                    if self._exec_log:
                        self._exec_log.log_error(
                            f"Execution failed: {err_msg}",
                            error_type="internal_error",
                            detail=err_msg,
                        )
                    elapsed = time.perf_counter() - init_result.t0
                    ended_at = datetime.now(timezone.utc)
                    result = NodeExecutionResult(
                        **self._node_identity(),
                        node_id=self.node_id,
                        status="internal_error",
                        response=NodeResponseData(
                            output={"output_format": "json", "data": {"internal_error": True, "detail": err_msg}},
                            metadata={},
                        ),
                        initial_state=init_result.initial_state,
                        input_params=dict(init_result.params_dict),
                        final_state=self._to_dict(init_result.state_for_node) if init_result.state_for_node else {},
                        started_at=init_result.started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        elapsed_time=_format_elapsed(elapsed),
                        event_logs=[],
                    )
                    if self._exec_log:
                        result.event_logs = self._exec_log.get_events()
                        self._on_error(result)
                    return result

                # Guard: _do_execute must return a NodeOutput. A silent failure (swallowed
                # exception, missing return, wrong type) would otherwise crash at the first
                # attribute access below without ever calling _on_error.
                if not isinstance(output, NodeOutput):
                    err_msg = (
                        f"_do_execute returned {type(output).__name__!r} instead of NodeOutput. "
                        "Likely a silent failure (swallowed exception or missing return statement)."
                    )
                    logger.error("Invalid _do_execute return in %s: %s", self.__class__.__name__, err_msg)
                    if self._exec_log:
                        self._exec_log.log_error(err_msg, error_type="internal_error", detail=err_msg)
                    elapsed = time.perf_counter() - init_result.t0
                    ended_at = datetime.now(timezone.utc)
                    result = NodeExecutionResult(
                        **self._node_identity(),
                        node_id=self.node_id,
                        status="internal_error",
                        response=NodeResponseData(
                            output={"output_format": "json", "data": {"internal_error": True, "detail": err_msg}},
                            metadata={},
                        ),
                        initial_state=init_result.initial_state,
                        input_params=dict(init_result.params_dict),
                        final_state=self._to_dict(init_result.state_for_node) if init_result.state_for_node else {},
                        started_at=init_result.started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        elapsed_time=_format_elapsed(elapsed),
                        event_logs=[],
                    )
                    if self._exec_log:
                        result.event_logs = self._exec_log.get_events()
                        self._on_error(result)
                    return result

                if self._exec_log:
                    out_dict = output.output if hasattr(output, "output") else {}
                    meta_dict = output.metadata if hasattr(output, "metadata") else {}
                    self._exec_log.log(
                        "info",
                        event="output ready",
                        message=f"{self.__class__.__name__} output ready",
                        node_output={"output": out_dict, "metadata": meta_dict},
                    )

                # Validate output and metadata with node schemas if defined
                if self._exec_log:
                    self._exec_log.log(
                        "info",
                        event="validating output",
                        message=f"{self.__class__.__name__} validating output and metadata...",
                    )

                # --- Resolve output_format (priority: CLI > node runtime > node default) ---
                # 1. CLI --output_format (requested_output_format, None if not provided)
                # 2. output_format in NodeOutput.output — optional runtime override from _do_execute
                # 3. self.default_output_format — declared at class level, always has a value (base = "json")
                raw_out = output.output if isinstance(output.output, dict) else {}
                node_runtime_format = str(raw_out.get("output_format") or "").lower().strip() or None
                if init_result.requested_output_format is not None:
                    effective_format = init_result.requested_output_format   # CLI wins
                elif node_runtime_format:
                    effective_format = node_runtime_format                    # runtime override from _do_execute
                else:
                    effective_format = self.default_output_format             # class-level default (always set)

                # Extract data (backward-compat: if 'data' key absent, treat whole output as data)
                if "data" in raw_out:
                    data_val: Any = raw_out["data"]
                else:
                    data_val = raw_out
                    logger.warning(
                        "Node %s returned NodeOutput.output without 'data' key; treating entire output as data",
                        self.node_id,
                    )

                out_meta = output.metadata or {}
                try:
                    # Validate data with output_schema when defined
                    if self.output_schema:
                        if isinstance(data_val, dict):
                            validated = self.output_schema(**data_val)
                            data_val = (
                                validated.model_dump()
                                if hasattr(validated, "model_dump")
                                else dict(validated)
                            )
                        elif issubclass(self.output_schema, RootModel):
                            validated = self.output_schema.model_validate(data_val)
                            data_val = validated.root
                    if self.metadata_schema:
                        validated_meta = self.metadata_schema(**out_meta)
                        out_meta = validated_meta.model_dump() if hasattr(validated_meta, "model_dump") else dict(validated_meta)
                except PydanticValidationError as val_err:
                    err_msg = str(val_err)
                    logger.warning(f"Output/metadata validation failed: {val_err}")
                    if self._exec_log:
                        self._exec_log.log_error(f"Output validation failed: {err_msg}", error_type="output_validation_error", detail=err_msg)
                    elapsed = time.perf_counter() - init_result.t0
                    ended_at = datetime.now(timezone.utc)
                    result = NodeExecutionResult(
                        **self._node_identity(),
                        node_id=self.node_id,
                        status="output_validation_error",
                        response=NodeResponseData(
                            output={"output_format": "json", "data": {"output_validation_error": True, "detail": err_msg, "raw_output": data_val}},
                            metadata={"raw_metadata": out_meta},
                        ),
                        initial_state=init_result.initial_state,
                        input_params=dict(init_result.params_dict),
                        final_state=self._to_dict(init_result.state_for_node) if init_result.state_for_node else {},
                        started_at=init_result.started_at.isoformat(),
                        ended_at=ended_at.isoformat(),
                        elapsed_time=_format_elapsed(elapsed),
                        event_logs=[],
                    )
                    if self._exec_log:
                        result.event_logs = self._exec_log.get_events()
                        self._on_error(result)
                    return result

                if self._exec_log:
                    self._exec_log.log(
                        "info",
                        event="output validated",
                        message=f"{self.__class__.__name__} output validated",
                    )

                elapsed = time.perf_counter() - init_result.t0
                ended_at = datetime.now(timezone.utc)
                final_state = self._to_dict(init_result.state_for_node) if init_result.state_for_node else {}

                out_data = {"output_format": effective_format, "data": data_val}

                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="completed",
                    response=NodeResponseData(output=out_data, metadata=out_meta),
                    initial_state=init_result.initial_state,
                    input_params=dict(init_result.params_dict),
                    final_state=final_state,
                    started_at=init_result.started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time=_format_elapsed(elapsed),
                    event_logs=[],
                )

                if self._exec_log:
                    result.event_logs = self._exec_log.get_events()
                    # NodeExecutionResult is already sent by on_execution_complete (engine callback).
                    # log_node_output temporarily disabled (real-time output+metadata).
                    # self._exec_log.log_node_output(out_data, out_meta)
                    self._on_end(result)

                return result

            except CancellationError:
                # ── Transparent cooperative stop ─────────────────────────────────────
                # Raised by log() when exec_log.request_stop() was called.
                # Node developers write NO cancellation code; this is pure infrastructure.
                elapsed = time.perf_counter() - init_result.t0
                ended_at = datetime.now(timezone.utc)
                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="cancelled",
                    response=NodeResponseData(
                        output={"output_format": "json", "data": {"cancelled": True, "reason": "Execution stopped by user"}},
                        metadata={},
                    ),
                    initial_state=init_result.initial_state,
                    input_params=dict(init_result.params_dict),
                    final_state=self._to_dict(init_result.state_for_node) if init_result.state_for_node else {},
                    started_at=init_result.started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time=_format_elapsed(elapsed),
                    event_logs=[],
                )
                if self._exec_log:
                    result.event_logs = self._exec_log.get_events()
                    self._on_stop(result, message="Execution cancelled by user")
                return result

            except Exception as unexpected_err:
                # Post-init failures not handled by narrower handlers (e.g. non-Pydantic errors in
                # output path, attribute errors). Does not catch CancellationError (handled above).
                err_msg = str(unexpected_err)
                logger.exception("Unexpected error in Node.execute (post-init): %s", unexpected_err)
                if self._exec_log:
                    self._exec_log.log_error(
                        f"Execution failed: {err_msg}",
                        error_type="internal_error",
                        detail=err_msg,
                    )
                elapsed = time.perf_counter() - init_result.t0
                ended_at = datetime.now(timezone.utc)
                result = NodeExecutionResult(
                    **self._node_identity(),
                    node_id=self.node_id,
                    status="internal_error",
                    response=NodeResponseData(
                        output={
                            "output_format": "json",
                            "data": {
                                "internal_error": True,
                                "detail": err_msg,
                                "stage": "execute",
                            },
                        },
                        metadata={},
                    ),
                    initial_state=init_result.initial_state,
                    input_params=dict(init_result.params_dict),
                    final_state=self._to_dict(init_result.state_for_node) if init_result.state_for_node else {},
                    started_at=init_result.started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                    elapsed_time=_format_elapsed(elapsed),
                    event_logs=[],
                )
                if self._exec_log:
                    result.event_logs = self._exec_log.get_events()
                    self._on_error(result)
                return result

        finally:
            self._active_run_execution_id = None

    @abstractmethod
    def _do_execute(self, state_dict: Dict[str, Any], params_dict: Dict[str, Any]) -> NodeOutput:
        """
        Main execution method of the node. Subclasses must implement this.

        INPUTS
        ------
        state_dict : dict
            Workflow/context state validated against input_state_schema.
            May be ObservableStateDict when run in a workflow engine.

        params_dict : dict
            Direct input parameters validated against input_params_schema.

        RULES
        -----
        - NEVER modify params_dict (treat as read-only).
        - ALWAYS read parameters from params_dict.
        - ALWAYS return NodeOutput.
        - The output dict MUST match output_schema (if defined).
        - The metadata dict MUST match metadata_schema (if defined).

        RETURNS
        -------
        NodeOutput
            With output and metadata dicts.
        """
        pass

    def request_cooperative_stop(self, execution_id: Optional[str] = None) -> None:
        """
        Ask the current (or given) run to stop cooperatively.

        Resolution order for the execution id when ``execution_id`` is omitted:

        1. ``execution_id`` argument
        2. ``execution_id`` on the attached execution log (engine / API runs)
        3. :attr:`_active_run_execution_id` while :meth:`execute` is in progress

        If none apply, this is a no-op (debug log only). Otherwise: calls
        :meth:`~nos.core.execution_log.event_log_buffer.EventLogBuffer.request_stop`
        when a log is attached, and notifies the process-wide workflow engine (lazy import)
        so registered runs get the same signal and cancellation metadata.

        Normal pattern is a single active run per node instance; overlapping runs on the same
        instance are unsupported — pass an explicit ``execution_id`` if you must disambiguate.
        """
        resolved = execution_id
        if not resolved and self._exec_log:
            resolved = self._exec_log.execution_id
        if not resolved:
            resolved = self._active_run_execution_id
        if not resolved:
            logger.debug(
                "request_cooperative_stop: no execution_id for node_id=%r; nothing to stop",
                self.node_id,
            )
            return
        if self._exec_log:
            self._exec_log.request_stop()
        try:
            from ..workflow_engine import get_shared_engine

            get_shared_engine().stop_execution(resolved)
        except Exception as exc:
            logger.warning("request_cooperative_stop: engine notification failed: %s", exc, exc_info=True)

    def set_exec_log(self, exec_log: Optional["EventLogBuffer"]):
        """
        Set the execution log sink (EventLogBuffer / platform EventLog) and attach the scoped
        per-run hook manager (adapters forward to this sink). Pass ``None`` to clear.

        Called by workflow engine or API routes before execution.
        """
        self._exec_log = exec_log
        if exec_log is None:
            self._run_event_hook = None
        else:
            from ...execution_log.node_run_hooks import attach_node_run_hooks_bus

            attach_node_run_hooks_bus(self, exec_log)

    def set_run_event_hook(self, hook) -> None:
        """Internal: scoped :class:`~nos.hooks.manager.EventHookManager` from :meth:`set_exec_log`; cleared in :meth:`run` ``finally``."""
        self._run_event_hook = hook

    def set_debug_mode(self, enabled: bool = True):
        """
        Enable or disable debug mode for this node.
        
        In debug mode, an interactive form is shown before execution
        allowing the user to review and modify state/params.
        
        Args:
            enabled: True to enable debug mode (show form), False to skip
        """
        self._debug_mode = enabled

    def request_and_wait_result(
        self,
        event_type: str,
        data: Dict[str, Any],
        timeout: float = 60.0,
        *,
        no_exec_log_detail: Optional[str] = None,
        no_channel_detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a request to the client and wait for a response; return a structured outcome.

        This is the single implementation used by :meth:`request_and_wait` and
        :meth:`request_form_input`. Use it when you need to distinguish **no execution log**,
        **timeout**, and **errors** (exceptions from the exec_log / transport layer).

        Returns:
            A dict with:

            - **ok** (``bool``): ``True`` only if the client returned a payload.
            - **status** (``str``): ``success`` | ``timeout`` | ``no_channel`` | ``error``.
              The value ``no_channel`` is retained for compatibility; it means no :attr:`exec_log` is attached.
            - **detail** (``str | None``): Human-readable reason when ``ok`` is false.
            - **error_type** (``str | None``): Exception class name when ``status == "error"``.
            - **response** (``dict | None``): Client payload when ``ok`` is true; otherwise ``None``.

        Args:
            no_exec_log_detail: Custom message when ``self._exec_log`` is unset (default explains missing log).
            no_channel_detail: Deprecated alias for ``no_exec_log_detail``.
        """
        if no_channel_detail is not None:
            warnings.warn(
                "no_channel_detail is deprecated; use no_exec_log_detail instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        detail_no_exec_log = no_exec_log_detail or no_channel_detail or "No execution log attached."
        if not self._exec_log:
            return {
                "ok": False,
                "status": "no_channel",
                "detail": detail_no_exec_log,
                "error_type": None,
                "response": None,
            }
        try:
            raw = self._exec_log.request_and_wait(event_type, data, timeout)
        except Exception as e:
            logger.warning(
                "request_and_wait failed (event_type=%r): %s",
                event_type,
                e,
                exc_info=True,
            )
            return {
                "ok": False,
                "status": "error",
                "detail": str(e),
                "error_type": type(e).__name__,
                "response": None,
            }
        if raw is None:
            return {
                "ok": False,
                "status": "timeout",
                "detail": f"No response within {timeout} seconds.",
                "error_type": None,
                "response": None,
            }
        return {
            "ok": True,
            "status": "success",
            "detail": None,
            "error_type": None,
            "response": raw,
        }

    def request_and_wait(
        self,
        event_type: str,
        data: Dict[str, Any],
        timeout: float = 60.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a request to the client and wait for response.

        Convenience wrapper around :meth:`request_and_wait_result`: returns the client
        **response** dict on success, or ``None`` if there is no :attr:`exec_log`, the wait times out,
        or the exec_log layer raises (errors are logged). To inspect **why** it failed, call
        :meth:`request_and_wait_result` instead.

        Use this when the node needs user input, approval, or any other bidirectional
        interaction during execution.

        Args:
            event_type: Event type to emit (e.g., "user_approval_required", "input_requested")
            data: Event data to send to client
            timeout: Maximum time to wait in seconds (default 60s)

        Returns:
            Response data from client, or ``None`` on failure (see above).

        Example:
            def _do_execute(self, state_dict, params_dict):
                response = self.request_and_wait(
                    "confirmation_required",
                    {"message": "Proceed with operation?", "options": ["yes", "no"]},
                    timeout=120.0,
                )
                if response and response.get("choice") == "yes":
                    ...
        """
        env = self.request_and_wait_result(event_type, data, timeout)
        if env["ok"]:
            return env["response"]
        return None

    def request_form_input(
        self,
        state_values: Optional[Dict[str, Any]] = None,
        params_values: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Request interactive form input from the user.

        Sends a form to the console for the user to edit state and parameters.
        The form is rendered based on the node's input_state_schema and input_params_schema.

        Always returns a structured dict (never None). Inspect ``ok`` and ``status``:

        - ``ok`` is True only when the client submitted successfully (``status == "success"``).
        - ``status`` is one of: ``success``, ``cancelled``, ``timeout``, ``no_channel`` (no :attr:`exec_log`), ``error``.
        - On failure paths, ``detail`` explains why; ``error_type`` is set when ``status == "error"``.
        - ``state`` / ``params`` are the submitted values when present; otherwise None.

        Payload build errors use ``status="error"``; the wait phase uses :meth:`request_and_wait_result`
        (shared with :meth:`request_and_wait`) for ``timeout`` / missing exec_log (``no_channel``) / sink ``error``.

        Args:
            state_values: Current state values to populate the form
            params_values: Current param values to populate the form
            timeout: Maximum wait time in seconds (default 5 minutes)
            title: Optional form title

        Returns:
            Structured result dict (see above).

        Example:
            def _do_execute(self, state_dict, params_dict):
                response = self.request_form_input(
                    state_values=state_dict,
                    params_values=params_dict,
                    title="Review Configuration",
                )
                if response.get("ok"):
                    if response.get("state") is not None:
                        state_dict = response["state"]
                    if response.get("params") is not None:
                        params_dict = response["params"]
                elif response.get("status") == "cancelled":
                    ...
                elif response.get("status") in ("timeout", "no_channel", "error"):
                    # use response.get("detail"), fall back behaviour, etc.
                    ...
        """
        try:
            from nos.io_adapters.input_form_mapping import create_form_request_payload

            payload = create_form_request_payload(
                state_schema=self.input_state_schema,
                params_schema=self.input_params_schema,
                state_values=state_values,
                params_values=params_values,
                node_id=self.node_id,
                title=title or f"Configure {self.name}",
            )
        except Exception as e:
            logger.warning("Failed to build form input payload: %s", e, exc_info=True)
            return {
                "ok": False,
                "status": "error",
                "detail": str(e),
                "error_type": type(e).__name__,
                "state": None,
                "params": None,
            }

        env = self.request_and_wait_result(
            "form_input",
            payload,
            timeout,
            no_exec_log_detail="No execution log attached; interactive form is unavailable.",
        )
        if not env["ok"]:
            out_fail: Dict[str, Any] = {
                "ok": False,
                "status": env["status"],
                "detail": env.get("detail"),
                "state": None,
                "params": None,
            }
            if env.get("error_type"):
                out_fail["error_type"] = env["error_type"]
            return out_fail

        raw = env["response"] or {}
        out: Dict[str, Any] = {**raw}
        if out.get("cancelled"):
            out["ok"] = False
            out["status"] = "cancelled"
        else:
            out["ok"] = True
            out["status"] = "success"
        out.setdefault("state", None)
        out.setdefault("params", None)
        return out

    @property
    def default_state_mapping(self) -> Optional['StateMapping']:
        """
        Define default state mapping for this node.

        This mapping defines how workflow state is converted to node input
        and how node output is converted back to workflow state updates.

        Returns:
            StateMapping instance or None to use identity mapping (backward compatible)
        """
        if self._default_state_mapping is None and StateMapping is not None:
            if create_identity_mapping:
                return create_identity_mapping(f"Default mapping for {self.node_id}")
        return self._default_state_mapping

    def set_default_state_mapping(self, mapping: Optional['StateMapping']):
        """
        Set default state mapping for this node.

        Args:
            mapping: StateMapping instance or None to use identity mapping
        """
        self._default_state_mapping = mapping
