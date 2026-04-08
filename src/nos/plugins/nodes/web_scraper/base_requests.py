"""
HTTP GET via ``requests`` — returns the response body as text in ``output``.

For raw HTTP without robots or throttling, use this node; for polite scraping see
:mod:`polite_scrape`.

``output`` is a dict with ``response`` and ``error`` keys.

Module path:  ``nos.plugins.nodes.web_scraper.base_requests``
Class name:  ``BaseRequestsNode``
Node ID:     ``base_requests``

Register::

    reg node base_requests BaseRequestsNode nos.plugins.nodes.web_scraper.base_requests
"""

import requests
from pydantic import BaseModel, Field
from typing import Optional

from nos.core.engine.base import Node, NodeOutput


class BaseRequestsInputParams(BaseModel):
    """Input parameters for :class:`BaseRequestsNode`."""

    url: str = Field(default="https://example.com", description="URL to fetch")


class BaseRequestsOutput(BaseModel):
    """Validated shape of ``NodeOutput.output`` (``response`` / ``error``)."""

    response: str = Field(default="", description="Response body as text")
    error: str = Field(default="", description="Error message on failure")


class BaseRequestsNode(Node):
    """Single ``requests.get``; body in ``output['response']`` or error in ``output['error']``."""

    def __init__(self, node_id: str = "base_requests", name: Optional[str] = None):
        super().__init__(node_id, name or "Base requests")

    @property
    def input_state_schema(self):
        return None

    @property
    def input_params_schema(self):
        return BaseRequestsInputParams

    @property
    def output_schema(self):
        return BaseRequestsOutput

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        url = (params_dict.get("url") or "").strip()
        if not url:
            return NodeOutput(
                output={"response": "", "error": "url is required"},
                metadata={"node_id": self.node_id},
            )
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            return NodeOutput(
                output={"response": r.text, "error": ""},
                metadata={"node_id": self.node_id, "status_code": r.status_code},
            )
        except requests.RequestException as e:
            return NodeOutput(
                output={"response": "", "error": str(e)},
                metadata={"node_id": self.node_id},
            )


# Deprecated: pre-rename symbols
BaseFetchNode = BaseRequestsNode
BaseFetchInputParams = BaseRequestsInputParams
BaseFetchOutput = BaseRequestsOutput
RequestNode = BaseRequestsNode
RequestNodeInput = BaseRequestsInputParams
RequestNodeOutput = BaseRequestsOutput
