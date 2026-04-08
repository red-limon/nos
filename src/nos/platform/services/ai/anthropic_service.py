"""
Anthropic Service - Claude Messages API integration.

Uses Anthropic Messages API (service='chat' only).
Supports streaming and non-streaming. API key from request or ANTHROPIC_API_KEY env.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Generator

logger = logging.getLogger(__name__)


@dataclass
class AnthropicResponse:
    """Response from Anthropic API."""
    success: bool
    content: str = ""
    model: str = ""
    total_duration: Optional[int] = None
    eval_count: Optional[int] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class AnthropicService:
    """
    Anthropic Claude Messages service.
    Uses POST /v1/messages. Supports streaming.
    """

    def __init__(self):
        self._default_model = "claude-sonnet-4-20250514"

    def _get_client(self, api_key: Optional[str] = None):
        """Create Anthropic client. Prefer request api_key, else ANTHROPIC_API_KEY."""
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "Anthropic API key required. Set api_key in params or ANTHROPIC_API_KEY env."
            )
        try:
            from anthropic import Anthropic
            return Anthropic(api_key=key)
        except ImportError:
            raise ImportError("Anthropic library not installed. pip install anthropic")

    def _build_messages(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build messages for API. History + current user message."""
        messages = []
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
    ) -> AnthropicResponse:
        """Messages completion (non-streaming)."""
        model = model or self._default_model
        client = self._get_client(api_key)
        messages = self._build_messages(prompt, history)
        max_tok = max_tokens or 1024

        opts = {"temperature": temperature, **kwargs}
        create_opts = dict(
            model=model,
            max_tokens=max_tok,
            messages=messages,
            **opts
        )
        if system:
            create_opts["system"] = system

        try:
            response = client.messages.create(**create_opts)
            content = ""
            if response.content:
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        content += block.text
            usage = getattr(response, "usage", None)
            tokens = usage.output_tokens if usage else None
            return AnthropicResponse(
                success=True,
                content=content,
                model=getattr(response, "model", None) or model,
                eval_count=tokens,
                raw=None
            )
        except Exception as e:
            logger.error(f"Anthropic chat failed: {e}")
            return AnthropicResponse(
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
        """Messages completion (streaming). Yields content chunks."""
        model = model or self._default_model
        client = self._get_client(api_key)
        messages = self._build_messages(prompt, history)
        max_tok = max_tokens or 1024

        opts = {"temperature": temperature, **kwargs}
        stream_opts = dict(
            model=model,
            max_tokens=max_tok,
            messages=messages,
            **opts
        )
        if system:
            stream_opts["system"] = system

        try:
            with client.messages.stream(**stream_opts) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
        except Exception as e:
            logger.error(f"Anthropic chat stream failed: {e}")
            yield f"[Error: {e}]"


anthropic_svc = AnthropicService()


# =============================================================================
# Adapter for AIDispatcher (AIServiceProtocol)
# =============================================================================

class AnthropicChatAdapter:
    """Adapter for Anthropic Messages API. Implements AIServiceProtocol."""

    def infer_sync(self, request) -> "object":
        from .dispatcher import AIInferenceResponse
        model = request.model_id or anthropic_svc._default_model
        r = anthropic_svc.chat(
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
        model = request.model_id or anthropic_svc._default_model
        yield from anthropic_svc.chat_stream(
            prompt=request.prompt,
            model=model,
            system=request.system,
            history=request.history,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_key=request.api_key,
        )


__all__ = ["AnthropicService", "AnthropicResponse", "AnthropicChatAdapter", "anthropic_svc"]
