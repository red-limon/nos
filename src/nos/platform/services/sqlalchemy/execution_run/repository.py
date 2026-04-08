"""ExecutionRun DB read/write operations."""

from __future__ import annotations

import time
from typing import Any

from ....extensions import db
from .model import ExecutionRunDbModel


def create_run(
    execution_id: str,
    execution_type: str,
    plugin_id: str | None,
    user_id: str = "anonymous",
    started_at: float | None = None,
) -> ExecutionRunDbModel:
    """Insert a new execution_run header row (status='running')."""
    run = ExecutionRunDbModel(
        execution_id=execution_id,
        execution_type=execution_type,
        plugin_id=plugin_id,
        user_id=user_id,
        status="running",
        started_at=started_at or time.time(),
    )
    db.session.add(run)
    db.session.commit()
    return run


def complete_run(
    execution_id: str,
    status: str,
    message: str | None = None,
    ended_at: float | None = None,
    elapsed_time: str | None = None,
    execution_log: str | None = None,
) -> ExecutionRunDbModel | None:
    """Update an execution_run row at completion."""
    run = ExecutionRunDbModel.query.filter_by(execution_id=execution_id).first()
    if not run:
        return None
    run.status = status
    run.message = message
    run.ended_at = ended_at or time.time()
    run.elapsed_time = elapsed_time
    if execution_log is not None:
        run.execution_log = execution_log
    db.session.commit()
    return run


def set_pid(execution_id: str, pid: int | None) -> bool:
    """Store the worker OS process id for a running execution (best-effort)."""
    run = ExecutionRunDbModel.query.filter_by(execution_id=execution_id).first()
    if not run:
        return False
    run.pid = pid
    db.session.commit()
    return True


def set_execution_log_path(execution_id: str, path: str) -> bool:
    """Set the execution_log file path on an existing run record."""
    run = ExecutionRunDbModel.query.filter_by(execution_id=execution_id).first()
    if not run:
        return False
    run.execution_log = path
    db.session.commit()
    return True


def get_history(
    user_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ExecutionRunDbModel]:
    """Return execution history ordered by started_at descending."""
    query = ExecutionRunDbModel.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    query = query.order_by(ExecutionRunDbModel.started_at.desc())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return query.all()


def get_by_execution_id(execution_id: str) -> ExecutionRunDbModel | None:
    return ExecutionRunDbModel.query.filter_by(execution_id=execution_id).first()


def delete_by_execution_id(execution_id: str) -> bool:
    run = ExecutionRunDbModel.query.filter_by(execution_id=execution_id).first()
    if not run:
        return False
    db.session.delete(run)
    db.session.commit()
    return True
