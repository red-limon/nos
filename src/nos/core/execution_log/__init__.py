"""

Execution log — pluggable sinks for a run (structured events, Python logging, …).



Part of ``nos.core``. Not to be confused with :mod:`nos.hooks` (app-wide domain events).

Concrete sinks in core include :class:`EventLogBuffer`. Web realtime + bidirectional I/O

live in :mod:`nos.platform.execution_log` (:class:`~nos.platform.execution_log.EventLog`).



Provides:

- EventLogBuffer: collect structured events (REST / offline)

- ObservableStateDict: callback on state mutation

- Event schemas: Pydantic models for event payloads

- logger_factory: build platform ``EventLog`` via a callable registered at app bootstrap



Usage:

    from nos.core.execution_log import EventLogBuffer

    from nos.platform.execution_log import EventLog  # web / Socket.IO



The engine builds platform ``EventLog`` via :func:`logger_factory.build_event_log`;

register a factory from the Flask app (see ``nos.platform.services.event_log_factory``).



Pending client responses are routed via :data:`nos.platform.execution_log._event_log_registry`.

"""



from .events import (

    BaseEvent,

    NodeExecuteEvent,

    NodeExecutionRequestEvent,

    NodeInitEvent,

    NodeInitCompletedEvent,

    NodeFormResponseReceivedEvent,

    NodeStateChangedEvent,

    NodeOutputEvent,

    NodeEndEvent,

    NodeStopEvent,

    WorkflowStartEvent,

    WorkflowInitEvent,

    WorkflowInitCompletedEvent,

    WorkflowSharedStateChangedEvent,

    WorkflowExecutionResultEvent,

    LinkDecisionEvent,

    FormSchemaSentEvent,

    FormDataReceivedEvent,

    CustomEvent,

)

from .event_log_buffer import EventLogBuffer, ObservableStateDict

from .default_sinks import (
    create_default_node_exec_log,
    create_default_workflow_exec_log,
    normalize_debug_mode,
)

from .logger_factory import (

    build_event_log,

    clear_event_log_factory,

    get_event_log_factory,

    register_event_log_factory,

)

from .node_run_hooks import (

    NodeRunEventType,

    attach_node_run_hooks_bus,

    register_node_run_hooks_adapters,

)



__all__ = [

    "EventLogBuffer",

    "create_default_workflow_exec_log",

    "create_default_node_exec_log",

    "normalize_debug_mode",

    "build_event_log",

    "register_event_log_factory",

    "clear_event_log_factory",

    "get_event_log_factory",

    "ObservableStateDict",

    "BaseEvent",

    "NodeExecuteEvent",

    "NodeExecutionRequestEvent",

    "NodeInitEvent",

    "NodeInitCompletedEvent",

    "NodeFormResponseReceivedEvent",

    "NodeStateChangedEvent",

    "NodeOutputEvent",

    "NodeEndEvent",

    "NodeStopEvent",

    "WorkflowStartEvent",

    "WorkflowInitEvent",

    "WorkflowInitCompletedEvent",

    "WorkflowSharedStateChangedEvent",

    "WorkflowExecutionResultEvent",

    "LinkDecisionEvent",

    "FormSchemaSentEvent",

    "FormDataReceivedEvent",

    "CustomEvent",

    "NodeRunEventType",

    "attach_node_run_hooks_bus",

    "register_node_run_hooks_adapters",

]
