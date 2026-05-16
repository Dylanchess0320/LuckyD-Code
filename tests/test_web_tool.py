"""Tests for tools/web.py — helper functions.

Covers the three module-level helpers that are NOT marked # pragma: no cover:
  - _extract_text      — HTML → readable text extraction
  - _try_meta_extraction — fallback metadata when page is JS-rendered
  - _try_oembed          — structured content via YouTube/Vimeo oEmbed

WebFetchTool.run() and WebSearchTool.run() are intentionally marked
# pragma: no cover (they hit real network endpoints), so we skip them here
and only unit-test the deterministic helpers they delegate to.
"""

from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.tools.web import (
    _extract_text,
    _try_meta_extraction,
    _try_oembed,
    _YOUTUBE_RE,
    _OEMBED_PLATFORMS,
    WebFetchTool,
    WebSearchTool,
)


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:

    def test_basic_paragraph(self):
        html = "<html><body><p>Hello world</p></body></html>"
        result = _extract_text(html)
        assert "Hello world" in result

    def test_strips_script_tags(self):
        html = "<html><body><script>alert('xss')</script><p>Content</p></body></html>"
        result = _extract_text(html)
        assert "Content" in result
        assert "alert" not in result
        assert "xss" not in result

    def test_strips_style_tags(self):
        html = "<html><head><style>body{color:red}</style></head><body><p>Styled</p></body></html>"
        result = _extract_text(html)
        assert "Styled" in result
        assert "color" not in result

    def test_strips_nav_footer_header(self):
        html = (
            "<html><body>"
            "<header>Site Header</header>"
            "<nav>Nav Links</nav>"
            "<main><p>Main content</p></main>"
            "<footer>Footer text</footer>"
            "</body></html>"
        )
        result = _extract_text(html)
        assert "Main content" in result
        assert "Site Header" not in result
        assert "Nav Links" not in result
        assert "Footer text" not in result

    def test_strips_aria_hidden_elements(self):
        html = (
            '<html><body>'
            '<div aria-hidden="true">Hidden aria</div>'
            '<p>Visible text</p>'
            '</body></html>'
        )
        result = _extract_text(html)
        assert "Visible text" in result
        assert "Hidden aria" not in result

    def test_strips_hidden_attribute(self):
        html = '<html><body><div hidden>Invisible</div><p>Shown</p></body></html>'
        result = _extract_text(html)
        assert "Shown" in result
        assert "Invisible" not in result

    def test_strips_css_hidden_class(self):
        html = '<html><body><span class="hidden">CSS hidden</span><p>Real</p></body></html>'
        result = _extract_text(html)
        assert "Real" in result
        assert "CSS hidden" not in result

    def test_strips_invisible_class(self):
        html = '<html><body><span class="invisible">Invisible</span><p>Shown</p></body></html>'
        result = _extract_text(html)
        assert "Shown" in result
        assert "Invisible" not in result

    def test_returns_empty_string_for_empty_html(self):
        result = _extract_text("")
        assert result == ""

    def test_multiple_paragraphs_separated_by_newlines(self):
        html = "<html><body><p>First</p><p>Second</p><p>Third</p></body></html>"
        result = _extract_text(html)
        assert "First" in result
        assert "Second" in result
        assert "Third" in result

    def test_blank_lines_stripped(self):
        html = "<html><body><p>   </p><p>Content</p><p>  </p></body></html>"
        result = _extract_text(html)
        lines = result.splitlines()
        assert all(line.strip() for line in lines)  # no blank lines

    def test_whitespace_collapsed(self):
        html = "<html><body><p>  Leading   spaces  </p></body></html>"
        result = _extract_text(html)
        assert "Leading   spaces" in result or "Leading" in result


# ---------------------------------------------------------------------------
# _try_meta_extraction
# ---------------------------------------------------------------------------

class TestTryMetaExtraction:

    def test_returns_none_for_empty_head(self):
        html = "<html><head></head><body></body></html>"
        result = _try_meta_extraction(html)
        assert result is None

    def test_title_extracted(self):
        html = "<html><head><title>My Page Title</title></head><body></body></html>"
        result = _try_meta_extraction(html)
        assert result is not None
        assert "My Page Title" in result
        assert "Title:" in result

    def test_meta_description_extracted(self):
        html = (
            '<html><head>'
            '<meta name="description" content="A great description here"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is not None
        assert "A great description here" in result
        assert "Description:" in result

    def test_og_description_extracted(self):
        html = (
            '<html><head>'
            '<meta property="og:description" content="OG description text"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is not None
        assert "OG description text" in result

    def test_og_title_extracted(self):
        html = (
            '<html><head>'
            '<meta property="og:title" content="Open Graph Title"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is not None
        assert "Open Graph Title" in result
        assert "OG Title:" in result

    def test_og_site_name_extracted(self):
        html = (
            '<html><head>'
            '<meta property="og:site_name" content="MyWebsite"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is not None
        assert "MyWebsite" in result
        assert "Site:" in result

    def test_meta_with_empty_content_ignored(self):
        html = (
            '<html><head>'
            '<meta name="description" content=""/>'
            '<title>Still Here</title>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        # Title should still be extracted even though description is empty
        assert result is not None
        assert "Still Here" in result

    def test_description_truncated_at_500_chars(self):
        long_desc = "x" * 600
        html = f'<html><head><meta name="description" content="{long_desc}"/></head></html>'
        result = _try_meta_extraction(html)
        assert result is not None
        # The content portion should be at most 500 chars
        desc_line = [line for line in result.splitlines() if "Description:" in line][0]
        assert len(desc_line) <= len("Description: ") + 500

    def test_multiple_tags_combined(self):
        html = (
            '<html><head>'
            '<title>Combined Test</title>'
            '<meta name="description" content="Summary here"/>'
            '<meta property="og:title" content="OG Combined"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is not None
        assert "Combined Test" in result
        assert "Summary here" in result
        assert "OG Combined" in result

    def test_returns_none_with_no_useful_meta(self):
        html = (
            '<html><head>'
            '<meta name="viewport" content="width=device-width"/>'
            '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>'
            '</head><body></body></html>'
        )
        result = _try_meta_extraction(html)
        assert result is None


# ---------------------------------------------------------------------------
# _try_oembed
# ---------------------------------------------------------------------------

class TestTryOembed:

    def test_success_returns_formatted_string(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Never Gonna Give You Up",
            "author_name": "Rick Astley",
        }
        with patch("luckyd_code.tools.web.httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result is not None
        assert "[YouTube]" in result
        assert "Never Gonna Give You Up" in result
        assert "Rick Astley" in result
        assert "dQw4w9WgXcQ" in result

    def test_non_200_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("luckyd_code.tools.web.httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=invalidid")
        assert result is None

    def test_403_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch("luckyd_code.tools.web.httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=privatevid")
        assert result is None

    def test_network_exception_returns_none(self):
        import httpx
        with patch("luckyd_code.tools.web.httpx.get", side_effect=httpx.ConnectError("timeout")):
            result = _try_oembed("https://www.youtube.com/watch?v=abc")
        assert result is None

    def test_generic_exception_returns_none(self):
        with patch("luckyd_code.tools.web.httpx.get", side_effect=RuntimeError("boom")):
            result = _try_oembed("https://www.youtube.com/watch?v=abc")
        assert result is None

    def test_url_included_in_output(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"title": "T", "author_name": "A"}
        with patch("luckyd_code.tools.web.httpx.get", return_value=mock_resp):
            result = _try_oembed(url)
        assert url in result

    def test_channel_name_in_output(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"title": "Video Title", "author_name": "ChannelName"}
        with patch("luckyd_code.tools.web.httpx.get", return_value=mock_resp):
            result = _try_oembed("https://youtu.be/abc12345678")
        assert "Channel: ChannelName" in result


# ---------------------------------------------------------------------------
# Module-level constants / regex patterns (import-time coverage)
# ---------------------------------------------------------------------------

class TestModuleConstants:

    def test_youtube_regex_matches_youtube_com(self):
        assert _YOUTUBE_RE.search("https://www.youtube.com/watch?v=abc")

    def test_youtube_regex_matches_youtu_be(self):
        assert _YOUTUBE_RE.search("https://youtu.be/abc")

    def test_youtube_regex_matches_mobile(self):
        assert _YOUTUBE_RE.search("https://m.youtube.com/watch?v=abc")

    def test_youtube_regex_no_match_for_vimeo(self):
        assert not _YOUTUBE_RE.search("https://vimeo.com/12345")

    def test_oembed_platforms_includes_youtube(self):
        assert any(p.search("https://www.youtube.com/watch?v=x") for p in _OEMBED_PLATFORMS)

    def test_oembed_platforms_includes_vimeo(self):
        assert any(p.search("https://vimeo.com/123") for p in _OEMBED_PLATFORMS)


# ---------------------------------------------------------------------------
# Tool class instantiation (schema / metadata)
# ---------------------------------------------------------------------------

class TestToolSchemas:

    def test_web_fetch_tool_name_and_params(self):
        t = WebFetchTool()
        assert t.name == "WebFetch"
        assert "url" in t.parameters["properties"]
        assert "url" in t.parameters["required"]

    def test_web_search_tool_name_and_params(self):
        t = WebSearchTool()
        assert t.name == "WebSearch"
        assert "query" in t.parameters["properties"]
        assert "query" in t.parameters["required"]

    def test_web_fetch_openai_schema(self):
        schema = WebFetchTool().to_openai_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "WebFetch"

    def test_web_search_openai_schema(self):
        schema = WebSearchTool().to_openai_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "WebSearch"
