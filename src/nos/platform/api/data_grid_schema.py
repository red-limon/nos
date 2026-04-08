"""
Pydantic schema for data-grid API responses (columns, data rows, form_schema).

``form_schema`` is a plain JSON-serializable dict (see ``form_wire``).
"""

from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field


class DataGridResponseSchema(BaseModel):
    """Validated response for data-grid list endpoints."""

    columns: List[str] = Field(..., description="Column names for the grid (order matches data)")
    data: List[Union[List[Any], Dict[str, Any]]] = Field(
        ...,
        description="Rows: array of arrays (positional) or array of objects (keyed by column name)",
    )
    form_schema: Dict[str, Any] = Field(..., description="Form definition for create/edit UI")

    class Config:
        json_schema_extra = {
            "example": {
                "columns": ["id", "name", "status"],
                "data": [
                    [1, "Item A", "active"],
                    {"id": 2, "name": "Item B", "status": "pending"},
                ],
                "form_schema": {
                    "formId": "grid-form",
                    "title": "Edit",
                    "submitLabel": "Save",
                    "fields": [
                        {"name": "name", "label": "Name", "type": "text", "required": False},
                        {"name": "status", "label": "Status", "type": "select", "options": [], "required": False},
                    ],
                },
            }
        }
