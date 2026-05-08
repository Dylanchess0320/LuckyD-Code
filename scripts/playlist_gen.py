#!/usr/bin/env python3
"""
playlist_gen.py — YouTube Playlist Generator
=============================================
Converts YouTube video URLs or bare video IDs into a temporary playlist
URL that opens instantly without a YouTube account.

Uses YouTube's undocumented watch_videos endpoint:
  https://www.youtube.com/watch_videos?video_ids=ID1,ID2,...

Supports up to 50 videos per playlist (YouTube's hard limit).

USAGE EXAMPLES
--------------
# From a text file (one URL or ID per line):
    python playlist_gen.py urls.txt

# From clipboard:
    python playlist_gen.py --clipboard

# Inline URLs / IDs (any mix of formats):
    python playlist_gen.py "https://youtu.be/dQw4w9WgXcQ" "9bZkp7q19f0"

# Open in browser immediately after generating:
    python playlist_gen.py --open urls.txt

# Save the generated URL to a file:
    python playlist_gen.py --save playlist.txt urls.txt

# Mix a file with inline extras:
    python playlist_gen.py urls.txt "dQw4w9WgXcQ" --open

INTEGRATION
-----------
The core helpers (extract_video_id, process_inputs, build_playlist_url)
live in luckyd_code/tools/youtube.py and are imported here so both the
standalone script and the AI tool stay in sync with a single source of truth.
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow running as a standalone script from the project root without
# installing the package (adds the project root to sys.path).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent          # scripts/
_PROJECT_ROOT = _SCRIPT_DIR.parent                     # luckyd-code/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import shared logic from the tool module so there's one source of truth.
try:
    from luckyd_code.tools.youtube import (
        extract_video_id,
        process_inputs,
        build_playlist_url,
        MAX_VIDEOS,
        PLAYLIST_BASE,
    )
except ImportError:
    # Fallback: if the package isn't importable, inline the essentials so the
    # script still works when run in isolation (e.g. copied to another project).
    import re
    from urllib.parse import urlencode, urlparse, parse_qs
    from typing import Optional

    PLAYLIST_BASE = "https://www.youtube.com/watch_videos"
    MAX_VIDEOS = 50

    _YT_ID_PATTERN = re.compile(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|embed/|shorts/|v/))"
        r"([A-Za-z0-9_-]{11})"
    )
    _BARE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

    def extract_video_id(raw):
        raw = raw.strip()
        if not raw:
            return None
        match = _YT_ID_PATTERN.search(raw)
        if match:
            return match.group(1)
        try:
            parsed = urlparse(raw)
            if "youtube.com" in parsed.netloc:
                qs = parse_qs(parsed.query)
                if "v" in qs and len(qs["v"][0]) == 11:
                    return qs["v"][0]
        except Exception:
            pass
        if _BARE_ID_PATTERN.match(raw):
            return raw
        return None

    def build_playlist_url(video_ids):
        if not video_ids:
            raise ValueError("No video IDs provided.")
        return f"{PLAYLIST_BASE}?{urlencode({'video_ids': ','.join(video_ids)})}"

    def process_inputs(raw_inputs):
        seen, valid, skipped = set(), [], []
        for raw in raw_inputs:
            vid = extract_video_id(raw)
            if vid is None:
                skipped.append(f"Invalid: {raw!r}")
            elif vid in seen:
                skipped.append(f"Duplicate: {raw!r}")
            elif len(valid) >= MAX_VIDEOS:
                skipped.append(f"Over {MAX_VIDEOS}-video limit: {raw!r}")
            else:
                seen.add(vid)
                valid.append(vid)
        return valid, skipped


# ---------------------------------------------------------------------------
# Clipboard helper — optional; gracefully degrades if unavailable
# ---------------------------------------------------------------------------

def read_clipboard() -> list:
    """Return lines from the system clipboard as a list of strings.

    Tries (in order): pyperclip, tkinter, xclip/pbpaste via subprocess.
    Raises RuntimeError with a helpful message if nothing works.
    """
    # 1. pyperclip (cross-platform, pip install pyperclip)
    try:
        import pyperclip
        text = pyperclip.paste()
        if text:
            return [line.strip() for line in text.splitlines() if line.strip()]
    except ImportError:
        pass

    # 2. tkinter (ships with most Python installers)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        if text:
            return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        pass

    # 3. Platform clipboard via subprocess (Linux: xclip; macOS: pbpaste)
    try:
        import subprocess
        if sys.platform == "darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        else:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True,
            )
        if result.returncode == 0 and result.stdout.strip():
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except Exception:
        pass

    raise RuntimeError(
        "Could not read clipboard. Install pyperclip (`pip install pyperclip`) "
        "for reliable cross-platform clipboard support."
    )


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def collect_raw_inputs(args: argparse.Namespace) -> list:
    """Gather all raw URL/ID strings from every enabled input source."""
    raw: list = []

    # 1. Inline arguments passed directly on the command line
    if args.urls:
        raw.extend(args.urls)

    # 2. Text file(s) — one URL or ID per line; blank lines and # comments skipped
    if args.file:
        for filepath in args.file:
            path = Path(filepath)
            if not path.exists():
                print(f"[WARN] File not found: {filepath}", file=sys.stderr)
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        raw.append(line)
            except OSError as exc:
                print(f"[WARN] Could not read {filepath}: {exc}", file=sys.stderr)

    # 3. Clipboard
    if getattr(args, "clipboard", False):
        try:
            clip_lines = read_clipboard()
            print(f"[INFO] Read {len(clip_lines)} line(s) from clipboard.")
            raw.extend(clip_lines)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)

    # 4. stdin pipe (e.g. cat urls.txt | python playlist_gen.py)
    if not sys.stdin.isatty() and not args.urls and not args.file and not getattr(args, "clipboard", False):
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                raw.append(line)

    return raw


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="playlist_gen",
        description=(
            "Generate a temporary YouTube playlist URL — no account required.\n"
            "Supports up to 50 videos per playlist."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("USAGE EXAMPLES")[1].split("INTEGRATION")[0].strip(),
    )

    parser.add_argument(
        "urls",
        nargs="*",
        metavar="URL_OR_ID",
        help="YouTube URLs or bare video IDs to include in the playlist.",
    )
    parser.add_argument(
        "-f", "--file",
        nargs="+",
        metavar="FILE",
        help="Text file(s) with one YouTube URL or video ID per line.",
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Read URLs/IDs from the system clipboard.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Automatically open the playlist in the default web browser.",
    )
    parser.add_argument(
        "--save",
        metavar="OUTPUT_FILE",
        help="Save the generated playlist URL to a text file.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print the bare playlist URL (useful for scripting/piping).",
    )

    return parser


def main() -> int:
    """Entry point. Returns exit code (0 = success, 1 = error)."""
    parser = build_parser()
    args = parser.parse_args()

    # ---- Collect all raw inputs ----
    raw_inputs = collect_raw_inputs(args)

    if not raw_inputs:
        parser.print_help()
        print("\n[ERROR] No input provided. Pass URLs inline, use --file, or --clipboard.",
              file=sys.stderr)
        return 1

    # ---- Validate and deduplicate ----
    valid_ids, skipped = process_inputs(raw_inputs)

    # ---- Report skipped inputs (unless quiet mode) ----
    if not args.quiet and skipped:
        print(f"[WARN] Skipped {len(skipped)} input(s):", file=sys.stderr)
        for s in skipped:
            print(f"       {s}", file=sys.stderr)

    if not valid_ids:
        print("[ERROR] No valid YouTube video IDs found — nothing to do.", file=sys.stderr)
        return 1

    # ---- Build the playlist URL ----
    playlist_url = build_playlist_url(valid_ids)

    # ---- Output ----
    if args.quiet:
        # Bare URL only — ideal for shell scripting / piping
        print(playlist_url)
    else:
        print(f"\n{'='*60}")
        print(f"  YouTube Playlist  ({len(valid_ids)} video(s))")
        print(f"{'='*60}")
        print(f"  {playlist_url}")
        print(f"{'='*60}\n")

        if len(valid_ids) == MAX_VIDEOS and len(raw_inputs) > MAX_VIDEOS:
            print(f"[INFO] Playlist capped at {MAX_VIDEOS} videos (YouTube limit).")

    # ---- Optional: save to file ----
    if args.save:
        try:
            save_path = Path(args.save)
            save_path.write_text(playlist_url + "\n", encoding="utf-8")
            if not args.quiet:
                print(f"[INFO] URL saved to: {save_path.resolve()}")
        except OSError as exc:
            print(f"[WARN] Could not save URL to {args.save}: {exc}", file=sys.stderr)

    # ---- Optional: open in browser ----
    if args.open_browser:
        if not args.quiet:
            print("[INFO] Opening playlist in browser...")
        webbrowser.open(playlist_url)

    return 0


if __name__ == "__main__":
    sys.exit(main())
