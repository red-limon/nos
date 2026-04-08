"""Pydantic schemas for AI Model Config API."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class AIModelConfigCreateSchema(BaseModel):
    """Schema for creating an AI model configuration."""
    config_id: str = Field(..., min_length=1, max_length=100)
    model_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    params: Optional[Dict[str, Any]] = None
    service: Optional[str] = Field(None, max_length=20, description="'chat' | 'completion'")
    is_default: bool = False
    use_case: Optional[str] = Field(None, max_length=100)


class AIModelConfigUpdateSchema(BaseModel):
    """Schema for updating an AI model configuration."""
    config_id: Optional[str] = None
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    params: Optional[Dict[str, Any]] = None
    service: Optional[str] = Field(None, max_length=20, description="'chat' | 'completion'")
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    use_case: Optional[str] = Field(None, max_length=100)


class AIModelConfigDeleteSchema(BaseModel):
    """Schema for deleting AI model configurations."""
    ids: list[str] = Field(..., min_length=1)


class AIModelCreateSchema(BaseModel):
    """Schema for creating an AI model."""
    model_id: str = Field(..., min_length=1, max_length=100)
    provider_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    model_name: str = Field(..., min_length=1, max_length=200)
    context_length: Optional[int] = None
    supports_tools: bool = False
    supports_vision: bool = False
    supports_streaming: bool = True
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None


class AIProviderCreateSchema(BaseModel):
    """Schema for creating an AI provider."""
    provider_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    provider_type: str = Field(..., min_length=1, max_length=50)
    base_url: Optional[str] = Field(None, max_length=500)
    api_key_env: Optional[str] = Field(None, max_length=100)
    is_local: bool = False
    priority: int = Field(100, ge=0, le=1000)
