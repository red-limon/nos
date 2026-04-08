"""
Framework-reserved key names for ``state`` and ``input_params`` mappings.

These strings match keyword arguments of :meth:`nos.core.engine.node.node.Node.run`
and other execution entrypoints. Using them as **dict keys** in user-supplied
``state`` / ``input_params`` is forbidden when they are not explicitly declared
on the corresponding Pydantic schema (see :func:`validate_reserved_keys`).

This avoids confusion with framework options and keeps a single clear channel
for run configuration (Python kwargs, REST fields, engine args).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Set

#: Names aligned with ``Node.run(..., **kwargs)`` (keyword-only). Not exhaustive
#: for every subsystem, but covers the primary collision surface for dict payloads.
FRAMEWORK_RESERVED_KEY_NAMES: frozenset[str] = frozenset(
    {
        "background",
        "room",
        "callback",
        "persist_to_db",
        "debug_mode",
        "command",
        "user_id",
        "exec_log",
        "output_format",
        "request",
    }
)


def validate_reserved_keys(
    mapping: Mapping[str, Any],
    *,
    reserved: frozenset[str] = FRAMEWORK_RESERVED_KEY_NAMES,
    schema_field_names: Optional[Set[str]] = None,
    context_label: str = "mapping",
) -> None:
    """
    Reject reserved framework key names inside a user ``dict`` when they are not
    legitimate schema fields.

    **Policy**

    - Let ``R`` be ``reserved`` and ``K`` the keys present in ``mapping``.
    - If ``schema_field_names`` is ``None`` (no schema, or caller does not expose
      field names): any key in ``K & R`` raises :class:`ValueError` (**strict**).
    - If ``schema_field_names`` is provided: only keys in ``(K & R) \\ schema_field_names``
      raise (**allowed if declared on the schema**).

    So a node may still declare e.g. ``output_format`` on ``input_params_schema``
    as domain data; undecorated use of the same name in the raw dict is rejected.

    Args:
        mapping: Raw ``state`` or ``input_params`` (or workflow shared state) as a
            string-keyed mapping.
        reserved: Names treated as reserved; defaults to :data:`FRAMEWORK_RESERVED_KEY_NAMES`.
        schema_field_names: Declared field names for the Pydantic model that will
            validate this mapping, or ``None`` for strict checking.
        context_label: Human-readable label for error messages (e.g. ``"node state"``).

    Raises:
        ValueError: If a forbidden reserved key is present.

    Note:
        This does not replace schema validation or the state/input_params overlap
        check; it runs in addition, early in the validation pipeline.
    """
    if not mapping:
        return
    keys = set(mapping.keys())
    if not keys:
        return

    if schema_field_names is None:
        offending = keys & reserved
    else:
        offending = (keys & reserved) - schema_field_names

    if not offending:
        return

    names = ", ".join(sorted(offending))
    hint = (
        " These names match framework run options; use a different key for domain data, "
        "or declare the field on your Pydantic schema if the name is intentional."
    )
    raise ValueError(
        f"Reserved key(s) not allowed in {context_label}: {names}.{hint}"
    )
