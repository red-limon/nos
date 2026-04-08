"""
Ollama Service - Centralized LLM integration for Hythera.

Provides a unified interface to interact with Ollama from anywhere in the application.
Configuration is loaded from environment variables.

Environment Variables:
    OLLAMA_BASE_URL: Ollama server URL (default: http://localhost:11434)
    OLLAMA_DEFAULT_MODEL: Default model to use (default: llama3.2)
    OLLAMA_TIMEOUT: Request timeout in seconds (default: 120)

Usage:
    from nos.platform.services.ai.ollama_service import ollama

    # Simple chat
    response = ollama.chat("Hello, how are you?")

    # Chat with specific model
    response = ollama.chat("Explain Python decorators", model="codellama")

    # Streaming chat
    for chunk in ollama.chat_stream("Tell me a story"):
        print(chunk, end="", flush=True)

    # List available models
    models = ollama.list_models()
"""

import os
import logging
from typing import Optional, List, Dict, Any, Generator, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class OllamaMessage:
    """A message in a chat conversation."""
    role: str  # "system", "user", "assistant"
    content: str
    images: Optional[List[str]] = None  # Base64 encoded images for multimodal


@dataclass
class OllamaResponse:
    """Response from Ollama API."""
    success: bool
    content: str = ""
    model: str = ""
    total_duration: Optional[int] = None  # nanoseconds
    eval_count: Optional[int] = None  # tokens generated
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class OllamaModel:
    """Information about an Ollama model."""
    name: str
    size: int = 0
    digest: str = ""
    modified_at: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class OllamaService:
    """
    Centralized Ollama service for LLM interactions.

    This service provides a clean interface to Ollama that can be used
    from anywhere in the application - nodes, workflows, API routes, etc.
    """

    def __init__(self):
        """Initialize the Ollama service with configuration from environment."""
        self._base_url: Optional[str] = None
        self._default_model: Optional[str] = None
        self._timeout: int = 120
        self._client = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization - load config and create client on first use."""
        if self._initialized:
            return

        self._base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._default_model = os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.2")
        self._timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))

        logger.info(f"Ollama service initialized: {self._base_url}, default model: {self._default_model}")
        self._initialized = True

    @property
    def base_url(self) -> str:
        """Get the configured Ollama base URL."""
        self._ensure_initialized()
        return self._base_url

    @property
    def default_model(self) -> str:
        """Get the configured default model."""
        self._ensure_initialized()
        return self._default_model

    @property
    def client(self):
        """Get or create the Ollama client (lazy loading)."""
        self._ensure_initialized()
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self._base_url, timeout=self._timeout)
            except ImportError:
                raise ImportError(
                    "Ollama library not installed. Install with: pip install ollama"
                )
        return self._client

    def is_available(self) -> bool:
        """Check if Ollama server is available and responding."""
        try:
            self.client.list()
            return True
        except Exception as e:
            logger.warning(f"Ollama server not available: {e}")
            return False

    def _get_field(self, obj: Any, field: str, default: Any = None) -> Any:
        """Get a field from an object that could be a dict or a Pydantic model."""
        if hasattr(obj, 'get'):
            value = obj.get(field, default)
            if value is not None:
                return value
        if hasattr(obj, field):
            return getattr(obj, field, default)
        try:
            return obj[field]
        except (KeyError, TypeError, IndexError):
            pass
        return default

    def list_models(self) -> List[OllamaModel]:
        """List all available models on the Ollama server."""
        try:
            response = self.client.list()
            models = []
            models_list = self._get_field(response, "models", [])

            for model_data in models_list:
                name = self._get_field(model_data, "name", "") or self._get_field(model_data, "model", "")
                modified_at = self._get_field(model_data, "modified_at", "")
                if hasattr(modified_at, 'isoformat'):
                    modified_at = modified_at.isoformat()
                elif not isinstance(modified_at, str):
                    modified_at = str(modified_at) if modified_at else ""
                digest = self._get_field(model_data, "digest", "")
                if isinstance(digest, str) and len(digest) > 12:
                    digest = digest[:12]

                models.append(OllamaModel(
                    name=name,
                    size=self._get_field(model_data, "size", 0),
                    digest=digest,
                    modified_at=modified_at,
                    details=self._get_field(model_data, "details", {})
                ))
            return models
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> OllamaResponse:
        """Send a chat message and get a response."""
        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature, **kwargs}
            )
            return OllamaResponse(
                success=True,
                content=response.get("message", {}).get("content", ""),
                model=response.get("model", model),
                total_duration=response.get("total_duration"),
                eval_count=response.get("eval_count"),
                raw=response
            )
        except Exception as e:
            logger.error(f"Ollama chat failed: {e}")
            return OllamaResponse(
                success=False,
                error=str(e),
                model=model
            )

    def chat_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Generator[str, None, None]:
        """Send a chat message and stream the response."""
        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        try:
            stream = self.client.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature, **kwargs},
                stream=True
            )
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        except Exception as e:
            logger.error(f"Ollama chat stream failed: {e}")
            yield f"[Error: {e}]"

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> OllamaResponse:
        """Generate a completion (non-chat mode)."""
        model = model or self.default_model
        try:
            response = self.client.generate(
                model=model,
                prompt=prompt,
                system=system,
                options={"temperature": temperature, **kwargs}
            )
            return OllamaResponse(
                success=True,
                content=response.get("response", ""),
                model=response.get("model", model),
                total_duration=response.get("total_duration"),
                eval_count=response.get("eval_count"),
                raw=response
            )
        except Exception as e:
            logger.error(f"Ollama generate failed: {e}")
            return OllamaResponse(
                success=False,
                error=str(e),
                model=model
            )

    def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> Generator[str, None, None]:
        """Generate a completion with streaming."""
        model = model or self.default_model
        try:
            stream = self.client.generate(
                model=model,
                prompt=prompt,
                system=system,
                options={"temperature": temperature, **kwargs},
                stream=True
            )
            for chunk in stream:
                content = chunk.get("response", "")
                if content:
                    yield content
        except Exception as e:
            logger.error(f"Ollama generate stream failed: {e}")
            yield f"[Error: {e}]"

    def embeddings(
        self,
        text: Union[str, List[str]],
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate embeddings for text."""
        model = model or self.default_model
        try:
            if isinstance(text, list):
                results = []
                for t in text:
                    response = self.client.embeddings(model=model, prompt=t)
                    results.append(response.get("embedding", []))
                return {"embeddings": results, "model": model}
            else:
                response = self.client.embeddings(model=model, prompt=text)
                return {"embedding": response.get("embedding", []), "model": model}
        except Exception as e:
            logger.error(f"Ollama embeddings failed: {e}")
            return {"error": str(e), "model": model}

    def pull_model(self, model_name: str) -> bool:
        """Pull/download a model from Ollama registry."""
        try:
            logger.info(f"Pulling model: {model_name}")
            self.client.pull(model_name)
            logger.info(f"Model {model_name} pulled successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False

    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific model."""
        try:
            return self.client.show(model_name)
        except Exception as e:
            logger.error(f"Failed to get model info for {model_name}: {e}")
            return None


# Global singleton instance
ollama = OllamaService()


# =============================================================================
# Adapters for AIDispatcher (AIServiceProtocol)
# =============================================================================

def _ollama_response_to_inference(r: OllamaResponse, model_name: str):
    """Convert OllamaResponse to AIInferenceResponse."""
    from .dispatcher import AIInferenceResponse
    duration_ms = r.total_duration / 1_000_000 if r.total_duration else None
    return AIInferenceResponse(
        success=r.success,
        content=r.content or "",
        model=r.model or model_name,
        tokens=r.eval_count,
        duration_ms=duration_ms,
        error=r.error,
        streamed=False,
    )


class OllamaChatAdapter:
    """Adapter for Ollama chat API. Implements AIServiceProtocol."""

    def infer_sync(self, request) -> "object":
        model = request.model_id or ollama.default_model
        r = ollama.chat(
            prompt=request.prompt,
            model=model,
            system=request.system,
            history=request.history,
            temperature=request.temperature,
        )
        return _ollama_response_to_inference(r, model)

    def infer_stream(self, request) -> Generator[str, None, None]:
        model = request.model_id or ollama.default_model
        yield from ollama.chat_stream(
            prompt=request.prompt,
            model=model,
            system=request.system,
            history=request.history,
            temperature=request.temperature,
        )


class OllamaCompletionAdapter:
    """Adapter for Ollama completion/generate API. Implements AIServiceProtocol."""

    def infer_sync(self, request) -> "object":
        model = request.model_id or ollama.default_model
        r = ollama.generate(
            prompt=request.prompt,
            model=model,
            system=request.system,
            temperature=request.temperature,
        )
        return _ollama_response_to_inference(r, model)

    def infer_stream(self, request) -> Generator[str, None, None]:
        model = request.model_id or ollama.default_model
        yield from ollama.generate_stream(
            prompt=request.prompt,
            model=model,
            system=request.system,
            temperature=request.temperature,
        )


__all__ = [
    "OllamaService",
    "OllamaResponse",
    "OllamaMessage",
    "OllamaModel",
    "OllamaChatAdapter",
    "OllamaCompletionAdapter",
    "ollama",
]
