"""
Polite HTTP scrape — robots.txt, per-domain throttle, multi-seed JSON crawl.

================================================================================
MODULE CONTENTS
================================================================================
    * **Core** (registry, :func:`_domain_from_url`, :meth:`PoliteScrapeNode._fetch_one`).
    * :class:`PoliteScrapeNode` — JSON output (``urls`` seeds, BFS or sitemap);
      ``deep`` 0 or 1 = only the start URL(s). One seed + shallow depth is the
      usual substitute for a legacy single-URL HTML fetch.

================================================================================
CLI / REGISTRATION
================================================================================
    ::

        reg node polite_scrape PoliteScrapeNode nos.plugins.nodes.web_scraper.polite_scrape
"""

import json
import logging
import mimetypes
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse, unquote
from urllib.robotparser import RobotFileParser

import requests
from pydantic import BaseModel, Field, field_validator

# Package import when loaded as nos.* ; fallback adds repo src/ for CLI scripts.
try:
    from nos.core.engine.base import Node, NodeOutput, NodeInputSchema
    from nos.core.execution_log.event_log_buffer import CancellationError
except ImportError:
    import sys
    from pathlib import Path
    _src = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(_src))
    from nos.core.engine.base import Node, NodeOutput, NodeInputSchema
    from nos.core.execution_log.event_log_buffer import CancellationError

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Request registry: per-domain throttle (shared across instances)
# -----------------------------------------------------------------------------
# Structure (for each key = domain string from _domain_from_url):
#   {
#       "last_end": float | None,   # time.monotonic() when last request finished
#       "in_progress": bool,        # True while a request holds the domain slot
#   }
# Used by _wait_and_acquire_domain / _release_domain to enforce
# min_interval_seconds between calls to the same host across all node instances.
_request_registry: Dict[str, Dict[str, Any]] = {}
_registry_lock = threading.Lock()

DEFAULT_USER_AGENT = "NOSWebScraper/1.0 (+https://github.com/seedx-lab/n-os; polite scraper)"

DEFAULT_ANTI_BLOCK_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# =============================================================================
# URL utilities
# =============================================================================

def _domain_from_url(url: str) -> str:
    """
    Normalise URL to ``scheme://netloc`` for throttling and grouping.

    Args:
        url: Absolute HTTP(S) URL (fragments/query ignored for keying intent).

    Returns:
        Registry key string, e.g. ``"https://example.com"``. On parse failure,
        returns ``url`` unchanged (degraded behaviour).
    """
    try:
        p = urlparse(url)
        return (p.scheme or "http") + "://" + (p.netloc or "")
    except Exception:
        return url


def _origin_from_url(url: str) -> str:
    """
    Same value as :func:`_domain_from_url` — naming matches Web “origin” for
    same-origin link checks in the scraper subclass.
    """
    return _domain_from_url(url)


# =============================================================================
# Schemas (``urls`` only for the node form; no top-level ``url`` field)
# =============================================================================


def _split_seed_urls_string(s: str) -> List[str]:
    """Turn user/console string input into a list of URL strings (JSON array, comma-URLs, or single URL)."""
    s = (s or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        # Non-JSON bracket list (shell often strips quotes): [www.a.it,www.b.it] or [https://a,https://b]
        inner = s[1:-1].strip()
        if inner and '"' not in inner and "'" not in inner:
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            if parts:
                return parts
    if "," in s:
        parts = [p.strip().strip('"').strip("'") for p in s.split(",") if p.strip()]
        if len(parts) > 1:
            if all(p.startswith(("http://", "https://")) for p in parts):
                return parts
            # Bare hosts only (no path): www.a.it,www.b.it — avoid splitting URLs that contain commas in query
            if all(p and "/" not in p and "://" not in p for p in parts):
                return parts
    return [s] if s else []


class PoliteScrapeInputParams(NodeInputSchema):
    """Input for :class:`PoliteScrapeNode`. Seeds are **only** ``urls`` (see :meth:`PoliteScrapeNode._effective_seed_urls`)."""

    client: str = Field(
        default="requests",
        description="HTTP client: 'requests' or 'httpx'",
    )
    min_interval_seconds: float = Field(
        default=10.0,
        ge=0,
        le=300,
        description="Min seconds between requests to the same domain (anti-throttle)",
    )
    timeout: int = Field(
        default=15,
        ge=1,
        le=120,
        description="HTTP timeout in seconds",
    )
    extra_headers: Dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_ANTI_BLOCK_HEADERS),
        description="HTTP headers sent with every request. Shows anti-block defaults; override or add keys as needed.",
        json_schema_extra={"input_type": "json"},
    )
    urls: List[str] = Field(
        default_factory=lambda: ["https://example.com"],
        description="Start URLs (seeds); at least one non-empty entry required at run time; max 50.",
    )

    @field_validator("urls", mode="before")
    @classmethod
    def _coerce_urls(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return _split_seed_urls_string(v)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("urls")
    @classmethod
    def _max_seed_urls(cls, v: List[str]) -> List[str]:
        if len(v) > 50:
            raise ValueError("At most 50 seed URLs allowed in urls")
        return v

    deep: int = Field(
        default=1,
        ge=0,
        le=10,
        description="BFS depth for mode 'url': 0 or 1 = start URL only; >1 = follow same-origin links",
    )
    mode: str = Field(
        default="url",
        description="'url' = BFS from seed(s); 'site_map' = URLs from robots.txt sitemap(s)",
    )


class PoliteScrapePageItem(BaseModel):
    """One fetched page row inside ``output.data['seeds'][*].pages``."""

    url: str = Field(..., description="Requested URL")
    html: Optional[str] = Field(default=None, description="HTML content on success")
    error: Optional[str] = Field(default=None, description="Error message on failure")
    extras: dict = Field(
        default_factory=dict,
        description="Optional per-row payload from subclass hooks (e.g. parsed fields)",
    )


class PoliteScrapeSeedBucket(BaseModel):
    """One input seed and all pages fetched for that crawl branch."""

    url: str = Field(..., description="Normalised seed URL from input")
    pages: List[PoliteScrapePageItem] = Field(
        default_factory=list,
        description="Pages for this seed (may be empty if the seed crawl failed)",
    )


class PoliteScrapeOutput(BaseModel):
    """Shape of ``NodeOutput.output['data']`` for :class:`PoliteScrapeNode`."""

    seeds: List[PoliteScrapeSeedBucket] = Field(
        default_factory=list,
        description="Per-seed buckets: each seed's pages and global counters below",
    )
    total_pages: int = Field(default=0, description="Total pages attempted (success + error)")
    total_success: int = Field(default=0, description="Pages fetched successfully")
    total_errors: int = Field(default=0, description="Pages that failed")
    errors_trace: List[str] = Field(
        default_factory=list,
        description="Concise error messages for debugging",
    )


class PoliteScrapeMetadata(BaseModel):
    """Per-run scrape summary (``metadata=`` in :meth:`PoliteScrapeNode._do_execute`)."""

    url: str = Field(default="", description="First seed URL (primary)")
    seed_urls: List[str] = Field(
        default_factory=list,
        description="All seed URLs used in this run",
    )
    mode: str = Field(default="", description="url | site_map")
    client: str = Field(default="", description="requests | httpx")
    deep: int = Field(default=1, description="Depth parameter (0/1 = single page per seed in url mode)")
    total_pages: int = Field(default=0, description="Total pages scraped")
    total_success: int = Field(default=0, description="Successful fetches")
    total_errors: int = Field(default=0, description="Failed fetches")
    robots_allowed: bool = Field(default=True, description="Whether robots.txt allowed scraping")
    crawl_delay_used: Optional[float] = Field(
        default=None, description="Crawl-Delay from robots.txt if any"
    )
    error: str = Field(default="", description="Top-level error if execution failed")


# =============================================================================
# Node
# =============================================================================


class _PoliteScrapeHTTPMixin:
    """Shared HTTP / robots / throttle helpers used by :class:`PoliteScrapeNode`."""

    def _wait_and_acquire_domain(self, domain: str, min_interval_seconds: float) -> None:
        """
        Block until this **domain** may start a new request (fairness + politeness).

        Behaviour (under ``_registry_lock``):
            1. If another caller holds ``in_progress`` or ``last_end`` is too recent,
               compute ``wait`` and ``time.sleep`` (capped at 60s per wait slice).
            2. Spin briefly (0.5s sleeps) while ``in_progress`` remains True.
            3. Set ``in_progress=True``, ``last_end=None`` for this domain.

        Args:
            domain: Key from :func:`_domain_from_url`.
            min_interval_seconds: Minimum spacing **after** previous request ended.

        Note:
            Must be paired with :meth:`_release_domain` in a ``try``/``finally``.
        """
        with _registry_lock:
            now = time.monotonic()
            entry = _request_registry.get(domain)
            if entry:
                last_end = entry.get("last_end")
                if entry.get("in_progress") or (
                    last_end is not None and (now - last_end) < min_interval_seconds
                ):
                    if last_end is not None:
                        wait = min_interval_seconds - (now - last_end)
                        if wait > 0:
                            time.sleep(min(wait, 60.0))
                    while entry and entry.get("in_progress"):
                        time.sleep(0.5)
                        entry = _request_registry.get(domain)
            _request_registry[domain] = {"last_end": None, "in_progress": True}

    def _release_domain(self, domain: str) -> None:
        """
        Mark **domain** idle and record ``last_end = time.monotonic()``.

        Args:
            domain: Same key used in :meth:`_wait_and_acquire_domain`.
        """
        with _registry_lock:
            entry = _request_registry.get(domain)
            if entry:
                entry["last_end"] = time.monotonic()
                entry["in_progress"] = False

    # -------------------------------------------------------------------------
    # Robots.txt
    # -------------------------------------------------------------------------

    def _get_robots_parser(
        self, origin: str, headers: dict, timeout: int
    ) -> Optional[RobotFileParser]:
        """
        Load ``{origin}/robots.txt`` once per **instance** and cache parser.

        Args:
            origin: ``scheme://netloc``.
            headers: Forwarded to ``requests.get`` (typically includes User-Agent).
            timeout: Network timeout for robots fetch.

        Returns:
            Configured :class:`~urllib.robotparser.RobotFileParser`. If download
            fails, returns a parser built from **empty rules** (permissive fallback).

        Side effects:
            Mutates ``self._robots_cache[origin]``.
        """
        if origin in self._robots_cache:
            return self._robots_cache[origin]
        robots_url = urljoin(origin + "/", "/robots.txt")
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            req = requests.get(robots_url, headers=headers, timeout=timeout)
            req.raise_for_status()
            rp.parse(req.text.splitlines())
        except Exception as e:
            logger.debug("robots.txt unavailable for %s: %s", origin, e)
            rp.parse([])  # permissive when robots.txt is unreachable
        self._robots_cache[origin] = rp
        return rp

    def _can_fetch_and_delay(
        self, url: str, user_agent: str, headers: dict, timeout: int
    ) -> Tuple[bool, float]:
        """
        Query robots rules for **url** and derive an extra delay (seconds).

        Returns:
            Tuple ``(allowed, delay_seconds)``:
                * ``allowed`` — ``rp.can_fetch(user_agent, url)``.
                * ``delay_seconds`` — ``crawl_delay(user_agent)`` if set, else
                  ``request_rate.seconds / request_rate.requests`` when available,
                  else ``0.0``.

        Note:
            ``delay_seconds`` is applied **inside** :meth:`_fetch_one` **after**
            the domain registry wait (both stack for politeness).
        """
        origin = _origin_from_url(url)
        rp = self._get_robots_parser(origin, headers, timeout)
        if rp is None:
            return True, 0.0
        allowed = rp.can_fetch(user_agent, url)
        delay = 0.0
        try:
            crawl_delay = rp.crawl_delay(user_agent)
            if crawl_delay is not None and crawl_delay > 0:
                delay = float(crawl_delay)
            else:
                rr = rp.request_rate(user_agent)
                if rr is not None and rr.seconds > 0 and rr.requests > 0:
                    delay = rr.seconds / rr.requests
        except Exception:
            pass
        return allowed, delay

    # -------------------------------------------------------------------------
    # HTTP: requests + _smart_fetch
    # -------------------------------------------------------------------------

    def _smart_fetch(
        self,
        url: str,
        timeout: int = 10,
        headers: Optional[dict] = None,
    ) -> Tuple[Union[bytes, str], dict]:
        """
        Low-level GET using ``requests``: classify body as text or binary.

        Returns:
            * **data** — ``str`` (decoded text) or ``bytes`` (binary).
            * **meta** — dict with ``url``, ``filename``, ``content_type``,
              ``is_text``, ``size_bytes``, ``status_code``.

        Raises:
            requests.HTTPError: Via ``raise_for_status()`` on non-2xx.

        Note:
            Heuristic: ``Content-Type`` sniff + NUL-byte scan on first 1 KiB
            to guess text when header is ambiguous.
        """
        h = dict(DEFAULT_ANTI_BLOCK_HEADERS)
        if headers:
            h.update(headers)
        r = requests.get(url, timeout=timeout, headers=h)
        r.raise_for_status()

        content_type = (r.headers.get("Content-Type") or "").lower()
        content_disp = r.headers.get("Content-Disposition", "")

        filename = None
        match = re.search(r'filename="?([^"]+)"?', content_disp)
        if match:
            filename = match.group(1)
        if not filename:
            try:
                parsed = urlparse(url)
                path = unquote(parsed.path or "").strip("/")
                if path and "." in path.split("/")[-1]:
                    filename = path.split("/")[-1]
            except Exception:
                pass
        if not filename:
            mime = (content_type.split(";")[0] or "").strip()
            ext = mimetypes.guess_extension(mime) or ".bin"
            filename = "download" + ext

        is_text = any(x in content_type for x in ["text/", "json", "xml", "javascript"])
        if not is_text and b"\x00" not in (r.content[:1024] or b""):
            is_text = True

        if is_text:
            r.encoding = r.encoding or "utf-8"
            data: Union[str, bytes] = r.text
        else:
            data = r.content

        meta = {
            "url": url,
            "filename": filename,
            "content_type": content_type,
            "is_text": is_text,
            "size_bytes": len(r.content),
            "status_code": r.status_code,
        }
        return data, meta

    def _fetch_with_requests(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: int = 15,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Adapter: :meth:`_smart_fetch` → HTML string suitable for scraping.

        Returns:
            ``(html, None)`` on success; ``(None, error_message)`` if response is
            treated as binary or on network/HTTP errors.
        """
        try:
            data, meta = self._smart_fetch(url, timeout=timeout, headers=headers or {})
            if not meta.get("is_text", True):
                return None, "Binary content not supported"
            return (data if isinstance(data, str) else data.decode("utf-8", errors="replace")), None
        except requests.RequestException as e:
            return None, f"HTTP error: {e}"
        except Exception as e:
            return None, str(e)

    def _fetch_with_httpx(
        self,
        url: str,
        headers: Optional[dict] = None,
        timeout: int = 15,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Same contract as :meth:`_fetch_with_requests` using ``httpx.Client``.

        Returns:
            ``(None, "httpx not installed")`` if import fails; otherwise
            ``(text, None)`` or ``(None, error)``.

        Note:
            Stricter content-type check than ``_smart_fetch`` path — rejects
            obvious non-text types early.
        """
        try:
            import httpx
        except ImportError:
            return None, "httpx not installed"

        h = dict(DEFAULT_ANTI_BLOCK_HEADERS)
        if headers:
            h.update(headers)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(url, headers=h)
                r.raise_for_status()
                ct = (r.headers.get("content-type") or "").lower()
                if not any(x in ct for x in ["text/", "json", "xml", "javascript"]):
                    return None, "Binary or non-HTML content not supported"
                return r.text, None
        except httpx.HTTPStatusError as e:
            return None, f"HTTP {e.response.status_code}: {e}"
        except Exception as e:
            return None, str(e)

    # -------------------------------------------------------------------------
    # High-level: fetch one URL with polite throttle + registry
    # -------------------------------------------------------------------------

    def _fetch_one(
        self,
        url: str,
        client: str,
        headers: dict,
        timeout: int,
        min_interval_seconds: float,
        user_agent: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        **Single** end-to-end fetch — used by crawl loops on this node.

        Pipeline:
            1. ``_can_fetch_and_delay`` → early exit if disallowed.
            2. ``_wait_and_acquire_domain`` → honour ``min_interval_seconds``.
            3. Optional ``time.sleep(crawl_delay)`` from robots.
            4. Delegate to ``_fetch_with_httpx`` or ``_fetch_with_requests``.
            5. ``finally``: ``_release_domain``.

        Args:
            url: Full HTTP(S) URL.
            client: ``"httpx"`` or ``"requests"``.
            headers: Merged anti-block + user ``extra_headers``.
            timeout: Per-request timeout.
            min_interval_seconds: Registry spacing for this domain.
            user_agent: Robots ``User-Agent`` string (from headers).

        Returns:
            ``(html, error, crawl_delay_used)`` where ``crawl_delay_used`` is
            the robots delay **if** it was > 0 (for metadata); else ``None``.
        """
        ch = getattr(self, "_exec_log", None)
        if ch is not None and ch.is_stop_requested():
            raise CancellationError("Scrape interrupted (stop requested before fetch)")

        domain = _domain_from_url(url)
        allowed, crawl_delay = self._can_fetch_and_delay(url, user_agent, headers, timeout)
        if not allowed:
            return None, "Disallowed by robots.txt", None

        self._wait_and_acquire_domain(domain, min_interval_seconds)
        try:
            if crawl_delay > 0:
                time.sleep(crawl_delay)
            if client == "httpx":
                html, err = self._fetch_with_httpx(url, headers=headers, timeout=timeout)
            else:
                html, err = self._fetch_with_requests(url, headers=headers, timeout=timeout)
            return html, err, crawl_delay if crawl_delay > 0 else None
        finally:
            self._release_domain(domain)


class PoliteScrapeNode(Node, _PoliteScrapeHTTPMixin):
    """
    Polite multi-seed HTTP scrape: robots + throttle via :meth:`_fetch_one`,
    JSON ``output`` with ``seeds`` buckets.

    Per-URL failures are non-fatal (:meth:`_on_fetch_error` logs only). Per-seed
    exceptions yield an empty ``pages`` list for that seed.
    """

    @property
    def default_output_format(self) -> str:
        return "json"

    def __init__(self, node_id: str = "polite_scrape", name: str = None):
        super().__init__(node_id, name or "Polite scrape")
        self._robots_cache: Dict[str, RobotFileParser] = {}

    @property
    def input_state_schema(self):
        return None

    @property
    def input_params_schema(self):
        return PoliteScrapeInputParams

    @property
    def output_schema(self):
        return PoliteScrapeOutput

    @property
    def metadata_schema(self):
        return PoliteScrapeMetadata

    def _on_fetch_error(self, url: str, error: str) -> None:
        self.exec_log.log("warning", event="fetch error", message=f"Fetch failed: {url} — {error}")

    def _collect_links_same_origin(
        self, html: str, current_url: str, limit: int = 500
    ) -> List[str]:
        from html.parser import HTMLParser

        origin = _origin_from_url(current_url)
        seen = set()
        out: List[str] = []

        class LinkParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag.lower() != "a":
                    return
                for k, v in attrs:
                    if k and k.lower() == "href" and v:
                        try:
                            full = urljoin(current_url, v.strip())
                            if (
                                full.startswith(("http://", "https://"))
                                and _origin_from_url(full) == origin
                                and full not in seen
                                and len(out) < limit
                            ):
                                seen.add(full)
                                out.append(full)
                        except Exception:
                            pass

        try:
            LinkParser().feed(html)
        except Exception:
            pass
        return out[:limit]

    def _run_mode_url(
        self,
        start_url: str,
        deep: int,
        client: str,
        headers: dict,
        timeout: int,
        min_interval_seconds: float,
        user_agent: str,
    ):
        """BFS crawl; ``deep`` is already normalised to >= 1."""
        to_visit: List[Tuple[str, int]] = [(start_url, 0)]
        seen = {start_url}
        fetched = 0
        max_pages = 500

        while to_visit and fetched < max_pages:
            url, depth_now = to_visit.pop(0)
            html, err, crawl_delay = self._fetch_one(
                url, client, headers, timeout, min_interval_seconds, user_agent
            )
            fetched += 1
            yield url, html, err, crawl_delay

            if err or not html or depth_now >= deep - 1:
                continue
            for link in self._collect_links_same_origin(html, url):
                if link not in seen:
                    seen.add(link)
                    to_visit.append((link, depth_now + 1))

    def _fetch_sitemap_urls(
        self, sitemap_url: str, headers: dict, timeout: int
    ) -> List[str]:
        try:
            r = requests.get(sitemap_url, headers=headers, timeout=timeout)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception:
            return []

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls: List[str] = []
        for loc in root.findall(".//sm:url/sm:loc", ns):
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        for loc in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        if not urls:
            for loc in root.findall(".//loc"):
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
        return urls

    def _urls_for_mode_sitemap(
        self, start_url: str, headers: dict, timeout: int
    ) -> List[str]:
        origin = _origin_from_url(start_url)
        rp = self._get_robots_parser(origin, headers, timeout)
        if rp is None:
            return []
        sitemaps = (
            rp.site_maps()
            if hasattr(rp, "site_maps") and callable(rp.site_maps)
            else []
        )
        if not sitemaps:
            return []
        all_urls: List[str] = []
        for sm_url in sitemaps[:20]:
            all_urls.extend(self._fetch_sitemap_urls(sm_url, headers, timeout))
        return list(dict.fromkeys(all_urls))[:1000]

    @staticmethod
    def _normalise_http_url(raw: str) -> str:
        u = (raw or "").strip()
        if not u:
            raise ValueError("empty URL")
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        return u

    def _effective_seed_urls(self, params_dict: dict) -> List[str]:
        raw_list = params_dict.get("urls")
        if raw_list is None:
            raw_list = []
        if isinstance(raw_list, str):
            raw_list = _split_seed_urls_string(raw_list)
        seeds: List[str] = []
        for x in raw_list:
            s = str(x).strip()
            if not s:
                continue
            seeds.append(self._normalise_http_url(s))
        if not seeds:
            raise ValueError("urls must contain at least one non-empty URL")
        if len(seeds) > 50:
            raise ValueError("At most 50 seed URLs allowed")
        return seeds

    def _finalize_metadata(self, metadata: dict, params_dict: dict) -> dict:
        return metadata

    def _postprocess_page(
        self,
        url: str,
        html: Optional[str],
        err: Optional[str],
        params_dict: dict,
    ) -> dict:
        return {}

    def _make_page_item(
        self,
        u: str,
        html: Optional[str],
        err: Optional[str],
        params_dict: dict,
    ) -> PoliteScrapePageItem:
        extras = self._postprocess_page(u, html, err, params_dict)
        if not isinstance(extras, dict):
            extras = {}
        return PoliteScrapePageItem(
            url=u,
            html=None if err else html,
            error=err,
            extras=extras,
        )

    def _crawl_one_seed(
        self,
        start_url: str,
        mode: str,
        bfs_deep: int,
        client: str,
        headers: dict,
        timeout: int,
        min_interval_seconds: float,
        user_agent: str,
        params_dict: dict,
    ) -> Tuple[List[PoliteScrapePageItem], List[str], int, int, Optional[float]]:
        errors_trace: List[str] = []
        pages: List[PoliteScrapePageItem] = []
        total_success = 0
        total_errors = 0
        crawl_delay_used: Optional[float] = None

        if mode == "site_map":
            urls_to_fetch = self._urls_for_mode_sitemap(start_url, headers, timeout) or [
                start_url
            ]
            for u in urls_to_fetch:
                html, err, delay = self._fetch_one(
                    u, client, headers, timeout, min_interval_seconds, user_agent
                )
                if delay is not None:
                    crawl_delay_used = delay
                if err:
                    total_errors += 1
                    errors_trace.append(f"{u}: {err}")
                    pages.append(self._make_page_item(u, html, err, params_dict))
                    self._on_fetch_error(u, err)
                else:
                    total_success += 1
                    pages.append(self._make_page_item(u, html, None, params_dict))
                    self.exec_log.log(
                        "info",
                        event="fetch success",
                        message=f"Fetched {u} ({len(html or '')} chars)",
                    )
        else:
            for u, html, err, delay in self._run_mode_url(
                start_url,
                bfs_deep,
                client,
                headers,
                timeout,
                min_interval_seconds,
                user_agent,
            ):
                if delay is not None:
                    crawl_delay_used = delay
                if err:
                    total_errors += 1
                    errors_trace.append(f"{u}: {err}")
                    pages.append(self._make_page_item(u, html, err, params_dict))
                    self._on_fetch_error(u, err)
                else:
                    total_success += 1
                    pages.append(self._make_page_item(u, html, None, params_dict))
                    self.exec_log.log(
                        "info",
                        event="fetch success",
                        message=f"Fetched {u} ({len(html or '')} chars)",
                    )

        return pages, errors_trace, total_success, total_errors, crawl_delay_used

    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        seeds = self._effective_seed_urls(params_dict)

        raw_deep = int(params_dict.get("deep", 1))
        bfs_deep = max(1, raw_deep)
        client = (params_dict.get("client") or "requests").strip().lower()
        if client not in ("requests", "httpx"):
            client = "requests"
        mode = (params_dict.get("mode") or "url").strip().lower()
        if mode not in ("url", "site_map"):
            mode = "url"
        min_interval_seconds = float(params_dict.get("min_interval_seconds", 10.0))
        timeout = int(params_dict.get("timeout", 15))
        extra_headers = params_dict.get("extra_headers") or {}
        headers = {**DEFAULT_ANTI_BLOCK_HEADERS, **extra_headers}
        user_agent = headers.get("User-Agent", DEFAULT_USER_AGENT)

        errors_trace: List[str] = []
        seed_buckets: List[PoliteScrapeSeedBucket] = []
        total_success = 0
        total_errors = 0
        crawl_delay_used: Optional[float] = None

        for seed in seeds:
            try:
                pages, local_trace, ts, te, delay = self._crawl_one_seed(
                    seed,
                    mode,
                    bfs_deep,
                    client,
                    headers,
                    timeout,
                    min_interval_seconds,
                    user_agent,
                    params_dict,
                )
                errors_trace.extend(local_trace)
                total_success += ts
                total_errors += te
                if delay is not None:
                    crawl_delay_used = delay
                seed_buckets.append(PoliteScrapeSeedBucket(url=seed, pages=pages))
            except Exception as e:
                msg = str(e)
                self.exec_log.log(
                    "warning",
                    event="seed crawl failed",
                    message=f"Seed crawl failed: {seed} — {msg}",
                )
                errors_trace.append(f"{seed}: {msg}")
                seed_buckets.append(PoliteScrapeSeedBucket(url=seed, pages=[]))

        total_pages = total_success + total_errors
        metadata = {
            "url": seeds[0] if seeds else "",
            "seed_urls": seeds,
            "mode": mode,
            "client": client,
            "deep": raw_deep,
            "total_pages": total_pages,
            "total_success": total_success,
            "total_errors": total_errors,
            "robots_allowed": True,
            "crawl_delay_used": crawl_delay_used,
            "error": "",
        }
        metadata = self._finalize_metadata(metadata, params_dict)

        return NodeOutput(
            output={
                "output_format": "json",
                "data": {
                    "seeds": [b.model_dump() for b in seed_buckets],
                    "total_pages": total_pages,
                    "total_success": total_success,
                    "total_errors": total_errors,
                    "errors_trace": errors_trace,
                },
            },
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Deprecated aliases (pre-rename web scraper symbols)
# ---------------------------------------------------------------------------
BaseWebScraperNode = PoliteScrapeNode
BaseWebScraperInputParams = PoliteScrapeInputParams
BaseWebScraperOutput = PoliteScrapeOutput
BaseWebScraperMetadata = PoliteScrapeMetadata
BaseWebScraperSeedBucket = PoliteScrapeSeedBucket
PageResultItem = PoliteScrapePageItem


if __name__ == "__main__":
    node = PoliteScrapeNode()
    result = node.execute(
        state={},
        input_params={
            "urls": ["https://example.com"],
            "client": "requests",
            "mode": "url",
            "deep": 0,
        },
    )
    print("PoliteScrapeNode", result.execution_id, result.status)
