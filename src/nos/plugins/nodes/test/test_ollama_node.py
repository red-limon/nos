"""
Test Ollama Node Plugin.

This node demonstrates integration with Ollama LLM service.
Use it to test your Ollama connection and experiment with prompts.

Based on the PATTERN from simple_sum_node. _do_execute is a minimal
orchestrator that delegates to internal methods for clarity and testability.

Module path: nos.plugins.nodes.dev_.test_ollama_node
Class name:  TestOllamaNode
Node ID:     test_ollama

To register this node:
    reg node test_ollama TestOllamaNode nos.plugins.nodes.dev_.test_ollama_node

To execute this node:
    run node db test_ollama --sync --debug --param prompt="Hello, who are you?"
    run node db test_ollama --sync --debug --param prompt="Explain Python in 3 sentences" --param model="llama3.2"

AI coding agent mode (default): uses docs/AI_CODING_AGENT_PROMPT.md as system prompt.
Your Prompt textarea = natural language request for plugin creation.
To render generated code in the Console code view: run with --output_format code
"""

# Base Node class and NodeOutput (typed return of _do_execute)
from nos.core.engine.base import Node, NodeOutput
# Pydantic for input/output validation schemas
from pydantic import BaseModel, Field
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

def _normalize_code_indentation(text: str) -> str:
    """
    Normalize Python code indentation: tabs → 4 spaces, trim trailing whitespace.
    Reduces IndentationError from LLM output (mixed tabs/spaces).
    """
    if not text or not isinstance(text, str):
        return text or ""
    lines = text.replace("\t", "    ").splitlines()
    return "\n".join(line.rstrip() for line in lines)


# Path to AI coding agent prompt (docs/AI_CODING_AGENT_PROMPT.md)
def _load_coding_agent_prompt() -> str:
    """Load AI coding agent system prompt from docs. Fallback if file missing."""
    try:
        import nos
        pkg_root = Path(nos.__file__).resolve().parent
        for base in (pkg_root.parent.parent, pkg_root.parent):
            path = base / "docs" / "AI_CODING_AGENT_PROMPT.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return (
        "You are an expert AI coding assistant for Hythera (workflow engine). "
        "You generate Node and Workflow plugins from natural language. "
        "If the request is not about creating a plugin, say so. "
        "If details are missing, ask for them. "
        "Otherwise output only the Python code, no markdown fences."
    )


# =============================================================================
# Input/Output Schemas
# =============================================================================
#
# PATTERN: Use default values for params when running with --debug form,
#          so validation passes with empty {} before the user fills the form.
# =============================================================================

class TestOllamaInputState(BaseModel):
    """Input state schema - workflow/context state. Empty when node has no state dependencies."""
    pass


class TestOllamaInputParams(BaseModel):
    """Input params schema - direct parameters for Ollama chat."""
    prompt: str = Field(
        default="Create a minimal reverse-string node: single `text` input, single `reversed` output. Follow Example 1 structure exactly.",
        description="Natural language request (e.g. plugin creation). With AI coding agent mode: your request is sent as user message; system uses coding agent prompt from docs/AI_CODING_AGENT_PROMPT.md.",
        json_schema_extra={
            "input_type": "textarea",
            "rows": 8,
        },
    )
    model: str = Field(
        default="gemma3:270m",
        description="Ollama model to use (default: gemma3:270m)"
    )
    system: Optional[str] = Field(
        default=None,
        description="System prompt to set context (optional)"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Creativity level 0.0-2.0 (default: 0.7)"
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response (default: False)"
    )
    use_coding_agent: bool = Field(
        default=True,
        description="When True, use AI coding agent system prompt from docs/AI_CODING_AGENT_PROMPT.md; your Prompt becomes the user request for plugin generation (default: True)"
    )
    num_predict: Optional[int] = Field(
        default=4096,
        description="Max tokens to generate (default: 4096). Increase if code is truncated."
    )
    repeat_penalty: Optional[float] = Field(
        default=1.1,
        ge=1.0,
        le=2.0,
        description="Penalize repetition (default: 1.1). Helps avoid generation loops."
    )


class TestOllamaOutput(BaseModel):
    """Output schema - result of Ollama chat request."""
    success: bool = Field(description="Whether the request succeeded")
    response: Optional[str] = Field(default=None, description="The LLM's response text")
    model: Optional[str] = Field(default=None, description="Model that was used")
    tokens: Optional[int] = Field(default=None, description="Number of tokens generated")
    duration_ms: Optional[float] = Field(default=None, description="Generation time in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if request failed")
    streamed: Optional[bool] = Field(default=None, description="Whether response was streamed")
    chunks: Optional[int] = Field(default=None, description="Number of chunks received (streaming mode)")
    language: Optional[str] = Field(default=None, description="Code language for code view (e.g. 'python')")


class TestOllamaMetadata(BaseModel):
    """Metadata schema - execution metadata."""
    executed_by: str = Field(..., description="Node class name")
    ollama_url: str = Field(..., description="Ollama server URL")
    timestamp: str = Field(..., description="Execution timestamp (ISO 8601)")
    mode: Optional[str] = Field(default=None, description="'streaming' when streaming")
    prompt_length: Optional[int] = Field(default=None, description="Length of prompt (sync mode)")
    response_length: Optional[int] = Field(default=None, description="Length of response (sync mode)")


# =============================================================================
# Node Implementation
# =============================================================================
#
# PATTERN: _do_execute is a minimal orchestrator - delegates to internal methods.
# Each internal method has a single responsibility and can be tested independently.
# =============================================================================

class TestOllamaNode(Node):
    """
    Test Ollama Node - Test LLM integration with Ollama.
    
    Input state: empty
    Input params: prompt, model, system, temperature, stream
    
    Output: success, response, model, tokens, duration_ms, error, streamed, chunks
    Metadata: executed_by, ollama_url, timestamp, mode, prompt_length, response_length
    """
    
    def __init__(self, node_id: str = "test_ollama", name: str = None):
        # PATTERN: Always call super().__init__(node_id, name)
        super().__init__(node_id, name or "Test Ollama")
    
    @property
    def input_state_schema(self):
        """Return Pydantic model for workflow state validation."""
        return TestOllamaInputState
    
    @property
    def input_params_schema(self):
        """Return Pydantic model for direct params validation."""
        return TestOllamaInputParams
    
    @property
    def output_schema(self):
        """Return Pydantic model for output validation."""
        return TestOllamaOutput
    
    @property
    def metadata_schema(self):
        """Return Pydantic model for metadata validation."""
        return TestOllamaMetadata
    
    @property
    def default_output_format(self) -> str:
        """Default to code view for generated plugin output."""
        return "code"
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Orchestrator: coordinates node execution; delegates to internal methods.

        Pattern note for agents: _do_execute is the central entry point. Keep it minimal.
        For complex logic, use private methods (e.g. _check_availability, _run_streaming).
        This yields: (1) single responsibility per method, (2) more readable flow,
        (3) separated logic easier to maintain, (4) scalable node structure.
        """
        from nos.platform.services.ai.ollama_service import ollama
        
        # PATTERN: Use self.exec_log.log for real-time logs
        self.exec_log.log("info", "🤖 Test Ollama Node starting...")
        
        # Check availability
        error_out = self._check_availability(ollama, params_dict)
        if error_out:
            return error_out
        
        # Run chat (streaming or sync)
        if params_dict.get("stream", False):
            output, metadata = self._run_streaming(ollama, params_dict)
        else:
            output, metadata = self._run_sync(ollama, params_dict)
        
        return NodeOutput(output=output, metadata=metadata)
    
    def _get_system_prompt(self, params_dict: dict) -> Optional[str]:
        """Resolve system prompt: coding agent template or explicit system param."""
        if params_dict.get("use_coding_agent", True):
            return _load_coding_agent_prompt()
        return params_dict.get("system")

    def _check_availability(self, ollama, params_dict: dict) -> Optional[NodeOutput]:
        """
        Check if Ollama server is available. Log config and available models.
        Returns NodeOutput with error if unavailable, None otherwise.
        """
        prompt = params_dict.get("prompt", "")
        model = params_dict.get("model")
        system = self._get_system_prompt(params_dict)
        temperature = float(params_dict.get("temperature", 0.7))
        
        self.exec_log.log("info", f"Ollama server: {ollama.base_url}")
        self.exec_log.log("info", f"Model: {model or ollama.default_model}")
        self.exec_log.log("debug", f"Temperature: {temperature}")
        if system:
            self.exec_log.log("debug", f"System prompt: {system[:50]}...")
        
        self.exec_log.log("info", "Checking Ollama server availability...")
        if not ollama.is_available():
            self.exec_log.log("error", "❌ Ollama server is not available!")
            return NodeOutput(
                output={
                    "success": False,
                    "error": f"Ollama server not available at {ollama.base_url}",
                    "response": None,
                    "model": model or ollama.default_model,
                },
                metadata={
                    "executed_by": "TestOllamaNode",
                    "ollama_url": ollama.base_url,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        
        self.exec_log.log("info", "✓ Ollama server is available")
        models = ollama.list_models()
        model_names = [m.name for m in models]
        self.exec_log.log(
            "info",
            f"Available models: {', '.join(model_names[:5])}{'...' if len(model_names) > 5 else ''}",
        )
        self.exec_log.log(
            "info",
            f"📤 Sending prompt: \"{prompt[:100]}{'...' if len(prompt) > 100 else ''}\"",
        )
        return None
    
    def _run_streaming(self, ollama, params_dict: dict) -> Tuple[dict, dict]:
        """Run streaming chat. Returns (output_dict, metadata_dict)."""
        prompt = params_dict.get("prompt", "")
        model = params_dict.get("model")
        system = self._get_system_prompt(params_dict)
        temperature = float(params_dict.get("temperature", 0.7))
        
        self.exec_log.log("info", "Streaming response...")
        full_response = ""
        chunk_count = 0
        
        num_predict = params_dict.get("num_predict", 4096)
        repeat_penalty = params_dict.get("repeat_penalty", 1.1)
        for chunk in ollama.chat_stream(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            num_predict=num_predict,
            repeat_penalty=repeat_penalty,
        ):
            full_response += chunk
            chunk_count += 1
            if chunk_count % 10 == 0:
                self.exec_log.log("debug", f"Received {chunk_count} chunks...")
        
        self.exec_log.log("info", f"✓ Received {chunk_count} chunks")
        
        if params_dict.get("output_format") == "code":
            full_response = _normalize_code_indentation(full_response)
        
        output = {
            "success": True,
            "response": full_response,
            "model": model or ollama.default_model,
            "chunks": chunk_count,
            "streamed": True,
        }
        if params_dict.get("output_format") == "code":
            output["language"] = "python"
        metadata = {
            "executed_by": "TestOllamaNode",
            "ollama_url": ollama.base_url,
            "mode": "streaming",
            "timestamp": datetime.now().isoformat(),
        }
        return output, metadata
    
    def _run_sync(self, ollama, params_dict: dict) -> Tuple[dict, dict]:
        """Run sync (non-streaming) chat. Returns (output_dict, metadata_dict)."""
        prompt = params_dict.get("prompt", "")
        model = params_dict.get("model")
        system = self._get_system_prompt(params_dict)
        temperature = float(params_dict.get("temperature", 0.7))
        
        num_predict = params_dict.get("num_predict", 4096)
        repeat_penalty = params_dict.get("repeat_penalty", 1.1)
        response = ollama.chat(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            num_predict=num_predict,
            repeat_penalty=repeat_penalty,
        )
        
        if response.success:
            duration_ms = response.total_duration / 1_000_000 if response.total_duration else None
            self.exec_log.log("info", f"✓ Response received from {response.model}")
            if response.eval_count:
                self.exec_log.log("debug", f"Tokens generated: {response.eval_count}")
            if duration_ms:
                self.exec_log.log("debug", f"Generation time: {duration_ms:.0f}ms")
            content = response.content
            if params_dict.get("output_format") == "code":
                content = _normalize_code_indentation(content)
            preview = content[:500] + "..." if len(content) > 500 else content
            self.exec_log.log("info", f"📥 Response: {preview}")
            
            output = {
                "success": True,
                "response": content,
                "model": response.model,
                "tokens": response.eval_count,
                "duration_ms": duration_ms,
                "streamed": False,
            }
            if params_dict.get("output_format") == "code":
                output["language"] = "python"
            metadata = {
                "executed_by": "TestOllamaNode",
                "ollama_url": ollama.base_url,
                "prompt_length": len(prompt),
                "response_length": len(content),
                "timestamp": datetime.now().isoformat(),
            }
            return output, metadata
        else:
            self.exec_log.log("error", f"❌ Ollama request failed: {response.error}")
            output = {
                "success": False,
                "error": response.error,
                "response": None,
                "model": response.model,
            }
            metadata = {
                "executed_by": "TestOllamaNode",
                "ollama_url": ollama.base_url,
                "timestamp": datetime.now().isoformat(),
            }
            return output, metadata
