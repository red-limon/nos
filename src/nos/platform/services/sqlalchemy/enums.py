"""Enums shared by db models."""
from enum import Enum


class RecordStatus(str, Enum):
    SUSPENDED = "suspended"
    VALID = "valid"
    CANCELLED = "cancelled"


class RegistrationStatus(str, Enum):
    """Registration outcome: OK if loaded into registry, Error if registration failed, Published if publicly available."""
    OK = "OK"
    ERROR = "Error"
    PUBLISHED = "Pub"



