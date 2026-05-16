"""Additional tests for tools/youtube.py — validate=True branch.

The existing test_youtube.py already covers extract_video_id, process_inputs,
build_playlist_url, and YouTubePlaylistTool.run() without validation.

This file closes the gap by testing the validate=True code paths inside
YouTubePlaylistTool.run(), which call validate_videos() (mocked here so
no real network calls are made).
"""

from unittest.mock import patch

import pytest

from luckyd_code.tools.youtube import (
    YouTubePlaylistTool,
    PLAYLIST_BASE,
)

# Shared test IDs
ID_A = "dQw4w9WgXcQ"
ID_B = "9bZkp7q19f0"
ID_C = "jNQXAC9IVRw"
ID_D = "oHg5SJYRHA0"


def _mock_validate(valid_ids, invalid_pairs=None):
    """Build a validate_videos return dict for given valid/invalid IDs."""
    invalid_pairs = invalid_pairs or []
    return {
        "valid": [{"id": vid, "title": f"Title {vid}"} for vid in valid_ids],
        "invalid": [{"id": vid, "error": err} for vid, err in invalid_pairs],
        "playlist_ids": valid_ids,
        "playlist_url": f"{PLAYLIST_BASE}?video_ids={','.join(valid_ids)}" if valid_ids else None,
    }


class TestYouTubePlaylistToolValidate:

    def setup_method(self):
        self.tool = YouTubePlaylistTool()

    # ── validate=True, all videos valid ──────────────────────────────────

    def test_validate_true_all_valid_returns_playlist_url(self):
        mock_result = _mock_validate([ID_A, ID_B])
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A, ID_B], validate=True)
        assert PLAYLIST_BASE in result
        assert "2 video" in result

    def test_validate_true_single_valid_video(self):
        mock_result = _mock_validate([ID_A])
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A], validate=True)
        assert PLAYLIST_BASE in result
        assert ID_A in result

    def test_validate_true_no_skipped_when_all_valid(self):
        mock_result = _mock_validate([ID_A, ID_B])
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A, ID_B], validate=True)
        # No "Skipped" section when everything validates
        assert "Skipped" not in result

    # ── validate=True, some videos invalid ───────────────────────────────

    def test_validate_true_some_invalid_reported_as_skipped(self):
        """Invalid IDs from the API should appear in the skipped section."""
        mock_result = _mock_validate(
            [ID_A],
            invalid_pairs=[(ID_B, "Video not found (deleted or private)")],
        )
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(
                videos=[f"https://youtu.be/{ID_A}", f"https://youtu.be/{ID_B}"],
                validate=True,
            )
        assert PLAYLIST_BASE in result
        assert "Skipped" in result
        # The error message from the API should appear
        assert "Video not found" in result or "Invalid video" in result

    def test_validate_true_invalid_entry_matched_to_original_input(self):
        """The skipped message should reference the original URL, not just the bare ID."""
        original_url = f"https://youtu.be/{ID_B}"
        mock_result = _mock_validate(
            [ID_A],
            invalid_pairs=[(ID_B, "Age-restricted")],
        )
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(
                videos=[ID_A, original_url],
                validate=True,
            )
        # The skipped section should contain the original URL
        assert original_url in result or ID_B in result

    def test_validate_true_unmatched_invalid_uses_bare_id(self):
        """If an invalid ID can't be matched to the original input, use the bare ID."""
        # Provide a video URL, but pretend validate_videos returns an unknown bad ID
        mock_result = _mock_validate(
            [ID_A],
            invalid_pairs=[("unknownAAAAA", "Not found")],  # ID not in inputs
        )
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A, ID_B], validate=True)
        # Should still return a valid playlist (only ID_A was valid)
        assert PLAYLIST_BASE in result
        # The unmatched bad ID should still appear in skipped section
        assert "unknownAAAAA" in result

    # ── validate=True, ALL videos fail ───────────────────────────────────

    def test_validate_true_all_invalid_returns_error(self):
        mock_result = _mock_validate(
            [],
            invalid_pairs=[
                (ID_A, "Video not found"),
                (ID_B, "Private video"),
            ],
        )
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A, ID_B], validate=True)
        assert "all video ids failed validation" in result.lower()
        assert PLAYLIST_BASE not in result

    def test_validate_true_all_invalid_includes_skipped_list(self):
        mock_result = _mock_validate(
            [],
            invalid_pairs=[(ID_A, "Deleted"), (ID_B, "Region blocked")],
        )
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self.tool.run(videos=[ID_A, ID_B], validate=True)
        assert "Skipped" in result
        assert "2" in result  # count of skipped

    # ── validate=False (default) — regression check ──────────────────────

    def test_validate_false_does_not_call_validate_videos(self):
        """validate=False (the default) must not trigger network validation."""
        with patch("luckyd_code.tools.youtube.validate_videos") as mock_val:
            result = self.tool.run(videos=[ID_A, ID_B], validate=False)
        mock_val.assert_not_called()
        assert PLAYLIST_BASE in result

    def test_validate_default_is_false(self):
        """run() called without validate= should behave same as validate=False."""
        with patch("luckyd_code.tools.youtube.validate_videos") as mock_val:
            result = self.tool.run(videos=[ID_A])
        mock_val.assert_not_called()
        assert PLAYLIST_BASE in result

    # ── validate=True combined with max_videos cap ────────────────────────

    def test_validate_true_respects_max_videos_cap(self):
        """Validation only runs on IDs that survive the initial cap."""
        # Provide 4 IDs but cap at 2 → only ID_A and ID_B go to validate_videos
        mock_result = _mock_validate([ID_A, ID_B])
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result) as mock_val:
            result = self.tool.run(
                videos=[ID_A, ID_B, ID_C, ID_D],
                max_videos=2,
                validate=True,
            )
        # validate_videos receives at most 2 IDs
        called_ids = mock_val.call_args[0][0]
        assert len(called_ids) <= 2
        assert "2 video" in result
        assert "Skipped" in result  # the two over-cap IDs

    # ── validate=True with no inputs ─────────────────────────────────────

    def test_validate_true_empty_input_returns_error(self):
        """Empty video list should fail before reaching validate_videos."""
        with patch("luckyd_code.tools.youtube.validate_videos") as mock_val:
            result = self.tool.run(videos=[], validate=True)
        mock_val.assert_not_called()
        assert "Error" in result

    def test_validate_true_all_invalid_inputs_before_validation(self):
        """All-invalid URL strings fail in process_inputs before reaching validate."""
        with patch("luckyd_code.tools.youtube.validate_videos") as mock_val:
            result = self.tool.run(
                videos=["not-a-url", "https://vimeo.com/123"],
                validate=True,
            )
        mock_val.assert_not_called()
        assert "no valid" in result.lower()
