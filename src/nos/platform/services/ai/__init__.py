"""
AI services subpackage.

Contains provider-specific services (Ollama, OpenAI, Anthropic) and the AI dispatcher.
"""

from .ollama_service import (
    OllamaService,
    OllamaResponse,
    OllamaMessage,
    OllamaModel,
    OllamaChatAdapter,
    OllamaCompletionAdapter,
    ollama,
)
from .dispatcher import (
    AIInferenceRequest,
    AIInferenceResponse,
    AIDispatcher,
    ai_dispatcher,
)

__all__ = [
    "OllamaService",
    "OllamaResponse",
    "OllamaMessage",
    "OllamaModel",
    "OllamaChatAdapter",
    "OllamaCompletionAdapter",
    "ollama",
    "AIInferenceRequest",
    "AIInferenceResponse",
    "AIDispatcher",
    "ai_dispatcher",
]

# OpenAI and Anthropic services are lazy-loaded by the dispatcher.
# Install with: pip install openai anthropic
