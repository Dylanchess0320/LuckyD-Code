"""YouTube playlist generator tool.

Converts a list of YouTube URLs or video IDs into a temporary playlist URL
that works without a YouTube account (YouTube's watch_videos endpoint).
Supports up to 50 videos per playlist (YouTube's hard limit for this endpoint).

Validates video IDs concurrently against YouTube's lightweight oembed API
so the AI agent doesn't have to manually verify each ID — just pass them all
in one call and the tool filters out dead/private/invalid IDs automatically.

Integrated into the tool registry so the AI agent can generate playlists
on demand during a coding/automation session.
"""

import re
import json
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Optional

# macOS Python often lacks root CA certs — certifi ships its own bundle.
# Without this, all HTTPS validation fails on a fresh Mac install.
try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL_CONTEXT = ssl.create_default_context()  # pragma: no cover

from .registry import Tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLAYLIST_BASE = "https://www.youtube.com/watch_videos"
MAX_VIDEOS = 50  # YouTube's limit for the watch_videos endpoint

# Regex patterns for extracting video IDs from various URL formats.
# Handles: youtu.be/<id>, youtube.com/watch?v=<id>, /embed/<id>, /shorts/<id>
_YT_ID_PATTERN = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|embed/|shorts/|v/))"
    r"([A-Za-z0-9_-]{11})"
)
# A bare 11-character video ID with no URL wrapper
_BARE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


# ---------------------------------------------------------------------------
# Concurrent oembed validation — 10x faster than full-page fetching
# ---------------------------------------------------------------------------

OEMBED_URL = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
MAX_CONCURRENT = 10  # YouTube oembed API handles concurrent requests well


def _validate_one(video_id: str, timeout: int = 10) -> tuple:  # pragma: no cover
    """Validate a single video ID via YouTube's lightweight oembed API.

    Returns (video_id, is_valid, title_or_error).
    The oembed endpoint returns a tiny JSON payload (~200 bytes) vs. a full
    YouTube page (~1.5 MB), making concurrent validation orders of magnitude
    faster and cheaper.
    """
    url = OEMBED_URL.format(video_id=video_id)
    req = Request(url, headers={"User-Agent": "LuckyD-Code/1.0"})
    try:
        with urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        title = data.get("title", "")
        if title:
            return video_id, True, title
        return video_id, False, "Empty title in oembed response"
    except HTTPError as e:
        if e.code == 404:
            return video_id, False, "Video not found (deleted, private, or invalid ID)"
        if e.code == 403:
            return video_id, False, "Video is age-restricted or region-blocked"
        return video_id, False, f"YouTube API error (HTTP {e.code})"
    except URLError as e:
        return video_id, False, f"Network error: {e.reason}"
    except Exception as e:
        return video_id, False, f"Validation error: {e}"


def validate_videos(video_ids: list, max_concurrent: int = MAX_CONCURRENT) -> dict:  # pragma: no cover
    """Validate multiple video IDs concurrently against YouTube's oembed API.

    Returns a dict with:
      - valid: list of {"id": ..., "title": ...}
      - invalid: list of {"id": ..., "error": ...}
      - playlist_ids: ordered list of valid IDs only
      - playlist_url: ready-to-open playlist URL (None if no valid IDs)
    """
    if not video_ids:
        return {"valid": [], "invalid": [], "playlist_ids": [], "playlist_url": None}

    valid = []
    invalid = []

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(video_ids))) as pool:
        futures = {pool.submit(_validate_one, vid): vid for vid in video_ids}
        for future in as_completed(futures):
            vid, is_valid, info = future.result()
            if is_valid:
                valid.append({"id": vid, "title": info})
            else:
                invalid.append({"id": vid, "error": info})

    # Preserve original order in the valid list
    id_order = {vid: idx for idx, vid in enumerate(video_ids)}
    valid.sort(key=lambda v: id_order.get(v["id"], 999))

    playlist_ids = [v["id"] for v in valid]
    playlist_url = None
    if playlist_ids:
        playlist_url = build_playlist_url(playlist_ids)

    return {
        "valid": valid,
        "invalid": invalid,
        "playlist_ids": playlist_ids,
        "playlist_url": playlist_url,
    }


# ---------------------------------------------------------------------------
# Core extraction logic (reused by both Tool and CLI script)
# ---------------------------------------------------------------------------

def extract_video_id(raw: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL or bare ID string.

    Returns the ID string on success, or None if the input is not recognised
    as a valid YouTube reference.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Try URL-based regex extraction first (covers youtu.be, /embed, /shorts)
    match = _YT_ID_PATTERN.search(raw)
    if match:
        return match.group(1)

    # Handle youtube.com/watch?v=ID where v= may not be the first parameter
    try:
        parsed = urlparse(raw)
        if "youtube.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "v" in qs:
                vid = qs["v"][0]
                if len(vid) == 11:
                    return vid
    except Exception:
        pass

    # Fall back: accept a bare 11-char ID (only valid YouTube ID characters)
    if _BARE_ID_PATTERN.match(raw):
        return raw

    return None


def build_playlist_url(video_ids: list) -> str:
    """Construct a YouTube watch_videos URL from a list of video IDs.

    Uses safe="," to prevent urlencode from percent-encoding the commas
    between video IDs — YouTube's watch_videos endpoint expects literal commas.
    """
    if not video_ids:
        raise ValueError("No video IDs provided — cannot build a playlist URL.")
    params = urlencode({"video_ids": ",".join(video_ids)}, safe=",")
    return f"{PLAYLIST_BASE}?{params}"


def process_inputs(raw_inputs: list, cap: int = MAX_VIDEOS) -> tuple:
    """Parse raw input strings into (valid_ids, skipped_inputs).

    Deduplicates IDs while preserving order. Enforces the video cap and
    records a warning entry in *skipped* for any videos over the limit.

    Args:
        raw_inputs: Raw URL/ID strings to process.
        cap: Maximum number of videos to accept (default: MAX_VIDEOS = 50).
    """
    seen: set = set()
    valid: list = []
    skipped: list = []

    for raw in raw_inputs:
        vid = extract_video_id(raw)
        if vid is None:
            skipped.append(f"Invalid: {raw!r}")
            continue
        if vid in seen:
            skipped.append(f"Duplicate: {raw!r}")
            continue
        if len(valid) >= cap:
            skipped.append(f"Over {cap}-video limit: {raw!r}")
            continue
        seen.add(vid)
        valid.append(vid)

    return valid, skipped


# ---------------------------------------------------------------------------
# Tool class — integrates with the DeepSeek Code tool registry
# ---------------------------------------------------------------------------

class YouTubePlaylistTool(Tool):
    """Generate a temporary YouTube playlist URL from a list of video URLs or IDs.

    Use this tool whenever the user asks to:
      - Create or build a YouTube playlist
      - Combine multiple YouTube videos into a single watchable link
      - Generate a shareable playlist without a YouTube account
      - Produce a playlist URL from a list of video URLs or IDs

    The playlist URL opens in any browser — no login required. This tool does
    NOT need browser/Playwright — it just builds the URL string.

    By default skips API validation (fast, works offline, no network calls).
    Pass validate=True to check video IDs against YouTube's oembed API in
    parallel (10 at a time), filtering out dead/private/invalid videos.
    """

    name = "YouTubePlaylist"
    description = (
        "Use when the user wants to combine YouTube videos into a playlist or generate "
        "a shareable playlist URL. Accepts any mix of YouTube URL formats (full URLs, "
        "youtu.be short links, embed/shorts URLs, or bare 11-char video IDs) and returns "
        "a ready-to-open playlist link. No YouTube account required. Supports up to 50 videos. "
        "By default skips API validation (fast, works offline). Pass validate=True to check "
        "all IDs against YouTube's API and filter out dead/private/invalid ones. "
        "Also reports any invalid or duplicate inputs that were skipped."
    )
    parameters = {
        "type": "object",
        "properties": {
            "videos": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of YouTube video URLs (any format: full URL, youtu.be short "
                    "link, embed URL, shorts URL) or bare 11-character video IDs."
                ),
            },
            "max_videos": {
                "type": "integer",
                "description": (
                    f"Maximum number of videos to include (1–{MAX_VIDEOS}). "
                    f"Defaults to {MAX_VIDEOS}. Videos beyond this cap are reported as skipped."
                ),
                "default": MAX_VIDEOS,
            },
            "validate": {
                "type": "boolean",
                "description": (
                    "Whether to validate video IDs against YouTube's API before building "
                    "the playlist. Defaults to false for speed and offline use. "
                    "Set to true to validate — invalid/deleted/private videos are "
                    "automatically filtered out."
                ),
                "default": False,
            },
        },
        "required": ["videos"],
    }
    permission_risk = "safe"

    def run(  # type: ignore[override]
        self,
        videos: list,
        max_videos: int = MAX_VIDEOS,
        validate: bool = False,
    ) -> str:
        if not videos:
            return "Error: no videos provided."

        cap = max(1, min(max_videos, MAX_VIDEOS))
        lines: list = []

        # Step 1: extract and deduplicate IDs
        valid_ids, skipped = process_inputs(videos, cap=cap)

        if not valid_ids:
            lines.append("Error: no valid YouTube video IDs found.")
            if skipped:
                lines.append(f"Skipped {len(skipped)} input(s):")
                lines.extend(f"  • {s}" for s in skipped)
            return "\n".join(lines)

        # Step 2: validate against YouTube API (concurrent, lightweight oembed)
        if validate:
            result = validate_videos(valid_ids)
            valid_ids = result["playlist_ids"]
            if result["invalid"]:
                for inv in result["invalid"]:
                    # Find matching original input for the error message
                    matched = False
                    for raw in videos:
                        if extract_video_id(raw) == inv["id"]:
                            skipped.append(f"Invalid video: {raw!r} — {inv['error']}")
                            matched = True
                            break
                    if not matched:
                        skipped.append(f"Invalid video: {inv['id']} — {inv['error']}")

        if not valid_ids:
            lines.append("Error: all video IDs failed validation.")
            if skipped:
                lines.append(f"Skipped {len(skipped)} input(s):")
                lines.extend(f"  • {s}" for s in skipped)
            return "\n".join(lines)

        # Step 3: build the final playlist URL
        url = build_playlist_url(valid_ids)
        lines.append(f"Playlist URL ({len(valid_ids)} video(s)):")
        lines.append(url)

        if skipped:
            lines.append(f"\nSkipped {len(skipped)} input(s):")
            lines.extend(f"  • {s}" for s in skipped)

        return "\n".join(lines)
