"""Assistant DB model and repository (table: assistant)."""

from .model import AssistantDbModel
from . import repository

__all__ = ["AssistantDbModel", "repository"]
