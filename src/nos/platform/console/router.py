"""
Console command router.

Parses, validates, and routes console commands.
"""

import shlex
from typing import List, Tuple, Optional

from .schemas import ConsoleCommand, ConsoleValidationResult, CommandRouting, ConsoleOutput
from .commands import command_registry, CommandDefinition


class ConsoleRouter:
    """
    Router for console commands.
    
    Responsibilities:
    - Parse raw command strings
    - Validate command syntax
    - Return routing information for valid commands
    - Execute synchronous commands (help, clear, echo)
    """
    
    CONSOLE_EVENT = "console_command"
    
    def __init__(self):
        self.registry = command_registry
    
    def parse_command(self, raw: str) -> Tuple[str, List[str]]:
        """
        Parse a raw command string into command name and arguments.
        
        Args:
            raw: Raw command string from user input
            
        Returns:
            Tuple of (command_name, [arguments])
        """
        raw = raw.strip()
        if not raw:
            return "", []
        
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()
        
        if not parts:
            return "", []
        
        return parts[0].lower(), parts[1:]
    
    def validate(self, command: ConsoleCommand) -> ConsoleValidationResult:
        """
        Validate a console command.
        
        Args:
            command: ConsoleCommand with raw_command string
            
        Returns:
            ConsoleValidationResult with validation status and routing info
        """
        raw = command.raw_command.strip()
        
        # Empty command
        if not raw:
            return ConsoleValidationResult(
                valid=False,
                error="Empty command"
            )
        
        # Parse command
        cmd_name, args = self.parse_command(raw)
        
        # Look up command
        cmd_def = self.registry.get(cmd_name)
        
        if not cmd_def:
            return ConsoleValidationResult(
                valid=False,
                error=f"Unknown command: {cmd_name}. Type 'help' for available commands."
            )
        
        # Handle subcommands (e.g., "run node", "list nodes")
        subcommand = None
        if cmd_def.subcommands and args:
            sub_name = args[0].lower()
            if sub_name in cmd_def.subcommands:
                subcommand = sub_name
                args = args[1:]  # Remove subcommand from args
            else:
                # Unknown subcommand
                valid_subs = ", ".join(cmd_def.subcommands.keys())
                return ConsoleValidationResult(
                    valid=False,
                    error=f"Unknown subcommand '{sub_name}' for '{cmd_name}'. Valid: {valid_subs}"
                )
        elif cmd_def.subcommands and not args:
            # Subcommand required but not provided
            valid_subs = ", ".join(cmd_def.subcommands.keys())
            return ConsoleValidationResult(
                valid=False,
                error=f"Command '{cmd_name}' requires a subcommand: {valid_subs}"
            )
        
        # Build routing
        action = f"{cmd_name}_{subcommand}" if subcommand else cmd_name
        description = cmd_def.subcommands[subcommand].description if subcommand else cmd_def.description
        
        routing = CommandRouting(
            event_name=self.CONSOLE_EVENT,
            payload={
                "action": action,
                "command": cmd_name,
                "subcommand": subcommand,
                "args": args,
                "raw": raw
            },
            description=description
        )
        
        return ConsoleValidationResult(
            valid=True,
            routing=routing
        )
    
    def execute_sync(self, action: str, args: List[str]) -> Optional[ConsoleOutput]:
        """
        Execute synchronous commands (help, clear, status, echo).
        
        These commands can be executed immediately without async processing.
        
        Args:
            action: Command action (e.g., "help", "clear")
            args: Command arguments
            
        Returns:
            ConsoleOutput if command is synchronous, None otherwise
        """
        # Map of synchronous commands that can be handled directly
        sync_commands = {
            "help": self.registry._handle_help,
            "clear": self.registry._handle_clear,
            "status": self.registry._handle_status,
            "echo": self.registry._handle_echo,
            "config_list": self.registry._handle_config_list,
        }
        
        handler = sync_commands.get(action)
        if handler:
            return handler(args)
        
        return None
    
    def is_async_command(self, action: str) -> bool:
        """
        Check if a command requires async processing.
        
        Args:
            action: Command action string
            
        Returns:
            True if async processing is required
        """
        async_prefixes = [
            "run_", "list_", "create_", "reg_", "open_", "save",
            "unreg_", "pub_", "unpub_", "update_", "info_",
            "reload_", "rm_", "mv_", "ai_", "ollama_", "vect_",
            "plugin_",
        ]
        async_commands = ["dir", "stop", "ps", "logs", "sql", "tables", "describe", "save"]
        return any(action.startswith(prefix) for prefix in async_prefixes) or action in async_commands


# Global router instance
console_router = ConsoleRouter()


def validate_command(raw_command: str) -> ConsoleValidationResult:
    """
    Validate a raw command string.
    
    Convenience function for external use.
    
    Args:
        raw_command: Raw command string
        
    Returns:
        ConsoleValidationResult
    """
    command = ConsoleCommand(raw_command=raw_command)
    return console_router.validate(command)


def execute_command(action: str, args: List[str]) -> Optional[ConsoleOutput]:
    """
    Execute a command and return output.
    
    For synchronous commands, returns output directly.
    For async commands, returns None (handled via Socket.IO).
    
    Args:
        action: Command action string
        args: Command arguments
        
    Returns:
        ConsoleOutput or None
    """
    return console_router.execute_sync(action, args)
