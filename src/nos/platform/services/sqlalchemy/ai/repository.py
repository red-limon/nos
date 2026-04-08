"""
Repository functions for AI Provider, Model, and Config.

Provides CRUD operations and query helpers for AI-related tables.
"""

from typing import List, Optional, Tuple
from datetime import datetime

from ....extensions import db
from .model import AIProvider, AIModel, AIModelConfig


# ============================================================================
# AIProvider Repository
# ============================================================================

def get_all_providers(active_only: bool = False) -> List[AIProvider]:
    """Get all AI providers, optionally filtered by active status."""
    query = AIProvider.query.order_by(AIProvider.priority, AIProvider.name)
    if active_only:
        query = query.filter(AIProvider.is_active == True)
    return query.all()


def get_provider_by_id(provider_id: str) -> Optional[AIProvider]:
    """Get a provider by its ID."""
    return AIProvider.query.get(provider_id)


def get_providers_by_type(provider_type: str, active_only: bool = True) -> List[AIProvider]:
    """Get providers by type (openai, ollama, anthropic, etc.)."""
    query = AIProvider.query.filter(AIProvider.provider_type == provider_type)
    if active_only:
        query = query.filter(AIProvider.is_active == True)
    return query.order_by(AIProvider.priority).all()


def get_local_providers(active_only: bool = True) -> List[AIProvider]:
    """Get all local providers."""
    query = AIProvider.query.filter(AIProvider.is_local == True)
    if active_only:
        query = query.filter(AIProvider.is_active == True)
    return query.order_by(AIProvider.priority).all()


def create_provider(
    provider_id: str,
    name: str,
    provider_type: str,
    base_url: Optional[str] = None,
    api_key_env: Optional[str] = None,
    is_local: bool = False,
    priority: int = 100,
    headers: Optional[dict] = None,
    created_by: str = "system"
) -> AIProvider:
    """Create a new AI provider."""
    provider = AIProvider(
        provider_id=provider_id,
        name=name,
        provider_type=provider_type,
        base_url=base_url,
        api_key_env=api_key_env,
        is_local=is_local,
        priority=priority,
        headers=headers,
        created_by=created_by,
        updated_by=created_by,
    )
    db.session.add(provider)
    db.session.commit()
    return provider


def update_provider(provider_id: str, **kwargs) -> Optional[AIProvider]:
    """Update a provider. Pass only the fields to update."""
    provider = get_provider_by_id(provider_id)
    if not provider:
        return None
    
    allowed_fields = {
        "name", "provider_type", "base_url", "api_key", "api_key_env",
        "headers", "is_local", "is_active", "priority", "updated_by"
    }
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(provider, key, value)
    
    db.session.commit()
    return provider


def delete_provider(provider_id: str) -> Tuple[bool, Optional[str]]:
    """Delete a provider. Returns (success, error_message)."""
    provider = get_provider_by_id(provider_id)
    if not provider:
        return False, f"Provider '{provider_id}' not found"
    
    # Check for related models
    if provider.models.count() > 0:
        return False, f"Cannot delete provider '{provider_id}': has {provider.models.count()} associated models"
    
    db.session.delete(provider)
    db.session.commit()
    return True, None


# ============================================================================
# AIModel Repository
# ============================================================================

def get_all_models(active_only: bool = False) -> List[AIModel]:
    """Get all AI models, optionally filtered by active status."""
    query = AIModel.query.order_by(AIModel.name)
    if active_only:
        query = query.filter(AIModel.is_active == True)
    return query.all()


def get_model_by_id(model_id: str) -> Optional[AIModel]:
    """Get a model by its ID."""
    return AIModel.query.get(model_id)


def get_models_by_provider(provider_id: str, active_only: bool = True) -> List[AIModel]:
    """Get all models for a specific provider."""
    query = AIModel.query.filter(AIModel.provider_id == provider_id)
    if active_only:
        query = query.filter(AIModel.is_active == True)
    return query.order_by(AIModel.name).all()


def get_models_with_tools(active_only: bool = True) -> List[AIModel]:
    """Get all models that support function calling / tools."""
    query = AIModel.query.filter(AIModel.supports_tools == True)
    if active_only:
        query = query.filter(AIModel.is_active == True)
    return query.order_by(AIModel.name).all()


def get_models_with_vision(active_only: bool = True) -> List[AIModel]:
    """Get all models that support vision / image inputs."""
    query = AIModel.query.filter(AIModel.supports_vision == True)
    if active_only:
        query = query.filter(AIModel.is_active == True)
    return query.order_by(AIModel.name).all()


def create_model(
    model_id: str,
    provider_id: str,
    name: str,
    model_name: str,
    context_length: Optional[int] = None,
    supports_tools: bool = False,
    supports_vision: bool = False,
    supports_streaming: bool = True,
    cost_per_1k_input: Optional[float] = None,
    cost_per_1k_output: Optional[float] = None,
    model_metadata: Optional[dict] = None,
    created_by: str = "system"
) -> AIModel:
    """Create a new AI model."""
    model = AIModel(
        model_id=model_id,
        provider_id=provider_id,
        name=name,
        model_name=model_name,
        context_length=context_length,
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        supports_streaming=supports_streaming,
        cost_per_1k_input=cost_per_1k_input,
        cost_per_1k_output=cost_per_1k_output,
        model_metadata=model_metadata,
        created_by=created_by,
        updated_by=created_by,
    )
    db.session.add(model)
    db.session.commit()
    return model


def update_model(model_id: str, **kwargs) -> Optional[AIModel]:
    """Update a model. Pass only the fields to update."""
    model = get_model_by_id(model_id)
    if not model:
        return None
    
    allowed_fields = {
        "name", "model_name", "context_length", "supports_tools", "supports_vision",
        "supports_streaming", "cost_per_1k_input", "cost_per_1k_output",
        "is_active", "model_metadata", "updated_by"
    }
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(model, key, value)
    
    db.session.commit()
    return model


def delete_model(model_id: str) -> Tuple[bool, Optional[str]]:
    """Delete a model. Returns (success, error_message)."""
    model = get_model_by_id(model_id)
    if not model:
        return False, f"Model '{model_id}' not found"
    
    # Check for related configs
    if model.configs.count() > 0:
        return False, f"Cannot delete model '{model_id}': has {model.configs.count()} associated configurations"
    
    db.session.delete(model)
    db.session.commit()
    return True, None


# ============================================================================
# AIModelConfig Repository
# ============================================================================

def get_all_configs(active_only: bool = False) -> List[AIModelConfig]:
    """Get all model configurations, optionally filtered by active status."""
    query = AIModelConfig.query.order_by(AIModelConfig.name)
    if active_only:
        query = query.filter(AIModelConfig.is_active == True)
    return query.all()


def get_config_by_id(config_id: str) -> Optional[AIModelConfig]:
    """Get a configuration by its ID."""
    return AIModelConfig.query.get(config_id)


def get_configs_by_model(model_id: str, active_only: bool = True) -> List[AIModelConfig]:
    """Get all configurations for a specific model."""
    query = AIModelConfig.query.filter(AIModelConfig.model_id == model_id)
    if active_only:
        query = query.filter(AIModelConfig.is_active == True)
    return query.order_by(AIModelConfig.name).all()


def get_default_config_for_model(model_id: str) -> Optional[AIModelConfig]:
    """Get the default configuration for a model."""
    return AIModelConfig.query.filter(
        AIModelConfig.model_id == model_id,
        AIModelConfig.is_default == True,
        AIModelConfig.is_active == True
    ).first()


def get_configs_by_use_case(use_case: str, active_only: bool = True) -> List[AIModelConfig]:
    """Get configurations by use case (coding, chat, analysis, etc.)."""
    query = AIModelConfig.query.filter(AIModelConfig.use_case == use_case)
    if active_only:
        query = query.filter(AIModelConfig.is_active == True)
    return query.order_by(AIModelConfig.name).all()


def create_config(
    config_id: str,
    model_id: str,
    name: str,
    params: Optional[dict] = None,
    description: Optional[str] = None,
    service: Optional[str] = None,
    is_default: bool = False,
    use_case: Optional[str] = None,
    created_by: str = "system"
) -> AIModelConfig:
    """Create a new model configuration."""
    # If setting as default, unset other defaults for this model
    if is_default:
        AIModelConfig.query.filter(
            AIModelConfig.model_id == model_id,
            AIModelConfig.is_default == True
        ).update({"is_default": False})
    
    config = AIModelConfig(
        config_id=config_id,
        model_id=model_id,
        name=name,
        params=params or {},
        description=description,
        service=service,
        is_default=is_default,
        use_case=use_case,
        created_by=created_by,
        updated_by=created_by,
    )
    db.session.add(config)
    db.session.commit()
    return config


def update_config(config_id: str, **kwargs) -> Optional[AIModelConfig]:
    """Update a configuration. Pass only the fields to update."""
    config = get_config_by_id(config_id)
    if not config:
        return None
    
    # Handle is_default special case
    if kwargs.get("is_default") == True:
        AIModelConfig.query.filter(
            AIModelConfig.model_id == config.model_id,
            AIModelConfig.is_default == True,
            AIModelConfig.config_id != config_id
        ).update({"is_default": False})
    
    allowed_fields = {
        "name", "description", "params", "service", "is_default", "is_active", "use_case", "updated_by"
    }
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(config, key, value)
    
    db.session.commit()
    return config


def delete_config(config_id: str) -> Tuple[bool, Optional[str]]:
    """Delete a configuration. Returns (success, error_message)."""
    config = get_config_by_id(config_id)
    if not config:
        return False, f"Configuration '{config_id}' not found"
    
    db.session.delete(config)
    db.session.commit()
    return True, None


# ============================================================================
# Utility Functions
# ============================================================================

def get_model_with_provider(model_id: str) -> Optional[dict]:
    """Get model with its provider info for API calls."""
    model = get_model_by_id(model_id)
    if not model:
        return None
    
    provider = model.provider
    return {
        "model": model.to_dict(),
        "provider": provider.to_dict() if provider else None,
        "api_key": provider.get_api_key() if provider else None,
    }


def get_ready_models(
    supports_tools: Optional[bool] = None,
    supports_vision: Optional[bool] = None,
    provider_type: Optional[str] = None,
    local_only: bool = False
) -> List[dict]:
    """
    Get all models that are ready to use (active model + active provider).
    
    Args:
        supports_tools: Filter by tool support
        supports_vision: Filter by vision support
        provider_type: Filter by provider type
        local_only: Only return local providers
    
    Returns:
        List of dicts with model and provider info
    """
    query = db.session.query(AIModel).join(AIProvider).filter(
        AIModel.is_active == True,
        AIProvider.is_active == True
    )
    
    if supports_tools is not None:
        query = query.filter(AIModel.supports_tools == supports_tools)
    if supports_vision is not None:
        query = query.filter(AIModel.supports_vision == supports_vision)
    if provider_type:
        query = query.filter(AIProvider.provider_type == provider_type)
    if local_only:
        query = query.filter(AIProvider.is_local == True)
    
    query = query.order_by(AIProvider.priority, AIModel.name)
    
    results = []
    for model in query.all():
        results.append({
            "model": model.to_dict(),
            "provider": model.provider.to_dict() if model.provider else None,
        })
    return results
