"""
OpenAI Service - Chat completions API integration.

Uses OpenAI Chat Completions API (service='chat' only).
Supports streaming and non-streaming. API key from request or OPENAI_API_KEY env.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Generator

logger = logging.getLogger(__name__)


@dataclass
class OpenAIResponse:
    """Response from OpenAI API."""
    success: bool
    content: str = ""
    model: str = ""
    total_duration: Optional[int] = None
    eval_count: Optional[int] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


# Models that do NOT support the temperature parameter (GPT-5 reasoning models)
_OPENAI_NO_TEMPERATURE_MODELS = ("gpt-5-nano", "gpt-5-mini", "gpt-5")


def _openai_supports_temperature(model: str) -> bool:
    """True if the model supports temperature; GPT-5 models do not."""
    name = (model or "").lower()
    return not any(name.startswith(m) for m in _OPENAI_NO_TEMPERATURE_MODELS)


class OpenAIService:
    """
    OpenAI Chat Completions service.
    Uses POST /v1/chat/completions. Supports streaming.
    """

    def __init__(self):
        self._default_model = "gpt-5-nano"

    def _get_client(self, api_key: Optional[str] = None):
        """Create OpenAI client. Prefer request api_key, else OPENAI_API_KEY."""
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OpenAI API key required. Set api_key in params or OPENAI_API_KEY env.")
        try:
            from openai import OpenAI
            return OpenAI(api_key=key)
        except ImportError:
            raise ImportError("OpenAI library not installed. pip install openai")

    def _build_messages(
        self,
        prompt: str,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build messages list for Chat Completions."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return messages

    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        **kwargs
    ) -> "OpenAIResponse":
        """Chat completion (non-streaming)."""
        model = model or self._default_model
        client = self._get_client(api_key)
        messages = self._build_messages(prompt, system, history)
        opts = dict(kwargs)
        if _openai_supports_temperature(model):
            opts["temperature"] = temperature
        if max_tokens is not None:
            opts["max_tokens"] = max_tokens

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                **opts
            )
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice and choice.message else ""
            usage = getattr(response, "usage", None)
            tokens = usage.total_tokens if usage else None
            return OpenAIResponse(
                success=True,
                content=content or "",
                model=getattr(response, "model", None) or model,
                eval_count=tokens,
                raw=None
            )
        except Exception as e:
            logger.error(f"OpenAI chat failed: {e}")
            return OpenAIResponse(
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
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """Chat completion (streaming). Yields content chunks."""
        model = model or self._default_model
        client = self._get_client(api_key)
        messages = self._build_messages(prompt, system, history)
        opts = {"stream": True, **kwargs}
        if _openai_supports_temperature(model):
            opts["temperature"] = temperature
        if max_tokens is not None:
            opts["max_tokens"] = max_tokens

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                **opts
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"OpenAI chat stream failed: {e}")
            yield f"[Error: {e}]"


openai_svc = OpenAIService()


# =============================================================================
# Adapter for AIDispatcher (AIServiceProtocol)
# =============================================================================

class OpenAIChatAdapter:
    """Adapter for OpenAI Chat Completions. Implements AIServiceProtocol."""

    def infer_sync(self, request) -> "object":
        from .dispatcher import AIInferenceResponse
        model = request.model_id or openai_svc._default_model
        r = openai_svc.chat(
            prompt=request.prompt,
            model=model,
            system=request.system,
            history=request.history,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_key=request.api_key,
        )
        return AIInferenceResponse(
            success=r.success,
            content=r.content or "",
            model=r.model or model,
            tokens=r.eval_count,
            duration_ms=None,
            error=r.error,
            streamed=False,
        )

    def infer_stream(self, request) -> Generator[str, None, None]:
        model = request.model_id or openai_svc._default_model
        yield from openai_svc.chat_stream(
            prompt=request.prompt,
            model=model,
            system=request.system,
            history=request.history,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_key=request.api_key,
        )


__all__ = ["OpenAIService", "OpenAIResponse", "OpenAIChatAdapter", "openai_svc"]
