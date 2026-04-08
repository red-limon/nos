"""
WebScraper Node - Fetches HTML content from a URL using Playwright.

Requires: pip install playwright && playwright install
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

from nos.core.engine.base import Node, NodeOutput

logger = logging.getLogger(__name__)


class WebScraperInput(BaseModel):
    """Input schema for WebScraperNode."""

    url: str = Field(..., description="URL of the page to fetch (e.g. https://example.com)")


class WebScraperOutput(BaseModel):
    """Output schema for WebScraperNode."""

    html: str = Field(..., description="HTML content of the page")


class WebScraperNode(Node):
    """
    WebScraper node - fetches the HTML content of a URL using Playwright.

    Uses a headless browser to render the page and return its HTML.
    Can be executed standalone or in a workflow.
    """

    def __init__(self, node_id: str = "web_scraper", name: Optional[str] = None):
        super().__init__(node_id, name or "Web Scraper")

    @property
    def input_schema(self):
        """Return input schema for form rendering."""
        return WebScraperInput

    @property
    def output_schema(self):
        """Return output schema."""
        return WebScraperOutput

    def _do_execute(self, state: dict, input_dict: dict) -> NodeOutput:
        """
        Fetch HTML from the given URL using Playwright.

        Args:
            state: Shared workflow state (mutable)
            input_dict: Normalized input (url key)

        Returns:
            NodeOutput with data.html (string) and metadata
        """
        url = (input_dict.get("url") or state.get("url") or "").strip()
        if not url:
            raise ValueError("URL is required")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        self.log("info", f"Fetching URL: {url}")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ImportError(
                "Playwright is not installed. Run: pip install playwright && playwright install"
            ) from e

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    html = page.content()
                finally:
                    browser.close()
        except Exception as e:
            self.log("error", f"WebScraper failed for {url}: {e}")
            raise

        state["url"] = url
        state["html"] = html

        self.log("info", f"Fetched {len(html)} characters from {url}")

        return NodeOutput(
            output={"html": html},
            metadata={
                "url": url,
                "html_length": len(html),
            },
        )
