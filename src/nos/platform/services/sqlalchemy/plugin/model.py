"""SQLAlchemy model for table ``plugins`` (entry-point engine plugins metadata)."""
from datetime import datetime

from ....extensions import db

# Isolated SQLite (or other URI) — not mixed with core platform tables (see SQLALCHEMY_BINDS ``plugins``).
PLUGIN_DB_BIND = "plugins"


class PluginDbModel(db.Model):
    """
    One row per engine plugin discovered via ``importlib.metadata`` entry points (``nos.plugins``).

    ``plugin_id`` is the canonical ``node_id`` or ``workflow_id`` from the Node / Workflow class.

    Stored in the **plugins** database bind (``plugins.db`` by default), not in core ``nos.db``.
    """

    __bind_key__ = PLUGIN_DB_BIND
    __tablename__ = "plugins"

    plugin_id = db.Column(db.String(100), primary_key=True, nullable=False)
    plugin_type = db.Column(db.String(20), nullable=False)  # PluginRecordType value
    module_path = db.Column(db.String(500), nullable=False)
    class_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_type": self.plugin_type,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "status": self.status,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<PluginDbModel {self.plugin_id} ({self.plugin_type})>"
