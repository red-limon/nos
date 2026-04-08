"""Assistant DB model (table: assistant)."""
from datetime import datetime

from ....extensions import db
from ..enums import RegistrationStatus


class AssistantDbModel(db.Model):
    __tablename__ = "assistant"
    assistant_id = db.Column(db.String(100), primary_key=True, nullable=False)
    class_name = db.Column(db.String(200), nullable=False)
    module_path = db.Column(db.String(500), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    created_by = db.Column(db.String(80), nullable=False, default="system")
    updated_by = db.Column(db.String(80), nullable=False, default="system")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    registration_status = db.Column(db.String(20), nullable=False, default=RegistrationStatus.ERROR.value)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    def to_dict(self):
        return {
            "assistant_id": self.assistant_id,
            "class_name": self.class_name,
            "module_path": self.module_path,
            "name": self.name,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "registration_status": self.registration_status,
            "registration_date": self.registration_date.isoformat() if self.registration_date else None,
        }

    def __repr__(self):
        return f"<AssistantDbModel {self.assistant_id}>"
