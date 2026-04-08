"""
Workflow plugin registry.

Manages registration and discovery of:
- Workflows
- Nodes
- Links
"""

import logging
from typing import Dict, Type, Optional
from .base import Workflow, Node, Link

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """
    Central registry for workflow plugins.
    
    Stores:
    - Workflow classes (by workflow_id)
    - Node classes (by node_id)
    - Link classes (by link_id)
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self._workflows: Dict[str, Type[Workflow]] = {}
        self._nodes: Dict[str, Type[Node]] = {}
        self._links: Dict[str, Type[Link]] = {}
    
    def register_workflow(self, workflow_class: Type[Workflow], workflow_id: Optional[str] = None):
        """
        Register a workflow class.
        
        Workflow classes must define workflow_id as a class attribute. The registry uses
        that as the lookup key. When storing workflows in the DB (or any external store),
        use workflow_class.workflow_id as the id so create_workflow_instance(lookup_id)
        finds the correct class.
        
        Args:
            workflow_class: Workflow class (must have workflow_id as class attribute)
            workflow_id: Optional override. If None, uses workflow_class.workflow_id (recommended)
        """
        if workflow_id is None:
            if not hasattr(workflow_class, "workflow_id"):
                raise TypeError(
                    f"{workflow_class.__name__} must define workflow_id as a class attribute. "
                    "Example: workflow_id = 'my_workflow'"
                )
            workflow_id = workflow_class.workflow_id
        
        if workflow_id in self._workflows:
            logger.warning(f"Overwriting workflow {workflow_id}")
        
        self._workflows[workflow_id] = workflow_class
        logger.info(f"Registered workflow: {workflow_id} ({workflow_class.__name__})")
    
    def register_node(self, node_class: Type[Node], node_id: Optional[str] = None):
        """
        Register a node class.

        If ``node_id`` is omitted, ``node_class.node_id`` must be set (class attribute).

        If ``node_id`` is provided explicitly (e.g. from DB) and the class also defines
        ``node_id``, both must match.
        """
        if node_id is None:
            if not hasattr(node_class, "node_id") or not getattr(node_class, "node_id", None):
                raise TypeError(
                    f"{node_class.__name__} must define node_id as a non-empty class attribute "
                    "when register_node is called without an explicit node_id."
                )
            node_id = node_class.node_id
        else:
            class_nid = getattr(node_class, "node_id", None)
            if class_nid and class_nid != node_id:
                raise ValueError(
                    f"register_node: explicit node_id {node_id!r} does not match "
                    f"{node_class.__name__}.node_id {class_nid!r}"
                )

        if node_id in self._nodes:
            logger.warning(f"Overwriting node {node_id}")

        self._nodes[node_id] = node_class
        logger.info(f"Registered node: {node_id} ({node_class.__name__})")

    def unregister_node(self, node_id: str) -> None:
        """Remove a node class from the registry."""
        if node_id in self._nodes:
            del self._nodes[node_id]
            logger.info("Unregistered node: %s", node_id)

    def unregister_workflow(self, workflow_id: str) -> None:
        """Remove a workflow class from the registry."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            logger.info("Unregistered workflow: %s", workflow_id)
    
    def register_link(self, link_class: Type[Link], link_id: Optional[str] = None):
        """
        Register a link class.
        
        Args:
            link_class: Link class
            link_id: Optional link ID (defaults to class name)
        """
        if link_id is None:
            link_id = link_class.__name__.lower().replace('link', '')
        
        if link_id in self._links:
            logger.warning(f"Overwriting link {link_id}")
        
        self._links[link_id] = link_class
        logger.info(f"Registered link: {link_id} ({link_class.__name__})")
    
    def get_workflow(self, workflow_id: str) -> Optional[Type[Workflow]]:
        """Get workflow class by ID."""
        return self._workflows.get(workflow_id)
    
    def get_node(self, node_id: str) -> Optional[Type[Node]]:
        """Get node class by ID."""
        return self._nodes.get(node_id)
    
    def get_link(self, link_id: str) -> Optional[Type[Link]]:
        """Get link class by ID."""
        return self._links.get(link_id)
    
    def list_workflows(self) -> list[str]:
        """List all registered workflow IDs."""
        return list(self._workflows.keys())
    
    def list_nodes(self) -> list[str]:
        """List all registered node IDs."""
        return list(self._nodes.keys())
    
    def list_links(self) -> list[str]:
        """List all registered link IDs."""
        return list(self._links.keys())
    
    def create_workflow_instance(self, workflow_id: str, **kwargs) -> Optional[Workflow]:
        """
        Create a workflow instance.
        
        The workflow_id is used only to look up the workflow class. The instance is
        created with workflow_class(**kwargs); the workflow's workflow_id comes from
        its class attribute (workflow_class.workflow_id). Ensure workflows are
        registered and stored in DB using the same id as the class defines.
        
        Args:
            workflow_id: Lookup key (must match workflow_class.workflow_id from registration)
            **kwargs: Arguments to pass to workflow constructor
        
        Returns:
            Workflow instance or None if not found
        """
        workflow_class = self.get_workflow(workflow_id)
        if workflow_class is None:
            return None
        
        class_wid = getattr(workflow_class, "workflow_id", None)
        if class_wid and class_wid != workflow_id:
            logger.warning(
                f"Lookup workflow_id '{workflow_id}' differs from class workflow_id '{class_wid}'. "
                "Register and store in DB using workflow_class.workflow_id for consistency."
            )
        
        return workflow_class(**kwargs)
    
    def create_node_instance(self, node_id: str, **kwargs) -> Optional[Node]:
        """
        Create a node instance.
        
        Args:
            node_id: Node ID
            **kwargs: Arguments to pass to node constructor
        
        Returns:
            Node instance or None if not found
        """
        node_class = self.get_node(node_id)
        if node_class is None:
            return None
        
        return node_class(node_id=node_id, **kwargs)
    
    def create_link_instance(self, link_id: str, **kwargs) -> Optional[Link]:
        """
        Create a link instance.
        
        Args:
            link_id: Link ID
            **kwargs: Arguments to pass to link constructor
        
        Returns:
            Link instance or None if not found
        """
        link_class = self.get_link(link_id)
        if link_class is None:
            return None
        
        return link_class(link_id=link_id, **kwargs)


# Global registry instance
workflow_registry = WorkflowRegistry()
