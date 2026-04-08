"""REST endpoints for execution_run (execution history and saved log download)."""

import json
import logging
import os
from pathlib import Path

from flask import jsonify, request, send_file, session, abort

logger = logging.getLogger(__name__)


def register_routes(api_bp):
    """Register execution_run routes on the shared api_bp Blueprint."""

    @api_bp.get("/execution-run/history")
    def get_execution_history():
        """Return execution history for the current user (or all if admin).

        Query params:
            user_id (str): override user filter (default: session username)
            limit   (int): max rows (default 100)
            offset  (int): pagination offset (default 0)
        """
        from ...services.sqlalchemy.execution_run import repository as run_repo

        user_id = request.args.get("user_id") or session.get("username", "developer")
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = int(request.args.get("offset", 0))

        try:
            runs = run_repo.get_history(user_id=user_id, limit=limit, offset=offset)
            return jsonify([r.to_dict() for r in runs])
        except Exception as e:
            logger.error("get_execution_history failed: %s", e, exc_info=True)
            return jsonify({"error": str(e)}), 500

    @api_bp.get("/execution-run/<execution_id>")
    def get_execution_run(execution_id: str):
        """Return a single execution_run record."""
        from ...services.sqlalchemy.execution_run import repository as run_repo

        run = run_repo.get_by_execution_id(execution_id)
        if not run:
            return jsonify({"error": "Not found"}), 404
        return jsonify(run.to_dict())

    @api_bp.get("/execution-run/download/<execution_id>")
    def download_execution_log(execution_id: str):
        """Download the saved JSON log for an execution.

        Returns the file as attachment if execution_log path is set, else 404.
        """
        from ...services.sqlalchemy.execution_run import repository as run_repo

        run = run_repo.get_by_execution_id(execution_id)
        if not run:
            return jsonify({"error": "Execution not found"}), 404
        if not run.execution_log:
            return jsonify({
                "error": "No execution log file on disk. Logs are written by default; use --nolog to skip."
            }), 404

        path = Path(run.execution_log)
        if not path.exists():
            return jsonify({"error": f"File not found on disk: {run.execution_log}"}), 404

        return send_file(
            str(path),
            mimetype="application/json",
            as_attachment=True,
            download_name=f"{execution_id}.json",
        )

    @api_bp.get("/execution-run/result-json/<execution_id>")
    def get_execution_result_json(execution_id: str):
        """Return parsed JSON from the saved execution file, or metadata-only if no file.

        Used by the console Result document to load history rows without forcing a file download.
        """
        from ...services.sqlalchemy.execution_run import repository as run_repo

        run = run_repo.get_by_execution_id(execution_id)
        if not run:
            return jsonify({"error": "Not found"}), 404

        payload = None
        source = "metadata"
        read_error = None

        if run.execution_log:
            path = Path(run.execution_log)
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    source = "file"
                except Exception as e:
                    logger.warning("result-json: invalid JSON at %s: %s", path, e)
                    read_error = str(e)

        return jsonify(
            {
                "source": source,
                "read_error": read_error,
                "execution_run": run.to_dict(),
                "payload": payload,
            }
        )
