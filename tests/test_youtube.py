"""Tests for the YouTube playlist generator tool and CLI helpers.

Covers:
  - extract_video_id: all URL formats + edge cases
  - process_inputs: dedup, cap enforcement (default + custom), validation
  - build_playlist_url: URL construction
  - YouTubePlaylistTool.run: Tool integration including max_videos param
  - CLI argument parsing and collect_raw_inputs logic

No network calls are made anywhere in this file; the playlist URL is
constructed entirely from string operations.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from luckyd_code.tools.youtube import (
    extract_video_id,
    process_inputs,
    build_playlist_url,
    YouTubePlaylistTool,
    MAX_VIDEOS,
    PLAYLIST_BASE,
)


# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

# A selection of real-looking (but not necessarily live) video IDs
ID_A = "dQw4w9WgXcQ"   # 11 chars, valid charset
ID_B = "9bZkp7q19f0"
ID_C = "jNQXAC9IVRw"
ID_D = "oHg5SJYRHA0"


# ===========================================================================
# extract_video_id
# ===========================================================================

class TestExtractVideoId:

    # --- Standard youtube.com/watch URLs ---

    def test_full_watch_url(self):
        url = f"https://www.youtube.com/watch?v={ID_A}"
        assert extract_video_id(url) == ID_A

    def test_watch_url_with_extra_params(self):
        """v= may not be the first query parameter."""
        url = f"https://www.youtube.com/watch?t=42&v={ID_A}&list=PLabc"
        assert extract_video_id(url) == ID_A

    def test_watch_url_http(self):
        """http:// (not https://) should still parse."""
        url = f"http://www.youtube.com/watch?v={ID_B}"
        assert extract_video_id(url) == ID_B

    def test_watch_url_no_www(self):
        url = f"https://youtube.com/watch?v={ID_C}"
        assert extract_video_id(url) == ID_C

    # --- youtu.be short links ---

    def test_youtu_be_bare(self):
        url = f"https://youtu.be/{ID_A}"
        assert extract_video_id(url) == ID_A

    def test_youtu_be_with_query(self):
        url = f"https://youtu.be/{ID_B}?t=30"
        assert extract_video_id(url) == ID_B

    def test_youtu_be_http(self):
        url = f"http://youtu.be/{ID_C}"
        assert extract_video_id(url) == ID_C

    # --- Embed URLs ---

    def test_embed_url(self):
        url = f"https://www.youtube.com/embed/{ID_A}"
        assert extract_video_id(url) == ID_A

    def test_embed_url_with_params(self):
        url = f"https://www.youtube.com/embed/{ID_B}?autoplay=1"
        assert extract_video_id(url) == ID_B

    # --- Shorts URLs ---

    def test_shorts_url(self):
        url = f"https://www.youtube.com/shorts/{ID_C}"
        assert extract_video_id(url) == ID_C

    # --- Bare video IDs ---

    def test_bare_id_exact_11_chars(self):
        assert extract_video_id(ID_A) == ID_A

    def test_bare_id_with_whitespace_stripped(self):
        assert extract_video_id(f"  {ID_B}  ") == ID_B

    # --- Invalid / edge cases ---

    def test_empty_string_returns_none(self):
        assert extract_video_id("") is None

    def test_whitespace_only_returns_none(self):
        assert extract_video_id("   ") is None

    def test_non_youtube_url_returns_none(self):
        assert extract_video_id("https://vimeo.com/123456789") is None

    def test_short_id_returns_none(self):
        """IDs shorter than 11 chars are not valid."""
        assert extract_video_id("short") is None

    def test_long_id_returns_none(self):
        """IDs longer than 11 chars are not valid bare IDs."""
        assert extract_video_id("dQw4w9WgXcQXXX") is None

    def test_id_with_invalid_chars_returns_none(self):
        """IDs with characters outside [A-Za-z0-9_-] are invalid."""
        assert extract_video_id("dQw4w9WgX!@") is None

    def test_plain_text_returns_none(self):
        assert extract_video_id("hello world") is None

    def test_youtube_channel_url_returns_none(self):
        """Channel URLs (no video ID) should return None."""
        assert extract_video_id("https://www.youtube.com/channel/UCxxxxxx") is None

    def test_youtube_playlist_url_returns_none(self):
        """Playlist-only URLs (no v= param) should return None."""
        assert extract_video_id("https://www.youtube.com/playlist?list=PLabc123") is None

    def test_v_slash_url(self):
        """/v/<id> format should work."""
        url = f"https://www.youtube.com/v/{ID_D}"
        assert extract_video_id(url) == ID_D

    def test_underscore_and_hyphen_in_id(self):
        """IDs legitimately contain _ and -."""
        vid = "aB3-cD4_eF5"
        assert extract_video_id(vid) == vid


# ===========================================================================
# process_inputs
# ===========================================================================

class TestProcessInputs:

    def test_single_valid_url(self):
        valid, skipped = process_inputs([f"https://youtu.be/{ID_A}"])
        assert valid == [ID_A]
        assert skipped == []

    def test_multiple_valid_urls(self):
        inputs = [
            f"https://youtu.be/{ID_A}",
            f"https://www.youtube.com/watch?v={ID_B}",
            ID_C,
        ]
        valid, skipped = process_inputs(inputs)
        assert valid == [ID_A, ID_B, ID_C]
        assert skipped == []

    def test_duplicate_urls_are_skipped(self):
        """The same video ID appearing twice should only be added once."""
        inputs = [ID_A, f"https://youtu.be/{ID_A}"]
        valid, skipped = process_inputs(inputs)
        assert valid == [ID_A]
        assert len(skipped) == 1
        assert "Duplicate" in skipped[0]

    def test_invalid_url_is_skipped(self):
        inputs = ["not-a-url", ID_B]
        valid, skipped = process_inputs(inputs)
        assert valid == [ID_B]
        assert len(skipped) == 1
        assert "Invalid" in skipped[0]

    def test_empty_list_returns_empty(self):
        valid, skipped = process_inputs([])
        assert valid == []
        assert skipped == []

    def test_all_invalid_returns_empty_valid(self):
        inputs = ["bad1", "bad2", "https://vimeo.com/12345"]
        valid, skipped = process_inputs(inputs)
        assert valid == []
        assert len(skipped) == 3

    def test_default_cap_is_max_videos(self):
        """Default cap should be MAX_VIDEOS (50). Videos beyond are skipped."""
        ids = [f"videoID{str(i).zfill(4)}" for i in range(MAX_VIDEOS + 5)]
        valid, skipped = process_inputs(ids)
        assert len(valid) == MAX_VIDEOS
        assert len(skipped) == 5
        assert all("Over" in s for s in skipped)

    def test_custom_cap_is_respected(self):
        """A custom cap lower than MAX_VIDEOS should be enforced."""
        ids = [ID_A, ID_B, ID_C, ID_D]
        valid, skipped = process_inputs(ids, cap=2)
        assert valid == [ID_A, ID_B]
        assert len(skipped) == 2
        assert all("Over 2-video limit" in s for s in skipped)

    def test_custom_cap_of_one(self):
        """cap=1 should accept only the first video."""
        valid, skipped = process_inputs([ID_A, ID_B, ID_C], cap=1)
        assert valid == [ID_A]
        assert len(skipped) == 2

    def test_preserves_insertion_order(self):
        """Video IDs should appear in the order they were first seen."""
        inputs = [ID_C, ID_A, ID_B]
        valid, _ = process_inputs(inputs)
        assert valid == [ID_C, ID_A, ID_B]

    def test_mixed_formats_all_accepted(self):
        inputs = [
            f"https://youtu.be/{ID_A}",
            f"https://www.youtube.com/watch?v={ID_B}",
            f"https://www.youtube.com/embed/{ID_C}",
            f"https://www.youtube.com/shorts/{ID_D}",
        ]
        valid, skipped = process_inputs(inputs)
        assert valid == [ID_A, ID_B, ID_C, ID_D]
        assert skipped == []


# ===========================================================================
# build_playlist_url
# ===========================================================================

class TestBuildPlaylistUrl:

    def test_single_video(self):
        url = build_playlist_url([ID_A])
        assert url.startswith(PLAYLIST_BASE)
        assert ID_A in url
        assert "video_ids=" in url

    def test_multiple_videos_comma_separated(self):
        url = build_playlist_url([ID_A, ID_B, ID_C])
        assert f"{ID_A},{ID_B},{ID_C}" in url

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="No video IDs"):
            build_playlist_url([])

    def test_url_format(self):
        """URL must use the watch_videos endpoint and video_ids param."""
        url = build_playlist_url([ID_A])
        assert url == f"{PLAYLIST_BASE}?video_ids={ID_A}"

    def test_50_videos_produces_valid_url(self):
        ids = [f"video{str(i).zfill(6)}"[:11].ljust(11, "0") for i in range(50)]
        url = build_playlist_url(ids)
        assert url.startswith(PLAYLIST_BASE)
        assert url.count(",") == 49   # 50 IDs → 49 commas


# ===========================================================================
# YouTubePlaylistTool (Tool integration)
# ===========================================================================

class TestYouTubePlaylistTool:

    def setup_method(self):
        self.tool = YouTubePlaylistTool()

    def test_tool_metadata(self):
        assert self.tool.name == "YouTubePlaylist"
        assert self.tool.description
        assert self.tool.permission_risk == "safe"
        props = self.tool.parameters["properties"]
        assert "videos" in props
        assert "max_videos" in props

    def test_run_with_valid_urls(self):
        result = self.tool.run(videos=[
            f"https://youtu.be/{ID_A}",
            f"https://www.youtube.com/watch?v={ID_B}",
        ])
        assert PLAYLIST_BASE in result
        assert "2 video" in result
        assert ID_A in result
        assert ID_B in result

    def test_run_with_bare_ids(self):
        result = self.tool.run(videos=[ID_A, ID_B, ID_C])
        assert "3 video" in result
        assert PLAYLIST_BASE in result

    def test_run_empty_list(self):
        result = self.tool.run(videos=[])
        assert "Error" in result

    def test_run_all_invalid(self):
        result = self.tool.run(videos=["bad1", "bad2", "https://vimeo.com/999"])
        assert "Error" in result
        assert "no valid" in result.lower()

    def test_run_reports_skipped_inputs(self):
        result = self.tool.run(videos=[ID_A, "not-a-video-id", ID_B])
        assert PLAYLIST_BASE in result
        assert "Skipped" in result
        assert "Invalid" in result

    def test_run_deduplicates(self):
        """Duplicate IDs should result in one entry in the playlist."""
        result = self.tool.run(videos=[ID_A, ID_A, f"https://youtu.be/{ID_A}"])
        assert "1 video" in result
        assert "Duplicate" in result

    def test_run_mixed_formats(self):
        result = self.tool.run(videos=[
            f"https://youtu.be/{ID_A}",
            f"https://www.youtube.com/embed/{ID_B}",
            f"https://www.youtube.com/shorts/{ID_C}",
            ID_D,
        ])
        assert "4 video" in result

    def test_run_max_videos_param_limits_output(self):
        """max_videos should cap the playlist shorter than the default 50."""
        result = self.tool.run(videos=[ID_A, ID_B, ID_C, ID_D], max_videos=2)
        assert "2 video" in result
        assert "Skipped" in result
        # Only first two IDs should appear in the URL
        assert ID_A in result
        assert ID_B in result
        assert ID_C not in result.split("\n")[1]   # URL line shouldn't have C or D
        assert ID_D not in result.split("\n")[1]

    def test_run_max_videos_clamped_to_hard_limit(self):
        """max_videos above MAX_VIDEOS should be clamped silently."""
        # Use real video IDs — validation checks YouTube's API for liveness
        ids = [ID_A, ID_B, ID_C, ID_D, ID_A, ID_B, ID_C, ID_D, ID_A, ID_B]
        result = self.tool.run(videos=ids, max_videos=MAX_VIDEOS + 999)
        # Should succeed normally — no error about the oversized max_videos.
        # After dedup, we have 4 unique valid IDs.
        assert PLAYLIST_BASE in result

    def test_run_max_videos_of_one(self):
        """max_videos=1 should produce a single-video playlist."""
        result = self.tool.run(videos=[ID_A, ID_B, ID_C], max_videos=1)
        assert "1 video" in result
        assert ID_A in result

    def test_to_openai_tool_format(self):
        """Tool should produce a valid OpenAI tool definition."""
        schema = self.tool.to_openai_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "YouTubePlaylist"
        props = schema["function"]["parameters"]["properties"]
        assert "videos" in props
        assert props["videos"]["type"] == "array"
        assert "max_videos" in props
        assert props["max_videos"]["type"] == "integer"

    def test_videos_is_required_param(self):
        """'videos' should be listed as required in the schema."""
        assert "videos" in self.tool.parameters["required"]

    def test_max_videos_is_not_required(self):
        """'max_videos' should be optional (not in required list)."""
        assert "max_videos" not in self.tool.parameters["required"]


# ===========================================================================
# CLI: argument parsing and collect_raw_inputs
# ===========================================================================

class TestCLIArgumentParsing:
    """Test the CLI script's argument parser and input collection in isolation."""

    @pytest.fixture(autouse=True)
    def _import_cli(self):
        """Import CLI helpers. Skips gracefully if the scripts package can't be found."""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "playlist_gen",
                Path(__file__).parent.parent / "scripts" / "playlist_gen.py",
            )
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        except Exception as exc:
            pytest.skip(f"Could not import playlist_gen.py: {exc}")

    def test_parser_inline_urls(self):
        parser = self.mod.build_parser()
        args = parser.parse_args([ID_A, ID_B])
        assert args.urls == [ID_A, ID_B]

    def test_parser_file_flag(self):
        parser = self.mod.build_parser()
        args = parser.parse_args(["--file", "urls.txt"])
        assert args.file == ["urls.txt"]

    def test_parser_clipboard_flag(self):
        parser = self.mod.build_parser()
        args = parser.parse_args(["--clipboard"])
        assert args.clipboard is True

    def test_parser_open_flag(self):
        parser = self.mod.build_parser()
        args = parser.parse_args(["--open", ID_A])
        assert args.open_browser is True

    def test_parser_save_flag(self):
        parser = self.mod.build_parser()
        args = parser.parse_args(["--save", "out.txt", ID_A])
        assert args.save == "out.txt"

    def test_parser_quiet_flag(self):
        parser = self.mod.build_parser()
        args = parser.parse_args(["--quiet", ID_A])
        assert args.quiet is True

    def test_collect_inline_urls(self):
        parser = self.mod.build_parser()
        args = parser.parse_args([ID_A, ID_B])
        raw = self.mod.collect_raw_inputs(args)
        assert ID_A in raw
        assert ID_B in raw

    def test_collect_from_file(self, tmp_path):
        """collect_raw_inputs should read URLs from a temp file."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text(f"{ID_A}\n{ID_B}\n# comment line\n\n{ID_C}\n")
        parser = self.mod.build_parser()
        args = parser.parse_args(["--file", str(urls_file)])
        raw = self.mod.collect_raw_inputs(args)
        assert ID_A in raw
        assert ID_B in raw
        assert ID_C in raw
        assert "# comment line" not in raw   # comments skipped
        assert "" not in raw                 # blank lines skipped

    def test_collect_from_missing_file_warns(self, capsys):
        """A missing file path should warn to stderr but not crash."""
        parser = self.mod.build_parser()
        args = parser.parse_args(["--file", "/nonexistent/path/urls.txt"])
        raw = self.mod.collect_raw_inputs(args)
        assert raw == []
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "warn" in captured.err.lower()

    def test_collect_from_clipboard(self):
        """collect_raw_inputs should read from clipboard when --clipboard is set."""
        parser = self.mod.build_parser()
        args = parser.parse_args(["--clipboard"])
        with patch.object(self.mod, "read_clipboard", return_value=[ID_A, ID_B]):
            raw = self.mod.collect_raw_inputs(args)
        assert ID_A in raw
        assert ID_B in raw

    def test_main_success(self, capsys):
        """main() should print the playlist URL and return exit code 0."""
        with patch("sys.argv", ["playlist_gen", ID_A, ID_B]):
            code = self.mod.main()
        assert code == 0
        captured = capsys.readouterr()
        assert PLAYLIST_BASE in captured.out

    def test_main_no_input_returns_1(self, capsys):
        """main() with no inputs should return exit code 1."""
        with patch("sys.argv", ["playlist_gen"]):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                code = self.mod.main()
        assert code == 1

    def test_main_open_browser(self, capsys):
        """--open flag should call webbrowser.open with the playlist URL."""
        with patch("sys.argv", ["playlist_gen", "--open", ID_A]):
            with patch.object(self.mod, "webbrowser") as mock_wb:
                code = self.mod.main()
        assert code == 0
        mock_wb.open.assert_called_once()
        call_url = mock_wb.open.call_args[0][0]
        assert PLAYLIST_BASE in call_url

    def test_main_save_to_file(self, tmp_path, capsys):
        """--save flag should write the URL to the specified file."""
        out_file = tmp_path / "result.txt"
        with patch("sys.argv", ["playlist_gen", "--save", str(out_file), ID_A]):
            code = self.mod.main()
        assert code == 0
        content = out_file.read_text()
        assert PLAYLIST_BASE in content

    def test_main_quiet_mode(self, capsys):
        """--quiet flag should print only the bare URL, no decorations."""
        with patch("sys.argv", ["playlist_gen", "--quiet", ID_A]):
            code = self.mod.main()
        assert code == 0
        captured = capsys.readouterr()
        lines = [line for line in captured.out.splitlines() if line.strip()]
        # In quiet mode there should be exactly one line of output — the URL
        assert len(lines) == 1
        assert lines[0].startswith(PLAYLIST_BASE)

    def test_main_all_invalid_returns_1(self, capsys):
        """main() with all-invalid inputs should return exit code 1."""
        with patch("sys.argv", ["playlist_gen", "not-valid", "also-bad"]):
            code = self.mod.main()
        assert code == 1
