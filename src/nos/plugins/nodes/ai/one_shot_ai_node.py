"""
OneShotAINode – Single-turn AI inference without conversation state.

PURPOSE:
    Performs one-shot completion/chat to an LLM. No memory, no multi-turn.
    Use for: QA, summarization, classification, one-off prompts.

INHERITANCE:
    Extends AI_Node. Input params: system_message, user_message, prompt_template
    (readonly). Uses AI dispatcher (Ollama by default).

REGISTRATION:
    reg node one_shot_ai_node OneShotAINode nos.plugins.nodes.ai.one_shot_ai_node

EXECUTION:
    run node prod one_shot_ai_node --sync --debug
"""

from pydantic import Field

from nos.core.engine.base import AI_Node
from nos.core.engine.node.ai import ai_node as _ai_node

_ONE_SHOT_SYSTEM_PROMPT = """You are a helpful AI assistant. Respond coherently to the user's message—whether it is a question, a statement, a request, or an instruction. Do not use filler phrases; reply directly and appropriately."""

_ONE_SHOT_PROMPT_TEMPLATE = """[System]
{system_message}

[User]
{user_message}"""


class OneShotAINodeInputParams(_ai_node.AINodeInputParams):
    """Params for one-shot node. Overrides system_message, prompt_template."""

    system_message: str = Field(
        default=_ONE_SHOT_SYSTEM_PROMPT,
        description="System prompt (model instructions)",
        json_schema_extra={"input_type": "textarea"},
    )
    prompt_template: str = Field(
        default=_ONE_SHOT_PROMPT_TEMPLATE,
        description="Payload structure (system + user). Read-only.",
        json_schema_extra={"input_type": "textarea", "readonly": True},
    )


class OneShotAINode(AI_Node):
    """
    One-shot AI inference. Uses completion API (generate), not chat.
    Routes to OllamaCompletionAdapter (or chat adapter for OpenAI/Anthropic).
    """

    @property
    def input_params_schema(self):
        return OneShotAINodeInputParams

    def _create_inference_request(self, params_dict: dict, state_dict=None):
        from nos.platform.services.ai import AIInferenceRequest
        from nos.core.engine.node.ai import ai_node as _ai_node

        system = str(params_dict.get("system_message") or params_dict.get("system") or "")
        user_message = str(params_dict.get("user_message") or "")
        svc = params_dict.get("service", "").strip()
        if not svc or not svc.startswith("nos.platform.services.ai."):
            svc = _ai_node._service_path_from_provider(
                params_dict.get("provider_id", "ollama"), "completion"
            )
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

    def __init__(self, node_id: str = "one_shot_ai_node", name: str = None):
        super().__init__(node_id, name or "One Shot AI")


__all__ = ["OneShotAINode", "OneShotAINodeInputParams"]
