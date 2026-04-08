"""
ChromaDB Service - Vector database connection and operations.

Provides a centralized interface for ChromaDB from anywhere in the application.
Configuration is loaded from environment variables.

Environment Variables:
    CHROMADB_PERSIST_PATH: Directory for persistent storage (default: ./.chroma)
    CHROMADB_HOST: Optional Chroma server host (empty = embedded mode)
    CHROMADB_PORT: Chroma server port (default: 8000)

Usage:
    from nos.platform.services.chromadb_service import chromadb_service

    result = chromadb_service.connect()
"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> str:
    """Resolve {user_home} placeholder in path."""
    if not path:
        return path
    user_home = os.path.expanduser("~")
    return path.replace("{user_home}", user_home)


class ChromaDBService:
    """
    ChromaDB service for vector database operations.

    Uses PersistentClient for local embedded storage by default.
    """

    def __init__(self):
        """Initialize the ChromaDB service."""
        self._client = None
        self._path: Optional[str] = None
        self._host: Optional[str] = None
        self._port: int = 8000
        self._initialized = False

    def _ensure_config(self) -> None:
        """Load configuration from environment."""
        if self._initialized:
            return
        raw_path = os.environ.get("CHROMADB_PERSIST_PATH", "./chroma")
        self._path = _resolve_path(raw_path)
        self._host = os.environ.get("CHROMADB_HOST", "").strip() or None
        self._port = int(os.environ.get("CHROMADB_PORT", "8000"))
        self._initialized = True

    def connect(self) -> Dict[str, Any]:
        """
        Connect to ChromaDB and return connection status.

        Returns:
            dict with keys: success, path|host, version, error (on failure)
        """
        self._ensure_config()

        try:
            import chromadb

            if self._host:
                self._client = chromadb.HttpClient(
                    host=self._host,
                    port=self._port,
                )
                loc = f"{self._host}:{self._port}"
            else:
                os.makedirs(self._path, exist_ok=True)
                self._client = chromadb.PersistentClient(path=self._path)
                loc = self._path

            version = getattr(chromadb, "__version__", "unknown")

            return {
                "success": True,
                "path": loc if not self._host else None,
                "host": f"{self._host}:{self._port}" if self._host else None,
                "version": version,
                "mode": "server" if self._host else "embedded",
            }

        except ImportError as e:
            logger.error(f"ChromaDB not installed: {e}")
            return {
                "success": False,
                "error": "ChromaDB not installed. Run: pip install chromadb",
            }
        except Exception as e:
            logger.error(f"ChromaDB connect error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "path": self._path,
            }

    @property
    def client(self):
        """Get ChromaDB client (connects on first access)."""
        if self._client is None:
            result = self.connect()
            if not result.get("success"):
                raise RuntimeError(result.get("error", "ChromaDB connection failed"))
        return self._client

    def get_collections(self) -> Dict[str, Any]:
        """
        List all collections.

        Returns:
            dict with success, collections list, count
        """
        try:
            result = self.connect()
            if not result.get("success"):
                return result
            cols = self.client.list_collections()
            names = [c.name for c in cols]
            return {
                "success": True,
                "collections": names,
                "count": len(names),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "collections": []}


# Global singleton
chromadb_service = ChromaDBService()

__all__ = ["ChromaDBService", "chromadb_service"]
