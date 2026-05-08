#!/usr/bin/env python3
"""
YouTube Playlist Validator
Filters out broken/private/invalid YouTube video IDs before playlist creation.

Uses YouTube's lightweight oembed API for validation — ~200 bytes per request
instead of fetching full ~1.5 MB YouTube pages. Concurrent validation (10 at a
time) makes verifying dozens of videos nearly instant.
"""

import json
import re
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# macOS Python often lacks root CA certs — certifi ships its own bundle.
try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

OEMBED_URL = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
MAX_CONCURRENT = 10


def extract_video_id(raw: str) -> str | None:
    """Extract an 11-char YouTube video ID from any URL format or bare ID."""
    raw = raw.strip()

    # Already a bare ID (11 alphanumeric chars with - and _)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw

    # Full URL parsing
    parsed = urlparse(raw)
    host = (parsed.hostname or "").replace("www.", "")

    if host in ("youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            return qs.get("v", [None])[0]
        # Shortened /v/VIDEO_ID
        if parsed.path.startswith("/v/"):
            return parsed.path.split("/v/")[1].split("/")[0][:11]
        # Embed
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1].split("/")[0][:11]
        # Shorts
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0][:11]

    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0][:11]

    return None


def _validate_one(video_id: str, timeout: int = 10) -> tuple:
    """Validate a single video ID via YouTube's lightweight oembed API.

    Returns (video_id, is_valid, title_or_error).
    The oembed endpoint returns a tiny JSON payload (~200 bytes) vs. a full
    YouTube page (~1.5 MB), making concurrent validation orders of magnitude
    faster.
    """
    url = OEMBED_URL.format(video_id=video_id)
    req = Request(url, headers={"User-Agent": "YouTubePlaylistValidator/1.0"})
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


def validate_videos(video_refs: list[str], max_concurrent: int = MAX_CONCURRENT) -> dict:
    """Validate YouTube URLs/IDs concurrently via the oembed API.

    Returns dict with 'valid', 'invalid', 'playlist_ids', 'playlist_url'.
    """
    # Extract IDs
    id_map: dict[str, str] = {}  # video_id -> original ref
    for ref in video_refs:
        vid = extract_video_id(ref)
        if vid:
            id_map[vid] = ref

    if not id_map:
        return {"valid": [], "invalid": [], "playlist_ids": [], "playlist_url": None}

    video_ids = list(id_map.keys())
    valid = []
    invalid = []

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(video_ids))) as pool:
        futures = {pool.submit(_validate_one, vid): vid for vid in video_ids}
        for future in as_completed(futures):
            vid, is_valid, info = future.result()
            if is_valid:
                valid.append({"id": vid, "title": info, "original": id_map[vid]})
            else:
                invalid.append({"id": vid, "error": info, "original": id_map[vid]})

    # Preserve original order
    id_order = {vid: idx for idx, vid in enumerate(video_ids)}
    valid.sort(key=lambda v: id_order.get(v["id"], 999))

    playlist_ids = [v["id"] for v in valid]
    playlist_url = None
    if playlist_ids:
        playlist_url = (
            "https://www.youtube.com/watch_videos?video_ids="
            + ",".join(playlist_ids)
        )

    return {
        "valid": valid,
        "invalid": invalid,
        "playlist_ids": playlist_ids,
        "playlist_url": playlist_url,
    }


def print_report(result: dict):
    """Pretty-print the validation results."""
    valid = result["valid"]
    invalid = result["invalid"]

    print(f"\n{'='*60}")
    print(f"  YouTube Playlist Validator")
    print(f"{'='*60}")

    if valid:
        print(f"\n✅ {len(valid)} VALID video(s):")
        for i, v in enumerate(valid, 1):
            title_short = v["title"]
            if len(title_short) > 70:
                title_short = title_short[:67] + "..."
            print(f"  {i:2d}. {v['id']}  →  {title_short}")

    if invalid:
        print(f"\n❌ {len(invalid)} INVALID video(s):")
        for i, v in enumerate(invalid, 1):
            print(f"  {i:2d}. {v['id']}  →  {v['error']}  (input: {v['original']})")

    print(f"\n{'='*60}")
    if result["playlist_url"]:
        print(f"  📋 Playlist URL ({len(valid)} videos):")
        print(f"  {result['playlist_url']}")
    else:
        print(f"  ⚠️  No valid videos — no playlist generated.")
    print(f"{'='*60}\n")

    return result


def main():
    """CLI entry point. Takes YouTube URLs/IDs as arguments."""
    if len(sys.argv) < 2:
        print("Usage: python yt_playlist_validator.py <video_id_or_url> [video_id_or_url ...]")
        print("       or pipe IDs:  echo 'id1 id2' | python yt_playlist_validator.py --stdin")
        sys.exit(1)

    video_refs = []
    if sys.argv[1] == "--stdin":
        video_refs = sys.stdin.read().strip().split()
    else:
        video_refs = sys.argv[1:]

    result = validate_videos(video_refs)  # synchronous — no asyncio needed
    print_report(result)

    # Exit code: 1 if any invalid found (useful for CI)
    if result["invalid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
