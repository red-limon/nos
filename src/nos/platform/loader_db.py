"""
Database-backed plugin registry load and sync.

Requires the web platform stack (Flask, Flask-SQLAlchemy). Import from application
startup or API only — not needed for library-only use of :mod:`nos.core`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import importlib

from nos.core.engine.registry import workflow_registry

if TYPE_CHECKING:
    from nos.platform.services.sqlalchemy import NodeDbModel, WorkflowDbModel

logger = logging.getLogger(__name__)

_PLATFORM_DB_ERROR = (
    "This operation requires the nOS web platform stack (Flask, Flask-SQLAlchemy). "
    "Install platform dependencies, e.g. pip install 'nos[web]' when extras are available."
)


def _platform_db():
    """Import Flask-SQLAlchemy bindings only when DB-backed loader APIs run."""
    try:
        from nos.platform.extensions import db
        from nos.platform.services.sqlalchemy import NodeDbModel, RegistrationStatus, WorkflowDbModel
    except ImportError as exc:
        raise RuntimeError(_PLATFORM_DB_ERROR) from exc
    return db, WorkflowDbModel, NodeDbModel, RegistrationStatus


def load_workflow_plugins():
    """
    (1) Read workflows and nodes from DB; on error stop.
    (2) For each record: register it in the registry.
    (3) Update the record in DB: registration_status (OK/Error), registration_date.
    """
    db, WorkflowDbModel, NodeDbModel, RegistrationStatus = _platform_db()
    now = datetime.utcnow()
    logger.info("=== Registry load: step 1 - reading DB ===")
    try:
        workflows = WorkflowDbModel.query.all()
        nodes = NodeDbModel.query.all()
    except Exception as e:
        logger.error("Registry load: DB read failed, stopping. Error: %s", e, exc_info=True)
        raise
    logger.info("Registry load: read %d workflow(s), %d node(s) from DB", len(workflows), len(nodes))

    ok_w, err_w = 0, 0
    logger.info("Registry load: step 2 & 3 - registering workflows and updating DB")
    for w in workflows:
        try:
            _register_workflow_from_db(w)
            w.registration_status = RegistrationStatus.OK.value
            w.registration_date = now
            ok_w += 1
            logger.info("Registry load: workflow '%s' -> registered, DB updated (OK)", w.workflow_id)
        except Exception as e:
            w.registration_status = RegistrationStatus.ERROR.value
            w.registration_date = now
            err_w += 1
            logger.warning(
                "Registry load: workflow '%s' -> registration failed, DB updated (Error): %s",
                w.workflow_id,
                e,
                exc_info=True,
            )
        try:
            db.session.commit()
        except Exception as e:
            logger.error("Registry load: failed to commit workflow '%s' update: %s", w.workflow_id, e, exc_info=True)
            db.session.rollback()

    ok_n, err_n = 0, 0
    logger.info("Registry load: step 2 & 3 - registering nodes and updating DB")
    for n in nodes:
        try:
            _register_node_from_db(n)
            n.registration_status = RegistrationStatus.OK.value
            n.registration_date = now
            ok_n += 1
            logger.info("Registry load: node '%s' -> registered, DB updated (OK)", n.node_id)
        except Exception as e:
            n.registration_status = RegistrationStatus.ERROR.value
            n.registration_date = now
            err_n += 1
            logger.warning(
                "Registry load: node '%s' -> registration failed, DB updated (Error): %s",
                n.node_id,
                e,
                exc_info=True,
            )
        try:
            db.session.commit()
        except Exception as e:
            logger.error("Registry load: failed to commit node '%s' update: %s", n.node_id, e, exc_info=True)
            db.session.rollback()

    logger.info(
        "=== Registry load: done. Workflows: %d OK, %d Error; Nodes: %d OK, %d Error ===",
        ok_w,
        err_w,
        ok_n,
        err_n,
    )


def sync_registry_workflows_to_db():
    """
    Insert workflows currently in the registry into the workflow table if not already present.
    Must be called within an active Flask app context.
    """
    db, WorkflowDbModel, _NodeDbModel, RegistrationStatus = _platform_db()
    from nos.core.engine.base import Workflow as WorkflowBase

    for workflow_id in workflow_registry.list_workflows():
        existing = WorkflowDbModel.query.get(workflow_id)
        if existing is not None:
            continue
        workflow_class = workflow_registry.get_workflow(workflow_id)
        if workflow_class is None or not issubclass(workflow_class, WorkflowBase):
            continue
        name = getattr(workflow_class, "name", None) or workflow_id
        plugin = WorkflowDbModel(
            workflow_id=workflow_id,
            class_name=workflow_class.__name__,
            module_path=workflow_class.__module__,
            name=name,
            registration_status=RegistrationStatus.OK.value,
            registration_date=datetime.utcnow(),
            created_by="system",
            updated_by="system",
        )
        db.session.add(plugin)
    try:
        db.session.commit()
        logger.info("Synced registry workflows to workflow table")
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to sync registry workflows to DB: %s", e, exc_info=True)
        raise


def sync_registry_nodes_to_db():
    """
    Insert nodes currently in the registry into the node table if not already present.
    Must be called within an active Flask app context.
    """
    db, _WorkflowDbModel, NodeDbModel, RegistrationStatus = _platform_db()
    from nos.core.engine.base import Node as NodeBase

    for node_id in workflow_registry.list_nodes():
        existing = NodeDbModel.query.get(node_id)
        if existing is not None:
            continue
        node_class = workflow_registry.get_node(node_id)
        if node_class is None or not issubclass(node_class, NodeBase):
            continue
        name = getattr(node_class, "name", None) or node_id
        plugin = NodeDbModel(
            node_id=node_id,
            class_name=node_class.__name__,
            module_path=node_class.__module__,
            name=name,
            registration_status=RegistrationStatus.OK.value,
            registration_date=datetime.utcnow(),
            created_by="system",
            updated_by="system",
        )
        db.session.add(plugin)
    try:
        db.session.commit()
        logger.info("Synced registry nodes to node table")
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to sync registry nodes to DB: %s", e, exc_info=True)
        raise


def _register_workflow_from_db(workflow_plugin: WorkflowDbModel):
    """Register a workflow from a database row."""
    try:
        module = importlib.import_module(workflow_plugin.module_path)
        workflow_class = getattr(module, workflow_plugin.class_name)

        if workflow_class is None:
            raise ValueError(f"Class {workflow_plugin.class_name} not found in module {workflow_plugin.module_path}")

        from nos.core.engine.base import Workflow as WorkflowBase

        if not issubclass(workflow_class, WorkflowBase):
            raise ValueError(f"Class {workflow_plugin.class_name} is not a Workflow subclass")

        workflow_registry.register_workflow(workflow_class, workflow_plugin.workflow_id)

        logger.info("Registered workflow %s from database", workflow_plugin.workflow_id)

    except ImportError as e:
        raise ValueError(f"Failed to import module {workflow_plugin.module_path}: {e}") from e
    except AttributeError as e:
        raise ValueError(
            f"Class {workflow_plugin.class_name} not found in module {workflow_plugin.module_path}: {e}"
        ) from e


def _register_node_from_db(node_plugin: NodeDbModel):
    """Register a node from a database row."""
    try:
        module = importlib.import_module(node_plugin.module_path)
        node_class = getattr(module, node_plugin.class_name)

        if node_class is None:
            raise ValueError(f"Class {node_plugin.class_name} not found in module {node_plugin.module_path}")

        from nos.core.engine.base import Node

        if not issubclass(node_class, Node):
            raise ValueError(f"Class {node_plugin.class_name} is not a Node subclass")

        workflow_registry.register_node(node_class, node_plugin.node_id)

        logger.info("Registered node %s from database", node_plugin.node_id)

    except ImportError as e:
        raise ValueError(f"Failed to import module {node_plugin.module_path}: {e}") from e
    except AttributeError as e:
        raise ValueError(f"Class {node_plugin.class_name} not found in module {node_plugin.module_path}: {e}") from e
