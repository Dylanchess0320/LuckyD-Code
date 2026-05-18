"""Web search and fetch tools.

WebFetch — fetches a URL and extracts readable text. Auto-detects
YouTube/oEmbed content and falls back to structured metadata when a
page is JS-rendered (returns very little text).

WebSearch — searches the web with multi-provider fallback:
  1. DuckDuckGo HTML (fastest, but increasingly rate-limited)
  2. DuckDuckGo Instant Answer API (encyclopedic results, always works)
  3. SearXNG public instance (full web search, may rate-limit)
"""

import re
from urllib.parse import quote as url_quote

import httpx
from bs4 import BeautifulSoup

from .registry import Tool

# ── helpers ──────────────────────────────────────────────────────────────────

_YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)
_MIN_MEANINGFUL_CHARS = 200  # below this, page is probably JS-rendered boilerplate

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Platforms where we should always prefer oEmbed over scraping
_OEMBED_PLATFORMS = [
    _YOUTUBE_RE,
    re.compile(r"(?:https?://)?(?:www\.)?vimeo\.com/", re.IGNORECASE),
]


def _extract_text(html: str) -> str:
    """Extract readable text from HTML, stripping boilerplate."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    # Also strip common invisible elements
    for tag in soup.select("[aria-hidden=true], [hidden], .hidden, .invisible"):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _try_meta_extraction(html: str) -> str | None:
    """Try to extract useful metadata when main content is JS-rendered."""
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    title = soup.find("title")
    if title and title.get_text(strip=True):
        parts.append(f"Title: {title.get_text(strip=True)}")

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = meta.get("content", "")
        if not content:
            continue
        if name in ("description",) or prop in ("og:description",):
            parts.append(f"Description: {content[:500]}")
        elif prop == "og:title":
            parts.append(f"OG Title: {content[:200]}")
        elif prop == "og:site_name":
            parts.append(f"Site: {content[:100]}")

    return "\n".join(parts) if parts else None


def _try_oembed(url: str) -> str | None:
    """Try to get structured content via oEmbed (YouTube, Vimeo, etc.)."""
    try:
        # Build oEmbed URL with httpx's params support (handles encoding correctly)
        oembed_url = "https://www.youtube.com/oembed"
        resp = httpx.get(
            oembed_url,
            params={"url": url, "format": "json"},
            headers={"User-Agent": _UA},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            title = data.get("title", "")
            author = data.get("author_name", "")
            return (
                f"[YouTube] {title}\n"
                f"  Channel: {author}\n"
                f"  URL: {url}"
            )
    except Exception:
        pass
    return None


# ── WebFetch ─────────────────────────────────────────────────────────────────


class WebFetchTool(Tool):
    name = "WebFetch"
    description = "Fetch content from a URL and extract its text content."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
        },
        "required": ["url"],
    }

    def run(self, url: str) -> str:  # pragma: no cover
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _UA},
                follow_redirects=True,
                timeout=30,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")

            if "text/html" in content_type:
                text = _extract_text(response.text)

                # Always try oEmbed for known platforms (YouTube, Vimeo) —
                # their SSR HTML is pure boilerplate
                for pattern in _OEMBED_PLATFORMS:
                    if pattern.search(url):
                        oembed = _try_oembed(url)
                        if oembed:
                            return oembed

                # Detect JS-rendered pages that returned almost nothing
                if len(text) < _MIN_MEANINGFUL_CHARS:

                    # Try meta tags as fallback
                    meta = _try_meta_extraction(response.text)
                    tip = (
                        "\n\n[Page is JavaScript-rendered — extracted metadata above. "
                        "Use BrowserNavigate for full interactive content.]"
                    )
                    if meta:
                        return meta + tip

                    return (
                        f"[Page content ({len(text)} chars)]\n{text}"
                        + tip
                    )

                if len(text) > 15000:
                    text = text[:15000] + f"\n... (truncated, {len(text)} total chars)"
                return text

            # Non-HTML: return plain text
            text = response.text
            if len(text) > 15000:
                text = text[:15000] + f"\n... (truncated, {len(text)} total chars)"
            return text

        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code}: {e.response.text[:500]}"
        except Exception as e:
            return f"Error fetching URL: {e}"


# ── WebSearch ────────────────────────────────────────────────────────────────


class WebSearchTool(Tool):
    name = "WebSearch"
    description = "Search the web and get results."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
        },
        "required": ["query"],
    }

    def run(self, query: str) -> str:  # pragma: no cover
        errors: list[str] = []

        # ── provider 1: DuckDuckGo HTML (real web results, may be rate-limited) ─
        result = self._search_ddg_html(query)
        if result:
            return result
        errors.append("DDG HTML: blocked (CAPTCHA) or empty")

        # ── provider 2: DuckDuckGo Instant Answer API (encyclopedic, always works but
        #    only returns results for factual/wiki-style queries) ─────────────────
        result = self._search_ddg_api(query)
        if result:
            return result
        errors.append("DDG API: no encyclopedic match for this query")

        # ── provider 3: SearXNG public instances ─────────────────────────────────
        result = self._search_searxng(query)
        if result:
            return result
        errors.append("SearXNG: all public instances unavailable")

        return (
            f"No results found for '{query}'.\n\n"
            f"Search providers tried:\n  • "
            + "\n  • ".join(errors)
            + "\n\n"
            "Try one of these instead:\n"
            "  • Use BrowserNavigate to search youtube.com, google.com, etc.\n"
            "  • Use WebFetch on a known URL directly\n"
            "  • Try a broader/alternate query (the DDG API works best for\n"
            "    factual, encyclopedia-style queries like 'chill out music')"
        )

    # ── provider implementations ───────────────────────────────────────────

    @staticmethod
    def _search_ddg_api(query: str) -> str | None:  # pragma: no cover
        """DuckDuckGo Instant Answer API — encyclopedic / topic results."""
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1"},
                headers={"User-Agent": _UA},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            results: list[str] = []

            # Abstract / primary answer
            abstract = data.get("AbstractText", "")
            if abstract:
                heading = data.get("Heading", "")
                src_url = data.get("AbstractURL", "")
                results.append(f"📖 {heading}\n{abstract[:500]}\nSource: {src_url}")

            # Related topics as search-like results
            related = data.get("RelatedTopics", [])
            for topic in related[:8]:
                text = topic.get("Text", "")
                if text:
                    # DDG wraps with <a href="...">text</a>
                    text_clean = re.sub(r"<[^>]+>", "", text)
                    first_url = topic.get("FirstURL", "")
                    if first_url:
                        results.append(f"{text_clean[:200]}\n  URL: {first_url}")
                    else:
                        results.append(text_clean[:200])

            # Infobox
            infobox = data.get("Infobox", {})
            if infobox.get("content"):
                for item in infobox["content"][:5]:
                    label = item.get("label", "")
                    value = item.get("value", "")
                    results.append(f"{label}: {value[:200]}")

            if results:
                # If we only have the abstract and nothing else useful
                total_text = "\n\n".join(results)
                if len(total_text) > 50:
                    return "Results from DuckDuckGo:\n\n" + total_text

            return None
        except Exception:
            return None

    @staticmethod
    def _search_ddg_html(query: str) -> str | None:  # pragma: no cover
        """DuckDuckGo HTML search — full web results, but often rate-limited."""
        try:
            resp = httpx.get(
                f"https://html.duckduckgo.com/html/?q={url_quote(query)}",
                headers={"User-Agent": _UA},
                follow_redirects=True,
                timeout=30,
            )

            # HTTP 202 means DDG served a CAPTCHA — total block
            if resp.status_code == 202:
                return None

            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Check for CAPTCHA in body
            body_text = soup.body.get_text(" ", strip=True) if soup.body else ""
            if "please complete the following challenge" in body_text.lower():
                return None

            # Try multiple selector patterns (DDG changes these occasionally)
            results: list[str] = []
            result_blocks = (
                soup.select(".result")
                or soup.select(".web-result")
                or soup.select(".links_main a.result-link")
            )

            if not result_blocks:
                return None

            for block in result_blocks[:10]:
                title_el = (
                    block.select_one(".result__title a")
                    or block.select_one(".result__a")
                    or block.find("a", class_=re.compile("result"))
                )
                snippet_el = (
                    block.select_one(".result__snippet")
                    or block.select_one(".result__extract")
                )

                if title_el:
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")  # type: ignore[union-attr]
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append(f"{title}\n  URL: {link}\n  {snippet}")

            if not results:
                return None

            return "Results from DuckDuckGo:\n\n" + "\n\n".join(results)
        except Exception:
            return None

    @staticmethod
    def _search_searxng(query: str) -> str | None:  # pragma: no cover
        """SearXNG public instance — metasearch engine."""
        searxng_instances = [
            "https://search.sapti.me",
            "https://searx.be",
            "https://search.bus-hit.me",
        ]
        for base_url in searxng_instances:
            try:
                resp = httpx.get(
                    f"{base_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "categories": "general",
                    },
                    headers={"User-Agent": _UA},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                web_results = data.get("results", [])
                if not web_results:
                    continue

                lines: list[str] = []
                for r in web_results[:10]:
                    title = r.get("title", "").strip()
                    url = r.get("url", "").strip()
                    snippet = (r.get("content", "") or r.get("snippet", "")).strip()
                    lines.append(f"{title}\n  URL: {url}\n  {snippet[:300]}")

                return f"Results from SearXNG ({base_url}):\n\n" + "\n\n".join(lines)
            except Exception:
                continue
        return None
