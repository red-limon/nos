"""
Resolved paths from environment: plugin development root and platform (repo) root.

``PLUGIN_PATH`` — root folder for external plugin packages (no fallback to legacy vars).
``PLATFORM_PATH`` — absolute path to the NOS platform checkout; virtualenv is
``{PLATFORM_PATH}/.venv`` with ``python`` under ``Scripts`` (Windows) or ``bin`` (Unix).
"""

from __future__ import annotations

import os
from pathlib import Path


def _expand_path_tokens(raw: str) -> str:
    s = os.path.expanduser(os.path.expandvars(raw.strip()))
    home = str(Path.home())
    for token, repl in (("{user_dir}", home), ("{user_home}", home)):
        s = s.replace(token, repl)
    return s


def get_plugin_path() -> Path:
    """
    Root directory for external plugin projects (Engine «Plugins explorer», ``plugin create``).

    Reads ``PLUGIN_PATH`` from the environment. If unset, defaults to ``~/.nos/plugins``.
    When set, the value must be an absolute path (after expansion).
    """
    raw = (os.environ.get("PLUGIN_PATH") or "").strip()
    if not raw:
        return (Path.home() / ".nos" / "plugins").resolve()
    p = Path(_expand_path_tokens(raw)).resolve()
    if not p.is_absolute():
        raise ValueError("PLUGIN_PATH must be an absolute path (after expansion)")
    return p


def get_platform_path() -> Path:
    """
    Absolute path to the NOS platform / repository root (contains ``pyproject.toml``, ``.venv``, etc.).

    ``PLATFORM_PATH`` must be set to an absolute path in production; when unset, defaults to
    ``~/seedx_lab/apps/dev/python_flask/nos``.
    """
    raw = (os.environ.get("PLATFORM_PATH") or "").strip()
    if not raw:
        return (
            Path.home()
            / "seedx_lab"
            / "apps"
            / "dev"
            / "python_flask"
            / "nos"
        ).resolve()
    p = Path(_expand_path_tokens(raw)).resolve()
    if not p.is_absolute():
        raise ValueError("PLATFORM_PATH must be an absolute path (after expansion)")
    return p


def get_platform_venv_python() -> Path:
    """Return ``{PLATFORM_PATH}/.venv/Scripts/python.exe`` (Windows) or ``.../bin/python`` (POSIX).

    Not used for ``plugin install`` (that follows :data:`sys.executable`); kept for callers that
    need an explicit platform venv path.
    """
    plat = get_platform_path()
    if os.name == "nt":
        return plat / ".venv" / "Scripts" / "python.exe"
    return plat / ".venv" / "bin" / "python"
