"""API module - REST API blueprints."""

from .routes import api_bp
from . import common
from . import workflow
from . import node
from . import run
from . import assistant
from . import engine
from . import test_datagrid
from . import ai_model_config
from . import console
from . import sql
from . import ollama
from . import download
from . import upload
from . import vect
from . import file_io
from . import execution_run
from . import sse

# Register grid-to-action-dispatcher route (uses handlers registered by test_datagrid)
common.register_grid_routes(api_bp)
# Register execution_run routes
execution_run.register_routes(api_bp)
# Register SSE streaming routes
sse.register_routes(api_bp)

from .form_wire import (
    add_form_schema_to_response,
    dump_grid_form_dict,
    engine_run_form_envelope,
    form_envelope,
    form_schema_with_values,
    node_engine_run_form_payload,
    workflow_engine_run_form_payload,
)

__all__ = [
    "api_bp",
    "add_form_schema_to_response",
    "dump_grid_form_dict",
    "engine_run_form_envelope",
    "form_envelope",
    "form_schema_with_values",
    "node_engine_run_form_payload",
    "workflow_engine_run_form_payload",
]
