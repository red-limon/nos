"""Console API routes. URL prefix: /console."""

import json
import logging
import os
import re
import ast
from pathlib import Path

from flask import jsonify, request, session

from ..routes import api_bp
from ..common import validate_payload
from nos.platform.console import (
    ConsoleCommand,
    ConsoleValidationResult,
    validate_command,
    execute_command,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Plugin Explorer API
# =============================================================================

def _get_nos_package_root() -> Path:
    """Directory ``src/nos`` (the ``nos`` Python package)."""
    # routes.py → …/nos/platform/api/console/routes.py → four parents up = ``nos`` package dir
    return Path(__file__).resolve().parent.parent.parent.parent


def _get_plugins_root() -> str:
    """Absolute path to ``src/nos/plugins``."""
    return str(_get_nos_package_root() / "plugins")


def _discover_default_project_root() -> Path:
    """
    Repository / project root when ``NOS_CONSOLE_PROJECT_ROOT`` is unset.
    Walks upward from the ``nos`` package dir for ``pyproject.toml``, ``setup.py``, or ``.git``.
    """
    start = _get_nos_package_root()
    cur: Path = start
    for _ in range(10):
        if (cur / "pyproject.toml").is_file() or (cur / "setup.py").is_file() or (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    # e.g. …/repo/src/nos → repo
    if start.parent.name == "src" and start.name == "nos":
        return start.parent.parent
    return start


def _get_console_project_root() -> Path:
    raw = (os.environ.get("NOS_CONSOLE_PROJECT_ROOT") or "").strip()
    if raw:
        expanded = os.path.expanduser(os.path.expandvars(raw))
        p = Path(expanded).resolve()
        if p.is_dir():
            return p
        logger.warning("NOS_CONSOLE_PROJECT_ROOT is not a directory: %s", raw)
    return _discover_default_project_root()


def _get_plugin_dev_root() -> Path:
    """
    Root folder for plugin development (Engine console «Plugins explorer»).

    Read from ``PLUGIN_PATH`` (e.g. in ``.env``, loaded at startup via dotenv).
    Default: ``~/.nos/plugins``. Must be an absolute path when set.
    """
    from nos.platform.config.paths import get_plugin_path

    try:
        p = get_plugin_path()
    except ValueError as e:
        logger.warning("Invalid PLUGIN_PATH: %s", e)
        p = (Path.home() / ".nos" / "plugins").resolve()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("Could not ensure plugin dev root exists (%s): %s", p, e)
    return p


_PROJECT_TREE_IGNORE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        ".eggs",
        "node_modules",
        "dist",
        "build",
        ".idea",
        ".vs",
        "htmlcov",
        ".coverage",
    }
)


def _plugins_module_path_for_file(py_file: Path) -> str | None:
    """If *py_file* is under ``nos.plugins``, return dotted module path (else None)."""
    try:
        plugins = Path(_get_plugins_root()).resolve()
        rel = py_file.resolve().relative_to(plugins)
    except ValueError:
        return None
    parts = list(rel.parts)
    if not parts or not parts[-1].endswith(".py"):
        return None
    stem = parts[-1][:-3]
    if stem == "__init__":
        return None
    pkg = [p for p in parts[:-1] if p != "__pycache__"]
    return "nos.plugins." + ".".join(pkg + [stem])


def _module_path_for_file_under_root(py_file: Path, anchor: Path) -> str | None:
    """
    Map a ``.py`` file under *anchor* to ``nos.plugins.<dotted>``.

    Used for the plugin dev tree (``PLUGIN_PATH``): files live under e.g. ``~/.nos/plugins``,
    not under the installed ``nos/plugins`` package path, so :func:`_plugins_module_path_for_file`
    would return None.
    """
    try:
        anchor = anchor.resolve()
        rel = py_file.resolve().relative_to(anchor)
    except ValueError:
        return None
    parts = list(rel.parts)
    if not parts or not parts[-1].endswith(".py"):
        return None
    stem = parts[-1][:-3]
    if stem == "__init__":
        return None
    pkg = [p for p in parts[:-1] if p != "__pycache__"]
    return "nos.plugins." + ".".join(pkg + [stem])


def _build_full_project_tree(root: Path, *, max_depth: int = 48, module_path_anchor: Path | None = None) -> list:
    """
    Full directory tree under *root* (folders + all files). Paths are absolute strings.
    Plugin ``.py`` files under ``nos/plugins`` also get ``module_path`` for console ``open`` commands.
    """
    try:
        root = root.resolve()
    except OSError:
        return []

    def walk(current: Path, depth: int) -> list:
        if depth > max_depth:
            return []
        items: list = []
        try:
            entries = sorted(
                current.iterdir(),
                key=lambda x: (not x.is_dir(), x.name.lower()),
            )
        except OSError:
            return items

        for entry in entries:
            name = entry.name
            if name in (".", ".."):
                continue
            _dot_keep = {".env", ".env.example", ".env.local", ".env.development", ".env.production"}
            if name.startswith(".") and name not in _dot_keep:
                continue
            try:
                resolved = entry.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue

            try:
                if entry.is_dir():
                    if name in _PROJECT_TREE_IGNORE_DIRS:
                        continue
                    children = walk(resolved, depth + 1)
                    items.append(
                        {
                            "type": "folder",
                            "name": name,
                            "path": str(resolved),
                            "children": children,
                        }
                    )
                elif entry.is_file():
                    row: dict = {
                        "type": "file",
                        "name": name,
                        "path": str(resolved),
                    }
                    if name.endswith(".py"):
                        mp = None
                        if module_path_anchor is not None:
                            mp = _module_path_for_file_under_root(resolved, module_path_anchor)
                        if mp is None:
                            mp = _plugins_module_path_for_file(resolved)
                        if mp:
                            row["module_path"] = mp
                    items.append(row)
            except OSError:
                continue

        return items

    return walk(root, 0)


def _build_file_tree(root_path: str, base_module: str = "nos.plugins") -> list:
    """
    Recursively build a file tree structure.
    
    Returns:
        List of dicts with {type, name, path, module_path?, children?}
    """
    tree = []
    
    try:
        entries = sorted(os.listdir(root_path))
    except OSError:
        return tree
    
    for entry in entries:
        # Skip __pycache__ and hidden files
        if entry.startswith(('__pycache__', '.')):
            continue
        
        full_path = os.path.join(root_path, entry)
        
        if os.path.isdir(full_path):
            # Check if it's a Python package (has __init__.py or contains .py files)
            has_init = os.path.exists(os.path.join(full_path, '__init__.py'))
            has_py_files = any(f.endswith('.py') and f != '__init__.py' for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f)))
            has_subdirs = any(os.path.isdir(os.path.join(full_path, d)) for d in os.listdir(full_path) if not d.startswith(('__pycache__', '.')))
            
            if has_init or has_py_files or has_subdirs:
                child_module = f"{base_module}.{entry}"
                children = _build_file_tree(full_path, child_module)
                
                # Only add folder if it has visible children
                if children:
                    tree.append({
                        "type": "folder",
                        "name": entry,
                        "path": full_path,
                        "children": children
                    })
        
        elif entry.endswith('.py') and entry != '__init__.py':
            # Python file (exclude __init__.py)
            module_name = entry[:-3]  # Remove .py
            tree.append({
                "type": "file",
                "name": entry,
                "path": full_path,
                "module_path": f"{base_module}.{module_name}"
            })
    
    return tree


def _parse_python_outline(file_path: str) -> list:
    """
    Parse a Python file and extract class/function definitions.
    
    Returns:
        List of dicts with {type, name, line, depth, parent?}
    """
    outline = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                outline.append({
                    "type": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "depth": 0
                })
                
                # Get methods inside the class
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
                        outline.append({
                            "type": "method",
                            "name": item.name,
                            "line": item.lineno,
                            "depth": 1,
                            "parent": node.name
                        })
            
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                # Top-level function (not inside a class)
                # Check if it's not already added as a method
                is_method = False
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        for item in parent.body:
                            if item is node:
                                is_method = True
                                break
                
                if not is_method:
                    outline.append({
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno,
                        "depth": 0
                    })
        
        # Sort by line number
        outline.sort(key=lambda x: x["line"])
        
    except Exception as e:
        logger.error(f"Failed to parse Python file {file_path}: {e}")
    
    return outline


@api_bp.route("/plugins/tree", methods=["GET"])
def plugins_file_tree():
    """
    Get the file tree structure of the plugins directory.
    
    Response:
        {
            "tree": [
                {
                    "type": "folder",
                    "name": "nodes",
                    "path": "/path/to/nodes",
                    "children": [...]
                },
                ...
            ]
        }
    """
    root_path = _get_plugins_root()
    
    if not os.path.exists(root_path):
        return jsonify({
            "error": "Plugins directory not found",
            "tree": []
        }), 404
    
    tree = _build_file_tree(root_path)
    
    return jsonify({"tree": tree})


def _is_path_allowed_for_outline(file_path: str) -> bool:
    """True if *file_path* is under the console project root, plugin dev root, or ``nos.plugins``."""
    try:
        p = Path(file_path).resolve()
    except OSError:
        return False
    roots = (
        _get_console_project_root().resolve(),
        _get_plugin_dev_root().resolve(),
        Path(_get_plugins_root()).resolve(),
    )
    for r in roots:
        try:
            p.relative_to(r)
            return True
        except ValueError:
            continue
    return False


@api_bp.route("/console/project-tree", methods=["GET"])
def console_project_tree():
    """
    Full Explorer \"Project\" tree from ``NOS_CONSOLE_PROJECT_ROOT`` (or auto-discovered repo root).
    """
    root = _get_console_project_root()
    if not root.is_dir():
        return jsonify(
            {
                "error": "Project root is not a directory",
                "project_root": str(root),
                "tree": [],
            }
        ), 404

    try:
        root_display = str(root.resolve())
    except OSError:
        root_display = str(root)

    children = _build_full_project_tree(root)
    tree = [
        {
            "type": "folder",
            "name": root.name or root_display,
            "path": root_display,
            "virtual_root": True,
            "children": children,
        }
    ]

    return jsonify(
        {
            "project_root": root_display,
            "tree": tree,
        }
    )


@api_bp.route("/console/plugins-explorer-tree", methods=["GET"])
def console_plugins_explorer_tree():
    """
    Full Explorer «Plugins explorer» tree from ``PLUGIN_PATH`` (default ``~/.nos/plugins``).
    Same JSON shape as ``/console/project-tree``.
    """
    root = _get_plugin_dev_root()
    if not root.is_dir():
        return jsonify(
            {
                "error": "Plugin development root is not a directory",
                "project_root": str(root),
                "tree": [],
            }
        ), 404

    try:
        root_display = str(root.resolve())
    except OSError:
        root_display = str(root)

    children = _build_full_project_tree(root, module_path_anchor=root)
    tree = [
        {
            "type": "folder",
            "name": root.name or Path(root_display).name or "plugins",
            "path": root_display,
            "virtual_root": True,
            "children": children,
        }
    ]

    return jsonify(
        {
            "project_root": root_display,
            "tree": tree,
        }
    )


@api_bp.route("/console/plugin-explorer-file", methods=["GET"])
def console_plugin_explorer_file():
    """
    Read a text file under the same roots allowed for outline (project, PLUGIN_PATH, nos.plugins).

    Used when the explorer shows a ``.py`` file without ``module_path`` (e.g. ``__init__.py``).
    """
    file_path = request.args.get("path", "")
    if not file_path:
        return jsonify({"error": "Missing path parameter", "content": None}), 400
    try:
        real_path = str(Path(file_path).resolve())
    except OSError:
        return jsonify({"error": "Invalid path", "content": None}), 400
    if not _is_path_allowed_for_outline(real_path):
        return jsonify({"error": "Access denied", "content": None}), 403
    if not os.path.isfile(real_path):
        return jsonify({"error": "Not found", "content": None}), 404
    try:
        with open(real_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        logger.warning("plugin-explorer-file read failed: %s", e)
        return jsonify({"error": str(e), "content": None}), 500
    return jsonify({"content": content, "file_path": real_path})


@api_bp.route("/plugins/outline", methods=["GET"])
def plugins_file_outline():
    """
    Get the outline (classes, methods, functions) of a Python file.
    
    Query params:
        path: Absolute path to the Python file
    
    Response:
        {
            "outline": [
                {"type": "class", "name": "MyClass", "line": 10, "depth": 0},
                {"type": "method", "name": "__init__", "line": 12, "depth": 1, "parent": "MyClass"},
                ...
            ]
        }
    """
    file_path = request.args.get('path', '')
    
    if not file_path:
        return jsonify({"error": "Missing 'path' parameter", "outline": []}), 400

    try:
        real_path = str(Path(file_path).resolve())
    except OSError:
        return jsonify({"error": "Invalid path", "outline": []}), 400

    if not _is_path_allowed_for_outline(real_path):
        return jsonify({"error": "Access denied", "outline": []}), 403

    if not os.path.exists(real_path):
        return jsonify({"error": "File not found", "outline": []}), 404

    if not real_path.endswith(".py"):
        return jsonify({"error": "Not a Python file", "outline": []}), 400

    outline = _parse_python_outline(real_path)
    
    return jsonify({"outline": outline})


def _nos_workspace_root() -> Path:
    """Root for per-execution snapshot JSON files (``~/.nos/execution_logs/{execution_id}.json``). Not per-user."""
    return Path.home() / ".nos" / "execution_logs"


def _nos_user_sessions_root() -> Path:
    """``~/.nos/drive/@{username}`` — drive root for the user."""
    user_id = session.get("username", "developer")
    safe_user = re.sub(r"[^\w.\-@]", "_", str(user_id))[:120] or "developer"
    return Path.home() / ".nos" / "drive" / f"@{safe_user}"


def _nos_session_folder_root() -> Path:
    """``~/.nos/drive/@{user}/session`` — workspace session files (``.wks``, ``.out``)."""
    return _nos_user_sessions_root() / "session"


def _ensure_sessions_root() -> Path:
    root = _nos_session_folder_root()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


_WKS_FILENAME_RE = re.compile(r"^[\w\-. ]+\.wks$", re.UNICODE)


def _safe_wks_filename(name: str) -> str | None:
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    if not base:
        return None
    lower = base.lower()
    if lower.endswith(".nos"):
        base = base[:-4] + ".wks"
    elif lower.endswith(".out"):
        base = f"{Path(base).stem}.wks"
    elif not lower.endswith(".wks"):
        base = f"{base}.wks"
    if _WKS_FILENAME_RE.match(base):
        return base
    stem = Path(base).stem
    safe = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip("._- ")
    if not safe:
        safe = "session"
    base = f"{safe[:120]}.wks"
    return base if _WKS_FILENAME_RE.match(base) else None


def _execution_output_snapshot(body: dict, session_data: dict) -> dict:
    """Always persist a ``.out`` alongside ``.wks`` (output-only shape, workspace only)."""
    raw = body.get("execution_output")
    if isinstance(raw, dict) and raw:
        return raw
    ws = session_data.get("workspace")
    if not isinstance(ws, dict):
        ws = {"documents": [], "active_execution_id": None}
    return {
        "format_version": session_data.get("format_version", 1),
        "kind": "nos_engine_console_output",
        "saved_at": session_data.get("saved_at"),
        "workspace": ws,
    }


def _session_file_must_be_under_root(file_path: str, root: Path) -> Path | None:
    try:
        p = Path(file_path).resolve()
        root_r = root.resolve()
        p.relative_to(root_r)
    except (OSError, ValueError):
        return None
    if not p.is_file():
        return None
    low = str(p).lower()
    if not (low.endswith(".wks") or low.endswith(".out")):
        return None
    return p


def _build_user_workspace_tree(root: Path, max_depth: int = 8) -> list:
    """
    File tree under ~/.nos/execution_logs (per-execution JSON snapshots, shared root).
    Paths are constrained under *root* (resolved).
    """
    if not root.exists() or not root.is_dir():
        return []

    try:
        root = root.resolve()
    except OSError:
        return []

    def walk(current: Path, depth: int) -> list:
        if depth > max_depth:
            return []
        items = []
        try:
            entries = sorted(
                current.iterdir(),
                key=lambda x: (not x.is_dir(), x.name.lower()),
            )
        except OSError:
            return items

        for entry in entries:
            name = entry.name
            if name in (".", ".."):
                continue
            if name.startswith(".") and not name.startswith("@"):
                continue
            try:
                resolved = entry.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue

            try:
                if entry.is_dir():
                    children = walk(resolved, depth + 1)
                    items.append(
                        {
                            "type": "folder",
                            "name": name,
                            "path": str(resolved),
                            "children": children,
                        }
                    )
                elif entry.is_file():
                    items.append(
                        {
                            "type": "file",
                            "name": name,
                            "path": str(resolved),
                        }
                    )
            except OSError:
                continue

        return items

    return walk(root, 0)


@api_bp.route("/console/user-workspace-tree", methods=["GET"])
def user_workspace_tree():
    """
    Tree for Explorer \"@ Workspace\" view: virtual root ``@`` → ~/.nos/execution_logs contents.
    """
    user_id = session.get("username", "developer")
    root = _nos_workspace_root()
    children = _build_user_workspace_tree(root)
    try:
        root_display = str(root.resolve()) if root.exists() else str(root)
    except OSError:
        root_display = str(root)

    tree = [
        {
            "type": "folder",
            "name": "@",
            "path": root_display,
            "virtual_root": True,
            "children": children,
        }
    ]

    return jsonify(
        {
            "username": user_id,
            "workspace_path": root_display,
            "tree": tree,
        }
    )


@api_bp.route("/console/user-sessions-tree", methods=["GET"])
def user_sessions_tree():
    """
    Explorer Drive tab: tree under ``~/.nos/drive/@{user}/session`` (``.wks`` / ``.out``).
    """
    user_id = session.get("username", "developer")
    root = _ensure_sessions_root()
    children = _build_user_workspace_tree(root, max_depth=16)
    return jsonify(
        {
            "username": user_id,
            "sessions_path": str(root),
            "tree": [
                {
                    "type": "folder",
                    "name": root.name or "sessions",
                    "path": str(root),
                    "virtual_root": True,
                    "children": children,
                }
            ],
        }
    )


@api_bp.route("/console/user-session/read", methods=["GET"])
def user_session_read():
    """Load a ``.wks`` session or ``.out`` execution-output snapshot from ``…/drive/@user/session``."""
    file_path = request.args.get("path", "")
    root = _ensure_sessions_root()
    if not root.is_dir():
        return jsonify({"error": "Sessions directory not found", "session": None}), 404
    p = _session_file_must_be_under_root(file_path, root)
    if p is None:
        return jsonify({"error": "Invalid or disallowed path", "session": None}), 403
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON: {e}", "session": None}), 400
    except OSError as e:
        return jsonify({"error": str(e), "session": None}), 400
    if p.suffix.lower() == ".out":
        return jsonify({"file_kind": "output", "output": data, "path": str(p), "session": None})
    return jsonify({"file_kind": "session", "session": data, "path": str(p)})


@api_bp.route("/console/user-session/save", methods=["POST"])
def user_session_save():
    """Write session (``.wks``) under ``…/session/`` and optional execution-only snapshot (``.out``)."""
    body = request.get_json(silent=True) or {}
    raw_name = body.get("filename") or ""
    filename = _safe_wks_filename(str(raw_name))
    session_data = body.get("session")
    if filename is None:
        return jsonify({"error": "Invalid filename (use only letters, numbers, ._- and end with .wks)"}), 400
    if not isinstance(session_data, dict):
        return jsonify({"error": "Body must include a \"session\" object"}), 400
    raw_exec = body.get("execution_output")
    if raw_exec is not None and not isinstance(raw_exec, dict):
        return jsonify({"error": "execution_output must be an object when provided"}), 400
    execution_output = _execution_output_snapshot(body, session_data)
    root = _ensure_sessions_root()
    base = Path(filename).stem
    dest_wks = (root / f"{base}.wks").resolve()
    try:
        dest_wks.relative_to(root.resolve())
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400
    try:
        text = json.dumps(session_data, indent=2, ensure_ascii=False)
        with open(dest_wks, "w", encoding="utf-8") as f:
            f.write(text)
        paths = {"wks": str(dest_wks)}
        dest_out = (root / f"{base}.out").resolve()
        dest_out.relative_to(root.resolve())
        with open(dest_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(execution_output, indent=2, ensure_ascii=False))
        paths["out"] = str(dest_out)
    except OSError as e:
        logger.exception("user_session_save failed")
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "path": str(dest_wks), "paths": paths, "filename": f"{base}.wks"})


@api_bp.route("/console/validate", methods=["POST"])
@validate_payload(ConsoleCommand)
def console_validate_command(validated_payload: ConsoleCommand):
    """
    Validate a console command and return routing information.
    
    Request body:
        {
            "raw_command": "help"
        }
    
    Response:
        {
            "valid": true,
            "error": null,
            "routing": {
                "event_name": "console_command",
                "payload": {"action": "help", ...},
                "description": "Display available commands"
            }
        }
    """
    result = validate_command(validated_payload.raw_command)
    return jsonify(result.model_dump())


@api_bp.route("/console/execute", methods=["POST"])
@validate_payload(ConsoleCommand)
def console_execute_command(validated_payload: ConsoleCommand):
    """
    Execute a synchronous console command.
    
    For async commands (run node, list nodes), returns routing info
    to be used with Socket.IO instead.
    
    Request body:
        {
            "raw_command": "help"
        }
    
    Response (sync):
        {
            "type": "info",
            "message": "Available commands: ...",
            "data": null,
            "timestamp": 1709125200.0
        }
    
    Response (async):
        {
            "async": true,
            "routing": { ... }
        }
    """
    # First validate the command
    validation = validate_command(validated_payload.raw_command)
    
    if not validation.valid:
        return jsonify({
            "type": "error",
            "message": validation.error,
            "data": None,
            "timestamp": None
        })
    
    # Try to execute synchronously
    routing = validation.routing
    action = routing.payload.get("action", "")
    args = routing.payload.get("args", [])
    
    output = execute_command(action, args)
    
    if output:
        return jsonify(output.model_dump())
    
    # Async command - return routing info for Socket.IO
    return jsonify({
        "async": True,
        "routing": routing.model_dump()
    })


@api_bp.route("/console/export", methods=["POST"])
def export_table_data():
    """
    Export table data to a file (CSV, Excel, JSON).
    
    Request body:
        {
            "columns": ["id", "name"],
            "rows": [{"id": 1, "name": "test"}],
            "format": "excel"  // csv, excel, json
        }
    
    Response:
        {
            "success": true,
            "download_url": "/download/temp/query_123456.xlsx",
            "filename": "query_123456.xlsx",
            "format": "excel",
            "size": 1234
        }
    """
    from ...services.export_query_service import export_query_service
    
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "Missing request body"}), 400
    
    columns = data.get("columns", [])
    rows = data.get("rows", [])
    export_format = data.get("format", "csv").lower()
    
    if not columns or not rows:
        return jsonify({"success": False, "error": "Missing columns or rows"}), 400
    
    if export_format not in ["csv", "excel", "json"]:
        return jsonify({
            "success": False, 
            "error": f"Invalid format: {export_format}. Supported: csv, excel, json"
        }), 400
    
    # Export using the service
    result = export_query_service.export_query_result(
        columns=columns,
        rows=rows,
        format=export_format
    )
    
    if result.success:
        return jsonify({
            "success": True,
            "download_url": result.download_url,
            "filename": result.filename,
            "format": result.format,
            "size": result.file_size
        })
    else:
        return jsonify({
            "success": False,
            "error": result.error
        }), 500
