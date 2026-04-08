"""
TranslationAINode – One-shot node specialized in translating the user message.

PURPOSE:
    Translates the user's message into a target language. Single-turn, no memory.
    Output: the translation only, no explanations.

INHERITANCE:
    Extends AI_Node. Adds `language` param (target language). Uses system_message
    built from language. AI dispatcher (Ollama by default).

REGISTRATION:
    reg node translation_ai_node TranslationAINode nos.plugins.nodes.ai.translation_ai_node

EXECUTION:
    run node prod translation_ai_node --sync --debug
"""

from pydantic import Field

from nos.core.engine.base import AI_Node
from nos.core.engine.node.ai import ai_node as _ai_node

_TRANSLATION_SYSTEM_TEMPLATE = """Translate the user's message into {language}. Output only the translation, no explanations or preamble."""

_PROMPT_TEMPLATE = """[System]
{system_message}

[User]
{user_message}"""


class TranslationAINodeInputParams(_ai_node.AINodeInputParams):
    """Params for translation node. Adds language, overrides prompt_template."""

    prompt_template: str = Field(
        default=_PROMPT_TEMPLATE,
        description="Payload structure (system + user). Read-only.",
        json_schema_extra={"input_type": "textarea", "readonly": True},
    )
    language: str = Field(
        default="English",
        description="Target language for the translation (e.g. English, Italian, Spanish)",
    )
    system_message: str = Field(
        default=_TRANSLATION_SYSTEM_TEMPLATE,
        description="System prompt. Use {language} for target language.",
        json_schema_extra={"input_type": "textarea"},
    )
    user_message: str = Field(
        default="",
        description="Text to translate",
        json_schema_extra={"input_type": "textarea"},
    )


class TranslationAINode(AI_Node):
    """
    One-shot translation: user_message → target language.
    """

    @property
    def input_params_schema(self):
        return TranslationAINodeInputParams

    def _create_inference_request(self, params_dict: dict, state_dict=None):
        """
        Override base: inject `language` into system_message before sending to the LLM.

        REASON:
            Base AI_Node passes system_message as-is. This node needs the target language
            embedded in the system prompt (e.g. "Translate into Italian"). The system
            template contains {language}; we format it here.

        STEPS:
            1. Read language from params_dict; fallback "English".
            2. Get raw system_message (default: _TRANSLATION_SYSTEM_TEMPLATE).
            3. If raw contains {language}, call .format(language=lang); else use as-is.
            4. Build AIInferenceRequest with prompt=user_message, system=formatted_system.
            5. Use temperature=0.3 (lower than base) for more consistent translations.

        AGENT: When extending, keep the language injection logic; add new params
        via params_dict and pass them to AIInferenceRequest if the provider supports them.
        """
        from nos.platform.services.ai import AIInferenceRequest

        lang = str(params_dict.get("language", "English")).strip() or "English"
        raw_system = str(params_dict.get("system_message", "") or _TRANSLATION_SYSTEM_TEMPLATE)
        system = raw_system.format(language=lang) if "{language}" in raw_system else raw_system
        user_message = str(params_dict.get("user_message", "") or "").strip()

        from nos.core.engine.node.ai.ai_node import _service_path_from_provider
        svc = params_dict.get("service", "").strip()
        if not svc or not svc.startswith("nos.platform.services.ai."):
            svc = _service_path_from_provider(params_dict.get("provider_id", "ollama"), "chat")
        return AIInferenceRequest(
            prompt=user_message or "(no text to translate)",
            provider_id=params_dict.get("provider_id", "ollama"),
            model_id=params_dict.get("model_id"),
            config_id=params_dict.get("config_id"),
            system=system,
            service=svc,
            api_key=params_dict.get("api_key"),
            temperature=float(params_dict.get("temperature", 0.3)),
            stream=params_dict.get("stream", True),
            max_tokens=params_dict.get("max_tokens"),
        )

    def __init__(self, node_id: str = "translation_ai_node", name: str = None):
        super().__init__(node_id, name or "Translation AI")


__all__ = ["TranslationAINode", "TranslationAINodeInputParams"]
