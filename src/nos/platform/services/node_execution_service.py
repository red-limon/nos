"""
Node Execution Service.

Provides reusable node execution logic for REST API and Socket.IO handlers.
"""

import logging
import time
import importlib
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of node execution."""
    success: bool
    message: str
    execution_id: Optional[str] = None
    node_id: Optional[str] = None
    status: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    elapsed_time: Optional[str] = None
    event_logs: Optional[list] = None
    error: Optional[str] = None


def _get_nos_pkg_dir() -> str:
    """Get the nos package directory path."""
    import os
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _module_path_to_file_path(module_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Convert module path to file path if under allowed directory.
    
    Returns:
        Tuple of (file_path, allowed_dir) or (None, None) if invalid
    """
    import os
    
    if not module_path.startswith("nos.plugins.nodes"):
        return None, None
    
    nos_dir = _get_nos_pkg_dir()
    allowed_dir = os.path.join(nos_dir, "plugins", "nodes")
    
    # Convert module path to relative path
    relative_parts = module_path.replace("nos.plugins.nodes", "").strip(".")
    if not relative_parts:
        return None, None
    
    file_path = os.path.join(allowed_dir, *relative_parts.split(".")) + ".py"
    
    # Security check: ensure path is under allowed directory
    real_path = os.path.realpath(file_path)
    real_allowed = os.path.realpath(allowed_dir)
    
    if not real_path.startswith(real_allowed + os.sep) and real_path != real_allowed:
        return None, None
    
    return file_path, allowed_dir


def is_module_path_allowed(module_path: str) -> bool:
    """Check if module_path is under nos.plugins.nodes (whitelist for security)."""
    file_path, _ = _module_path_to_file_path(module_path)
    return file_path is not None


def create_node_instance(
    module_path: str,
    class_name: str,
    node_id: str = "adhoc",
    name: Optional[str] = None
) -> Tuple[Any, Optional[str]]:
    """
    Dynamically import module and create node instance.
    
    Args:
        module_path: Full Python module path
        class_name: Node class name
        node_id: Node identifier
        name: Display name (defaults to class_name)
        
    Returns:
        Tuple of (node_instance, error_message)
        On success: (node, None)
        On error: (None, error_message)
    """
    from nos.core.engine.base import Node
    
    # Security check
    if not is_module_path_allowed(module_path):
        return None, f"Invalid module_path: must be under nos.plugins.nodes"
    
    try:
        module = importlib.import_module(module_path)
        node_class = getattr(module, class_name)
    except ImportError as e:
        return None, f"Import error: {str(e)}"
    except AttributeError as e:
        return None, f"Class '{class_name}' not found in module: {str(e)}"
    
    if not isinstance(node_class, type) or not issubclass(node_class, Node):
        return None, f"'{class_name}' is not a valid Node class"
    
    try:
        node = node_class(node_id=node_id, name=name or class_name)
        return node, None
    except Exception as e:
        return None, f"Failed to create node instance: {str(e)}"


def execute_node_direct(
    module_path: str,
    class_name: str,
    state: Optional[Dict[str, Any]] = None,
    input_params: Optional[Dict[str, Any]] = None,
    node_id: str = "adhoc_direct",
    room: Optional[str] = None
) -> ExecutionResult:
    """
    Execute a node directly by module_path and class_name.
    
    Args:
        module_path: Full Python module path (e.g., nos.plugins.nodes.developer.my_node)
        class_name: Node class name
        state: Initial state dict
        input_params: Input parameters dict
        node_id: Node identifier for logging
        room: Socket.IO room/client_id for real-time streaming (uses EventLog)
              If None, uses EventLogBuffer (no real-time)
        
    Returns:
        ExecutionResult with execution details
    """
    from nos.core.execution_log import ObservableStateDict
    
    # Create node instance
    node, error = create_node_instance(module_path, class_name, node_id, class_name)
    if error:
        return ExecutionResult(
            success=False,
            message=error,
            error=error
        )
    
    # Create execution channel
    execution_id = f"node_{node_id}_{int(time.time())}"
    
    # Use EventLog for real-time Socket.IO, EventLogBuffer otherwise
    if room:
        from nos.platform.execution_log.event_log import EventLog
        channel = EventLog(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=None,
            module_path=module_path,
            class_name=class_name,
            shared_state={},
            room=room,
        )
    else:
        from nos.core.execution_log.event_log_buffer import EventLogBuffer
        channel = EventLogBuffer(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=None,
            module_path=module_path,
            class_name=class_name,
            shared_state={},
        )
    
    # Set channel on node
    node.set_exec_log(channel)

    # Prepare state and params
    state = state.copy() if state else {}
    input_params = input_params if input_params is not None else {}
    
    # Create observable state for tracking changes (node._on_state_changed emits to channel)
    observable_state = ObservableStateDict(
        state.copy(),
        on_set=lambda k, o, n: node._on_state_changed(k, o, n),
    )
    
    run_request = {
        "node_id": node_id,
        "state": state.copy(),
        "input_params": dict(input_params),
        "module_path": module_path,
        "class_name": class_name,
    }
    try:
        # Execute node via run() - _on_start emits node_start event, then execute()
        result = node.run(observable_state, input_params, request=run_request)

        # Check node output for semantic success (e.g. AI inference failed without raising)
        result_dict = result.model_dump() if hasattr(result, 'model_dump') else dict(result)
        output_data = (result.response.output if hasattr(result.response, 'output') else
                      result_dict.get("response", {}).get("output", {}))
        if output_data.get("success") is False:
            error_msg = output_data.get("error") or "Unknown error"
            return ExecutionResult(
                success=False,
                message=error_msg,
                execution_id=execution_id,
                node_id=node_id,
                status="error",
                result=result_dict,
                elapsed_time=result.elapsed_time,
                event_logs=channel.get_events(),
                error=error_msg
            )
        
        return ExecutionResult(
            success=True,
            message=f"Node '{node_id}' executed successfully",
            execution_id=execution_id,
            node_id=node_id,
            status="completed",
            result=result_dict,
            elapsed_time=result.elapsed_time,
            event_logs=channel.get_events()
        )
        
    except TypeError as e:
        if "not subscriptable" in str(e):
            error_msg = (
                f"Node {node_id}: input_params type error. "
                "Ensure params are accessed as dict keys, not attributes."
            )
        else:
            error_msg = str(e)
        logger.error(f"Node execution error: {error_msg}", exc_info=True)
        return ExecutionResult(
            success=False,
            message=f"Execution error: {error_msg}",
            execution_id=execution_id,
            node_id=node_id,
            status="error",
            error=error_msg,
            event_logs=channel.get_events()
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Node execution error: {error_msg}", exc_info=True)
        return ExecutionResult(
            success=False,
            message=f"Execution error: {error_msg}",
            execution_id=execution_id,
            node_id=node_id,
            status="error",
            error=error_msg,
            event_logs=channel.get_events()
        )


def execute_node_from_db(
    node_id: str,
    state: Optional[Dict[str, Any]] = None,
    input_params: Optional[Dict[str, Any]] = None,
    room: Optional[str] = None
) -> ExecutionResult:
    """
    Execute a node by node_id from DATABASE registry (loads class dynamically).
    
    This fetches module_path/class_name from DB and loads the class via importlib.
    Use execute_node_from_registry() to execute from in-memory plugin registry.
    
    Args:
        node_id: Node identifier (must exist in database)
        state: Initial state dict
        input_params: Input parameters dict
        room: Socket.IO room/client_id for real-time streaming
        
    Returns:
        ExecutionResult with execution details
    """
    from .sqlalchemy.node import repository as node_repo
    
    # Get node from database
    node_record = node_repo.get_by_id(node_id)
    if not node_record:
        return ExecutionResult(
            success=False,
            message=f"Node '{node_id}' not found in database",
            error=f"Node '{node_id}' not found"
        )
    
    # Execute using module_path and class_name from DB
    return execute_node_direct(
        module_path=node_record.module_path,
        class_name=node_record.class_name,
        state=state,
        input_params=input_params,
        node_id=node_id,
        room=room
    )


def execute_node_from_registry(
    node_id: str,
    state: Optional[Dict[str, Any]] = None,
    input_params: Optional[Dict[str, Any]] = None,
    room: Optional[str] = None
) -> ExecutionResult:
    """
    Execute a node from the IN-MEMORY plugin registry (workflow_registry).
    
    The node must have been loaded by the plugin loader at application startup.
    This is faster than execute_node_direct as it doesn't re-import modules.
    
    Args:
        node_id: Node identifier (must be registered in workflow_registry)
        state: Initial state dict
        input_params: Input parameters dict
        room: Socket.IO room/client_id for real-time EventLog streaming
              If None, uses EventLogBuffer (no real-time streaming)
        
    Returns:
        ExecutionResult with execution details
    """
    from nos.core.engine.registry import workflow_registry
    from nos.core.execution_log import EventLogBuffer, ObservableStateDict
    from nos.platform.execution_log import EventLog
    
    state = state or {}
    input_params = input_params or {}
    
    # Get node class from in-memory registry
    node_class = workflow_registry.get_node(node_id)
    if not node_class:
        return ExecutionResult(
            success=False,
            message=f"Node '{node_id}' not found in registry. Was it loaded by the plugin loader?",
            error=f"Node '{node_id}' not found in registry"
        )
    
    # Create node instance
    node = workflow_registry.create_node_instance(node_id)
    if not node:
        return ExecutionResult(
            success=False,
            message=f"Failed to create instance of node '{node_id}'",
            error=f"Failed to instantiate node '{node_id}'"
        )
    
    # Generate execution ID
    execution_id = f"node_{node_id}_{int(time.time())}"
    
    # Get module info from class
    module_path = node.__class__.__module__
    class_name = node.__class__.__name__
    
    logger.info(f"Executing node from registry: {node_id} ({module_path}.{class_name})")
    
    # Choose channel type based on room parameter
    if room:
        # Real-time streaming via Socket.IO
        from ..extensions import socketio
        channel = EventLog(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=None,
            module_path=module_path,
            class_name=class_name,
            shared_state=state.copy(),
            room=room
        )
    else:
        # Buffer-only (for REST API or non-realtime scenarios)
        channel = EventLogBuffer(
            execution_id=execution_id,
            node_id=node_id,
            workflow_id=None,
            module_path=module_path,
            class_name=class_name,
            shared_state=state.copy()
        )
    
    node.set_exec_log(channel)

    # Observable state for tracking changes (node._on_state_changed emits to channel)
    def on_state_set(key, old_val, new_val):
        node._on_state_changed(key, old_val, new_val)

    observable_state = ObservableStateDict(state.copy(), on_set=on_state_set)

    run_request = {
        "node_id": node_id,
        "state": state.copy(),
        "input_params": input_params.copy() if input_params else {},
        "module_path": module_path,
        "class_name": class_name,
    }
    try:
        result = node.run(observable_state, input_params, request=run_request)
        result_dict = result.model_dump() if hasattr(result, 'model_dump') else result.__dict__

        # Check node output for semantic success
        output_data = (result.response.output if hasattr(result.response, 'output') else
                      result_dict.get("response", {}).get("output", {}))
        if output_data.get("success") is False:
            error_msg = output_data.get("error") or "Unknown error"
            return ExecutionResult(
                success=False,
                message=error_msg,
                execution_id=execution_id,
                node_id=node_id,
                status="error",
                result=result_dict,
                elapsed_time=result.elapsed_time,
                event_logs=channel.get_events(),
                error=error_msg
            )

        return ExecutionResult(
            success=True,
            message=f"Node '{node_id}' executed successfully",
            execution_id=execution_id,
            node_id=node_id,
            status=result.status,
            result=result_dict,
            elapsed_time=result.elapsed_time,
            event_logs=channel.get_events()
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error executing node {node_id} from registry: {error_msg}", exc_info=True)
        
        return ExecutionResult(
            success=False,
            message=f"Execution error: {error_msg}",
            execution_id=execution_id,
            node_id=node_id,
            status="error",
            error=error_msg,
            event_logs=channel.get_events()
        )
