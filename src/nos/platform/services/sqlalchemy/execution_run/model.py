"""ExecutionRun DB model (table: execution_run).

Header table: one row per execution.
Paired with execution_log (detail events) via execution_id.
"""
from ....extensions import db


class ExecutionRunDbModel(db.Model):
    """
    Header record for a node or workflow execution.

    Created at execution start, updated at completion.
    Paired with execution_log rows (many events per execution) via execution_id.
    """

    __tablename__ = "execution_run"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    execution_id = db.Column(db.String(100), nullable=False, unique=True, index=True)
    execution_type = db.Column(db.String(20), nullable=False)          # "node" | "workflow"
    plugin_id = db.Column(db.String(100), nullable=True, index=True)   # node_id or workflow_id
    user_id = db.Column(db.String(100), nullable=True, index=True)     # session username
    status = db.Column(db.String(20), nullable=False, default="running")
    message = db.Column(db.Text, nullable=True)                        # final message
    started_at = db.Column(db.Float, nullable=False)                   # Unix timestamp
    ended_at = db.Column(db.Float, nullable=True)
    elapsed_time = db.Column(db.String(20), nullable=True)             # e.g. "1m 05s"
    execution_log = db.Column(db.String(500), nullable=True)           # path to saved JSON (--save)
    pid = db.Column(db.Integer, nullable=True)                         # OS worker process id (when applicable)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "execution_type": self.execution_type,
            "plugin_id": self.plugin_id,
            "user_id": self.user_id,
            "status": self.status,
            "message": self.message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_time": self.elapsed_time,
            "execution_log": self.execution_log,
            "pid": self.pid,
        }

    def __repr__(self):
        return f"<ExecutionRunDbModel {self.execution_id} {self.status}>"
