"""
Vector DB API routes.

Endpoints:
- POST /api/vect/chromadb/connect  Test ChromaDB connection
- GET  /api/vect/chromadb/collections  List ChromaDB collections
"""

import logging
from flask import jsonify

from ..routes import api_bp
from ...services.chromadb_service import chromadb_service

logger = logging.getLogger(__name__)


@api_bp.get("/vect/chromadb/connect")
@api_bp.get("/vect/chromadb/connect/")
@api_bp.post("/vect/chromadb/connect")
@api_bp.post("/vect/chromadb/connect/")
def vect_chromadb_connect():
    """
    Test ChromaDB connection.

    Returns:
        {
            "success": true,
            "path": "/path/to/chroma",
            "version": "0.4.x",
            "mode": "embedded"
        }
    """
    try:
        result = chromadb_service.connect()
        status = 200 if result.get("success") else 503
        return jsonify(result), status
    except Exception as e:
        logger.error(f"ChromaDB connect API error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.get("/vect/chromadb/collections")
@api_bp.get("/vect/chromadb/collections/")
def vect_chromadb_collections():
    """
    List ChromaDB collections.

    Returns:
        {
            "success": true,
            "collections": ["name1", "name2"],
            "count": 2
        }
    """
    try:
        result = chromadb_service.get_collections()
        status = 200 if result.get("success") else 500
        return jsonify(result), status
    except Exception as e:
        logger.error(f"ChromaDB collections API error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
