"""
State mapping system for isolating node state from shared workflow state.

This module provides a symmetric mapping between shared workflow state and node state:
- map_to_node: shared state → node state (initialization)
- map_to_shared: node state → shared state updates (after execution)

The same mapping is used in both directions. Node state is the single source of truth
for what flows back to shared state; output.output is a separate rich report.
"""

from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass


@dataclass
class StateMapping:
    """
    Symmetric mapping between shared workflow state and node state.

    Defines how data flows in both directions:
    - To node: shared state → node state (for input initialization)
    - To shared: node state → shared state updates (source is node's internal state)

    Attributes:
        input_mapping: Maps shared state to node state (map_to_node)
        output_mapping: Maps node state to shared state updates (map_to_shared)
        description: Optional description of the mapping
    """

    input_mapping: Callable[[Dict[str, Any]], Dict[str, Any]]
    output_mapping: Callable[[Dict[str, Any]], Dict[str, Any]]
    description: Optional[str] = None

    def map_to_node(self, shared_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map shared workflow state to node state (initialization).

        Args:
            shared_state: Current shared workflow state

        Returns:
            Dictionary for node input/state
        """
        return self.input_mapping(shared_state)

    def map_to_shared(self, node_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map node state to shared state updates.

        Source is the node's internal state after execution, not output.output.
        The engine merges the returned dict into the shared workflow state.

        Args:
            node_state: Node's state dict (after execute, possibly modified)

        Returns:
            Dictionary of updates to apply to shared workflow state
        """
        return self.output_mapping(node_state)

    def map_input(self, workflow_state: Dict[str, Any]) -> Dict[str, Any]:
        """Alias for map_to_node (backward compatibility)."""
        return self.map_to_node(workflow_state)

    def map_output(self, node_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Alias for map_to_shared (backward compatibility).

        Note: Source is node state, not output.output.
        """
        return self.map_to_shared(node_state)


def create_simple_mapping(
    input_fields: Dict[str, str],
    output_fields: Dict[str, str],
    description: Optional[str] = None
) -> StateMapping:
    """
    Create a symmetric field-to-field mapping.

    Args:
        input_fields: Mapping from shared state keys to node state keys
        output_fields: Mapping from node state keys to shared state keys
        description: Optional description

    Returns:
        StateMapping instance
    """
    def input_mapper(workflow_state: Dict[str, Any]) -> Dict[str, Any]:
        """Map shared state to node state."""
        node_input = {}
        for workflow_key, node_key in input_fields.items():
            if workflow_key in workflow_state:
                node_input[node_key] = workflow_state[workflow_key]
        return node_input

    def output_mapper(node_state: Dict[str, Any]) -> Dict[str, Any]:
        """Map node state to shared state updates."""
        state_updates = {}
        for node_key, workflow_key in output_fields.items():
            if node_key in node_state:
                state_updates[workflow_key] = node_state[node_key]
        return state_updates

    return StateMapping(
        input_mapping=input_mapper,
        output_mapping=output_mapper,
        description=description or f"Simple mapping: {len(input_fields)} input fields, {len(output_fields)} output fields"
    )


def create_identity_mapping(description: Optional[str] = None) -> StateMapping:
    """
    Create identity mapping (shared state = node state, no transformation).

    Args:
        description: Optional description

    Returns:
        StateMapping instance
    """
    def identity(d: Dict[str, Any]) -> Dict[str, Any]:
        return d.copy()

    return StateMapping(
        input_mapping=identity,
        output_mapping=identity,
        description=description or "Identity mapping (no transformation)"
    )


def create_prefix_mapping(
    input_prefix: str = "",
    output_prefix: str = "",
    description: Optional[str] = None
) -> StateMapping:
    """
    Create prefix-based symmetric mapping.

    Input: strip prefix from shared state keys → node state
    Output: add prefix to node state keys → shared state updates

    Args:
        input_prefix: Prefix to strip when mapping to node
        output_prefix: Prefix to add when mapping to shared
        description: Optional description

    Returns:
        StateMapping instance
    """
    def input_mapper(workflow_state: Dict[str, Any]) -> Dict[str, Any]:
        """Strip prefix from shared state keys for node state."""
        node_input = {}
        prefix_len = len(input_prefix)
        for key, value in workflow_state.items():
            if key.startswith(input_prefix):
                node_key = key[prefix_len:]
                node_input[node_key] = value
            else:
                node_input[key] = value
        return node_input

    def output_mapper(node_state: Dict[str, Any]) -> Dict[str, Any]:
        """Add prefix to node state keys for shared state updates."""
        state_updates = {}
        for key, value in node_state.items():
            if output_prefix:
                state_key = f"{output_prefix}{key}"
            else:
                state_key = key
            state_updates[state_key] = value
        return state_updates

    return StateMapping(
        input_mapping=input_mapper,
        output_mapping=output_mapper,
        description=description or f"Prefix mapping: input_prefix='{input_prefix}', output_prefix='{output_prefix}'"
    )


def create_namespace_mapping(
    namespace: str,
    description: Optional[str] = None
) -> StateMapping:
    """
    Create namespace-based symmetric mapping.

    Node state uses keys like "value", "result"; shared state uses "namespace.value", "namespace.result".

    Args:
        namespace: Namespace prefix
        description: Optional description

    Returns:
        StateMapping instance
    """
    return create_prefix_mapping(
        input_prefix=f"{namespace}.",
        output_prefix=f"{namespace}.",
        description=description or f"Namespace mapping: '{namespace}'"
    )


def create_suffix_mapping(
    input_suffix: str = "",
    output_suffix: str = "",
    description: Optional[str] = None,
) -> StateMapping:
    """
    Create suffix-based symmetric mapping (mirror of :func:`create_prefix_mapping`).

    Input: strip ``input_suffix`` from the **end** of shared state keys → node state keys.
    Output: append ``output_suffix`` to node state keys → shared state updates.

    Example: ``input_suffix=output_suffix=".wikipedia"`` maps shared ``html.wikipedia`` ↔ node ``html``.

    Args:
        input_suffix: Suffix to strip when mapping shared state to node state
        output_suffix: Suffix to append when mapping node state to shared updates
        description: Optional description

    Returns:
        StateMapping instance
    """
    def input_mapper(workflow_state: Dict[str, Any]) -> Dict[str, Any]:
        node_input: Dict[str, Any] = {}
        slen = len(input_suffix)
        for key, value in workflow_state.items():
            if input_suffix and key.endswith(input_suffix):
                node_key = key[:-slen] if slen else key
                node_input[node_key] = value
            else:
                node_input[key] = value
        return node_input

    def output_mapper(node_state: Dict[str, Any]) -> Dict[str, Any]:
        state_updates: Dict[str, Any] = {}
        for key, value in node_state.items():
            state_key = f"{key}{output_suffix}" if output_suffix else key
            state_updates[state_key] = value
        return state_updates

    return StateMapping(
        input_mapping=input_mapper,
        output_mapping=output_mapper,
        description=description
        or f"Suffix mapping: input_suffix={input_suffix!r}, output_suffix={output_suffix!r}",
    )


def create_suffix_namespace_mapping(
    branch: str,
    description: Optional[str] = None,
) -> StateMapping:
    """
    Convenience for shared keys shaped ``<stem>.<branch>`` (branch is the last segment).

    Equivalent to :func:`create_suffix_mapping` with ``input_suffix=output_suffix=".{branch}"``:
    shared ``html.wikipedia`` ↔ node ``html`` when ``branch="wikipedia"``.

    This complements :func:`create_namespace_mapping`, which uses ``namespace.`` as a **prefix**
    on shared keys (e.g. ``wikipedia.html`` ↔ node ``html``).

    Args:
        branch: Last path segment after the dot (e.g. ``"wikipedia"`` → suffix ``.wikipedia``)
        description: Optional description

    Returns:
        StateMapping instance
    """
    suf = f".{branch}"
    return create_suffix_mapping(
        input_suffix=suf,
        output_suffix=suf,
        description=description or f"Suffix namespace: '.{branch}' (e.g. stem.{branch} ↔ stem in node)",
    )
