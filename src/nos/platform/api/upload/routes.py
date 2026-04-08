"""Upload API routes. POST multipart files for form execution (2-step: upload then form_data via Socket.IO)."""

import logging
from flask import request, jsonify

from ..routes import api_bp
from ...services.upload_service import upload_service

logger = logging.getLogger(__name__)


@api_bp.route("/upload/temp", methods=["POST"])
@api_bp.route("/upload/temp/", methods=["POST"])
def upload_temp():
    """
    Accept one or more files (multipart/form-data).
    Returns list of { upload_id, filename, size } for use in form_data via Socket.IO.

    Form fields:
      - file: single file (optional)
      - files: multiple files (optional)
      - max_size_mb: optional, override default
      - accept: optional, e.g. ".pdf,image/*"
    """
    max_size_mb = request.form.get("max_size_mb", type=float) or upload_service.DEFAULT_MAX_FILE_SIZE_MB
    accept = request.form.get("accept") or None

    # Collect file storages: "file" (single) or "files" / "files[]" (multiple)
    files = []
    if "file" in request.files and request.files["file"].filename:
        files.append(request.files["file"])
    for key in request.files:
        if key == "file":
            continue
        for f in request.files.getlist(key):
            if f and f.filename:
                files.append(f)

    if not files:
        return jsonify({"success": False, "error": "No files", "uploads": []}), 400

    results = upload_service.save_uploads(
        files,
        max_size_mb=max_size_mb,
        accept=accept,
    )

    uploads = []
    for r in results:
        if r.success:
            uploads.append({
                "upload_id": r.upload_id,
                "filename": r.filename,
                "size": r.size,
            })
        else:
            return jsonify({
                "success": False,
                "error": r.error or "Upload failed",
                "uploads": uploads,
            }), 400

    return jsonify({"success": True, "uploads": uploads})
