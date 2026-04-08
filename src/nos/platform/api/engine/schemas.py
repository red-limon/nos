"""Request/Response Pydantic schemas for Engine API."""

from typing import Literal

from pydantic import BaseModel, Field

# Command list for engine run shell (help response)
ENGINE_COMMANDS = [
    {"name": "help", "description": "Show available commands"},
    {"name": "pub", "description": "Publish plugin (update registration status from OK to Published)"},
    {
        "name": "run --background",
        "description": "Run in background (non-interactive; trace semantics, no realtime room)",
    },
    {
        "name": "run --background trace",
        "description": "Same as run --background (trace is forced for background)",
    },
    {
        "name": "run --sync trace",
        "description": "Run synchronously. Init form + logs; no intermediate node forms",
    },
    {
        "name": "run --sync debug",
        "description": "Run synchronously. All forms and logs (interactive step-by-step)",
    },
]


class EngineValidateCommandSchema(BaseModel):
    """Schema for validating engine run command."""

    command: str = Field(..., min_length=1, description="Command string (e.g. 'help', 'run --background')")
    type: Literal["nd", "wk", "ass"] = Field(..., description="Record type: nd=node, wk=workflow, ass=assistant")
    id: str = Field(..., min_length=1, max_length=100, description="Record id")


class EngineGetRecordSchema(BaseModel):
    """Schema for getting a single record by type and id. type: nd=node, wk=workflow, ass=assistant."""

    type: Literal["nd", "wk", "ass"] = Field(..., description="Record type: nd=node, wk=workflow, ass=assistant")
    id: str = Field(..., min_length=1, max_length=100, description="Record id (node_id, workflow_id, or assistant_id)")
