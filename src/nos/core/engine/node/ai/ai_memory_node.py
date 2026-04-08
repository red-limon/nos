"""
AI Memory Node - AI_Node with conversation memory (state-backed).

Uses conversational/chat format: system + history (parsed from memory) + current
user_message. Dispatches to Ollama chat API with proper message structure, not
single completion prompt. Better alignment with chat model training.

**input_state_schema**: AINodeWithMemoryInputState (memory, chat_turn, idle_timeout_minutes).
**input_params_schema**: AINodeWithMemoryInputParams (system_message, user_message, prompt_template).
**Format**: Conversational (history + prompt) via AIInferenceRequest.history.

Module path: nos.core.engine.node.ai.ai_memory_node
Class name:  AIMemoryNode
Node ID:     ai_memory_node

To register:
    reg node ai_memory_node AIMemoryNode nos.core.engine.node.ai.ai_memory_node

To execute (after reg):
    run node prod ai_memory_node --sync --debug
"""

import re
from typing import List, Type

from pydantic import BaseModel, ConfigDict, Field

from .ai_node import AI_Node
from ..node import NodeOutput
from . import ai_node as _ai_node


class AINodeWithMemoryInputState(BaseModel):
    """Input state schema for AI nodes with memory. Extra fields allowed for workflow use."""

    model_config = ConfigDict(extra="allow")

    memory: str = Field(
        default="",
        description="Conversation history (system + user + assistant messages)",
        json_schema_extra={"input_type": "textarea"},
    )
    chat_turn: int = Field(default=0, description="Turn counter (incremented each execution; used by ChatModel workflow)")
    idle_timeout_minutes: float = Field(
        default=5.0,
        description="Minutes to wait for form input before timeout (workflow state)",
    )


_SYSTEM_BLOCK = """You are a helpful, clear and precise conversational assistant.

STRICT RULES - you MUST follow:
1. NEVER start with: "Okay", "I understand", "Sure", "I will do my best", "Certainly", or similar acknowledgments.
2. ALWAYS start your reply with the actual answer. For "Who was X?" start directly with "X was..." or "X is...".
3. Do not repeat or echo the user message.
4. Be concise but complete. Give the key facts first.
5. Use the history only if relevant; if not, ignore it."""

# Template shown in form (readonly): payload structure sent to Ollama
_MEMORY_PROMPT_TEMPLATE = """### PAYLOAD AL MODELLO (conversazionale)

[System]
{system_message}

[History] (da memory)
{memory}

[User message]
{user_message}"""


class AINodeWithMemoryInputParams(_ai_node.AINodeInputParams):
    """Input params: memory-specific prompt_template, service='chat'."""

    service: str = Field(
        default="chat",
        description="Use chat API (multi-turn with history).",
    )
    prompt_template: str = Field(
        default=_MEMORY_PROMPT_TEMPLATE,
        description="Struttura payload (system + history + user). Solo lettura.",
        json_schema_extra={"input_type": "textarea", "readonly": True},
    )


def _parse_memory_to_history(memory: str) -> List[dict]:
    """Parse memory (### CURRENT USER MESSAGE / ### ASSISTANT) into chat history for Ollama."""
    if not memory or not memory.strip():
        return []
    pattern = r"### CURRENT USER MESSAGE\n(.*?)\n\n### ASSISTANT\n(.*?)(?=\n\n### CURRENT USER MESSAGE|$)"
    matches = re.findall(pattern, memory.strip(), re.DOTALL)
    history = []
    for msg, resp in matches:
        msg, resp = msg.strip(), resp.strip()
        if msg or resp:
            history.append({"role": "user", "content": msg})
            history.append({"role": "assistant", "content": resp})
    return history


class AIMemoryNode(AI_Node):
    """
    AI Node with memory - Multi-turn chat with state-backed conversation history.

    Uses conversational format: system + history + current user message.
    Dispatches to chat API (service='chat') with proper message structure.

    Overrides _create_inference_request because it must:
    - Read memory from state_dict (base has no access to state)
    - Parse memory into history (list of user/assistant messages)
    - Pass history to AIInferenceRequest (base does not handle history)

    The base _create_inference_request builds prompt-only requests from params_dict.
    AIMemoryNode needs state_dict to build history, so it must override.
    """

    def __init__(self, node_id: str = "ai_memory_node", name: str = None):
        super().__init__(node_id, name or "AI Memory")

    @property
    def input_state_schema(self) -> Type[BaseModel]:
        """State schema with required memory field."""
        return AINodeWithMemoryInputState

    @property
    def input_params_schema(self) -> Type[BaseModel]:
        """Params: system_message, user_message, prompt_template (readonly)."""
        return AINodeWithMemoryInputParams

    def _get_form_timeout_seconds(self, state_dict: dict) -> float:
        """Use idle_timeout_minutes from workflow state; default 5 min."""
        mins = state_dict.get("idle_timeout_minutes", 5.0)
        return max(10.0, float(mins) * 60.0)

    def _create_inference_request(self, params_dict: dict, state_dict: dict = None):
        """
        Build AIInferenceRequest with history from memory.

        Override required: base AI_Node does not read state_dict or build history.
        Steps:
        1. Read memory from state_dict (workflow conversation state).
        2. Parse memory into history (list of {role, content} for Ollama/OpenAI).
        3. Build request with system, history, current user_message, service='chat'.
        """
        state_dict = state_dict or {}
        memory = state_dict.get("memory", "")
        user_message = str(params_dict.get("user_message", "") or "").strip()
        system = str(params_dict.get("system_message", "") or "").strip() or _SYSTEM_BLOCK.strip()
        history = _parse_memory_to_history(memory)
        from .ai_node import _service_path_from_provider
        from nos.platform.services.ai import AIInferenceRequest

        svc = params_dict.get("service", "").strip()
        if not svc or not svc.startswith("nos.platform.services.ai."):
            svc = _service_path_from_provider(params_dict.get("provider_id", "ollama"), "chat")
        return AIInferenceRequest(
            prompt=user_message or "Hello",
            provider_id=params_dict.get("provider_id", "ollama"),
            model_id=params_dict.get("model_id"),
            config_id=params_dict.get("config_id"),
            system=system,
            history=history if history else None,
            service=svc,
            api_key=params_dict.get("api_key"),
            temperature=float(params_dict.get("temperature", 0.7)),
            stream=params_dict.get("stream", True),
            max_tokens=params_dict.get("max_tokens"),
        )

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """Execute inference and append exchange to memory."""
        result = super()._do_execute(state_dict, params_dict)
        memory = state_dict.get("memory", "")
        msg = str(params_dict.get("user_message", "") or "")
        response = result.output.get("response") or ""
        if msg or response:
            append = f"\n\n### CURRENT USER MESSAGE\n{msg}\n\n### ASSISTANT\n{response}"
            state_dict["memory"] = (memory or "").strip() + append
        # Increment chat_turn for ChatModel workflow (LoopLink uses it)
        state_dict["chat_turn"] = state_dict.get("chat_turn", 0) + 1
        return result


__all__ = ["AIMemoryNode", "AINodeWithMemoryInputState", "AINodeWithMemoryInputParams"]
