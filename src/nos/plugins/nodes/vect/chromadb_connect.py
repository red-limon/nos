"""
ChromaDB Connect Node - Tests connection to ChromaDB vector database.

Uses the centralized ChromaDBService. Configuration from .env (CHROMADB_PERSIST_PATH).

Module path:  nos.plugins.nodes.vect.chromadb_connect
Class name:   ChromaDBConnectNode
Node ID:      chromadb_connect

To register:
    reg node chromadb_connect ChromaDBConnectNode nos.plugins.nodes.vect.chromadb_connect

To execute:
    run node db chromadb_connect --sync --debug
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput

logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================

class ChromaDBConnectOutput(BaseModel):
    """Output schema for ChromaDBConnectNode."""

    success: bool = Field(..., description="Connection success")
    path: Optional[str] = Field(default=None, description="Persist path (embedded mode)")
    host: Optional[str] = Field(default=None, description="Host:port (server mode)")
    version: str = Field(default="", description="ChromaDB version")
    mode: str = Field(default="embedded", description="embedded or server")
    error: Optional[str] = Field(default=None, description="Error message on failure")


# =============================================================================
# Node Implementation
# =============================================================================

class ChromaDBConnectNode(Node):
    """
    ChromaDB Connect Node - tests connection to ChromaDB.

    No input params required. Uses CHROMADB_PERSIST_PATH from .env.
    Output: success, path, version, mode (or error on failure).
    """

    def __init__(self, node_id: str = "chromadb_connect", name: Optional[str] = None):
        super().__init__(node_id, name or "ChromaDB Connect")

    @property
    def input_state_schema(self):
        return None

    @property
    def input_params_schema(self):
        return None

    @property
    def output_schema(self):
        return ChromaDBConnectOutput

    def _do_execute(self, state: dict, params_dict: dict) -> NodeOutput:
        from nos.platform.services.chromadb_service import chromadb_service

        result = chromadb_service.connect()

        return NodeOutput(
            output=result,
            metadata={"node_id": self.node_id, "service": "chromadb"},
        )
