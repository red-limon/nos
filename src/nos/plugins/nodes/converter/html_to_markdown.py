"""
HtmlToMarkdown Node - Converts HTML to Markdown using Microsoft MarkItDown.

The HTML string is written to a temporary file because MarkItDown converts from file path,
not directly from string.

Requires: pip install 'markitdown[all]'

Module path:  nos.plugins.nodes.converter.html_to_markdown
Class name:   HtmlToMarkdownNode
Node ID:      html_to_markdown

To register:
    reg node html_to_markdown HtmlToMarkdownNode nos.plugins.nodes.converter.html_to_markdown

To execute:
    run node dev nos.plugins.nodes.converter.html_to_markdown HtmlToMarkdownNode --sync --debug
    run node db html_to_markdown --sync --debug --param '{"html":"<h1>Hello</h1><p>World</p>"}'
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput

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


# =============================================================================
# Input/Output Schemas
# =============================================================================

class HtmlToMarkdownInputParams(BaseModel):
    """Input params schema for HtmlToMarkdownNode."""

    html: str = Field(
        default=DEFAULT_HTML,
        description="HTML string to convert to Markdown. Paste in textarea or provide via params.",
        json_schema_extra={"input_type": "textarea"},
    )


class HtmlToMarkdownOutput(BaseModel):
    """Output schema for HtmlToMarkdownNode."""

    markdown: str = Field(..., description="Markdown content converted from HTML")


class HtmlToMarkdownMetadata(BaseModel):
    """Metadata schema for HtmlToMarkdownNode."""

    html_length: int = Field(default=0, description="Input HTML length in characters")
    markdown_length: int = Field(default=0, description="Output Markdown length in characters")


# =============================================================================
# Node Implementation
# =============================================================================

class HtmlToMarkdownNode(Node):
    """
    HtmlToMarkdown Node - converts HTML to Markdown using Microsoft MarkItDown.

    Input params: html (string, textarea in form)
    Output: markdown (string)
    Metadata: html_length, markdown_length
    """

    def __init__(self, node_id: str = "html_to_markdown", name: Optional[str] = None):
        super().__init__(node_id, name or "HTML to Markdown")

    @property
    def input_state_schema(self):
        """Return None for flat state (no workflow state dependencies)."""
        return None

    @property
    def input_params_schema(self):
        """Return input params schema."""
        return HtmlToMarkdownInputParams

    @property
    def output_schema(self):
        """Return output schema."""
        return HtmlToMarkdownOutput

    @property
    def metadata_schema(self):
        """Return metadata schema."""
        return HtmlToMarkdownMetadata

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        """
        Convert HTML to Markdown using Microsoft MarkItDown.

        Args:
            state_dict: Workflow/context state (unused for this node)
            params_dict: Direct params (html key)

        Returns:
            NodeOutput with output.markdown and metadata
        """
        html = (params_dict.get("html") or "").strip()
        if not html:
            html = DEFAULT_HTML

        self.exec_log.log("info", f"Converting {len(html)} characters of HTML to Markdown")

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

        self.exec_log.log("info", f"Converted to {len(markdown)} characters of Markdown")

        return NodeOutput(
            output={
                "output_format": "text",
                "data": markdown,
            },
            metadata={
                "html_length": len(html),
                "markdown_length": len(markdown),
            },
        )


if __name__ == "__main__":
    node = HtmlToMarkdownNode()
    result = node.execute(state={}, input_params={"html": "<h1>Hello</h1><p>World</p>"})
    print("markdown:", result.response.output["markdown"][:200])
    print("metadata:", result.response.metadata)
    print("elapsed_time:", result.elapsed_time)
