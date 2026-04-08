"""
AI Dispatcher - Routes inference requests to the correct AI service adapter.

Given service (full class path, e.g. nos.platform.services.ai.ollama_service.OllamaChatAdapter),
loads the adapter and invokes infer_sync or infer_stream.
"""

import importlib
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Generator, List

logger = logging.getLogger(__name__)

_AI_SERVICES_WHITELIST = "nos.platform.services.ai."


@dataclass
class AIInferenceRequest:
    """Request for AI inference.

    - service: Full class path of adapter (e.g. nos.platform.services.ai.ollama_service.OllamaChatAdapter).
    - provider_id: Used for model resolution (DB lookup).
    - history: Optional. For chat adapters: [user, assistant, ...]. Ignored in completion.
    """

    prompt: str
    service: str = "nos.platform.services.ai.ollama_service.OllamaChatAdapter"  # Full class path
    provider_id: str = "ollama"
    model_id: Optional[str] = None  # DB model_id or raw model name (e.g. gemma3:270m)
    config_id: Optional[str] = None
    system: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    api_key: Optional[str] = None
    temperature: float = 0.7
    stream: bool = True
    max_tokens: Optional[int] = None


@dataclass
class AIInferenceResponse:
    """Response from AI inference."""

    success: bool
    content: str = ""
    model: str = ""
    tokens: Optional[int] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    streamed: bool = False
    chunks: Optional[int] = None


def _load_service_class(service: str) -> type:
    """Load adapter class from service path. Whitelist: nos.platform.services.ai.*"""
    if not service or not service.strip():
        raise ValueError("service is required (full class path)")
    s = service.strip()
    if not s.startswith(_AI_SERVICES_WHITELIST):
        raise ValueError(f"service path must start with {_AI_SERVICES_WHITELIST}")
    if s.count(".") < 2:
        raise ValueError("service must be module.path.ClassName")
    mod_path, cls_name = s.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name, None)
    if cls is None:
        raise ValueError(f"Class {cls_name} not found in {mod_path}")
    return cls


class AIDispatcher:
    """
    Dispatches AI inference requests to adapter classes loaded by service path.

    Adapters implement infer_sync(request) and infer_stream(request).
    """

    def __init__(self):
        self._instances: Dict[str, Any] = {}

    def _get_or_create_instance(self, cls: type) -> Any:
        """Singleton per adapter class."""
        key = f"{cls.__module__}.{cls.__qualname__}"
        if key not in self._instances:
            self._instances[key] = cls()
        return self._instances[key]

    def _prepare_request(self, request: AIInferenceRequest) -> None:
        """Mutate request with config and resolved model name."""
        config_params = self._load_config_params(request.config_id)
        system = request.system or config_params.get("system_prompt") or config_params.get("system")
        if system:
            request.system = system
        temperature = config_params.get("temperature", request.temperature)
        if temperature is not None:
            request.temperature = temperature
        provider_id = (request.provider_id or "ollama").lower()
        model_name = self._resolve_model_name(provider_id, request.model_id)
        request.model_id = model_name

    def _resolve_model_name(
        self,
        provider_id: str,
        model_id: Optional[str],
    ) -> str:
        """Resolve model_id to actual API model name."""
        if provider_id == "openai":
            if not model_id:
                from .openai_service import openai_svc
                return openai_svc._default_model
            try:
                from ...services.sqlalchemy.ai import repository as ai_repo
                model = ai_repo.get_model_by_id(model_id)
                if model:
                    return model.model_name
            except Exception as e:
                logger.debug(f"Could not resolve model from DB: {e}")
            return model_id
        if provider_id == "anthropic":
            if not model_id:
                from .anthropic_service import anthropic_svc
                return anthropic_svc._default_model
            try:
                from ...services.sqlalchemy.ai import repository as ai_repo
                model = ai_repo.get_model_by_id(model_id)
                if model:
                    return model.model_name
            except Exception as e:
                logger.debug(f"Could not resolve model from DB: {e}")
            return model_id
        if not model_id:
            from .ollama_service import ollama
            return ollama.default_model
        try:
            from ...services.sqlalchemy.ai import repository as ai_repo
            model = ai_repo.get_model_by_id(model_id)
            if model:
                return model.model_name
        except Exception as e:
            logger.debug(f"Could not resolve model from DB: {e}")
        return model_id

    def _load_config_params(self, config_id: Optional[str]) -> Dict[str, Any]:
        """Load params from ai_model_config if config_id is provided."""
        if not config_id:
            return {}
        try:
            from ...services.sqlalchemy.ai import repository as ai_repo
            config = ai_repo.get_config_by_id(config_id)
            if config and config.params:
                return dict(config.params)
        except Exception as e:
            logger.warning(f"Could not load config {config_id}: {e}")
        return {}

    def infer(self, request: AIInferenceRequest) -> AIInferenceResponse:
        """Run sync (non-streaming) inference."""
        self._prepare_request(request)
        cls = _load_service_class(request.service)
        instance = self._get_or_create_instance(cls)
        return instance.infer_sync(request)

    def infer_stream(
        self,
        request: AIInferenceRequest,
    ) -> Generator[str, None, None]:
        """Run streaming inference. Yields content chunks."""
        self._prepare_request(request)
        cls = _load_service_class(request.service)
        instance = self._get_or_create_instance(cls)
        yield from instance.infer_stream(request)


# Global singleton
ai_dispatcher = AIDispatcher()


__all__ = [
    "AIInferenceRequest",
    "AIInferenceResponse",
    "AIDispatcher",
    "ai_dispatcher",
]
