"""
Console command definitions.

Defines available commands, their syntax, and handlers.
"""

from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
import time

from .schemas import CommandRouting, ConsoleOutput


@dataclass
class CommandDefinition:
    """
    Definition of a console command.
    
    Attributes:
        name: Command name (e.g., "help", "status", "run")
        aliases: Alternative names for the command
        description: Human-readable description
        usage: Usage syntax string
        handler: Function to execute the command (returns ConsoleOutput)
        subcommands: Optional subcommands (e.g., "run node", "run workflow")
    """
    name: str
    description: str
    usage: str = ""
    aliases: List[str] = field(default_factory=list)
    handler: Optional[Callable[..., ConsoleOutput]] = None
    subcommands: Dict[str, "CommandDefinition"] = field(default_factory=dict)


class CommandRegistry:
    """
    Registry of available console commands.
    
    Manages command definitions and provides lookup functionality.
    """
    
    def __init__(self):
        self._commands: Dict[str, CommandDefinition] = {}
        self._register_builtin_commands()
    
    def _register_builtin_commands(self):
        """Register built-in commands."""
        
        # help command
        self.register(CommandDefinition(
            name="help",
            description="Display available commands",
            usage="help [command] [--table|--default]\n\nOutput mode: --table renders as table, --default (default) uses formatted help.",
            aliases=["?", "h"],
            handler=self._handle_help
        ))
        
        # clear command
        self.register(CommandDefinition(
            name="clear",
            description="Clear console output",
            usage="clear",
            aliases=["cls"],
            handler=self._handle_clear
        ))
        
        # status command
        self.register(CommandDefinition(
            name="status",
            description="Show connection and system status",
            usage="status",
            aliases=["stat"],
            handler=self._handle_status
        ))
        
        # run command with subcommands
        run_cmd = CommandDefinition(
            name="run",
            description="Execute a node or workflow",
            usage="""run <node|workflow> <dev|prod> <id|path> [class_name] [--sync|--bk] [--trace|--debug] [--state k=v] [--param k=v] [--output_format ...]

Source modes:
  dev       Load class dynamically (requires full Python module path + class name)
            Example: run node dev nos.plugins.nodes.math.simple_sum SimpleSumNode
  prod      Use in-memory registry (requires node_id)
            Example: run node prod simple_sum

Execution modes (threading):
  --sync    Synchronous (blocking, waits for completion)
  --bk      Background (non-blocking, default)

Debug modes (with --sync only; --bk forces non-interactive trace, no realtime room):
  --trace   Real-time logs via WebSocket (skip node forms)
  --debug   Real-time logs + interactive forms (default)

Rendering:
  --output_format  Output format for result (default: json). Allowed: json, text, html, table, code, tree

Examples:
  run node prod my_node --sync --debug    Sync execution with full output
  run node prod my_node --bk --trace      Background with real-time logs
  run node prod my_node --output_format table   Render result as table""",
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Execute a node plugin",
                    usage="""run node <dev|prod> <module_path|node_id> [class_name] [--sync|--bk] [--trace|--debug] [--state k=v] [--param k=v] [--output_format ...]

Source modes:
  dev       Requires: <module.path> <ClassName> (passed to importlib as-is). External plugins: e.g.
            run node dev my_pkg.node_plugin MyNode. In-repo monorepo code: nos.plugins.nodes....
  prod      Requires: <node_id>
            Example: run node prod my_node --sync --debug"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Execute a workflow plugin",
                    usage="""run workflow <dev|prod> <module_path|workflow_id> [class_name] [--sync|--bk] [--trace|--debug] [--state k=v] [--param k=v] [--output_format ...]

Source modes:
  dev       Requires: <module.path> <ClassName> (import as-is). External: my_pkg.workflow_plugin MyWf;
            monorepo: nos.plugins.workflows....
  prod      Requires: <workflow_id>

Rendering:
  --output_format  Output format for result (default: json). Allowed: json, text, html, table, code, tree, chart, download"""
                )
            }
        )
        self.register(run_cmd)
        
        # list command with subcommands
        list_cmd = CommandDefinition(
            name="list",
            description="List registered plugins",
            usage="list <nodes|workflows|assistants>",
            aliases=["ls"],
            subcommands={
                "nodes": CommandDefinition(
                    name="nodes",
                    description="List all registered nodes",
                    usage="list nodes"
                ),
                "workflows": CommandDefinition(
                    name="workflows",
                    description="List all registered workflows",
                    usage="list workflows"
                ),
                "assistants": CommandDefinition(
                    name="assistants",
                    description="List all registered assistants",
                    usage="list assistants"
                )
            }
        )
        self.register(list_cmd)
        
        # config command with subcommands
        config_cmd = CommandDefinition(
            name="config",
            description="Show configuration variables from .env",
            usage="config list",
            subcommands={
                "list": CommandDefinition(
                    name="list",
                    description="List configuration variables from .env file",
                    usage="config list"
                )
            }
        )
        self.register(config_cmd)

        # echo command (for testing)
        self.register(CommandDefinition(
            name="echo",
            description="Echo back the input (for testing)",
            usage="echo <message>",
            handler=self._handle_echo
        ))
        
        # create command with subcommands
        create_cmd = CommandDefinition(
            name="create",
            description="Create a new node or workflow plugin",
            usage="""create <node|workflow> <id> --class ClassName --path <module.path> [--name DisplayName]

--class and --path are REQUIRED. Full or relative path supported:
  Full:   nos.plugins.nodes.my_folder.my_node
  Rel:    nodes.my_folder.my_node

Example: create node my_node --class MyNode --path nodes.my_folder.my_node""",
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Create a new node plugin with template code",
                    usage="create node <node_id> --class ClassName --path <path> [--name DisplayName] (--class and --path required)"
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Create a new workflow plugin with template code",
                    usage="create workflow <workflow_id> --class ClassName --path <path> [--name DisplayName] (--class and --path required)"
                )
            }
        )
        self.register(create_cmd)
        
        # save command - save plugin file to disk only (no registration)
        self.register(CommandDefinition(
            name="save",
            description="Save plugin code to file (from editor toolbar or console)",
            usage="""save

Writes the current editor content to the plugin file.

Can be invoked two ways:
  - Click the Save button in the code editor toolbar
  - Type 'save' in the console and press Enter

Requires a plugin to be open in the editor (open node <module_path> first).

Example:
  save

Behavior:
  - Saves the file to disk only (no registration)
  - Test with: run node dev <module_path> <ClassName> --sync --debug
  - Register when ready: reg node <id> <class> <module>""",
        ))
        
        # open command with subcommands
        open_cmd = CommandDefinition(
            name="open",
            description="Open and load a plugin file into the code editor",
            usage="""open <node|workflow> <module_path>

Full or relative path supported:
  open node nos.plugins.nodes.my_folder.my_node
  open node nodes.my_folder.my_node""",
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Open a node plugin file",
                    usage="open node <module_path>  (full or relative: nodes.my_folder.my_node)"
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Open a workflow plugin file",
                    usage="open workflow <module_path>  (full or relative: workflows.my_folder.my_workflow)"
                )
            }
        )
        self.register(open_cmd)
        
        # reg (register) command with subcommands
        reg_cmd = CommandDefinition(
            name="reg",
            description="Register a node or workflow (import and validate)",
            usage="""reg <node|workflow> <id> <class_name> <module_path> [name]

Example: reg node my_node MyNode nos.plugins.nodes.my_folder.my_node "My Node"

All arguments except name are REQUIRED.""",
            aliases=["register"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Register a node (import module, validate class, update DB status)",
                    usage="reg node <node_id> <ClassName> <module_path> [name]"
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Register a workflow (import module, validate class, update DB status)",
                    usage="reg workflow <workflow_id> <ClassName> <module_path> [name]"
                )
            }
        )
        self.register(reg_cmd)
        
        # dir command - show plugins directory structure
        self.register(CommandDefinition(
            name="dir",
            description="Show plugins directory structure (nos/plugins)",
            usage="dir",
            aliases=["tree", "ls-tree"]
        ))
        
        # stop command - stop a running execution
        self.register(CommandDefinition(
            name="stop",
            description="Stop a running node or workflow execution",
            usage="stop <execution_id>",
            aliases=["cancel", "kill"]
        ))
        
        # ps command - list active executions
        self.register(CommandDefinition(
            name="ps",
            description="List all active executions",
            usage="ps",
            aliases=["jobs", "executions"]
        ))
        
        # logs command - view execution logs from DB
        self.register(CommandDefinition(
            name="logs",
            description="View execution logs from database (for background executions)",
            usage="logs [execution_id] [--limit N]",
            aliases=["log"]
        ))
        
        # unreg (unregister) command with subcommands
        unreg_cmd = CommandDefinition(
            name="unreg",
            description="Unregister a plugin (delete DB record, remove from registry)",
            usage="""unreg <node|workflow> <id>

Remove a plugin from the database and in-memory registry.
The source file is NOT deleted. Cannot unregister published plugins.

Examples:
  unreg node my_test_node        Unregister a node
  unreg workflow test_pipeline   Unregister a workflow
  unregister node old_node       Using full alias""",
            aliases=["unregister"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Unregister a node plugin (cannot unregister published plugins)",
                    usage="""unreg node <node_id>

Examples:
  unreg node my_test_node
  unreg node deprecated_calculator"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Unregister a workflow plugin (cannot unregister published plugins)",
                    usage="""unreg workflow <workflow_id>

Examples:
  unreg workflow test_pipeline
  unreg workflow old_etl_process"""
                )
            }
        )
        self.register(unreg_cmd)
        
        # pub (publish) command with subcommands
        pub_cmd = CommandDefinition(
            name="pub",
            description="Publish a plugin (change status from OK to Pub)",
            usage="""pub <node|workflow> <id>

Mark a plugin as published (production-ready).
Published plugins cannot be deleted, renamed, or unregistered.

Examples:
  pub node data_processor       Publish a node for production
  pub workflow etl_pipeline     Publish a workflow
  publish node my_api_node      Using full alias""",
            aliases=["publish"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Publish a node plugin for production use",
                    usage="""pub node <node_id>

Examples:
  pub node data_processor
  pub node validated_calculator"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Publish a workflow plugin for production use",
                    usage="""pub workflow <workflow_id>

Examples:
  pub workflow etl_pipeline
  pub workflow data_sync_flow"""
                )
            }
        )
        self.register(pub_cmd)
        
        # unpub (unpublish) command with subcommands
        unpub_cmd = CommandDefinition(
            name="unpub",
            description="Unpublish a plugin (change status from Pub to OK)",
            usage="""unpub <node|workflow> <id>

Revert a published plugin back to development status.
This allows editing, renaming, or deletion of the plugin.

Examples:
  unpub node data_processor      Unpublish for further development
  unpub workflow etl_pipeline    Revert workflow to dev status
  unpublish node my_node         Using full alias""",
            aliases=["unpublish"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Unpublish a node plugin (back to development)",
                    usage="""unpub node <node_id>

Examples:
  unpub node data_processor
  unpub node api_connector"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Unpublish a workflow plugin (back to development)",
                    usage="""unpub workflow <workflow_id>

Examples:
  unpub workflow etl_pipeline
  unpub workflow batch_processor"""
                )
            }
        )
        self.register(unpub_cmd)
        
        # update command with subcommands
        update_cmd = CommandDefinition(
            name="update",
            description="Update plugin fields in database",
            usage="""update <node|workflow> <id> [--name value] [--class value] [--path value]

Update plugin metadata in the database without modifying source files.

Options:
  --name <value>   Update display name
  --class <value>  Update class name reference
  --path <value>   Update module path reference

Examples:
  update node my_node --name "My Improved Node"
  update node calc --class NewCalculatorNode
  update workflow pipeline --name "Data Pipeline v2" --class PipelineV2""",
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Update node plugin fields (name, class_name, module_path)",
                    usage="""update node <node_id> [--name value] [--class value] [--path value]

Examples:
  update node my_node --name "Better Node Name"
  update node calc --class ImprovedCalculator
  update node api --name "API Node" --class ApiNodeV2"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Update workflow plugin fields (name, class_name, module_path)",
                    usage="""update workflow <workflow_id> [--name value] [--class value] [--path value]

Examples:
  update workflow pipeline --name "ETL Pipeline v2"
  update workflow sync --class DataSyncV2"""
                )
            }
        )
        self.register(update_cmd)
        
        # info command with subcommands
        info_cmd = CommandDefinition(
            name="info",
            description="Show detailed plugin information",
            usage="""info <node|workflow> <id>

Display comprehensive information about a plugin:
- Database record (ID, name, class, module path, status)
- File status (exists, path, size)
- Registry status (loaded in memory)

Examples:
  info node simple_sum           Show node details
  info workflow data_pipeline    Show workflow details
  details node my_node           Using 'details' alias
  describe workflow etl          Using 'describe' alias""",
            aliases=["details", "describe"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Show node plugin details (DB, file, registry status)",
                    usage="""info node <node_id>

Examples:
  info node simple_sum
  info node data_processor
  details node my_calculator"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Show workflow plugin details (DB, file, registry status)",
                    usage="""info workflow <workflow_id>

Examples:
  info workflow data_pipeline
  info workflow etl_process
  describe workflow batch_sync"""
                )
            }
        )
        self.register(info_cmd)
        
        # reload command with subcommands
        reload_cmd = CommandDefinition(
            name="reload",
            description="Reload a plugin (unregister and re-register from source)",
            usage="""reload <node|workflow> <id>

Hot-reload a plugin after code changes without restarting the server.
Unregisters from memory and re-imports the module from disk.

Examples:
  reload node my_calculator      Reload after editing node code
  reload workflow data_pipeline  Reload workflow after changes
  refresh node api_node          Using 'refresh' alias""",
            aliases=["refresh"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Reload a node plugin after code changes",
                    usage="""reload node <node_id>

Examples:
  reload node my_calculator
  reload node data_processor
  refresh node test_node"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Reload a workflow plugin after code changes",
                    usage="""reload workflow <workflow_id>

Examples:
  reload workflow data_pipeline
  reload workflow etl_process
  refresh workflow batch_job"""
                )
            }
        )
        self.register(reload_cmd)
        
        # rm (remove) command with subcommands
        rm_cmd = CommandDefinition(
            name="rm",
            description="Delete a plugin (file + DB record)",
            usage="""rm <node|workflow> <id>

PERMANENTLY delete a plugin: removes source file and database record.
Cannot delete published plugins - unpublish first.
WARNING: This action cannot be undone!

Examples:
  rm node test_node              Delete a test node
  rm workflow old_pipeline       Delete an old workflow
  delete node deprecated_calc    Using 'delete' alias
  remove workflow temp_flow      Using 'remove' alias""",
            aliases=["delete", "remove"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Delete a node plugin permanently (cannot delete published)",
                    usage="""rm node <node_id>

Examples:
  rm node test_node
  rm node deprecated_calculator
  delete node old_api_node"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Delete a workflow plugin permanently (cannot delete published)",
                    usage="""rm workflow <workflow_id>

Examples:
  rm workflow old_pipeline
  rm workflow test_etl
  delete workflow deprecated_flow"""
                )
            }
        )
        self.register(rm_cmd)
        
        # mv (rename) command with subcommands
        mv_cmd = CommandDefinition(
            name="mv",
            description="Rename a plugin (file + DB record)",
            usage="""mv <node|workflow> <old_id> <new_id>

Rename a plugin: updates file name, class name, and database record.
Cannot rename published plugins - unpublish first.

Examples:
  mv node old_calc new_calculator     Rename a node
  mv workflow pipe_v1 pipe_v2         Rename a workflow
  rename node test_node prod_node     Using 'rename' alias
  move workflow draft final           Using 'move' alias""",
            aliases=["rename", "move"],
            subcommands={
                "node": CommandDefinition(
                    name="node",
                    description="Rename a node plugin (cannot rename published)",
                    usage="""mv node <old_node_id> <new_node_id>

Examples:
  mv node old_calculator new_calculator
  mv node test_api production_api
  rename node draft_node final_node"""
                ),
                "workflow": CommandDefinition(
                    name="workflow",
                    description="Rename a workflow plugin (cannot rename published)",
                    usage="""mv workflow <old_workflow_id> <new_workflow_id>

Examples:
  mv workflow pipeline_v1 pipeline_v2
  mv workflow test_etl production_etl
  rename workflow draft_flow final_flow"""
                )
            }
        )
        self.register(mv_cmd)

        # plugin — scaffold or editable-install external packages under PLUGIN_PATH
        plugin_cmd = CommandDefinition(
            name="plugin",
            description="Create or install an external plugin package under PLUGIN_PATH",
            usage="""plugin <create|install> <name>

create   Scaffold a pip-installable package at PLUGIN_PATH/<distribution-name>/ (node.py, workflow.py,
         link.py from reference_templates; models.py, routes.py). Fails if the folder already exists.

install  Run pip install -e into ``{PLATFORM_PATH}/.venv`` when that interpreter exists; else the
         running process (sys.executable). Override: PLUGIN_INSTALL_PYTHON.

Environment:
  PLUGIN_PATH            Absolute path to external plugin projects (default ~/.nos/plugins).
  PLATFORM_PATH          NOS checkout; default venv for pip is ``<PLATFORM_PATH>/.venv``.
  PLUGIN_INSTALL_PYTHON  Optional absolute path to python.exe / python (override for pip).

After install, you can run dev tests immediately; restart the server so PluginManager picks up new entry points.

Examples:
  plugin create my-thing
  plugin install my-thing""",
            subcommands={
                "create": CommandDefinition(
                    name="create",
                    description="Scaffold a new plugin package under PLUGIN_PATH",
                    usage="plugin create <name>  (e.g. my-thing or my_thing)",
                ),
                "install": CommandDefinition(
                    name="install",
                    description="Editable-install into PLATFORM_PATH/.venv (or override)",
                    usage="plugin install <name>  (same name as create; distribution folder under PLUGIN_PATH)",
                ),
            },
        )
        self.register(plugin_cmd)
        
        # sql command - execute raw SQL queries
        self.register(CommandDefinition(
            name="sql",
            description="Execute a SQL query on the database",
            usage="""sql <query> [--write] [--output_format csv|excel|json]

Execute raw SQL queries. Read-only by default (SELECT, PRAGMA, EXPLAIN).
Use --write flag to enable INSERT/UPDATE/DELETE operations.
Use --output_format to export results as downloadable file.

Options:
  --write                         Enable write operations (INSERT/UPDATE/DELETE)
  --output_format csv|excel|json  Export results to downloadable file

Examples:
  sql SELECT * FROM ai_provider
  sql SELECT * FROM ai_model WHERE is_active = 1 LIMIT 10
  sql PRAGMA table_info(ai_provider)
  sql UPDATE ai_provider SET is_active = 0 WHERE provider_id = 'test' --write
  sql SELECT * FROM node --output_format excel
  sql SELECT * FROM ai_model --output_format csv""",
            aliases=["exec"]
        ))
        
        # query command - SELECT only with table output
        self.register(CommandDefinition(
            name="query",
            description="Execute a SELECT query and display results as table",
            usage="""query <SELECT statement> [--limit N] [--output_format csv|excel|json]

Execute SELECT queries only. Results are displayed in an interactive table.
Default limit is 100 rows, use --limit to change.
Use --output_format to export results as downloadable file.

Options:
  --limit N                       Maximum rows to return (default: 100)
  --output_format csv|excel|json  Export results to downloadable file

Examples:
  query SELECT * FROM ai_provider
  query SELECT name, is_active FROM ai_model --limit 50
  query SELECT COUNT(*) as total FROM ai_provider
  query SELECT * FROM workflow --limit 100 --output_format excel
  query SELECT name, description FROM node --output_format json""",
            aliases=["select"]
        ))
        
        # ai command with subcommands for AI management
        ai_cmd = CommandDefinition(
            name="ai",
            description="Manage AI providers, models, and configurations",
            usage="""ai <providers|models|configs> [action] [args...]

Subcommands:
  ai providers [list|add|update|delete]   Manage AI providers
  ai models [list|add|update|delete]      Manage AI models
  ai configs [list|add|update|delete]     Manage model configurations

Examples:
  ai providers list
  ai providers add ollama-local "Local Ollama" ollama http://localhost:11434
  ai models list --provider ollama-local
  ai configs list --model ollama-llama3""",
            subcommands={
                "providers": CommandDefinition(
                    name="providers",
                    description="Manage AI providers",
                    usage="""ai providers <list|add|update|delete|info> [args...]

Actions:
  list                              List all providers
  add <id> <name> <type> [url]      Add a new provider
  update <id> [--field value]       Update provider fields
  delete <id>                       Delete a provider
  info <id>                         Show provider details

Examples:
  ai providers list
  ai providers add openai "OpenAI" openai --env OPENAI_API_KEY
  ai providers add ollama-local "Local Ollama" ollama http://localhost:11434 --local
  ai providers info ollama-local"""
                ),
                "models": CommandDefinition(
                    name="models",
                    description="Manage AI models",
                    usage="""ai models <list|add|update|delete|info> [args...]

Actions:
  list [--provider <id>]            List all models (optionally by provider)
  add <id> <provider> <name> <model_name> [options]  Add a new model
  update <id> [--field value]       Update model fields
  delete <id>                       Delete a model
  info <id>                         Show model details

Examples:
  ai models list
  ai models list --provider ollama-local
  ai models add ollama-llama3 ollama-local "Llama 3" llama3 --context 8192
  ai models info ollama-llama3"""
                ),
                "configs": CommandDefinition(
                    name="configs",
                    description="Manage model configurations",
                    usage="""ai configs <list|add|update|delete|info> [args...]

Actions:
  list [--model <id>]               List all configs (optionally by model)
  add <id> <model> <name> [options] Add a new configuration
  update <id> [--field value]       Update config fields
  delete <id>                       Delete a configuration
  info <id>                         Show config details

Options for add/update:
  --temp <float>    Temperature (0.0-2.0)
  --tokens <int>    Max tokens
  --system <str>    System prompt
  --default         Set as default for model

Examples:
  ai configs list
  ai configs add coding-assistant ollama-llama3 "Coding Assistant" --temp 0.3 --system "You are a coding expert"
  ai configs info coding-assistant"""
                )
            }
        )
        self.register(ai_cmd)
        
        # tables command - list database tables
        self.register(CommandDefinition(
            name="tables",
            description="List all database tables",
            usage="tables",
            aliases=["show-tables", "schema"]
        ))
        
        # describe command - show table structure
        self.register(CommandDefinition(
            name="describe",
            description="Show table structure/schema",
            usage="describe <table_name>",
            aliases=["desc"]
        ))
        
        # vect command - vector DB operations (ChromaDB, etc.)
        vect_cmd = CommandDefinition(
            name="vect",
            description="Vector database operations",
            usage="""vect <chromadb> <connect|collections|coll>

Subcommands:
  chromadb connect      Test ChromaDB connection
  chromadb collections  List ChromaDB collections (alias: coll)

Examples:
  vect chromadb connect       Test connection (default)
  vect chromadb collections   List collections
  vect chromadb coll          Same as collections""",
            subcommands={
                "chromadb": CommandDefinition(
                    name="chromadb",
                    description="ChromaDB vector database",
                    usage="vect chromadb <connect|collections>",
                    subcommands={
                        "connect": CommandDefinition(
                            name="connect",
                            description="Test ChromaDB connection",
                            usage="vect chromadb connect"
                        ),
                        "collections": CommandDefinition(
                            name="collections",
                            description="List ChromaDB collections",
                            usage="vect chromadb collections"
                        ),
                    }
                )
            }
        )
        self.register(vect_cmd)
        
        # ollama command with subcommands
        ollama_cmd = CommandDefinition(
            name="ollama",
            description="Interact with Ollama LLM server",
            usage="""ollama <ping|models> [--output_format table|json|text]

Subcommands:
  ping      Check if Ollama server is available and responding
  models    List all models loaded on the Ollama server

Options (models only):
  --output_format  Output format: table (default for models), json, text

Examples:
  ollama ping       Check connection to Ollama
  ollama models     List available models (table)
  ollama models --output_format table   Render as table""",
            subcommands={
                "ping": CommandDefinition(
                    name="ping",
                    description="Check Ollama server connection and availability",
                    usage="ollama ping"
                ),
                "models": CommandDefinition(
                    name="models",
                    description="List all models available on Ollama server",
                    usage="ollama models [--output_format table|json|text]"
                )
            }
        )
        self.register(ollama_cmd)
    
    def register(self, command: CommandDefinition):
        """Register a command."""
        self._commands[command.name] = command
        for alias in command.aliases:
            self._commands[alias] = command
    
    def get(self, name: str) -> Optional[CommandDefinition]:
        """Get a command by name or alias."""
        return self._commands.get(name.lower())
    
    def get_all(self) -> List[CommandDefinition]:
        """Get all unique commands (excluding aliases)."""
        seen = set()
        commands = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                commands.append(cmd)
        return sorted(commands, key=lambda c: c.name)
    
    # Built-in command handlers
    
    def _handle_help(self, args: List[str] = None) -> ConsoleOutput:
        """Handle help command. Supports --table output mode."""
        args = args or []
        use_table = "--table" in args
        args = [a for a in args if a not in ("--table", "--default")]

        if args and len(args) > 0:
            cmd_name = args[0]
            cmd = self.get(cmd_name)
            if cmd:
                if use_table:
                    rows = [
                        {"Field": "Command", "Value": cmd.name},
                        {"Field": "Description", "Value": cmd.description},
                        {"Field": "Usage", "Value": (cmd.usage or "").strip()},
                        {"Field": "Aliases", "Value": ", ".join(cmd.aliases) if cmd.aliases else "-"},
                    ]
                    if cmd.subcommands:
                        for sub_name, sub_cmd in cmd.subcommands.items():
                            sub_usage = (sub_cmd.usage or "").strip().split("\n")[0]
                            sub_usage = sub_usage[:70] + ("..." if len(sub_usage) > 70 else "")
                            rows.append({
                                "Field": f"Subcommand: {sub_name}",
                                "Value": f"{sub_cmd.description} | {sub_usage}"
                            })
                    return ConsoleOutput(
                        type="info",
                        format="table",
                        message=f"Help: {cmd.name}",
                        data={
                            "columns": ["Field", "Value"],
                            "rows": rows,
                            "count": len(rows),
                        },
                        timestamp=time.time()
                    )
                lines = [
                    f"Command: {cmd.name}",
                    f"Description: {cmd.description}",
                    f"Usage: {cmd.usage}"
                ]
                if cmd.aliases:
                    lines.append(f"Aliases: {', '.join(cmd.aliases)}")
                if cmd.subcommands:
                    lines.append("")
                    lines.append("Subcommands:")
                    for sub_name, sub_cmd in cmd.subcommands.items():
                        lines.append(f"  {sub_name}: {sub_cmd.description}")
                        if sub_cmd.usage:
                            lines.append(f"    Usage: {sub_cmd.usage}")
                return ConsoleOutput(
                    type="info",
                    format="help",
                    message="\n".join(lines),
                    timestamp=time.time()
                )
            else:
                return ConsoleOutput(
                    type="error",
                    format="text",
                    message=f"Unknown command: {cmd_name}",
                    timestamp=time.time()
                )

        # General help
        if use_table:
            rows = []
            for cmd in self.get_all():
                usage_first = (cmd.usage or "").strip().split("\n")[0]
                usage_short = usage_first[:70] + ("..." if len(usage_first) > 70 else "")
                rows.append({
                    "Command": cmd.name,
                    "Description": cmd.description,
                    "Usage": usage_short,
                })
            return ConsoleOutput(
                type="info",
                format="table",
                message=f"Available commands ({len(rows)})",
                data={
                    "columns": ["Command", "Description", "Usage"],
                    "rows": rows,
                    "count": len(rows),
                },
                timestamp=time.time()
            )

        lines = ["Available commands:", ""]
        for cmd in self.get_all():
            lines.append(f"  {cmd.name:12} - {cmd.description}")
        lines.append("")
        lines.append("Type 'help <command>' for more information.")
        lines.append("Type 'help --table' for table view.")

        return ConsoleOutput(
            type="info",
            format="help",
            message="\n".join(lines),
            timestamp=time.time()
        )
    
    def _handle_clear(self, args: List[str] = None) -> ConsoleOutput:
        """Handle clear command."""
        return ConsoleOutput(
            type="clear",
            format="text",
            message="Console cleared",
            timestamp=time.time()
        )
    
    def _handle_status(self, args: List[str] = None) -> ConsoleOutput:
        """Handle status command."""
        return ConsoleOutput(
            type="success",
            format="json",
            message="Connected to nOS server",
            data={
                "connected": True,
                "server": "nos",
                "version": "0.1.0"
            },
            timestamp=time.time()
        )
    
    def _handle_echo(self, args: List[str] = None) -> ConsoleOutput:
        """Handle echo command."""
        message = " ".join(args) if args else "(empty)"
        return ConsoleOutput(
            type="info",
            format="text",
            message=message,
            timestamp=time.time()
        )

    def _handle_config_list(self, args: List[str] = None) -> ConsoleOutput:
        """Handle config list command. Returns env vars from .env in help format."""
        from ..services.config_service import config_service

        vars_list = config_service.list_env_vars()
        if not vars_list or (len(vars_list) == 1 and vars_list[0].get("key") == "(error)"):
            msg = vars_list[0]["value"] if vars_list else "No configuration variables found."
            return ConsoleOutput(
                type="warning",
                format="help",
                message=msg,
                timestamp=time.time()
            )
        lines = ["Configuration variables (.env):", ""]
        for item in vars_list:
            key = item.get("key", "")
            val = item.get("value", "")
            lines.append(f"  {key:<35} {val}")
        lines.append("")
        lines.append(f"Total: {len(vars_list)} variable(s)")
        return ConsoleOutput(
            type="info",
            format="help",
            message="\n".join(lines),
            timestamp=time.time()
        )


# Global registry instance
command_registry = CommandRegistry()
