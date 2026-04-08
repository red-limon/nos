"""
ChatModel Workflow - Multi-turn chat with memory and form per turn.

Entry node: ai_memory_node (with debug_mode → form each iteration).
Loop: ChatLoopLink back to ai_memory_node until max_turns or user stops (Ctrl+C).
State: memory, chat_turn, max_turns, idle_timeout_minutes.

Module path:  nos.plugins.workflows.test.ai.chat_model
Class name:   ChatModelWorkflow
Workflow ID:  chat_model

To register:
    reg workflow chat_model ChatModelWorkflow nos.plugins.workflows.test.ai.chat_model

To execute (after reg workflow and reg node ai_memory_node):
    run workflow registry chat_model --sync --debug
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Workflow, Link, LinkResult
from nos.core.engine.workflow.state_mapping import create_simple_mapping
from nos.core.engine.registry import workflow_registry
from nos.core.engine.node.ai.ai_memory_node import AIMemoryNode


# --- State schema ---
class ChatModelState(BaseModel):
    """State for ChatModel workflow."""

    memory: str = Field(
        default="",
        description="Conversation history (User/Assistant messages)",
        json_schema_extra={"input_type": "textarea"},
    )
    chat_turn: int = Field(
        default=0,
        description="Current turn counter",
    )
    max_turns: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum turns before loop exits",
    )
    idle_timeout_minutes: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        description="Minutes to wait for form input before timeout",
    )


# --- Links ---
class ChatLoopLink(Link):
    """Loop link - continues until chat_turn >= max_turns."""

    def _route_impl(
        self,
        state: dict,
        last_output: Any,
        current_node_id: Optional[str] = None,
    ) -> LinkResult:
        chat_turn = state.get("chat_turn", 0)
        max_turns = state.get("max_turns", 10)
        if chat_turn < max_turns:
            return LinkResult(
                next_node_id=self.to_node_id,
                should_continue=True,
                metadata={"loop": True, "chat_turn": chat_turn, "max_turns": max_turns},
            )
        return LinkResult(
            next_node_id=None,
            should_continue=False,
            metadata={"loop": False, "chat_turn": chat_turn, "max_turns": max_turns},
        )


# --- Workflow ---
class ChatModelWorkflow(Workflow):
    """Chat workflow with memory, form per turn, max_turns, and idle timeout."""

    workflow_id = "chat_model"
    name = "Chat Model (AI with memory)"

    @property
    def state_schema(self):
        return ChatModelState

    def define(self):
        # Get or create ai_memory_node
        node = workflow_registry.create_node_instance("ai_memory_node")
        if node is None:
            node = AIMemoryNode(node_id="ai_memory_node", name="AI Memory")
        node.set_debug_mode(True)

        mapping = create_simple_mapping(
            input_fields={
                "memory": "memory",
                "chat_turn": "chat_turn",
                "idle_timeout_minutes": "idle_timeout_minutes",
            },
            output_fields={
                "memory": "memory",
                "chat_turn": "chat_turn",
            },
            description="ChatModel: memory, chat_turn, idle_timeout_minutes",
        )
        self.add_node(node, state_mapping=mapping)

        self.add_link(
            ChatLoopLink(
                link_id="chat_loop",
                from_node_id="ai_memory_node",
                to_node_id="ai_memory_node",
                name="Chat Loop",
            )
        )
        self.set_entry_node("ai_memory_node")


__all__ = ["ChatModelWorkflow", "ChatModelState", "ChatLoopLink"]
