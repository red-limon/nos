"""
Web console command layer (shared by HTTP routes and Socket.IO).

Schemas, command registry, and routing live here so :mod:`nos.platform.api.console`
and :mod:`nos.platform.sockets.console_events` reuse one implementation without
depending on :mod:`nos.core` (engine / nodes do not import this package).
"""

from .schemas import (
    ConsoleCommand,
    CommandRouting,
    ConsoleValidationResult,
    ConsoleOutput,
    OutputFormat
)

from .commands import (
    CommandDefinition,
    CommandRegistry,
    command_registry
)

from .router import (
    ConsoleRouter,
    console_router,
    validate_command,
    execute_command
)

__all__ = [
    # Schemas
    "ConsoleCommand",
    "CommandRouting",
    "ConsoleValidationResult",
    "ConsoleOutput",
    "OutputFormat",
    # Commands
    "CommandDefinition",
    "CommandRegistry",
    "command_registry",
    # Router
    "ConsoleRouter",
    "console_router",
    "validate_command",
    "execute_command",
]
