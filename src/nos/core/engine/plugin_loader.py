"""
Core plugin loader — register workflows/nodes from Python modules (no database).

DB-backed registry load/sync lives in :mod:`nos.platform.loader_db`.
"""

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import List, Optional

from .registry import workflow_registry

logger = logging.getLogger(__name__)


def try_register_node(module_path: str, class_name: str, node_id: str) -> tuple[bool, Optional[str]]:
    """
    Try to load and register a node in the registry (no DB).
    Returns (True, None) on success, (False, error_message) on failure.
    """
    try:
        module = importlib.import_module(module_path)
        node_class = getattr(module, class_name)
        if node_class is None:
            return False, f"Class {class_name} not found in module {module_path}"
        from .base import Node

        if not issubclass(node_class, Node):
            return False, f"Class {class_name} is not a Node subclass"
        workflow_registry.register_node(node_class, node_id)
        logger.info("Registered node %s from create request", node_id)
        return True, None
    except ImportError as e:
        return False, f"Failed to import module {module_path}: {e}"
    except AttributeError as e:
        return False, f"Class {class_name} not found in module {module_path}: {e}"
    except Exception as e:
        return False, str(e)


def try_register_assistant(module_path: str, class_name: str, assistant_id: str) -> tuple[bool, Optional[str]]:
    """
    Try to load and register an assistant (placeholder: no assistant registry yet).
    Returns (True, None) on success, (False, error_message) on failure.
    """
    try:
        module = importlib.import_module(module_path)
        getattr(module, class_name)
        logger.info("Registered assistant %s from create request (placeholder)", assistant_id)
        return True, None
    except ImportError as e:
        return False, f"Failed to import module {module_path}: {e}"
    except AttributeError as e:
        return False, f"Class {class_name} not found in module {module_path}: {e}"
    except Exception as e:
        return False, str(e)


def try_register_workflow(module_path: str, class_name: str, workflow_id: str) -> tuple[bool, Optional[str]]:
    """
    Try to load and register a workflow in the registry (no DB).
    Returns (True, None) on success, (False, error_message) on failure.
    """
    try:
        module = importlib.import_module(module_path)
        workflow_class = getattr(module, class_name)
        if workflow_class is None:
            return False, f"Class {class_name} not found in module {module_path}"
        from .base import Workflow as WorkflowBase

        if not issubclass(workflow_class, WorkflowBase):
            return False, f"Class {class_name} is not a Workflow subclass"
        workflow_registry.register_workflow(workflow_class, workflow_id)
        logger.info("Registered workflow %s from create request", workflow_id)
        return True, None
    except ImportError as e:
        return False, f"Failed to import module {module_path}: {e}"
    except AttributeError as e:
        return False, f"Class {class_name} not found in module {module_path}: {e}"
    except Exception as e:
        return False, str(e)


def get_workflow_node_ids(workflow_id: str) -> List[str]:
    """
    Return the list of node_ids used by the workflow (from its define()).
    Workflow must already be registered. Returns [] if workflow not found or define() fails.
    """
    instance = get_workflow_instance(workflow_id)
    if instance is None:
        return []
    return list(instance._nodes.keys())


def get_workflow_instance(workflow_id: str):
    """
    Return the workflow instance with define() already called (so _nodes is populated).
    Workflow must already be registered. Returns None if not found or define() fails.
    """
    workflow_class = workflow_registry.get_workflow(workflow_id)
    if workflow_class is None:
        return None
    try:
        instance = workflow_class()
        instance.define()
        return instance
    except Exception as e:
        logger.warning("Could not get workflow instance for %s: %s", workflow_id, e)
        return None


def _load_plugin_module(module_path: str):
    """
    Legacy: load a plugin module and register its components.

    Kept for backward compatibility; not used by :func:`load_workflow_plugins`
    in :mod:`nos.platform.loader_db`.
    """
    try:
        module = importlib.import_module(module_path)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)

            if not isinstance(attr, type):
                continue

            from .base import Workflow, Node, Link

            if issubclass(attr, Workflow) and attr is not Workflow:
                workflow_id = getattr(attr, "workflow_id", None) or attr_name.lower().replace("workflow", "")
                workflow_registry.register_workflow(attr, workflow_id)

            elif issubclass(attr, Node) and attr is not Node:
                node_id = getattr(attr, "node_id", None) or attr_name.lower().replace("node", "")
                workflow_registry.register_node(attr, node_id)

            elif issubclass(attr, Link) and attr is not Link:
                link_id = getattr(attr, "link_id", None) or attr_name.lower().replace("link", "")
                workflow_registry.register_link(attr, link_id)

    except ImportError as e:
        logger.debug("Plugin module %s not found (this is OK if optional): %s", module_path, e)
    except Exception as e:
        logger.error("Error loading plugin module %s: %s", module_path, e, exc_info=True)


def load_plugins_from_directory(directory: Path):
    """
    Load plugins from a directory (``*.py`` files).

    Args:
        directory: Path to plugin directory
    """
    if not directory.exists():
        logger.warning("Plugin directory does not exist: %s", directory)
        return

    for file_path in directory.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = file_path.stem
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _load_plugin_module(module.__name__)
        except Exception as e:
            logger.warning("Failed to load plugin from %s: %s", file_path, e)
