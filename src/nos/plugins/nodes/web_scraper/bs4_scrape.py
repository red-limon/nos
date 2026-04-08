"""
BS4 scrape node — polite multi-page fetch plus BeautifulSoup (bs4) extraction per row.

Extends :class:`~.polite_scrape.PoliteScrapeNode` so HTML is fetched via
:meth:`~.polite_scrape.PoliteScrapeNode._fetch_one` (robots, throttle). Selector /
attribute extraction runs in :meth:`BS4ScrapeNode._postprocess_page` and is stored
in each page's ``extras["results"]``.

Output shape matches the polite scraper: ``data.seeds`` with ``pages`` rows
including ``extras``.

Module path:  nos.plugins.nodes.web_scraper.bs4_scrape
Class name:   BS4ScrapeNode
Node ID:      bs4_scrape

Register::

    reg node bs4_scrape BS4ScrapeNode nos.plugins.nodes.web_scraper.bs4_scrape

Execute::

    run node dev nos.plugins.nodes.web_scraper.bs4_scrape BS4ScrapeNode --sync --debug
"""

from typing import List, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .polite_scrape import (
    PoliteScrapeInputParams,
    PoliteScrapeMetadata,
    PoliteScrapeNode,
    PoliteScrapeOutput,
)


# =============================================================================
# Input / metadata
# =============================================================================


class BS4ScrapeInputParams(PoliteScrapeInputParams):
    """Polite crawl parameters plus CSS selector extraction (BeautifulSoup)."""

    selector: str = Field(default="p", description="CSS selector to match elements")
    attributes: List[str] = Field(
        default_factory=lambda: ["text"],
        description="Attributes to extract per element (e.g. href, src, text, class)",
    )
    limit: int = Field(default=100, ge=1, le=10000, description="Max matches per page")


class BS4ScrapeMetadata(PoliteScrapeMetadata):
    """Run summary including bs4 extraction settings."""

    selector: str = Field(default="", description="CSS selector used")
    attributes: List[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=10000)


# =============================================================================
# Node
# =============================================================================


class BS4ScrapeNode(PoliteScrapeNode):
    """Polite crawl with per-page BeautifulSoup parsing into ``extras``."""

    def __init__(self, node_id: str = "bs4_scrape", name: str = None):
        PoliteScrapeNode.__init__(self, node_id, name or "BS4 scrape")

    @property
    def input_params_schema(self):
        return BS4ScrapeInputParams

    @property
    def metadata_schema(self):
        return BS4ScrapeMetadata

    @property
    def output_schema(self):
        return PoliteScrapeOutput

    def _finalize_metadata(self, metadata: dict, params_dict: dict) -> dict:
        metadata = dict(metadata)
        metadata["selector"] = (params_dict.get("selector") or "p").strip() or "p"
        metadata["attributes"] = params_dict.get("attributes") or ["text"]
        metadata["limit"] = int(params_dict.get("limit", 100))
        return metadata

    def _postprocess_page(
        self,
        url: str,
        html: Optional[str],
        err: Optional[str],
        params_dict: dict,
    ) -> dict:
        if err or not html:
            return {}
        selector = (params_dict.get("selector") or "p").strip() or "p"
        attributes = params_dict.get("attributes") or ["text"]
        limit = int(params_dict.get("limit", 100))
        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(selector)[:limit]
        results = []
        for el in elements:
            item = {}
            for attr in attributes:
                if str(attr).lower() == "text":
                    item["text"] = el.get_text(strip=True)
                else:
                    val = el.get(attr)
                    item[str(attr)] = val if val is not None else ""
            results.append(item)
        return {"results": results}
