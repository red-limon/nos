"""
File Write Service - Save content (text or binary) to the filesystem.

Parameters: content, path (relative to base), filename, extension (optional).
Extension is auto-detected from filename if present (e.g. "doc.txt" -> .txt).
Uses NOS_TEMP_PATH as base (supports {user_home} placeholder).

Environment Variables:
    NOS_TEMP_PATH: Base directory for file operations (default: {user_home}/.nos/temp)
    ORKESTRO_TEMP_PATH: Deprecated alias for NOS_TEMP_PATH (temporary compatibility).

Usage:
    from nos.platform.services.file_write_service import file_write_service

    result = file_write_service.save(content="Hello", path="out", filename="greeting", extension=".txt")
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> str:
    """Resolve {user_home} placeholder."""
    if not path:
        return path
    return path.replace("{user_home}", os.path.expanduser("~"))


def _safe_path_component(name: str) -> str:
    """Remove path traversal and restrict to safe characters."""
    name = name.replace("..", "").strip()
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:255] or "file"


@dataclass
class FileWriteResult:
    """Result of a file write operation."""

    success: bool
    path: Optional[str] = None
    filename: Optional[str] = None
    full_path: Optional[str] = None
    bytes_written: int = 0
    error: Optional[str] = None


class FileWriteService:
    """
    Service for writing content (text or binary) to the filesystem.

    Paths are relative to the configured base (NOS_TEMP_PATH).
    Extension can be provided or auto-detected from filename.
    """

    def __init__(self):
        self._base_path: Optional[Path] = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        raw = os.getenv("NOS_TEMP_PATH") or os.getenv("ORKESTRO_TEMP_PATH") or "{user_home}/.nos/temp"
        base_str = _resolve_path(raw)
        self._base_path = Path(base_str)
        try:
            self._base_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create base path %s: %s", base_str, e)
            import tempfile
            self._base_path = Path(tempfile.gettempdir()) / "nos" / "temp"
            self._base_path.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def _build_filepath(
        self,
        path: str,
        filename: str,
        extension: Optional[str] = None,
    ) -> Path:
        """Build safe full path. Extension from filename or param."""
        self._ensure_initialized()
        safe_path = _safe_path_component(path) if path else ""
        safe_name = _safe_path_component(filename) if filename else "output"

        # Auto-detect extension from filename (e.g. "report.txt" -> .txt)
        if "." in safe_name:
            base, ext = safe_name.rsplit(".", 1)
            full_filename = f"{base}.{ext}"
        elif extension:
            ext = extension if extension.startswith(".") else f".{extension}"
            full_filename = f"{safe_name}{ext}"
        else:
            full_filename = safe_name

        if path:
            target_dir = self._base_path / safe_path
        else:
            target_dir = self._base_path
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / full_filename

    def save(
        self,
        content: Union[str, bytes],
        path: str = "",
        filename: str = "output",
        extension: Optional[str] = None,
    ) -> FileWriteResult:
        """
        Save content to the filesystem.

        Args:
            content: Text (str) or binary (bytes) content
            path: Relative subdirectory under base (e.g. "exports", "logs")
            filename: Filename. If it includes extension (e.g. "doc.txt"), it is used.
            extension: Optional extension (e.g. "txt" or ".txt"). Used if filename has no extension.

        Returns:
            FileWriteResult with success, full_path, bytes_written, error
        """
        try:
            target = self._build_filepath(path, filename, extension)
            if isinstance(content, str):
                data = content.encode("utf-8")
            else:
                data = content
            target.write_bytes(data)
            return FileWriteResult(
                success=True,
                path=path or ".",
                filename=target.name,
                full_path=str(target),
                bytes_written=len(data),
            )
        except Exception as e:
            logger.error("File write failed: %s", e, exc_info=True)
            return FileWriteResult(success=False, error=str(e))


file_write_service = FileWriteService()

__all__ = ["FileWriteService", "FileWriteResult", "file_write_service"]
