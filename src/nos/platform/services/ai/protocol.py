"""
AI Service Protocol - Interface that all AI service adapters must implement.

Adapters are loaded by path (e.g. nos.platform.services.ai.ollama_service.OllamaChatAdapter)
and invoked by the dispatcher for infer_sync or infer_stream.
"""

from typing import Generator, Protocol, runtime_checkable


@runtime_checkable
class AIServiceProtocol(Protocol):
    """All AI service adapters must implement infer_sync and infer_stream."""

    def infer_sync(self, request) -> "object":
        """Sync inference. Returns AIInferenceResponse-like object."""
        ...

    def infer_stream(self, request) -> Generator[str, None, None]:
        """Streaming inference. Yields content chunks."""
        ...
