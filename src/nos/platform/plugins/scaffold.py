"""Generate a minimal installable NOS engine plugin package (``pip install -e .``)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple


def _parse_slug(raw: str) -> Tuple[str, str]:
    """
    Return (python_package_name, distribution_name).

    Accepts ``my-thing``, ``my_thing``, ``MyThing`` -> package ``my_thing``, dist ``my-thing``.
    """
    s = raw.strip()
    if not s:
        raise ValueError("name must be non-empty")
    kebab = s.lower().replace("_", "-")
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", kebab):
        snake = re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_")
        if not snake or not snake.replace("_", "").isalnum():
            raise ValueError(f"invalid plugin name: {raw!r}")
        pkg = snake.lower()
        dist = pkg.replace("_", "-")
        return pkg, dist
    pkg = kebab.replace("-", "_")
    return pkg, kebab


def create_plugin_project(name: str, out_dir: Path) -> Path:
    """
    Create ``out_dir`` with ``pyproject.toml`` and ``src/<pkg>/`` containing
    ``node.py``, ``workflow.py``, ``link.py`` (from ``reference_templates``), ``models.py``, and ``routes.py``.

    Delegates to :class:`~nos.platform.services.plugin_scaffold_service.PluginScaffoldService`.
    """
    from nos.platform.services.plugin_scaffold_service import PluginScaffoldService

    return PluginScaffoldService.create_project(name, out_dir)
