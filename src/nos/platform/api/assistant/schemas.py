"""Request/Response Pydantic schemas for Assistant API."""

from typing import Optional

from pydantic import BaseModel, Field


class AssistantCreateSchema(BaseModel):
    """Schema for creating an assistant. registration_status/registration_date are set by server (register then insert)."""

    assistant_id: str = Field(..., min_length=3, max_length=100, pattern="^[a-z0-9_]+$", description="Unique assistant identifier")
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    module_path: str = Field(..., min_length=1, max_length=500, pattern="^[a-z0-9_.]+$", description="Python module path")
    name: Optional[str] = Field(None, max_length=200)
    created_by: str = Field(default="system", max_length=80)
    updated_by: str = Field(default="system", max_length=80)


class AssistantUpdateSchema(BaseModel):
    """Schema for updating an assistant. All updatable table fields required. registration_date is server-managed."""

    assistant_id: str = Field(..., min_length=1, max_length=100, description="Assistant ID to update")
    class_name: str = Field(..., min_length=1, max_length=200, description="Python class name")
    module_path: str = Field(..., min_length=1, max_length=500, pattern="^[a-z0-9_.]+$", description="Python module path")
    name: str = Field(..., max_length=200)
    updated_by: str = Field(..., max_length=80)
    registration_status: str = Field(..., max_length=20, description="OK or Error")


class AssistantDeleteSchema(BaseModel):
    """Schema for deleting multiple assistants."""

    ids: list[str] = Field(..., min_length=1, description="List of assistant_id to delete")
