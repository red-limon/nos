"""
Upload Service - Temporary file uploads for engine/form execution.

Stores uploaded files with a unique upload_id. Used by the console form flow:
1. Client uploads files via HTTP (POST /api/upload/temp)
2. Server returns upload_id(s)
3. Client sends form_data via Socket.IO with upload_id(s) instead of raw files
4. Node execution resolves upload_id to path and reads file content when needed.
"""

import os
import re
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result of a single file upload."""
    success: bool
    upload_id: Optional[str] = None
    filename: Optional[str] = None
    path: Optional[str] = None
    size: int = 0
    error: Optional[str] = None


class UploadService:
    """
    Service for storing temporary uploads (form file fields).
    Files are stored under a dedicated uploads directory with unique IDs.
    """

    DEFAULT_MAX_FILE_SIZE_MB = 50
    DEFAULT_MAX_SIZE_MB = 50  # alias for API
    DEFAULT_MAX_FILES_PER_REQUEST = 10

    def __init__(self):
        self._uploads_path: Optional[Path] = None
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        base = os.getenv("NOS_TEMP_PATH") or os.getenv("ORKESTRO_TEMP_PATH") or "{user_home}/.nos/temp"
        user_home = str(Path.home())
        base = base.replace("{user_home}", user_home)
        self._uploads_path = Path(base) / "uploads"
        try:
            self._uploads_path.mkdir(parents=True, exist_ok=True)
            logger.info("Upload path: %s", self._uploads_path)
        except Exception as e:
            logger.error("Failed to create uploads dir: %s", e)
            import tempfile
            self._uploads_path = Path(tempfile.gettempdir()) / "nos" / "uploads"
            self._uploads_path.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    def _safe_filename(self, name: str) -> str:
        """Remove path components and restrict to safe characters."""
        base = os.path.basename(name)
        base = re.sub(r"[^\w\s.\-]", "_", base)
        return base[:200] or "upload"

    def save_upload(
        self,
        file_storage,
        max_size_mb: Optional[float] = None,
        accept: Optional[str] = None,
    ) -> UploadResult:
        """
        Save one uploaded file from Werkzeug FileStorage.

        Args:
            file_storage: request.files[key] (Werkzeug FileStorage)
            max_size_mb: Max size in MB (default DEFAULT_MAX_FILE_SIZE_MB)
            accept: Allowed MIME/types (e.g. ".pdf,image/*") - validated if provided

        Returns:
            UploadResult with upload_id, filename, path, size
        """
        self._ensure_initialized()
        max_bytes = int((max_size_mb or self.DEFAULT_MAX_FILE_SIZE_MB) * 1024 * 1024)

        if not file_storage or not file_storage.filename:
            return UploadResult(success=False, error="No file provided")

        try:
            file_storage.seek(0, 2)
            size = file_storage.tell()
            file_storage.seek(0)
        except Exception as e:
            return UploadResult(success=False, error=str(e))

        if size > max_bytes:
            return UploadResult(
                success=False,
                error=f"File too large (max {max_size_mb or self.DEFAULT_MAX_FILE_SIZE_MB} MB)",
            )

        safe_name = self._safe_filename(file_storage.filename)
        upload_id = str(uuid.uuid4())
        # Store as upload_id_safe_name to avoid collisions and keep original name
        stored_name = f"{upload_id}_{safe_name}"
        file_path = self._uploads_path / stored_name

        try:
            file_storage.save(str(file_path))
        except Exception as e:
            logger.error("Save upload failed: %s", e)
            return UploadResult(success=False, error=str(e))

        rel_path = f"uploads/{stored_name}"
        self._metadata[upload_id] = {
            "filename": safe_name,
            "path": str(file_path),
            "rel_path": rel_path,
            "size": size,
            "upload_id": upload_id,
        }
        return UploadResult(
            success=True,
            upload_id=upload_id,
            filename=safe_name,
            path=rel_path,
            size=size,
        )

    def save_uploads(
        self,
        file_storages: List[Any],
        max_size_mb: Optional[float] = None,
        accept: Optional[str] = None,
        max_files: Optional[int] = None,
    ) -> List[UploadResult]:
        """Save multiple uploads. Returns list of UploadResult."""
        max_files = max_files or self.DEFAULT_MAX_FILES_PER_REQUEST
        if len(file_storages) > max_files:
            return [
                UploadResult(success=False, error=f"Too many files (max {max_files})")
            ]
        return [
            self.save_upload(f, max_size_mb=max_size_mb, accept=accept)
            for f in file_storages
        ]

    def get_path(self, upload_id: str) -> Optional[str]:
        """Return absolute file path for an upload_id, or None if not found."""
        self._ensure_initialized()
        if not upload_id or not isinstance(upload_id, str):
            return None
        info = self._metadata.get(upload_id)
        if info:
            return info.get("path")
        # Reconstruct path from convention (uploads/{uuid}_{filename})
        for p in self._uploads_path.iterdir():
            if p.is_file() and p.name.startswith(upload_id + "_"):
                return str(p)
        return None

    def get_file_info(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Return metadata for an upload_id."""
        self._ensure_initialized()
        if self._metadata.get(upload_id):
            return dict(self._metadata[upload_id])
        for p in self._uploads_path.iterdir():
            if p.is_file() and p.name.startswith(upload_id + "_"):
                st = p.stat()
                return {
                    "upload_id": upload_id,
                    "filename": p.name[len(upload_id) + 1 :],
                    "path": str(p),
                    "rel_path": f"uploads/{p.name}",
                    "size": st.st_size,
                }
        return None

    def read_content(self, upload_id: str, mode: str = "rb") -> Optional[bytes]:
        """Read file content for an upload_id. Returns bytes in binary mode."""
        path = self.get_path(upload_id)
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, mode) as f:
                return f.read() if "b" in mode else f.read().encode("utf-8")
        except Exception as e:
            logger.warning("Read upload %s failed: %s", upload_id, e)
            return None

    def cleanup_old_uploads(self, max_age_hours: int = 24) -> int:
        """Remove upload files older than max_age_hours. Returns count deleted."""
        self._ensure_initialized()
        import time
        cutoff = time.time() - max_age_hours * 3600
        deleted = 0
        for p in self._uploads_path.iterdir():
            if p.is_file() and p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                    deleted += 1
                    uid = p.name.split("_", 1)[0] if "_" in p.name else None
                    if uid:
                        self._metadata.pop(uid, None)
                except Exception as e:
                    logger.warning("Cleanup %s failed: %s", p, e)
        return deleted


upload_service = UploadService()
