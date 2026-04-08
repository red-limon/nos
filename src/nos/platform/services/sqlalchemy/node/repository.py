"""Node DB read/write operations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ....extensions import db
from ..enums import RegistrationStatus
from .model import NodeDbModel

if TYPE_CHECKING:
    pass


def get_all() -> list[NodeDbModel]:
    """Return all nodes."""
    return NodeDbModel.query.all()


def get_by_id(node_id: str) -> NodeDbModel | None:
    """Return node by node_id or None if not found."""
    return NodeDbModel.query.get(node_id)


def create(
    node_id: str,
    class_name: str,
    module_path: str,
    name: str | None,
    created_by: str,
    updated_by: str,
    registration_status: str | None = None,
    registration_date: datetime | None = None,
) -> tuple[NodeDbModel | None, str | None]:
    """
    Create a node. Returns (model, None) on success, (None, "conflict") if node_id exists.
    Caller must commit/rollback on exception.
    """
    existing = NodeDbModel.query.get(node_id)
    if existing:
        return None, "conflict"
    node = NodeDbModel(
        node_id=node_id,
        class_name=class_name,
        module_path=module_path,
        name=name,
        created_by=created_by,
        updated_by=updated_by,
        registration_status=registration_status or RegistrationStatus.ERROR.value,
        registration_date=registration_date or datetime.utcnow(),
    )
    db.session.add(node)
    db.session.commit()
    return node, None


def update(node_id: str, payload: dict) -> tuple[NodeDbModel | None, str | None]:
    """
    Update a node by node_id. payload: dict with optional class_name, module_path, name, updated_by,
    registration_status, registration_date.
    Returns (model, None) on success, (None, "not_found") or (None, "conflict").
    """
    node = NodeDbModel.query.get(node_id)
    if not node:
        return None, "not_found"
    if "class_name" in payload:
        node.class_name = payload["class_name"]
    if "module_path" in payload:
        node.module_path = payload["module_path"]
    if "name" in payload:
        node.name = payload["name"]
    if "updated_by" in payload:
        node.updated_by = payload["updated_by"]
    if "registration_status" in payload:
        node.registration_status = payload["registration_status"]
    if "registration_date" in payload:
        node.registration_date = payload["registration_date"]
    db.session.commit()
    return node, None


def delete(node_id: str) -> tuple[bool, str | None]:
    """Delete a node by node_id. Returns (True, None) on success, (False, "not_found")."""
    node = NodeDbModel.query.get(node_id)
    if not node:
        return False, "not_found"
    db.session.delete(node)
    db.session.commit()
    return True, None


def delete_many(node_ids: list[str]) -> tuple[list[str], list[str]]:
    """Delete nodes by node_ids. Returns (deleted_ids, not_found_ids)."""
    nodes = NodeDbModel.query.filter(NodeDbModel.node_id.in_(node_ids)).all()
    deleted_ids = [n.node_id for n in nodes]
    not_found = [i for i in node_ids if i not in deleted_ids]
    for n in nodes:
        db.session.delete(n)
    db.session.commit()
    return deleted_ids, not_found
