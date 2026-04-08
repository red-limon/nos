"""Centralised safe execution helpers for plugin hooks (failure isolation)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def safe_call(
    fn: Callable[..., T],
    *args: Any,
    default: Optional[T] = None,
    **kwargs: Any,
) -> Tuple[Optional[T], Optional[BaseException]]:
    """
    Run ``fn`` inside a try/except; log failures and return ``(result, None)`` or ``(default, exc)``.
    """
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:
        logger.exception("Plugin hook failed: %s", getattr(fn, "__qualname__", fn))
        return default, exc
