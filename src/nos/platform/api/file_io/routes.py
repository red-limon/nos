"""
File I/O API routes.

Endpoints:
- POST /api/file-io/write  Save content to filesystem
"""

import base64
import logging
from flask import jsonify, request

from ..routes import api_bp
from ...services.file_write_service import file_write_service

logger = logging.getLogger(__name__)


@api_bp.post("/file-io/write")
@api_bp.post("/file-io/write/")
def file_io_write():
    """
    Save content to filesystem.

    Request body:
        {
            "content": "text or base64 string",
            "path": "subdir",           // optional, default ""
            "filename": "output",       // optional, default "output"
            "extension": "txt",         // optional, auto from filename if present
            "binary": false             // optional, if true content is base64
        }

    Returns:
        {
            "success": true,
            "path": "...",
            "filename": "...",
            "full_path": "/abs/path/to/file",
            "bytes_written": 42
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Request body must be JSON"}), 400

    content = data.get("content")
    path = data.get("path", "")
    filename = data.get("filename", "output")
    extension = data.get("extension")
    is_binary = data.get("binary", False)

    if content is None:
        return jsonify({"success": False, "error": "Missing required field: content"}), 400

    try:
        if is_binary:
            content = base64.b64decode(content)
        else:
            content = str(content)

        result = file_write_service.save(
            content=content,
            path=path,
            filename=filename,
            extension=extension,
        )

        if result.success:
            return jsonify({
                "success": True,
                "path": result.path,
                "filename": result.filename,
                "full_path": result.full_path,
                "bytes_written": result.bytes_written,
            }), 200
        else:
            return jsonify({"success": False, "error": result.error}), 400

    except Exception as e:
        logger.error("File write API error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
