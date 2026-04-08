"""Execution Log DB model (table: execution_log).

Stores execution events for audit trail and background execution log retrieval.
"""
from ....extensions import db


class ExecutionLogDbModel(db.Model):
    """
    Stores execution log events for nodes and workflows.
    
    Used for:
    - Audit trail (all executions, both interactive and background)
    - Historical log retrieval via console `logs` command or REST API
    - Debugging and troubleshooting past executions
    """
    __tablename__ = "execution_log"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    execution_id = db.Column(db.String(100), nullable=False, index=True)
    execution_type = db.Column(db.String(20), nullable=False)  # "node" | "workflow"
    plugin_id = db.Column(db.String(100), nullable=True, index=True)  # node_id or workflow_id
    user_id = db.Column(db.String(100), nullable=True, index=True)    # session username
    event = db.Column(db.String(50), nullable=False)  # node_start, node_end, etc.
    level = db.Column(db.String(20), nullable=False, default="info")  # debug, info, warning, error
    message = db.Column(db.Text, nullable=True)
    data = db.Column(db.Text, nullable=True)  # JSON string for extra data
    start_timestamp = db.Column(db.Float, nullable=False)  # Unix timestamp start
    end_timestamp = db.Column(db.Float, nullable=False)  # Unix timestamp end

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        import json
        data_parsed = None
        if self.data:
            try:
                data_parsed = json.loads(self.data)
            except (json.JSONDecodeError, TypeError):
                data_parsed = self.data
        
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "execution_type": self.execution_type,
            "plugin_id": self.plugin_id,
            "user_id": self.user_id,
            "event": self.event,
            "level": self.level,
            "message": self.message,
            "data": data_parsed,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
        }

    def __repr__(self):
        return f"<ExecutionLogDbModel {self.id} {self.execution_id} {self.event}>"
