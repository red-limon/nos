"""Execution Log DB read/write operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ....extensions import db
from .model import ExecutionLogDbModel

if TYPE_CHECKING:
    pass


def add_log(
    execution_id: str,
    execution_type: str,
    plugin_id: str | None,
    event: str,
    level: str,
    message: str | None,
    data: dict[str, Any] | None,
    timestamp: float,
    end_timestamp: float | None = None,
    user_id: str | None = None,
) -> ExecutionLogDbModel:
    """
    Add a log entry for an execution event.
    
    Args:
        execution_id: Unique execution identifier
        execution_type: "node" or "workflow"
        plugin_id: node_id or workflow_id
        event: Event type (e.g., node_start, node_end)
        level: Log level (debug, info, warning, error)
        message: Human-readable message
        data: Extra data (will be JSON serialized)
        timestamp: Unix timestamp (used as start_timestamp)
        end_timestamp: Unix timestamp end (defaults to timestamp if None)
    
    Returns:
        Created ExecutionLogDbModel instance
    """
    data_json = None
    if data is not None:
        try:
            data_json = json.dumps(data, default=str)
        except (TypeError, ValueError):
            data_json = str(data)
    
    ts_end = end_timestamp if end_timestamp is not None else timestamp
    
    log_entry = ExecutionLogDbModel(
        execution_id=execution_id,
        execution_type=execution_type,
        plugin_id=plugin_id,
        user_id=user_id,
        event=event,
        level=level,
        message=message,
        data=data_json,
        start_timestamp=timestamp,
        end_timestamp=ts_end,
    )
    db.session.add(log_entry)
    db.session.commit()
    return log_entry


def get_by_execution_id(
    execution_id: str,
    limit: int | None = None,
    offset: int | None = None,
) -> list[ExecutionLogDbModel]:
    """
    Get all log entries for a specific execution, ordered by timestamp.
    
    Args:
        execution_id: Execution identifier
        limit: Optional maximum number of entries
        offset: Optional offset for pagination
    
    Returns:
        List of ExecutionLogDbModel instances
    """
    query = ExecutionLogDbModel.query.filter_by(
        execution_id=execution_id
    ).order_by(ExecutionLogDbModel.start_timestamp.asc())
    
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    
    return query.all()


def get_by_plugin_id(
    plugin_id: str,
    execution_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionLogDbModel]:
    """
    Get all log entries for a specific plugin (node or workflow).
    
    Args:
        plugin_id: node_id or workflow_id
        execution_type: Optional filter by "node" or "workflow"
        limit: Optional maximum number of entries
    
    Returns:
        List of ExecutionLogDbModel instances
    """
    query = ExecutionLogDbModel.query.filter_by(plugin_id=plugin_id)
    
    if execution_type:
        query = query.filter_by(execution_type=execution_type)
    
    query = query.order_by(ExecutionLogDbModel.start_timestamp.desc())
    
    if limit is not None:
        query = query.limit(limit)
    
    return query.all()


def get_recent(
    limit: int = 100,
    execution_type: str | None = None,
    level: str | None = None,
) -> list[ExecutionLogDbModel]:
    """
    Get recent log entries across all executions.
    
    Args:
        limit: Maximum number of entries (default 100)
        execution_type: Optional filter by "node" or "workflow"
        level: Optional filter by log level
    
    Returns:
        List of ExecutionLogDbModel instances
    """
    query = ExecutionLogDbModel.query
    
    if execution_type:
        query = query.filter_by(execution_type=execution_type)
    if level:
        query = query.filter_by(level=level)
    
    query = query.order_by(ExecutionLogDbModel.start_timestamp.desc())
    
    if limit is not None:
        query = query.limit(limit)
    
    return query.all()


def count_by_execution_id(execution_id: str) -> int:
    """Count total log entries for an execution."""
    return ExecutionLogDbModel.query.filter_by(execution_id=execution_id).count()


def delete_by_execution_id(execution_id: str) -> int:
    """
    Delete all log entries for a specific execution.
    
    Returns:
        Number of deleted entries
    """
    count = ExecutionLogDbModel.query.filter_by(execution_id=execution_id).delete()
    db.session.commit()
    return count


def delete_older_than(days: int) -> int:
    """
    Delete log entries older than specified days.
    
    Returns:
        Number of deleted entries
    """
    cutoff_ts = datetime.utcnow().timestamp() - (days * 24 * 3600)
    count = ExecutionLogDbModel.query.filter(
        ExecutionLogDbModel.start_timestamp < cutoff_ts
    ).delete()
    db.session.commit()
    return count


def get_unique_executions(
    limit: int = 50,
    execution_type: str | None = None,
) -> list[dict]:
    """
    Get list of unique executions with summary info.
    
    Returns list of dicts with execution_id, execution_type, plugin_id,
    first_timestamp, last_timestamp, event_count.
    """
    from sqlalchemy import func
    
    query = db.session.query(
        ExecutionLogDbModel.execution_id,
        ExecutionLogDbModel.execution_type,
        ExecutionLogDbModel.plugin_id,
        func.min(ExecutionLogDbModel.start_timestamp).label('first_timestamp'),
        func.max(ExecutionLogDbModel.end_timestamp).label('last_timestamp'),
        func.count(ExecutionLogDbModel.id).label('event_count'),
    ).group_by(
        ExecutionLogDbModel.execution_id,
        ExecutionLogDbModel.execution_type,
        ExecutionLogDbModel.plugin_id,
    ).order_by(
        func.max(ExecutionLogDbModel.end_timestamp).desc()
    )
    
    if execution_type:
        query = query.filter(ExecutionLogDbModel.execution_type == execution_type)
    
    if limit is not None:
        query = query.limit(limit)
    
    results = query.all()
    return [
        {
            "execution_id": r.execution_id,
            "execution_type": r.execution_type,
            "plugin_id": r.plugin_id,
            "first_timestamp": r.first_timestamp,
            "last_timestamp": r.last_timestamp,
            "event_count": r.event_count,
        }
        for r in results
    ]
