"""Persistence helpers for ``plugins`` table."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from .enums import PluginRecordStatus, PluginRecordType
from .model import PluginDbModel

logger = logging.getLogger(__name__)


def get_by_id(session: Session, plugin_id: str) -> Optional[PluginDbModel]:
    return session.get(PluginDbModel, plugin_id)


def upsert_registered(
    session: Session,
    *,
    plugin_id: str,
    plugin_type: PluginRecordType,
    module_path: str,
    class_name: str,
) -> PluginDbModel:
    """
    Insert a new row with status ``registered`` if ``plugin_id`` is absent.
    If a row exists and status is ``registered`` or ``published``, return it unchanged.
    """
    row = get_by_id(session, plugin_id)
    if row is None:
        row = PluginDbModel(
            plugin_id=plugin_id,
            plugin_type=plugin_type.value,
            module_path=module_path,
            class_name=class_name,
            status=PluginRecordStatus.REGISTERED.value,
            last_error=None,
        )
        session.add(row)
        logger.info("plugins table: inserted %s as registered", plugin_id)
        return row

    if row.status in (
        PluginRecordStatus.REGISTERED.value,
        PluginRecordStatus.PUBLISHED.value,
    ):
        logger.debug("plugins table: %s already exists (status=%s), skip", plugin_id, row.status)
        return row

    # Was error — recovery path: mark registered again
    row.status = PluginRecordStatus.REGISTERED.value
    row.module_path = module_path
    row.class_name = class_name
    row.plugin_type = plugin_type.value
    row.last_error = None
    logger.info("plugins table: recovered %s to registered", plugin_id)
    return row


def upsert_error(
    session: Session,
    *,
    plugin_id: str,
    plugin_type: PluginRecordType,
    module_path: str,
    class_name: str,
    message: str,
) -> PluginDbModel:
    """Insert or update row with ``error`` status and ``last_error`` message."""
    row = get_by_id(session, plugin_id)
    if row is None:
        row = PluginDbModel(
            plugin_id=plugin_id,
            plugin_type=plugin_type.value,
            module_path=module_path,
            class_name=class_name,
            status=PluginRecordStatus.ERROR.value,
            last_error=message,
        )
        session.add(row)
    else:
        row.status = PluginRecordStatus.ERROR.value
        row.last_error = message
        row.module_path = module_path
        row.class_name = class_name
        row.plugin_type = plugin_type.value
    logger.warning("plugins table: error for %s — %s", plugin_id, message[:200])
    return row
