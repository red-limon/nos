"""
Wire JSON for forms: one shape for engine run, REST grid, and mid-execution forms.

Field rows follow ``nos.io_adapters.input_form_mapping.FormFieldSchema.to_dict`` (``name``,
``type``, ``label``, ``required``, ``value``, optional ``description``, ``min`` / ``max``,
``minLength`` / ``maxLength``, ``pattern``, ``options``, ``accept``, ``decode`` for JSON, …).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from nos.io_adapters.input_form_mapping import pydantic_to_form_schema

logger = logging.getLogger(__name__)


def form_envelope(
    *,
    form_id: str,
    title: str,
    fields: List[Dict[str, Any]],
    submit_label: str = "Submit",
    description: Optional[str] = None,
    method: Optional[str] = None,
    cancel_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Full form object for API or SocketIO (camelCase keys)."""
    out: Dict[str, Any] = {
        "formId": form_id,
        "title": title,
        "submitLabel": submit_label,
        "fields": fields,
    }
    if description:
        out["description"] = description
    if method:
        out["method"] = method
    if cancel_label:
        out["cancelLabel"] = cancel_label
    return out


def engine_run_form_envelope(
    *,
    form_id: str,
    title: str,
    fields: List[Dict[str, Any]],
    submit_label: str = "Run",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Envelope for ``engine_form_schema`` (no method/cancel)."""
    return form_envelope(
        form_id=form_id,
        title=title,
        fields=fields,
        submit_label=submit_label,
        description=description,
    )


def dump_grid_form_dict(d: Dict[str, Any], *, action: Optional[str] = None) -> Dict[str, Any]:
    """Response fragment for legacy grid clients: drop title/description; optional ``actionEndPoint``."""
    out = {k: v for k, v in d.items() if k not in ("title", "description")}
    if action is not None:
        out["actionEndPoint"] = action
    return out


def form_schema_with_values(schema: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Copy schema and set each field ``value`` from ``data`` (edit mode)."""
    fields: List[Dict[str, Any]] = []
    for f in schema.get("fields") or []:
        if not isinstance(f, dict):
            continue
        nf = dict(f)
        name = nf.get("name")
        if name is not None:
            val = data.get(name)
            nf["value"] = "" if val is None else val
        fields.append(nf)
    out = dict(schema)
    out["fields"] = fields
    return out


def api_form_field_dump_to_wire(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a legacy row shaped like ``FormFieldSchema.model_dump(by_alias=True)`` to wire field dict.
    """
    name = d["name"]
    label = d["label"]
    ftype = d.get("type", "text")
    val = d.get("value")
    v = d.get("validation") or {}
    required = bool(v.get("required", False))
    out: Dict[str, Any] = {
        "name": name,
        "type": ftype,
        "label": label,
        "required": required,
        "value": val,
    }
    if d.get("placeholder"):
        out["placeholder"] = d["placeholder"]
    ht = d.get("helpText")
    if ht:
        out["description"] = ht
    for key in ("min", "max", "pattern", "step"):
        if v.get(key) is not None:
            out[key] = v[key]
    for key in ("minLength", "maxLength"):
        if v.get(key) is not None:
            out[key] = v[key]
    if d.get("options"):
        out["options"] = d["options"]
    if ftype == "file":
        if v.get("accept") is not None:
            out["accept"] = v["accept"]
        if v.get("multiple"):
            out["multiple"] = True
        extra: Dict[str, Any] = {}
        if v.get("maxSizeMb") is not None:
            extra["maxSizeMb"] = v["maxSizeMb"]
        if v.get("maxFiles") is not None:
            extra["maxFiles"] = v["maxFiles"]
        if extra:
            out["extra"] = extra
    if ftype == "json":
        out["decode"] = "json"
        if val is not None and isinstance(val, (dict, list)):
            out["value"] = json.dumps(val, ensure_ascii=False)
    if d.get("disabled"):
        out["disabled"] = True
    if d.get("readonly"):
        out["readonly"] = True
    if d.get("cssClass"):
        out["class"] = d["cssClass"]
    return out


def coerce_field_row(f: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a field dict; convert nested-``validation`` rows to wire shape."""
    if isinstance(f.get("validation"), dict):
        return api_form_field_dump_to_wire(f)
    return dict(f)


def merge_custom_form_dict(
    custom: Dict[str, Any],
    *,
    form_id: str,
    title_fallback: str,
    submit_label_fallback: str = "Run",
) -> Dict[str, Any]:
    """Merge a plugin/custom form dict (wire or legacy API rows) into a full engine envelope."""
    raw_fields = custom.get("fields") or []
    fields: List[Dict[str, Any]] = []
    for f in raw_fields:
        if isinstance(f, dict):
            fields.append(coerce_field_row(f))
        else:
            fields.append(f)  # type: ignore[arg-type]
    title = custom.get("title")
    if not (isinstance(title, str) and title.strip()):
        title = title_fallback
    return engine_run_form_envelope(
        form_id=str(custom.get("formId") or form_id),
        title=str(title),
        description=custom.get("description"),
        submit_label=str(custom.get("submitLabel") or submit_label_fallback),
        fields=fields,
    )


def _fields_from_model(
    model: Type[BaseModel],
    *,
    values: Optional[Dict[str, Any]] = None,
    exclude: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    return pydantic_to_form_schema(model, values=values or {}, exclude=exclude or [])["fields"]


def node_engine_run_form_payload(node_id: str) -> Dict[str, Any]:
    """``form_schema`` dict for a registered node."""
    try:
        from nos.core.engine.registry import workflow_registry

        node_class = workflow_registry.get_node(node_id)
        if not node_class:
            return engine_run_form_envelope(
                form_id=f"node-{node_id}",
                title=f"Node {node_id}",
                fields=[],
            )

        node = workflow_registry.create_node_instance(node_id)
        if not node:
            return engine_run_form_envelope(
                form_id=f"node-{node_id}",
                title=f"Node {node_id}",
                fields=[],
            )

        custom = getattr(node, "form_schema", None)
        if custom is not None:
            if isinstance(custom, dict):
                return merge_custom_form_dict(
                    custom,
                    form_id=f"node-{node_id}",
                    title_fallback=f"Node: {node.name or node_id}",
                )
            logger.warning("node %s: form_schema must be a dict, got %s", node_id, type(custom))

        all_fields: List[Dict[str, Any]] = []
        state_schema = getattr(node, "input_state_schema", None)
        if state_schema:
            all_fields.extend(_fields_from_model(state_schema))
        params_schema = getattr(node, "input_params_schema", None)
        if params_schema:
            all_fields.extend(_fields_from_model(params_schema))

        return engine_run_form_envelope(
            form_id=f"node-{node_id}",
            title=f"Node: {node.name or node_id}",
            fields=all_fields,
        )
    except Exception as e:
        logger.error("node_engine_run_form_payload failed for %s: %s", node_id, e, exc_info=True)
        return engine_run_form_envelope(
            form_id=f"node-{node_id}",
            title=f"Node {node_id}",
            fields=[],
        )


def workflow_engine_run_form_payload(workflow_id: str) -> Dict[str, Any]:
    """``form_schema`` dict for a registered workflow."""
    try:
        from nos.core.engine.registry import workflow_registry

        workflow_class = workflow_registry.get_workflow(workflow_id)
        if not workflow_class:
            return engine_run_form_envelope(
                form_id=f"workflow-{workflow_id}",
                title=f"Workflow {workflow_id}",
                fields=[],
            )

        workflow = workflow_registry.create_workflow_instance(workflow_id)
        if not workflow:
            return engine_run_form_envelope(
                form_id=f"workflow-{workflow_id}",
                title=f"Workflow {workflow_id}",
                fields=[],
            )

        custom = getattr(workflow, "form_schema", None)
        if custom is not None:
            if isinstance(custom, dict):
                return merge_custom_form_dict(
                    custom,
                    form_id=f"workflow-{workflow_id}",
                    title_fallback=f"Workflow: {workflow.name or workflow_id}",
                )
            logger.warning("workflow %s: form_schema must be a dict, got %s", workflow_id, type(custom))

        state_schema = getattr(workflow, "state_schema", None)
        if state_schema:
            fields = _fields_from_model(state_schema)
            return engine_run_form_envelope(
                form_id=f"workflow-{workflow_id}",
                title=f"Workflow: {workflow.name or workflow_id}",
                fields=fields,
            )

        return engine_run_form_envelope(
            form_id=f"workflow-{workflow_id}",
            title=f"Workflow: {workflow.name or workflow_id}",
            fields=[],
        )
    except Exception as e:
        logger.error("workflow_engine_run_form_payload failed for %s: %s", workflow_id, e, exc_info=True)
        return engine_run_form_envelope(
            form_id=f"workflow-{workflow_id}",
            title=f"Workflow {workflow_id}",
            fields=[],
        )


def add_form_schema_to_response(response_data: Dict[str, Any], form_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach ``form_schema`` to a payload dict (examples / SSE)."""
    if form_schema:
        response_data = dict(response_data)
        response_data["form_schema"] = dict(form_schema)
    return response_data
