"""Workflow DB read/write operations."""

from __future__ import annotations

from datetime import datetime

from ....extensions import db
from ..enums import RegistrationStatus
from .model import WorkflowDbModel


def get_all() -> list[WorkflowDbModel]:
    """Return all workflows."""
    return WorkflowDbModel.query.all()


def get_by_id(workflow_id: str) -> WorkflowDbModel | None:
    """Return workflow by workflow_id or None if not found."""
    return WorkflowDbModel.query.filter_by(workflow_id=workflow_id).first()


def get_all_registered() -> list[WorkflowDbModel]:
    """Return all workflows with registration_status OK (loaded in registry)."""
    return WorkflowDbModel.query.filter_by(registration_status=RegistrationStatus.OK.value).all()


def create(
    workflow_id: str,
    class_name: str,
    module_path: str,
    name: str | None,
    created_by: str,
    updated_by: str,
    registration_status: str | None = None,
    registration_date: datetime | None = None,
) -> tuple[WorkflowDbModel | None, str | None]:
    """
    Create a workflow. Returns (model, None) on success, (None, "conflict") if workflow_id exists.

    IMPORTANT: workflow_id must match the workflow class's workflow_id attribute
    (workflow_class.workflow_id). The registry and loader use this id for lookup;
    use the class id for consistency.
    """
    existing = WorkflowDbModel.query.filter_by(workflow_id=workflow_id).first()
    if existing:
        return None, "conflict"
    workflow = WorkflowDbModel(
        workflow_id=workflow_id,
        class_name=class_name,
        module_path=module_path,
        name=name,
        created_by=created_by,
        updated_by=updated_by,
        registration_status=registration_status or RegistrationStatus.ERROR.value,
        registration_date=registration_date or datetime.utcnow(),
    )
    db.session.add(workflow)
    db.session.commit()
    return workflow, None


def update(workflow_id: str, payload: dict) -> tuple[WorkflowDbModel | None, str | None]:
    """
    Update a workflow. payload may contain workflow_id, class_name, module_path, name, updated_by,
    registration_status, registration_date.
    Returns (model, None) on success, (None, "not_found") or (None, "conflict").
    """
    workflow = WorkflowDbModel.query.get(workflow_id)
    if not workflow:
        return None, "not_found"
    if "workflow_id" in payload and payload["workflow_id"] != workflow.workflow_id:
        other = WorkflowDbModel.query.filter_by(workflow_id=payload["workflow_id"]).first()
        if other:
            return None, "conflict"
        workflow.workflow_id = payload["workflow_id"]
    if "class_name" in payload:
        workflow.class_name = payload["class_name"]
    if "module_path" in payload:
        workflow.module_path = payload["module_path"]
    if "name" in payload:
        workflow.name = payload["name"]
    if "registration_status" in payload:
        workflow.registration_status = payload["registration_status"]
    if "registration_date" in payload:
        workflow.registration_date = payload["registration_date"]
    if "updated_by" in payload:
        workflow.updated_by = payload["updated_by"]
    db.session.commit()
    return workflow, None


def delete(workflow_id: str) -> tuple[bool, str | None]:
    """Delete a workflow by workflow_id. Returns (True, None) on success, (False, "not_found")."""
    workflow = WorkflowDbModel.query.filter_by(workflow_id=workflow_id).first()
    if not workflow:
        return False, "not_found"
    db.session.delete(workflow)
    db.session.commit()
    return True, None


def delete_many(workflow_ids: list[str]) -> tuple[list[str], list[str]]:
    """Delete workflows by workflow_ids. Returns (deleted_ids, not_found_ids)."""
    workflows = WorkflowDbModel.query.filter(WorkflowDbModel.workflow_id.in_(workflow_ids)).all()
    deleted_ids = [w.workflow_id for w in workflows]
    not_found = [i for i in workflow_ids if i not in deleted_ids]
    for w in workflows:
        db.session.delete(w)
    db.session.commit()
    return deleted_ids, not_found
