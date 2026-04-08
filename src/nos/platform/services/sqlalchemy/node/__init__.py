"""Node DB model and repository (table: node)."""

from .model import NodeDbModel
from . import repository

__all__ = ["NodeDbModel", "repository"]
