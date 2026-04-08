"""
AI Node - Base class for nodes that perform AI inference.

AI_Node provides flat input params: system_message (textarea), user_message (textarea),
prompt_template (textarea readonly - shows full template with {placeholders}).
TemplateParams removed: params are explicit and common to all AI nodes.

Default behaviour: Ollama + gemma3:270m, streaming.

Module path: nos.core.engine.node.ai.ai_node
Class name:  AI_Node

Usage in plugins:
    from nos.core.engine.node.ai import AI_Node, NodeOutput
"""

from datetime import datetime
from typing import Optional, Dict, Any, Type, Tuple

from ..node import Node, NodeOutput
from pydantic import BaseModel, Field


# =============================================================================
# Input/Output Schemas
# =============================================================================

class AINodeInputState(BaseModel):
    """Input state schema - workflow/context state. Empty by default."""

    pass


_DEFAULT_PROMPT_TEMPLATE = "[System]\n{system_message}\n\n[User]\n{user_message}"


def _service_path_from_provider(provider_id: str, mode: str = "chat") -> str:
    """Resolve provider_id + mode to full adapter class path."""
    p = (provider_id or "ollama").lower()
    if p == "openai":
        return "nos.platform.services.ai.openai_service.OpenAIChatAdapter"
    if p == "anthropic":
        return "nos.platform.services.ai.anthropic_service.AnthropicChatAdapter"
    if p == "ollama" and mode == "completion":
        return "nos.platform.services.ai.ollama_service.OllamaCompletionAdapter"
    return "nos.platform.services.ai.ollama_service.OllamaChatAdapter"


class AINodeInputParams(BaseModel):
    """Input params schema for AI inference. Flat structure: system_message, user_message, prompt_template."""

    provider_id: str = Field(
        default="ollama",
        description="AI provider identifier (default: ollama)",
    )
    model_id: Optional[str] = Field(
        default="mistral:7b" ,
        description= "Model ID from DB or raw model name (e.g. mistral:7b)",
    )
    config_id: Optional[str] = Field(
        default=None,
        description="Optional ai_model_config ID for temperature, system_prompt",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key (optional; prefer OPENAI_API_KEY / ANTHROPIC_API_KEY in .env). Masked, readonly.",
        json_schema_extra={"input_type": "password", "readonly": True},
    )
    system_message: str = Field(
        default="You are a helpful assistant. Answer the user's question directly.",
        description="System prompt (instruzioni per il modello)",
        json_schema_extra={"input_type": "textarea"},
    )
    user_message: str = Field(
        default="",
        description="Messaggio dell'utente da inviare al modello",
        json_schema_extra={"input_type": "textarea"},
    )
    prompt_template: str = Field(
        default=_DEFAULT_PROMPT_TEMPLATE,
        description="Default prompt template. Placeholders: {system_message}, {user_message}.",
        json_schema_extra={"input_type": "textarea", "readonly": True},
    )
    service: str = Field(
        default="nos.platform.services.ai.ollama_service.OllamaChatAdapter",
        description="Full adapter class path (e.g. nos.platform.services.ai.ollama_service.OllamaChatAdapter).",
        json_schema_extra={"readonly": True},
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Creativity 0.0-2.0 (default: 0.7)",
    )
    stream: bool = Field(
        default=True,
        description="Use streaming response (default: True)",
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Max tokens (if supported by provider)",
    )


class AINodeOutput(BaseModel):
    """Output schema - result of AI inference."""

    success: bool = Field(description="Whether the request succeeded")
    response: Optional[str] = Field(default=None, description="LLM response text")
    model: Optional[str] = Field(default=None, description="Model used")
    tokens: Optional[int] = Field(default=None, description="Tokens generated")
    duration_ms: Optional[float] = Field(default=None, description="Generation time in ms")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    streamed: Optional[bool] = Field(default=None, description="Whether response was streamed")
    chunks: Optional[int] = Field(default=None, description="Number of chunks (streaming mode)")


class AINodeMetadata(BaseModel):
    """Metadata schema - execution metadata."""

    executed_by: str = Field(..., description="Node class name")
    provider_id: str = Field(..., description="AI provider used")
    model: Optional[str] = Field(default=None, description="Model used")
    timestamp: str = Field(..., description="Execution timestamp (ISO 8601)")
    mode: Optional[str] = Field(default=None, description="'streaming' or 'sync'")


# =============================================================================
# AI_Node Implementation
# =============================================================================
#
# PATTERN: _do_execute is the central orchestrator - delegates to private methods.
# Each method has a single responsibility. Subclasses override input_params_schema
# (including prompt_template).
# =============================================================================


class AI_Node(Node):
    """
    Base class for nodes that perform AI inference.

    Uses the AI dispatcher to route requests to the correct provider (Ollama, etc.).
    Default: Ollama, gemma3:270m, streaming.

    Input state: empty
    Input params: provider_id, model_id, config_id, system_message, user_message,
                  prompt_template, service, temperature, stream, max_tokens
    Output: success, response, model, tokens, duration_ms, error, streamed, chunks
    Metadata: executed_by, provider_id, model, timestamp, mode
    """

    def __init__(self, node_id: str = "ai_node", name: str = None):
        super().__init__(node_id, name or "AI Node")

    @property
    def input_state_schema(self) -> Type[BaseModel]:
        """Return Pydantic model for workflow state validation."""
        return AINodeInputState

    @property
    def input_params_schema(self) -> Type[BaseModel]:
        """Return Pydantic model for direct params validation."""
        return AINodeInputParams

    @property
    def output_schema(self) -> Type[BaseModel]:
        """Return Pydantic model for output validation."""
        return AINodeOutput

    @property
    def metadata_schema(self) -> Type[BaseModel]:
        """Return Pydantic model for metadata validation."""
        return AINodeMetadata

    def _build_prompt(self, params_dict: dict, state_dict: Optional[dict] = None) -> str:
        """
        Build prompt from prompt_template, system_message, user_message.
        State dict (e.g. memory) is merged for subclasses.
        """
        template = params_dict["prompt_template"]
        params = {
            "system_message": str(params_dict.get("system_message", "") or ""),
            "user_message": str(params_dict.get("user_message", "") or ""),
        }
        if state_dict:
            params = {**state_dict, **params}
        try:
            return template.format(**params)
        except KeyError as e:
            if self._exec_log:
                self.exec_log.log("warning", f"Missing template param: {e}")
            return template

    def _create_inference_request(self, params_dict: dict, state_dict: Optional[dict] = None) -> "AIInferenceRequest":
        """
        Build AIInferenceRequest. Override in subclasses (e.g. ai_memory_node) to use
        conversational format (history) instead of single prompt.

        Returns:
            AIInferenceRequest for chat mode by default.
        """
        from nos.platform.services.ai import AIInferenceRequest
        system = str(params_dict.get("system_message") or params_dict.get("system") or "")
        user_message = str(params_dict.get("user_message") or "")
        svc = params_dict.get("service", "").strip()
        if not svc or not svc.startswith("nos.platform.services.ai."):
            svc = _service_path_from_provider(params_dict.get("provider_id", "ollama"), "chat")
        return AIInferenceRequest(
            prompt=user_message or "Hello",
            provider_id=params_dict.get("provider_id", "ollama"),
            model_id=params_dict.get("model_id"),
            config_id=params_dict.get("config_id"),
            system=system or None,
            service=svc,
            api_key=params_dict.get("api_key"),
            temperature=float(params_dict.get("temperature", 0.7)),
            stream=params_dict.get("stream", True),
            max_tokens=params_dict.get("max_tokens"),
        )

    def _run_inference(self, request: "AIInferenceRequest") -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Run inference via AI dispatcher. Returns (output_dict, metadata_dict).

        Args:
            request: AIInferenceRequest (prompt or prompt+history for conversational)

        Returns:
            Tuple of (output, metadata) conforming to AINodeOutput and AINodeMetadata
        """
        from nos.platform.services.ai import ai_dispatcher

        provider_id = request.provider_id
        do_stream = request.stream

        if do_stream:
            full_response = ""
            chunk_count = 0
            for chunk in ai_dispatcher.infer_stream(request):
                full_response += chunk
                chunk_count += 1
                if chunk_count % 10 == 0 and self._exec_log:
                    self.exec_log.log("debug", f"Received {chunk_count} chunks...")

            # Detect streaming errors (e.g. openai_service yields "[Error: ...]")
            stream_error = None
            if full_response.strip().startswith("[Error:"):
                stream_error = full_response.strip()

            output = {
                "success": stream_error is None,
                "response": full_response if stream_error is None else None,
                "model": request.model_id or "gemma3:270m",
                "streamed": True,
                "chunks": chunk_count,
                "error": stream_error,
            }
            metadata = {
                "executed_by": self.__class__.__name__,
                "provider_id": provider_id,
                "model": request.model_id,
                "timestamp": datetime.now().isoformat(),
                "mode": "streaming",
            }
            return output, metadata
        else:
            response = ai_dispatcher.infer(request)
            output = {
                "success": response.success,
                "response": response.content if response.success else None,
                "model": response.model,
                "tokens": response.tokens,
                "duration_ms": response.duration_ms,
                "error": response.error,
                "streamed": False,
            }
            metadata = {
                "executed_by": self.__class__.__name__,
                "provider_id": provider_id,
                "model": response.model,
                "timestamp": datetime.now().isoformat(),
                "mode": "sync",
            }
            return output, metadata

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Orchestrator: coordinates node execution. Builds prompt and runs inference.

        Pattern note for agents: _do_execute is the central entry point. Keep it minimal.
        For complex logic, use private methods (_build_prompt, _run_inference).
        This yields: (1) single responsibility per method, (2) more readable flow,
        (3) separated logic easier to maintain, (4) scalable node structure.
        """
        # PATTERN: Use self.exec_log.log for real-time logs
        if self._exec_log:
            self.exec_log.log("info", "🤖 AI Node starting inference...")

        request = self._create_inference_request(params_dict, state_dict)

        if self._exec_log:
            preview = request.prompt[:100] + "..." if len(request.prompt) > 100 else request.prompt
            svc = request.service or "chat"
            self.exec_log.log("info", f"📤 Prompt ({svc}): {preview}")

        output, metadata = self._run_inference(request)

        if self._exec_log:
            if output.get("success"):
                self.exec_log.log("info", "✓ Inference completed")
            else:
                self.exec_log.log("error", f"❌ Inference failed: {output.get('error', 'Unknown error')}")
        if not output.get("success"):
            # Propagate failure to the engine (status/error on NodeExecutionResult). Logging alone is not enough.
            raise ValueError(f"Inference failed: {output.get('error', 'Unknown error')}")
        return NodeOutput(output=output, metadata=metadata)


__all__ = [
    "AI_Node",
    "AINodeInputState",
    "AINodeInputParams",
    "AINodeOutput",
    "AINodeMetadata",
]
