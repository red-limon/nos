"""Assistant DB read/write operations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ....extensions import db
from ..enums import RegistrationStatus
from .model import AssistantDbModel

if TYPE_CHECKING:
    pass


def get_all() -> list[AssistantDbModel]:
    """Return all assistants."""
    return AssistantDbModel.query.all()


def get_by_id(assistant_id: str) -> AssistantDbModel | None:
    """Return assistant by assistant_id or None if not found."""
    return AssistantDbModel.query.get(assistant_id)


def create(
    assistant_id: str,
    class_name: str,
    module_path: str,
    name: str | None,
    created_by: str,
    updated_by: str,
    registration_status: str | None = None,
    registration_date: datetime | None = None,
) -> tuple[AssistantDbModel | None, str | None]:
    """
    Create an assistant. Returns (model, None) on success, (None, "conflict") if assistant_id exists.
    """
    existing = AssistantDbModel.query.get(assistant_id)
    if existing:
        return None, "conflict"
    assistant = AssistantDbModel(
        assistant_id=assistant_id,
        class_name=class_name,
        module_path=module_path,
        name=name,
        created_by=created_by,
        updated_by=updated_by,
        registration_status=registration_status or RegistrationStatus.ERROR.value,
        registration_date=registration_date or datetime.utcnow(),
    )
    db.session.add(assistant)
    db.session.commit()
    return assistant, None


def update(assistant_id: str, payload: dict) -> tuple[AssistantDbModel | None, str | None]:
    """
    Update an assistant by assistant_id. payload: dict with optional class_name, module_path, name, updated_by,
    registration_status, registration_date.
    Returns (model, None) on success, (None, "not_found") or (None, "conflict").
    """
    assistant = AssistantDbModel.query.get(assistant_id)
    if not assistant:
        return None, "not_found"
    if "class_name" in payload:
        assistant.class_name = payload["class_name"]
    if "module_path" in payload:
        assistant.module_path = payload["module_path"]
    if "name" in payload:
        assistant.name = payload["name"]
    if "updated_by" in payload:
        assistant.updated_by = payload["updated_by"]
    if "registration_status" in payload:
        assistant.registration_status = payload["registration_status"]
    if "registration_date" in payload:
        assistant.registration_date = payload["registration_date"]
    db.session.commit()
    return assistant, None


def delete(assistant_id: str) -> tuple[bool, str | None]:
    """Delete an assistant by assistant_id. Returns (True, None) on success, (False, "not_found")."""
    assistant = AssistantDbModel.query.get(assistant_id)
    if not assistant:
        return False, "not_found"
    db.session.delete(assistant)
    db.session.commit()
    return True, None


def delete_many(assistant_ids: list[str]) -> tuple[list[str], list[str]]:
    """Delete assistants by assistant_ids. Returns (deleted_ids, not_found_ids)."""
    assistants = AssistantDbModel.query.filter(AssistantDbModel.assistant_id.in_(assistant_ids)).all()
    deleted_ids = [a.assistant_id for a in assistants]
    not_found = [i for i in assistant_ids if i not in deleted_ids]
    for a in assistants:
        db.session.delete(a)
    db.session.commit()
    return deleted_ids, not_found
