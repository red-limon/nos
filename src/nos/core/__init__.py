"""
Workflow Engine - Generic, extensible workflow execution system.

This module provides:
- Base classes for Workflow, Node, and Link
- Plugin system for dynamic loading
- Execution engine with multiple modes (sync, background, scheduled)
- Runtime hooks (execution sinks): EventLogBuffer (REST API); Socket.IO channel in nos.platform.execution_log
- REST API integration
"""

from .engine import (
    AI_Node,
    Link,
    Node,
    Workflow,
    WorkflowEngine,
    WorkflowExecutionResult,
    WorkflowOutput,
    WorkflowResponseData,
    WorkflowRegistry,
    WorkflowStatus,
    get_shared_engine,
    workflow_registry,
)
from .execution_log import BaseEvent, EventLogBuffer, ObservableStateDict
from .engine.workflow.state_mapping import (
    StateMapping,
    create_identity_mapping,
    create_namespace_mapping,
    create_prefix_mapping,
    create_simple_mapping,
    create_suffix_mapping,
    create_suffix_namespace_mapping,
)

ExecutionLogEntry = BaseEvent  # backward compatibility alias

__all__ = [
    "Workflow",
    "Node",
    "AI_Node",
    "Link",
    "WorkflowStatus",
    "WorkflowEngine",
    "WorkflowRegistry",
    "WorkflowOutput",
    "WorkflowResponseData",
    "WorkflowExecutionResult",
    "get_shared_engine",
    "workflow_registry",
    "EventLogBuffer",
    "ObservableStateDict",
    "ExecutionLogEntry",
    "StateMapping",
    "create_simple_mapping",
    "create_identity_mapping",
    "create_prefix_mapping",
    "create_namespace_mapping",
    "create_suffix_mapping",
    "create_suffix_namespace_mapping",
]
