"""
WebToMarkdown workflow: fetches HTML from URL and converts to Markdown.

Uses:
- WebScraperNode (url -> html)
- HtmlToMarkdownNode (html -> markdown)
- AlwaysLink for sequential connection
- State mappings to connect workflow state with node input/output
"""

from pydantic import BaseModel, Field

from nos.platform.api.form_wire import form_envelope
from nos.core.engine.base import Workflow, AlwaysLink
from nos.core.engine.workflow.state_mapping import create_simple_mapping
from nos.core.engine.registry import workflow_registry


# --- State schema ---
class WebToMarkdownState(BaseModel):
    """
    Workflow state schema.

    - url: Input (initialized by user via form). Mapped to WebScraperNode input.
    - html: Output from WebScraperNode. Mapped to HtmlToMarkdownNode input.
    - markdown: Output from HtmlToMarkdownNode. Final result.
    """

    url: str = Field(
        default="https://example.com",
        description="URL of the page to fetch and convert to Markdown",
    )
    html: str = Field(default="", description="HTML content (from WebScraper)")
    markdown: str = Field(default="", description="Markdown content (from HtmlToMarkdown)")


# --- State mappings ---
# WebScraper: workflow.url -> node input "url"; node output "html" -> workflow.html
WEB_SCRAPER_MAPPING = create_simple_mapping(
    input_fields={"url": "url"},
    output_fields={"html": "html"},
    description="Map workflow url to WebScraper input; html output to workflow state",
)

# HtmlToMarkdown: workflow.html -> node input "html"; node output "markdown" -> workflow.markdown
HTML_TO_MARKDOWN_MAPPING = create_simple_mapping(
    input_fields={"html": "html"},
    output_fields={"markdown": "markdown"},
    description="Map workflow html to HtmlToMarkdown input; markdown output to workflow state",
)


# --- Workflow ---
class WebToMarkdownWorkflow(Workflow):
    """
    WebToMarkdown workflow.

    Fetches HTML from a URL (WebScraperNode) and converts it to Markdown (HtmlToMarkdownNode).
    State mappings connect workflow state with node input/output.
    """

    workflow_id = "web_to_markdown"
    name = "Web to Markdown"

    @property
    def state_schema(self):
        """State schema for form rendering and validation."""
        return WebToMarkdownState

    @property
    def form_schema(self):
        """Form schema: only url for initialization (html/markdown are outputs)."""
        return form_envelope(
            form_id=f"workflow-{self.workflow_id}",
            title=f"Workflow: {self.name}",
            fields=[
                {
                    "name": "url",
                    "label": "URL",
                    "type": "url",
                    "value": "https://example.com",
                    "required": True,
                    "description": "URL of the page to fetch and convert to Markdown",
                },
            ],
            submit_label="Run",
        )

    def define(self):
        """Define workflow: two nodes, one link, state mappings."""
        # Get node instances from registry (reuse WebScraper and HtmlToMarkdown plugins)
        web_scraper = workflow_registry.create_node_instance("web_scraper")
        html_to_markdown = workflow_registry.create_node_instance("html_to_markdown")

        if not web_scraper:
            raise ValueError("WebScraperNode not found in registry. Ensure web_scraper node is registered.")
        if not html_to_markdown:
            raise ValueError("HtmlToMarkdownNode not found in registry. Ensure html_to_markdown node is registered.")

        # Add nodes with state mappings
        self.add_node(web_scraper, state_mapping=WEB_SCRAPER_MAPPING)
        self.add_node(html_to_markdown, state_mapping=HTML_TO_MARKDOWN_MAPPING)

        # Link: web_scraper -> html_to_markdown (always continues)
        link = AlwaysLink(
            link_id="scraper_to_markdown",
            from_node_id="web_scraper",
            to_node_id="html_to_markdown",
            name="To Markdown",
        )
        self.add_link(link)

        self.set_entry_node("web_scraper")
