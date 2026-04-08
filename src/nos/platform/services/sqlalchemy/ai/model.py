"""
AI Provider, Model, and Configuration DB models.

Tables:
- ai_provider: Connection settings for AI providers (OpenAI, Ollama, Anthropic, etc.)
- ai_model: Available models within each provider
- ai_model_config: Runtime configurations (temperature, max_tokens, system_prompt, etc.)

Security:
- API keys are NOT stored in plaintext; use api_key_env to reference environment variables
- api_key field is available for encrypted storage if needed (application-level encryption)
"""

from datetime import datetime
from typing import Optional, Dict, Any

from ....extensions import db


class AIProvider(db.Model):
    """
    AI Provider configuration.
    
    Represents a connection to an AI service provider (OpenAI, Ollama, Anthropic, local, etc.).
    API keys should be stored in environment variables and referenced via api_key_env.
    
    Attributes:
        provider_id: Unique identifier (e.g., 'openai', 'ollama-local', 'anthropic')
        name: Display name (e.g., 'OpenAI', 'Local Ollama', 'Anthropic Claude')
        provider_type: Type identifier (openai, ollama, anthropic, local, custom)
        base_url: API base URL (e.g., 'https://api.openai.com/v1', 'http://localhost:11434')
        api_key: Encrypted API key (optional, prefer api_key_env)
        api_key_env: Environment variable name for API key (e.g., 'OPENAI_API_KEY')
        headers: Additional HTTP headers as JSON (e.g., {"X-Custom-Header": "value"})
        is_local: Whether this provider runs locally (no network latency, free)
        is_active: Whether this provider is currently enabled
        priority: Order preference when multiple providers are available (lower = higher priority)
    """
    __tablename__ = "ai_provider"
    
    provider_id = db.Column(db.String(50), primary_key=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    provider_type = db.Column(db.String(50), nullable=False)  # openai, ollama, anthropic, local, custom
    base_url = db.Column(db.String(500), nullable=True)
    api_key = db.Column(db.String(500), nullable=True)  # Encrypted or null (use api_key_env)
    api_key_env = db.Column(db.String(100), nullable=True)  # e.g., "OPENAI_API_KEY"
    headers = db.Column(db.JSON, nullable=True)  # Additional HTTP headers
    is_local = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    priority = db.Column(db.Integer, nullable=False, default=100)
    
    # Audit fields
    created_by = db.Column(db.String(80), nullable=False, default="system")
    updated_by = db.Column(db.String(80), nullable=False, default="system")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    models = db.relationship("AIModel", back_populates="provider", lazy="dynamic")
    
    def to_dict(self, include_api_key: bool = False) -> Dict[str, Any]:
        """
        Convert to dictionary.
        
        Args:
            include_api_key: If True, include api_key (for admin use only)
        """
        result = {
            "provider_id": self.provider_id,
            "name": self.name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "headers": self.headers,
            "is_local": self.is_local,
            "is_active": self.is_active,
            "priority": self.priority,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_api_key:
            result["api_key"] = self.api_key
        return result
    
    def get_api_key(self) -> Optional[str]:
        """
        Get the API key, preferring environment variable over stored value.
        
        Returns:
            API key string or None if not configured
        """
        import os
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return self.api_key
    
    def __repr__(self) -> str:
        return f"<AIProvider {self.provider_id} ({self.provider_type})>"


class AIModel(db.Model):
    """
    AI Model definition.
    
    Represents a specific model available from a provider (e.g., gpt-4, llama3:8b).
    
    Attributes:
        model_id: Unique identifier (e.g., 'openai-gpt4', 'ollama-llama3-8b')
        provider_id: Foreign key to AIProvider
        name: Display name (e.g., 'GPT-4 Turbo', 'Llama 3 8B')
        model_name: Actual model identifier used in API calls (e.g., 'gpt-4-turbo', 'llama3:8b')
        context_length: Maximum context window size in tokens
        supports_tools: Whether model supports function calling / tools
        supports_vision: Whether model supports image inputs
        supports_streaming: Whether model supports streaming responses
        cost_per_1k_input: Cost per 1000 input tokens (for budgeting)
        cost_per_1k_output: Cost per 1000 output tokens (for budgeting)
        is_active: Whether this model is currently enabled
        model_metadata: Additional model metadata as JSON
    """
    __tablename__ = "ai_model"
    
    model_id = db.Column(db.String(100), primary_key=True, nullable=False)
    provider_id = db.Column(db.String(50), db.ForeignKey("ai_provider.provider_id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    model_name = db.Column(db.String(200), nullable=False)  # Actual API model name
    context_length = db.Column(db.Integer, nullable=True)
    supports_tools = db.Column(db.Boolean, nullable=False, default=False)
    supports_vision = db.Column(db.Boolean, nullable=False, default=False)
    supports_streaming = db.Column(db.Boolean, nullable=False, default=True)
    cost_per_1k_input = db.Column(db.Float, nullable=True)  # USD per 1K tokens
    cost_per_1k_output = db.Column(db.Float, nullable=True)  # USD per 1K tokens
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    model_metadata = db.Column(db.JSON, nullable=True)  # Additional model info
    
    # Audit fields
    created_by = db.Column(db.String(80), nullable=False, default="system")
    updated_by = db.Column(db.String(80), nullable=False, default="system")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    provider = db.relationship("AIProvider", back_populates="models")
    configs = db.relationship("AIModelConfig", back_populates="model", lazy="dynamic")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "name": self.name,
            "model_name": self.model_name,
            "context_length": self.context_length,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_streaming": self.supports_streaming,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "is_active": self.is_active,
            "model_metadata": self.model_metadata,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<AIModel {self.model_id} ({self.model_name})>"


class AIModelConfig(db.Model):
    """
    AI Model runtime configuration.
    
    Represents a reusable configuration profile for a model, containing parameters
    like temperature, max_tokens, system_prompt, etc.
    
    Attributes:
        config_id: Unique identifier (e.g., 'coding-assistant', 'creative-writer')
        model_id: Foreign key to AIModel
        name: Display name (e.g., 'Coding Assistant', 'Creative Writer')
        description: Description of this configuration's purpose
        params: JSON containing runtime parameters:
            - temperature: float (0.0-2.0)
            - max_tokens: int
            - top_p: float (0.0-1.0)
            - frequency_penalty: float
            - presence_penalty: float
            - system_prompt: str
            - stop_sequences: list[str]
            - response_format: dict (e.g., {"type": "json_object"})
        is_default: Whether this is the default config for the model
        is_active: Whether this config is currently enabled
        use_case: Optional use-case tag (coding, chat, analysis, creative, etc.)
    """
    __tablename__ = "ai_model_config"
    
    config_id = db.Column(db.String(100), primary_key=True, nullable=False)
    model_id = db.Column(db.String(100), db.ForeignKey("ai_model.model_id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    params = db.Column(db.JSON, nullable=False, default=dict)  # temperature, max_tokens, system_prompt, etc.
    service = db.Column(db.String(20), nullable=True)  # 'chat' | 'completion' - which API to use
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    use_case = db.Column(db.String(50), nullable=True)  # coding, chat, analysis, creative, etc.
    
    # Audit fields
    created_by = db.Column(db.String(80), nullable=False, default="system")
    updated_by = db.Column(db.String(80), nullable=False, default="system")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    model = db.relationship("AIModel", back_populates="configs")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "config_id": self.config_id,
            "model_id": self.model_id,
            "name": self.name,
            "description": self.description,
            "params": self.params,
            "service": self.service,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "use_case": self.use_case,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def get_param(self, key: str, default: Any = None) -> Any:
        """Get a specific parameter from params JSON."""
        if self.params and isinstance(self.params, dict):
            return self.params.get(key, default)
        return default
    
    def __repr__(self) -> str:
        return f"<AIModelConfig {self.config_id} for {self.model_id}>"
