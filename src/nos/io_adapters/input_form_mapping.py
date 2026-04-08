"""
Form schema for form request during execution (CLIENT → SERVER response).

This module defines the **canonical** mapping from Pydantic models to JSON field rows
(``FormFieldSchema.to_dict``). It is used for: (1) mid-execution forms
(``create_form_request_payload`` / ``form_input``) in ``nos.core.engine.node`` and ``nos.core.engine.workflow_engine``;
(2) the engine **run** form via ``platform.api.engine_form_wire`` (SocketIO
``engine_form_schema``), so Pydantic → form is not duplicated for that path.
REST/datagrid APIs embed the same wire dicts via ``platform.api.form_wire``.

Converts Pydantic BaseModel schemas to JSON structures for interactive HTML forms.
Supports text, number, checkbox, select, slider, textarea, file, etc.

Usage:
    from nos.io_adapters.input_form_mapping import pydantic_to_form_schema

    class MyInputParams(BaseModel):
        name: str = Field(description="User name")
        age: int = Field(ge=0, le=120, description="Age in years")

    form_schema = pydantic_to_form_schema(MyInputParams, values={"name": "John"})
"""

from typing import Any, Dict, List, Optional, Type, Union, get_origin, get_args
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from enum import Enum
import json
import re

# Pydantic v2 uses PydanticUndefined for required fields (not JSON serializable)
try:
    from pydantic_core import PydanticUndefined
except ImportError:
    PydanticUndefined = None


def _json_safe_value(val: Any) -> Any:
    """Return a JSON-serializable value; replace PydanticUndefined and similar with None."""
    if val is None:
        return None
    if PydanticUndefined is not None and val is PydanticUndefined:
        return None
    if type(val).__name__ in ("PydanticUndefinedType", "UndefinedType"):
        return None
    return val


# =============================================================================
# HTML Input Type Mapping
# =============================================================================

# Maps Python/Pydantic types to HTML input types
TYPE_TO_INPUT: Dict[str, str] = {
    "str": "text",
    "int": "number",
    "float": "number",
    "bool": "checkbox",
    "date": "date",
    "datetime": "datetime-local",
    "time": "time",
    "email": "email",
    "url": "url",
    "password": "password",
    "file": "file",
    "color": "color",
}


# =============================================================================
# Form Field Schema
# =============================================================================

class FormFieldSchema:
    """
    Represents a single form field with all HTML input attributes.
    """
    
    def __init__(
        self,
        name: str,
        input_type: str = "text",
        label: Optional[str] = None,
        description: Optional[str] = None,
        required: bool = False,
        default: Any = None,
        value: Any = None,
        placeholder: Optional[str] = None,
        # Constraints
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        step: Optional[Union[int, float]] = None,
        # Select/Radio options
        options: Optional[List[Dict[str, Any]]] = None,
        multiple: bool = False,
        # Textarea
        rows: Optional[int] = None,
        # File
        accept: Optional[str] = None,
        # Slider
        show_value: bool = True,
        # Additional attributes
        disabled: bool = False,
        readonly: bool = False,
        css_class: Optional[str] = None,
        # Extra metadata
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.input_type = input_type
        self.label = label or self._name_to_label(name)
        self.description = description
        self.required = required
        self.default = default
        self.value = value if value is not None else default
        self.placeholder = placeholder
        self.min_value = min_value
        self.max_value = max_value
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.step = step
        self.options = options
        self.multiple = multiple
        self.rows = rows
        self.accept = accept
        self.show_value = show_value
        self.disabled = disabled
        self.readonly = readonly
        self.css_class = css_class
        self.extra = extra or {}
    
    @staticmethod
    def _name_to_label(name: str) -> str:
        """Convert snake_case to Title Case label."""
        return name.replace("_", " ").title()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization (sanitizes value for PydanticUndefined etc.)."""
        result = {
            "name": self.name,
            "type": self.input_type,
            "label": self.label,
            "required": self.required,
            "value": _json_safe_value(self.value),
        }
        
        # Add optional fields only if set
        if self.description:
            result["description"] = self.description
        if self.placeholder:
            result["placeholder"] = self.placeholder
        if self.min_value is not None:
            result["min"] = self.min_value
        if self.max_value is not None:
            result["max"] = self.max_value
        if self.min_length is not None:
            result["minLength"] = self.min_length
        if self.max_length is not None:
            result["maxLength"] = self.max_length
        if self.pattern:
            result["pattern"] = self.pattern
        if self.step is not None:
            result["step"] = self.step
        if self.options:
            result["options"] = self.options
        if self.multiple:
            result["multiple"] = True
        if self.rows:
            result["rows"] = self.rows
        if self.accept:
            result["accept"] = self.accept
        if self.disabled:
            result["disabled"] = True
        if self.readonly:
            result["readonly"] = True
        if self.css_class:
            result["class"] = self.css_class
        if self.extra:
            result["extra"] = self.extra
        if self.input_type == "json":
            result["decode"] = "json"
            
        return result


# =============================================================================
# Pydantic to Form Schema Converter
# =============================================================================

def get_python_type_name(annotation: Any) -> str:
    """Extract the base Python type name from a type annotation."""
    origin = get_origin(annotation)
    
    # Handle Optional[X] -> X
    if origin is Union:
        args = get_args(annotation)
        # Filter out NoneType
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return get_python_type_name(non_none_args[0])
    
    # Handle List[X], Dict[X, Y], etc.
    if origin is not None:
        return origin.__name__ if hasattr(origin, '__name__') else str(origin)
    
    # Handle basic types
    if hasattr(annotation, '__name__'):
        return annotation.__name__
    
    return str(annotation)


def is_optional_type(annotation: Any) -> bool:
    """Check if a type annotation is Optional (Union with None)."""
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        return type(None) in args
    return False


def is_enum_type(annotation: Any) -> bool:
    """Check if annotation is an Enum type."""
    try:
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                annotation = non_none[0]
        return isinstance(annotation, type) and issubclass(annotation, Enum)
    except (TypeError, AttributeError):
        return False


def _numeric_bounds_from_field_info(field_info: Optional[FieldInfo]) -> Dict[str, Any]:
    """
    Collect ge/le/gt/lt from FieldInfo.

    Pydantic v2 stores numeric constraints in ``metadata`` (e.g. ``annotated_types.Ge``);
    older code paths may still expose ``field_info.ge`` / ``field_info.le`` directly.
    """
    bounds: Dict[str, Any] = {}
    if not field_info:
        return bounds
    for attr in ('ge', 'le', 'gt', 'lt'):
        if hasattr(field_info, attr):
            v = getattr(field_info, attr, None)
            if v is not None:
                bounds[attr] = v
    for item in getattr(field_info, 'metadata', None) or ():
        cls_name = type(item).__name__
        if cls_name == 'Ge' and hasattr(item, 'ge'):
            bounds['ge'] = item.ge
        elif cls_name == 'Le' and hasattr(item, 'le'):
            bounds['le'] = item.le
        elif cls_name == 'Gt' and hasattr(item, 'gt'):
            bounds['gt'] = item.gt
        elif cls_name == 'Lt' and hasattr(item, 'lt'):
            bounds['lt'] = item.lt
    return bounds


def get_enum_options(annotation: Any) -> List[Dict[str, Any]]:
    """Extract options from an Enum type."""
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            annotation = non_none[0]
    
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [
            {"value": member.value, "label": member.name.replace("_", " ").title()}
            for member in annotation
        ]
    return []


def determine_input_type(
    type_name: str,
    field_info: Optional[FieldInfo],
) -> str:
    """
    Determine the HTML input type based on Python type and field metadata.

    Priority:
    1. ``json_schema_extra["input_type"]`` when set (required for ``str`` fields that are not plain text).
    2. Dict/list-like type names → ``json``; numeric min+max on int/float → ``range``.
    3. ``TYPE_TO_INPUT`` for the resolved Python type name.

    The client renders from the resulting wire ``type``. Use :func:`pydantic_field_to_form_field`
    so ``json_schema_extra`` also supplies ``accept``, ``rows``, ``max_size_mb``, etc.
    """
    # Check field extra for explicit input_type
    if field_info and hasattr(field_info, 'json_schema_extra') and field_info.json_schema_extra:
        extra = field_info.json_schema_extra
        if isinstance(extra, dict) and 'input_type' in extra:
            return extra['input_type']

    # Dict / object-like types -> json textarea (client will stringify for display, parse on submit)
    if type_name.lower() in ('dict', 'list', 'mapping', 'mappingproxy'):
        return 'json'
    if 'dict' in type_name.lower() or 'list' in type_name.lower():
        return 'json'
    
    # Check if it should be a slider (has both min and max constraints)
    if field_info:
        b = _numeric_bounds_from_field_info(field_info)
        has_min = b.get('ge') is not None or b.get('gt') is not None
        has_max = b.get('le') is not None or b.get('lt') is not None
        if has_min and has_max and type_name in ('int', 'float'):
            return 'range'  # Slider
    
    # Default mapping
    return TYPE_TO_INPUT.get(type_name, 'text')


def extract_constraints(field_info: Optional[FieldInfo]) -> Dict[str, Any]:
    """Extract validation constraints from Pydantic FieldInfo."""
    constraints = {}
    
    if not field_info:
        return constraints
    
    b = _numeric_bounds_from_field_info(field_info)
    # Numeric constraints (prefer ge/le over gt/lt for min/max when both exist)
    if b.get('ge') is not None:
        constraints['min'] = b['ge']
    elif b.get('gt') is not None:
        gt = b['gt']
        constraints['min'] = gt + (0.001 if isinstance(gt, float) else 1)
    if b.get('le') is not None:
        constraints['max'] = b['le']
    elif b.get('lt') is not None:
        lt = b['lt']
        constraints['max'] = lt - (0.001 if isinstance(lt, float) else 1)
    step_val = None
    if hasattr(field_info, 'multiple_of') and field_info.multiple_of is not None:
        step_val = field_info.multiple_of
    if step_val is None:
        for item in getattr(field_info, 'metadata', None) or ():
            if type(item).__name__ == 'MultipleOf' and hasattr(item, 'multiple_of'):
                step_val = item.multiple_of
                break
    if step_val is not None:
        constraints['step'] = step_val
    
    # String constraints
    if hasattr(field_info, 'min_length') and field_info.min_length is not None:
        constraints['minLength'] = field_info.min_length
    if hasattr(field_info, 'max_length') and field_info.max_length is not None:
        constraints['maxLength'] = field_info.max_length
    if hasattr(field_info, 'pattern') and field_info.pattern is not None:
        constraints['pattern'] = field_info.pattern
    
    return constraints


def pydantic_field_to_form_field(
    name: str,
    annotation: Any,
    field_info: Optional[FieldInfo],
    value: Any = None
) -> FormFieldSchema:
    """
    Convert a single Pydantic field to a FormFieldSchema.
    
    Args:
        name: Field name
        annotation: Type annotation
        field_info: Pydantic FieldInfo
        value: Current value (overrides default)
    
    Returns:
        FormFieldSchema instance
    """
    type_name = get_python_type_name(annotation)
    is_optional = is_optional_type(annotation)
    
    # Determine required status
    required = not is_optional
    if field_info and field_info.default is not None:
        required = False
    if field_info and hasattr(field_info, 'default_factory') and field_info.default_factory is not None:
        required = False
    
    # Get default value.
    # PydanticUndefined is used as sentinel when only default_factory is set — it is NOT None,
    # so we must explicitly treat it as "no explicit default" to reach the default_factory branch.
    default = None
    if field_info:
        raw_default = field_info.default
        if PydanticUndefined is not None and raw_default is PydanticUndefined:
            raw_default = None
        if raw_default is not None and not isinstance(raw_default, type):
            default = _json_safe_value(raw_default)
        elif hasattr(field_info, 'default_factory') and field_info.default_factory:
            try:
                default = _json_safe_value(field_info.default_factory())
            except Exception:
                pass
    
    # Use provided value or default
    final_value = _json_safe_value(value if value is not None else default)
    
    # Get description
    description = None
    if field_info and field_info.description:
        description = field_info.description
    
    def _to_json_str(val: Any) -> str:
        """Serialize value to JSON string for form display (avoids [object Object] in text inputs)."""
        if val is None:
            return ""
        if isinstance(val, BaseModel):
            return json.dumps(val.model_dump())
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return str(val)
    
    # Handle Pydantic BaseModel types -> json textarea (value must be JSON string for display)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return FormFieldSchema(
            name=name,
            input_type='json',
            description=description,
            required=required,
            default=_to_json_str(default) if default is not None else "{}",
            value=_to_json_str(final_value) if final_value is not None else _to_json_str(default),
            rows=6,
        )
    
    # Handle Dict/List types -> json textarea (value as JSON string for display)
    if type_name.lower() in ('dict', 'list') or 'dict' in type_name.lower() or 'list' in type_name.lower():
        return FormFieldSchema(
            name=name,
            input_type='json',
            description=description,
            required=required,
            default=_to_json_str(default) if default is not None else "{}",
            value=_to_json_str(final_value) if final_value is not None else _to_json_str(default),
            rows=6,
        )
    
    # Handle Enum types -> select
    if is_enum_type(annotation):
        options = get_enum_options(annotation)
        return FormFieldSchema(
            name=name,
            input_type='select',
            description=description,
            required=required,
            default=_json_safe_value(default),
            value=final_value,
            options=options,
        )
    
    # Determine input type
    input_type = determine_input_type(type_name, field_info)
    
    # Extract constraints
    constraints = extract_constraints(field_info)
    
    # json_schema_extra: explicit input_type (handled above), readonly/placeholder, file/textarea attrs, client extra
    readonly = False
    placeholder = None
    accept: Optional[str] = None
    multiple = False
    rows_override: Optional[int] = None
    field_extra: Dict[str, Any] = {}
    if field_info and hasattr(field_info, 'json_schema_extra') and field_info.json_schema_extra:
        extra = field_info.json_schema_extra
        if isinstance(extra, dict):
            if extra.get('readonly'):
                readonly = True
            if extra.get('placeholder'):
                placeholder = str(extra['placeholder'])
            if extra.get('accept') is not None:
                accept = str(extra['accept'])
            if extra.get('multiple') is not None:
                multiple = bool(extra['multiple'])
            if extra.get('rows') is not None:
                try:
                    rows_override = int(extra['rows'])
                except (TypeError, ValueError):
                    rows_override = None
            if extra.get('max_size_mb') is not None:
                field_extra['maxSizeMb'] = extra['max_size_mb']
            # Pass through other keys for the client (skip keys consumed above / input_type)
            reserved = frozenset({
                'input_type', 'readonly', 'placeholder', 'accept', 'multiple', 'rows', 'max_size_mb',
            })
            for k, v in extra.items():
                if k in reserved:
                    continue
                field_extra[k] = v

    rows = rows_override if rows_override is not None else (5 if input_type == 'textarea' else None)

    return FormFieldSchema(
        name=name,
        input_type=input_type,
        description=description,
        required=required,
        default=_json_safe_value(default),
        value=final_value,
        min_value=constraints.get('min'),
        max_value=constraints.get('max'),
        min_length=constraints.get('minLength'),
        max_length=constraints.get('maxLength'),
        pattern=constraints.get('pattern'),
        step=constraints.get('step'),
        rows=rows,
        accept=accept,
        multiple=multiple,
        readonly=readonly,
        placeholder=placeholder,
        extra=field_extra if field_extra else None,
    )


def pydantic_to_form_schema(
    model: Type[BaseModel],
    values: Optional[Dict[str, Any]] = None,
    exclude: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Convert a Pydantic BaseModel class to a form schema dictionary.
    
    Args:
        model: Pydantic BaseModel class (not instance)
        values: Optional dict of current values to populate the form
        exclude: List of field names to exclude from the form
    
    Returns:
        Dictionary with 'fields' list ready for JSON serialization
        
    Example:
        class MyInput(BaseModel):
            name: str = Field(description="Your name")
            age: int = Field(ge=0, le=120)
            
        schema = pydantic_to_form_schema(MyInput, values={"name": "John"})
        # Returns: {"fields": [{"name": "name", "type": "text", ...}, ...]}
    """
    values = values or {}
    exclude = exclude or []
    fields = []
    
    # Get model fields
    model_fields = model.model_fields if hasattr(model, 'model_fields') else {}
    
    for field_name, field_info in model_fields.items():
        if field_name in exclude:
            continue
        
        annotation = field_info.annotation if hasattr(field_info, 'annotation') else str
        value = values.get(field_name)
        
        form_field = pydantic_field_to_form_field(
            name=field_name,
            annotation=annotation,
            field_info=field_info,
            value=value
        )
        fields.append(form_field.to_dict())
    
    return {"fields": fields}


def create_form_request_payload(
    state_schema: Optional[Type[BaseModel]] = None,
    params_schema: Optional[Type[BaseModel]] = None,
    state_values: Optional[Dict[str, Any]] = None,
    params_values: Optional[Dict[str, Any]] = None,
    node_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    title: Optional[str] = None,
    form_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a complete form request payload for execution_request.
    
    This creates the JSON structure that will be sent to the client
    for rendering an interactive form with State and Params sections.
    
    Args:
        state_schema: Pydantic model for state fields
        params_schema: Pydantic model for params fields
        state_values: Current state values
        params_values: Current param values
        node_id: Node identifier
        workflow_id: Workflow identifier (for workflow_initial_state form)
        execution_id: Execution identifier
        title: Form title
        form_type: Override form_type; default "node_input" or "workflow_initial_state" when workflow_id
    
    Returns:
        Dictionary payload for execution_request event
    """
    if form_type is None:
        form_type = "workflow_initial_state" if workflow_id else "node_input"
    payload = {
        "form_type": form_type,
        "title": title or f"Configure {node_id or workflow_id or 'Execution'}",
    }
    
    if node_id:
        payload["node_id"] = node_id
    if workflow_id:
        payload["workflow_id"] = workflow_id
    if execution_id:
        payload["execution_id"] = execution_id
    
    # State section
    if state_schema:
        state_form = pydantic_to_form_schema(state_schema, state_values)
        payload["state"] = {
            "label": "State",
            "description": "Workflow/execution state variables",
            "collapsed": False,
            "fields": state_form["fields"]
        }
    else:
        payload["state"] = {
            "label": "State",
            "description": "No state schema defined",
            "collapsed": True,
            "fields": []
        }
    
    # Params section
    if params_schema:
        params_form = pydantic_to_form_schema(params_schema, params_values)
        payload["params"] = {
            "label": "Parameters",
            "description": "Node input parameters",
            "collapsed": False,
            "fields": params_form["fields"]
        }
    else:
        payload["params"] = {
            "label": "Parameters",
            "description": "No parameters schema defined",
            "collapsed": True,
            "fields": []
        }
    
    return payload
