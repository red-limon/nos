"""
Shared output formats for node and workflow result rendering.

Used by:
- Node: NodeExecutionResult.format, NODE_OUTPUT_FORMATS
- Workflow: WorkflowExecutionResult.response.output["output_format"], WORKFLOW_OUTPUT_FORMATS
- Console/API: validate and pass output_format to engine
- Frontend: renderConsoleOutput uses format to select handler (json, table, text, etc.)

Each format has a Pydantic schema documenting the expected shape of NodeOutput.output['data'].
Use these schemas as type hints in _do_execute to get IDE autocomplete:

    from nos.io_adapters.output_formats_schema import OutputTableSchema
    return NodeOutput(output={"output_format": "table", "data": OutputTableSchema(columns=[...], rows=[...]).model_dump()})

Format → data type contract:
    json     → Any JSON-serializable value (dict, list, scalar)
    html     → str  (HTML markup)
    text     → str  (plain text)
    table    → OutputTableSchema  {columns: List[str], rows: List[Dict]}
    code     → OutputCodeSchema   {code: str, language: str}
    tree     → OutputTreeSchema   {name: str, children: [...]}
    chart    → OutputChartSchema  {type, labels, datasets}
    download → OutputDownloadSchema {url, filename, size}
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# Formats supported for rendering result output in the console/web UI
OUTPUT_FORMATS = ["json", "text", "html", "table", "code", "tree", "chart", "download"]

# Aliases for backward compatibility
NODE_OUTPUT_FORMATS = OUTPUT_FORMATS
WORKFLOW_OUTPUT_FORMATS = OUTPUT_FORMATS


# --- Pydantic schemas for format validation ---


# Type aliases for scalar formats (data IS the value, not a dict wrapper)
OutputHtmlData = str   # html   → data: str  (HTML markup)
OutputTextData = str   # text   → data: str  (plain text)
OutputJsonData = Any   # json   → data: Any  (any JSON-serializable value)


class OutputTableSchema(BaseModel):
    """Schema for table format. Frontend expects columns + rows."""

    model_config = ConfigDict(extra="allow")

    columns: List[str] = Field(..., description="Column names")
    rows: List[Dict[str, Any]] = Field(..., description="Rows as list of dicts keyed by column name")


class OutputChartDatasetSchema(BaseModel):
    """Schema for a chart dataset (Chart.js style)."""

    model_config = ConfigDict(extra="allow")

    data: List[float] = Field(default_factory=list, description="Data values")
    label: Optional[str] = Field(None, description="Dataset label")
    backgroundColor: Optional[List[str]] = Field(None, description="Bar/segment colors")


class OutputChartSchema(BaseModel):
    """Schema for chart format. Supports bar, line, pie, doughnut."""

    model_config = ConfigDict(extra="allow")

    type: Optional[str] = Field("bar", description="Chart type: bar, line, pie, doughnut")
    labels: List[str] = Field(default_factory=list, description="Category labels")
    datasets: Optional[List[OutputChartDatasetSchema]] = Field(None, description="Chart.js datasets")
    values: Optional[List[float]] = Field(None, description="Simple values (alternative to datasets)")


class OutputCodeSchema(BaseModel):
    """Schema for code format. Code content with optional language."""

    model_config = ConfigDict(extra="allow")

    code: str = Field("", description="Code content")
    language: Optional[str] = Field("plaintext", description="Syntax highlighting language")


class OutputDownloadSchema(BaseModel):
    """Schema for download format. Downloadable file link."""

    model_config = ConfigDict(extra="allow")

    url: str = Field(..., description="Download URL")
    filename: Optional[str] = Field(None, description="Suggested filename")
    size: Optional[int] = Field(None, description="File size in bytes")


class OutputTreeSchema(BaseModel):
    """Schema for tree format. Hierarchical structure with name and optional children."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="Node name")
    children: Optional[List[Dict[str, Any]]] = Field(None, description="Child nodes (same structure)")


# Mapping: format name -> schema class (None = scalar, validated by type check only)
OUTPUT_FORMAT_SCHEMAS: Dict[str, Optional[type]] = {
    "json": None,               # Any JSON-serializable
    "text": None,               # str — validated as typeof string by frontend
    "html": None,               # str — validated as typeof string by frontend
    "table": OutputTableSchema,
    "code": OutputCodeSchema,
    "tree": OutputTreeSchema,
    "chart": OutputChartSchema,
    "download": OutputDownloadSchema,
}


def validate_output_for_format(output: Any, format: str) -> tuple[bool, Optional[str]]:
    """
    Validate output against the schema for the given format.

    Args:
        output: Output to validate (typically dict from node/workflow)
        format: Output format name (json, text, html, table, code, tree, chart, download)

    Returns:
        (valid, error_message). valid=True and error_message=None on success.
    """
    if format not in OUTPUT_FORMATS:
        return False, f"Unknown format: {format}"
    schema_cls = OUTPUT_FORMAT_SCHEMAS.get(format)
    if schema_cls is None:
        return True, None
    try:
        to_validate = output
        if format == "table" and isinstance(output, dict):
            rows = output.get("rows", [])
            columns = output.get("columns", [])
            if columns and rows and isinstance(rows[0], (list, tuple)):
                to_validate = {**output, "rows": [dict(zip(columns, row)) for row in rows]}
        if format == "code" and isinstance(output, str):
            to_validate = {"code": output, "language": "plaintext"}
        schema_cls.model_validate(to_validate)
        return True, None
    except Exception as e:
        return False, str(e)
