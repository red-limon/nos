"""
IO adapters: Pydantic ↔ interactive forms and output format contracts (backend ↔ browser).

Not part of the execution kernel; consumed by :mod:`nos.core.engine` and
:mod:`nos.platform` (console, REST, Socket.IO).
"""

from .input_form_mapping import (
    create_form_request_payload,
    pydantic_to_form_schema,
)
from .output_formats_schema import (
    OUTPUT_FORMATS,
    NODE_OUTPUT_FORMATS,
    validate_output_for_format,
)

__all__ = [
    "create_form_request_payload",
    "pydantic_to_form_schema",
    "OUTPUT_FORMATS",
    "NODE_OUTPUT_FORMATS",
    "validate_output_for_format",
]
