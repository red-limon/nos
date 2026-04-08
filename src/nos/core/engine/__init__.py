"""
Engine package: workflow/node orchestration, registry, plugin loading, and domain types.

Subpackages use singular names: :mod:`node`, :mod:`link`, :mod:`workflow`.
Execution logging remains at :mod:`nos.core.execution_log`.
"""

from .base import (
    AI_Node,
    AlwaysLink,
    ChainLink,
    Link,
    LinkResult,
    Node,
    NodeExecutionResult,
    NodeInputSchema,
    NodeOutput,
    NodeResponseData,
    NodeStateSchema,
    NodeWorkflow,
    ParallelNode,
    Workflow,
    WorkflowExecutionResult,
    WorkflowOutput,
    WorkflowResponseData,
    WorkflowStatus,
)
from .registry import WorkflowRegistry, workflow_registry
from .workflow_engine import WorkflowEngine, get_shared_engine

__all__ = [
    "AI_Node",
    "AlwaysLink",
    "ChainLink",
    "Link",
    "LinkResult",
    "Node",
    "NodeExecutionResult",
    "NodeInputSchema",
    "NodeOutput",
    "NodeResponseData",
    "NodeStateSchema",
    "NodeWorkflow",
    "ParallelNode",
    "Workflow",
    "WorkflowOutput",
    "WorkflowResponseData",
    "WorkflowExecutionResult",
    "WorkflowStatus",
    "WorkflowEngine",
    "WorkflowRegistry",
    "get_shared_engine",
    "workflow_registry",
]
