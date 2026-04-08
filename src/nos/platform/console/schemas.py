"""
Pydantic schemas for Console module.

Defines the data models for console commands, validation results, and routing.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field


class ConsoleCommand(BaseModel):
    """
    Input command from client.
    
    The raw_command string is parsed and validated by the router.
    """
    raw_command: str = Field(..., description="Raw command string from console input")
    
    class Config:
        json_schema_extra = {
            "example": {
                "raw_command": "run node SimpleSumNode"
            }
        }


class CommandRouting(BaseModel):
    """
    Routing information for a validated command.
    
    Contains the Socket.IO event name and payload to emit after validation.
    """
    event_name: str = Field(..., description="Socket.IO event name to emit")
    payload: dict = Field(default_factory=dict, description="Payload data for the event")
    description: str = Field(default="", description="Human-readable description of the command")
    
    class Config:
        json_schema_extra = {
            "example": {
                "event_name": "console_command",
                "payload": {"action": "help"},
                "description": "Display available commands"
            }
        }


class ConsoleValidationResult(BaseModel):
    """
    API response for command validation.
    
    Returns validation status and routing info if valid.
    """
    valid: bool = Field(..., description="Whether the command is valid")
    error: Optional[str] = Field(default=None, description="Error message if invalid")
    routing: Optional[CommandRouting] = Field(default=None, description="Routing info if valid")
    
    class Config:
        json_schema_extra = {
            "example": {
                "valid": True,
                "error": None,
                "routing": {
                    "event_name": "console_command",
                    "payload": {"action": "status"},
                    "description": "Show connection status"
                }
            }
        }


class OutputFormat(str):
    """Valid output format types."""
    TEXT = "text"
    JSON = "json"
    HTML = "html"
    TABLE = "table"
    CODE = "code"
    PROGRESS = "progress"
    TREE = "tree"
    HELP = "help"
    FORM_DATA = "formData"  # Interactive form for state/params editing
    CHART = "chart"  # Dynamic chart (bar, pie, line, etc.)
    DOWNLOAD = "download"  # Styled download link with file icon


class ConsoleOutput(BaseModel):
    """
    Output message from server to client.
    
    Used for console_output Socket.IO events.
    target: when "output", client renders in the Output panel (final node/workflow result);
            when None or "terminal", renders in the command prompt / terminal.
    """
    type: str = Field(default="info", description="Output type: info, success, error, warning, clear")
    format: str = Field(default="json", description="Output format: text, json, html, table, code, progress, tree")
    message: str = Field(..., description="Output message content")
    data: Optional[Any] = Field(default=None, description="Optional structured data")
    timestamp: Optional[float] = Field(default=None, description="Unix timestamp")
    target: Optional[str] = Field(default=None, description="Render target: 'terminal' (default) or 'output' for final result panel")
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "success",
                "format": "json",
                "message": "Command executed successfully",
                "data": {"result": 42},
                "timestamp": 1709125200.0
            }
        }
