"""Download API routes. URL prefix: /download."""

import logging
from flask import send_file, jsonify, abort

from ..routes import api_bp
from ...services.export_query_service import export_query_service

logger = logging.getLogger(__name__)


@api_bp.route("/download/temp/<filename>", methods=["GET"])
def download_temp_file(filename: str):
    """
    Download a temporary export file.
    
    Args:
        filename: The filename to download
        
    Returns:
        File download response or 404 if not found
    """
    # Validate filename (security: prevent path traversal)
    if '..' in filename or '/' in filename or '\\' in filename:
        logger.warning(f"Attempted path traversal in download: {filename}")
        abort(400, description="Invalid filename")
    
    # Get file info
    file_info = export_query_service.get_file_info(filename)
    
    if not file_info:
        logger.warning(f"File not found for download: {filename}")
        abort(404, description="File not found")
    
    logger.info(f"Serving download: {filename} ({file_info['size']} bytes)")
    
    return send_file(
        file_info['file_path'],
        mimetype=file_info['mimetype'],
        as_attachment=True,
        download_name=filename
    )


@api_bp.route("/download/temp/<filename>/info", methods=["GET"])
def get_temp_file_info(filename: str):
    """
    Get information about a temporary export file.
    
    Args:
        filename: The filename to check
        
    Returns:
        JSON with file info or 404 if not found
    """
    # Validate filename
    if '..' in filename or '/' in filename or '\\' in filename:
        abort(400, description="Invalid filename")
    
    file_info = export_query_service.get_file_info(filename)
    
    if not file_info:
        abort(404, description="File not found")
    
    return jsonify({
        "success": True,
        "file": {
            "filename": file_info['filename'],
            "format": file_info['format'],
            "size": file_info['size'],
            "download_url": f"/api/download/temp/{filename}"
        }
    })
