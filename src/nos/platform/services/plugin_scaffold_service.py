"""
Scaffold and editable-install external engine plugin packages under ``PLUGIN_PATH``.

Use this service for console ``plugin create`` / ``plugin install``. Legacy helpers in
``plugin_code_service`` that only mapped paths remain; full scaffold flows should use this module.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Generator

from nos.platform.config.paths import get_platform_venv_python, get_plugin_path
from nos.platform.plugins.scaffold import _parse_slug


def _python_for_pip_install() -> Path:
    """
    Interpreter used for ``pip install -e``.

    Order:

    1. ``PLUGIN_INSTALL_PYTHON`` — explicit absolute path to ``python`` / ``python.exe`` if set.
    2. ``{PLATFORM_PATH}/.venv/.../python`` — platform virtualenv (same as documented workflow)
       when that file exists.
    3. :data:`sys.executable` — fallback if (2) is missing (wrong ``PLATFORM_PATH``, no venv yet).

    For ``run node dev`` to import the package, start the server with the **same** environment
    you install into (typically activate ``PLATFORM_PATH/.venv`` before ``nos``), or set
    ``PLUGIN_INSTALL_PYTHON`` to that interpreter.
    """
    raw = (os.environ.get("PLUGIN_INSTALL_PYTHON") or "").strip()
    if raw:
        return Path(os.path.expanduser(os.path.expandvars(raw))).resolve()
    try:
        py = get_platform_venv_python()
        if py.is_file():
            return py
    except (OSError, ValueError):
        pass
    return Path(sys.executable).resolve()

DEFAULT_PIP_INSTALL_TIMEOUT_SEC = 600


def _read_reference_template_file(filename: str) -> str:
    """
    Load template text from the ``nos.platform.reference_templates`` package.

    Uses :func:`importlib.resources.files` so it works for editable installs, wheels, and
    ``site-packages`` without relying on ``__file__`` relative paths (avoids stale bytecode
    pointing at removed ``src/reference_templates``).
    """
    try:
        root = resources.files("nos.platform.reference_templates")
        path = root / filename
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError, TypeError, ValueError) as e:
        raise FileNotFoundError(
            f"Reference template not found: {filename!r} in nos.platform.reference_templates. "
            "Reinstall nos from your checkout: pip install -e \".[web]\" (or your extras), then restart the server."
        ) from e


def _adapt_reference_templates_to_plugin_py(text: str, pkg: str) -> str:
    """Rewrite ``reference_templates.*`` imports and docstring refs to the plugin package."""
    text = text.replace(
        "from reference_templates.node_template import NodeTemplate",
        f"from {pkg}.node import NodeTemplate",
    )
    text = text.replace("reference_templates.node_template", f"{pkg}.node")
    text = text.replace("reference_templates.workflow_template", f"{pkg}.workflow")
    return text


class PluginScaffoldService:
    """Create plugin package trees and run ``pip install -e`` with streamed output."""

    @staticmethod
    def _write_models_and_routes(pkg_dir: Path) -> None:
        (pkg_dir / "models.py").write_text(
            '''"""Optional SQLAlchemy models for your plugin (use core or plugins bind as needed)."""
# from nos.platform.extensions import db
#
# class MyModel(db.Model):
#     __tablename__ = "my_plugin_rows"
#     id = db.Column(db.Integer, primary_key=True)
''',
            encoding="utf-8",
        )
        (pkg_dir / "routes.py").write_text(
            '''"""Optional Flask blueprint — register from Plugin.on_enable if you add HTTP surface."""
# from flask import Blueprint
#
# bp = Blueprint("my_plugin", __name__, url_prefix="/plugins/my-plugin")
#
# @bp.route("/health")
# def health():
#     return {"ok": True}
''',
            encoding="utf-8",
        )

    @classmethod
    def create_project(cls, name: str, out_dir: Path) -> Path:
        """
        Write ``pyproject.toml``, ``src/<pkg>/`` with ``node.py``, ``workflow.py``, ``link.py``
        (copied from ``nos.platform.reference_templates`` with package-local imports),
        plus ``models.py`` and ``routes.py``. Does not create ``plugin.py``.

        Raises:
            FileExistsError: if the output directory already exists and is non-empty, or ``src/<pkg>`` exists.
            ValueError: invalid name or unsafe path.
            FileNotFoundError: if reference template files are missing from the nos source tree.
        """
        pkg, dist = _parse_slug(name)
        root = out_dir.resolve()
        if root.exists():
            raise FileExistsError(
                f"Plugin folder already exists: {root}. Choose another name or remove the directory."
            )

        pkg_dir = root / "src" / pkg
        pkg_dir.mkdir(parents=True, exist_ok=False)

        ep = dist.replace("-", "_")

        (pkg_dir / "__init__.py").write_text(
            f'"""NOS engine plugin package `{dist}` (``nos.plugins`` entry points)."""\n',
            encoding="utf-8",
        )

        node_body = _adapt_reference_templates_to_plugin_py(
            _read_reference_template_file("node_template.py"), pkg
        )
        workflow_body = _adapt_reference_templates_to_plugin_py(
            _read_reference_template_file("workflow_template.py"), pkg
        )
        link_body = _read_reference_template_file("link_template.py")

        (pkg_dir / "node.py").write_text(node_body, encoding="utf-8")
        (pkg_dir / "workflow.py").write_text(workflow_body, encoding="utf-8")
        (pkg_dir / "link.py").write_text(link_body, encoding="utf-8")

        cls._write_models_and_routes(pkg_dir)

        (root / "pyproject.toml").write_text(
            f'''[build-system]
requires = ["setuptools>=65", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{dist}"
version = "0.1.0"
description = "NOS engine plugin (nos.plugins entry points)"
requires-python = ">=3.10"
dependencies = [
    "nos>=0.1.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.4.0"]

[tool.setuptools]
package-dir = {{"" = "src"}}

[tool.setuptools.packages.find]
where = ["src"]

[project.entry-points."nos.plugins"]
{ep}_node = "{pkg}.node:NodeTemplate"
{ep}_workflow = "{pkg}.workflow:WorkflowTemplate"
''',
            encoding="utf-8",
        )

        (root / "README.md").write_text(
            f"# {dist}\n\n"
            f"NOS engine plugin package.\n\n"
            f"## Editable install\n\n"
            f"```bash\npip install -e .\n```\n\n"
            f"## Entry points (`nos.plugins`)\n\n"
            f"- `{ep}_node` → `{pkg}.node:NodeTemplate`\n"
            f"- `{ep}_workflow` → `{pkg}.workflow:WorkflowTemplate`\n\n"
            f"## Layout\n\n"
            f"- `src/{pkg}/node.py`, `workflow.py`, `link.py` (from reference templates), "
            f"`models.py`, `routes.py`\n",
            encoding="utf-8",
        )
        return root

    @staticmethod
    def _validate_module_name(raw: str) -> None:
        if not raw or not str(raw).strip():
            raise ValueError("Module name is required.")
        s = raw.strip()
        if ".." in s or "/" in s or "\\" in s:
            raise ValueError("Invalid module name: path separators are not allowed.")

    @classmethod
    def resolve_project_root(cls, module_name: str) -> Path:
        """
        Return ``PLUGIN_PATH/<dist>/`` for a plugin name, ensuring the path stays under ``PLUGIN_PATH``.

        Raises:
            FileNotFoundError: if the directory does not exist.
            ValueError: invalid name or path escapes ``PLUGIN_PATH``.
        """
        cls._validate_module_name(module_name)
        _pkg, dist = _parse_slug(module_name)
        plugin_root = get_plugin_path().resolve()
        target = (plugin_root / dist).resolve()
        try:
            target.relative_to(plugin_root)
        except ValueError as exc:
            raise ValueError("Resolved path must stay under PLUGIN_PATH.") from exc
        if not target.is_dir():
            raise FileNotFoundError(
                f"Plugin directory not found: {target}. Run `plugin create {module_name}` first."
            )
        return target

    @classmethod
    def create_under_plugin_path(cls, module_name: str) -> Path:
        """
        Create a new plugin under ``PLUGIN_PATH/<distribution-name>/``.

        Raises:
            FileExistsError: if the target folder already exists.
        """
        cls._validate_module_name(module_name)
        _pkg, dist = _parse_slug(module_name)
        plugin_root = get_plugin_path().resolve()
        out = (plugin_root / dist).resolve()
        try:
            out.relative_to(plugin_root)
        except ValueError as exc:
            raise ValueError("Resolved path must stay under PLUGIN_PATH.") from exc
        plugin_root.mkdir(parents=True, exist_ok=True)
        return cls.create_project(module_name, out)

    @classmethod
    def stream_pip_install_editable(
        cls,
        module_name: str,
        *,
        timeout_sec: int = DEFAULT_PIP_INSTALL_TIMEOUT_SEC,
    ) -> Generator[str, None, None]:
        """
        Run ``python -m pip install -e <project>`` (see :func:`_python_for_pip_install`) and yield lines.

        Raises:
            FileNotFoundError: python executable or project missing.
            TimeoutError: command exceeded ``timeout_sec``.
            RuntimeError: non-zero exit from pip.
        """
        project_root = cls.resolve_project_root(module_name)
        py = _python_for_pip_install()
        if not py.is_file():
            raise FileNotFoundError(
                f"Python executable not found at {py}. "
                f"Unset PLUGIN_INSTALL_PYTHON or point it to a valid interpreter."
            )
        cmd = [str(py), "-m", "pip", "install", "-e", str(project_root)]
        yield f"(pip install using: {py})"
        env = os.environ.copy()
        # Avoid ANSI noise in streamed console
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        env.setdefault("PYTHONUNBUFFERED", "1")

        q: queue.Queue = queue.Queue()

        def _reader(proc: subprocess.Popen) -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    q.put(("line", line.rstrip("\n\r")))
                rc = proc.wait()
                q.put(("done", rc))
            except Exception as e:
                q.put(("err", str(e)))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            cwd=str(project_root),
            **(
                {"creationflags": subprocess.CREATE_NO_WINDOW}
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else {}
            ),
        )
        t = threading.Thread(target=_reader, args=(proc,), daemon=True)
        t.start()

        deadline = time.time() + timeout_sec
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                proc.kill()
                t.join(timeout=5)
                raise TimeoutError(
                    f"pip install timed out after {timeout_sec} seconds. "
                    f"Check network, credentials, or increase timeout."
                )
            try:
                kind, payload = q.get(timeout=min(0.5, max(0.05, remaining)))
            except queue.Empty:
                continue
            if kind == "line":
                yield payload
            elif kind == "err":
                proc.kill()
                raise RuntimeError(payload)
            elif kind == "done":
                if payload != 0:
                    raise RuntimeError(f"pip exited with code {payload}")
                return
