"""
HtmlToMarkdown Node - Converts HTML to Markdown using Microsoft MarkItDown.

Requires: pip install 'markitdown[all]'
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput
from nos.platform.api.form_wire import form_envelope

logger = logging.getLogger(__name__)

# Default minimal HTML for testing when no input is provided
DEFAULT_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
<h1>Test Title</h1>
<p>This is a paragraph.</p>
</body>
</html>"""


class HtmlToMarkdownInput(BaseModel):
    """Input schema for HtmlToMarkdownNode."""

    html: str = Field(
        default=DEFAULT_HTML,
        description="HTML string to convert to Markdown (paste in textarea). If empty, uses minimal default HTML.",
    )


class HtmlToMarkdownOutput(BaseModel):
    """Output schema for HtmlToMarkdownNode."""

    markdown: str = Field(..., description="Markdown content converted from HTML")


class HtmlToMarkdownNode(Node):
    """
    HtmlToMarkdown node - converts HTML to Markdown using Microsoft MarkItDown.

    Uses a textarea for HTML input. If the form submits empty, uses a minimal default HTML.
    Can be executed standalone or in a workflow.
    """

    def __init__(self, node_id: str = "html_to_markdown", name: Optional[str] = None):
        super().__init__(node_id, name or "HTML to Markdown")

    @property
    def input_schema(self):
        """Return input schema for form rendering."""
        return HtmlToMarkdownInput

    @property
    def output_schema(self):
        """Return output schema."""
        return HtmlToMarkdownOutput

    @property
    def form_schema(self):
        """Return form schema with textarea for HTML input."""
        return form_envelope(
            form_id=f"node-{self.node_id}",
            title=f"Node: {self.name}",
            fields=[
                {
                    "name": "html",
                    "label": "HTML",
                    "type": "textarea",
                    "value": DEFAULT_HTML,
                    "required": False,
                    "description": "Paste HTML content to convert to Markdown",
                },
            ],
            submit_label="Run",
        )

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """
        Convert HTML to Markdown using Microsoft MarkItDown.

        Args:
            state: Shared workflow state (mutable)
            input_dict: Normalized input (html key)

        Returns:
            NodeOutput with data.markdown (string) and metadata
        """
        html = (input_dict.get("html") or state.get("html") or "").strip()
        if not html:
            html = DEFAULT_HTML

        self.log("info", f"Converting {len(html)} characters of HTML to Markdown")

        try:
            from markitdown import MarkItDown
        except ImportError as e:
            raise ImportError(
                "markitdown is not installed. Run: pip install 'markitdown[all]'"
            ) from e

        md = MarkItDown()

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(html)
            temp_path = Path(f.name)

        try:
            result = md.convert(str(temp_path))
            markdown = result.text_content if result else ""
        finally:
            temp_path.unlink(missing_ok=True)

        if not markdown:
            markdown = ""

        state["html"] = html
        state["markdown"] = markdown

        self.log("info", f"Converted to {len(markdown)} characters of Markdown")

        return NodeOutput(
            output={"markdown": markdown},
            metadata={
                "html_length": len(html),
                "markdown_length": len(markdown),
            },
        )
