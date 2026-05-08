"""Tests for feedback_analyzer.py — LLM-powered error diagnosis."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock


from luckyd_code.feedback_analyzer import (
    Diagnosis,
    analyze_error,
    _call_llm,
    _parse_diagnosis_json,
    _get_relevant_files,
)


# ------------------------------------------------------------------ #
#  Diagnosis dataclass
# ------------------------------------------------------------------ #

class TestDiagnosis:
    def test_creation(self):
        d = Diagnosis(
            error_type="ValueError",
            error_message="bad value",
            root_cause="A None was passed",
            affected_files=["luckyd_code/foo.py"],
            fix_suggestion="Add a None check",
            confidence="high",
        )
        assert d.error_type == "ValueError"
        assert d.confidence == "high"

    def test_to_markdown(self):
        d = Diagnosis(
            error_type="KeyError",
            error_message="missing key 'x'",
            root_cause="Dict access without .get()",
            affected_files=["luckyd_code/bar.py", "luckyd_code/baz.py"],
            fix_suggestion="Use .get('x', default)",
            confidence="medium",
        )
        md = d.to_markdown()
        assert "Autonomous Diagnosis" in md
        assert "Dict access without .get()" in md
        assert "luckyd_code/bar.py" in md
        assert "luckyd_code/baz.py" in md
        assert "Use .get('x', default)" in md
        assert "medium" in md

    def test_to_markdown_no_files(self):
        d = Diagnosis(
            error_type="TypeError",
            error_message="None + 1",
            root_cause="None not checked",
            affected_files=[],
            fix_suggestion="Check for None",
            confidence="low",
        )
        md = d.to_markdown()
        assert "(none)" in md


# ------------------------------------------------------------------ #
#  JSON parsing
# ------------------------------------------------------------------ #

class TestParseDiagnosisJson:
    def test_plain_json(self):
        raw = '{"root_cause": "a bug", "affected_files": ["x.py"], "fix_suggestion": "fix it", "confidence": "high"}'
        result = _parse_diagnosis_json(raw)
        assert result is not None
        assert result["root_cause"] == "a bug"
        assert result["affected_files"] == ["x.py"]

    def test_fenced_json(self):
        raw = '```json\n{"root_cause": "fenced bug", "affected_files": [], "fix_suggestion": "fenced fix", "confidence": "medium"}\n```'
        result = _parse_diagnosis_json(raw)
        assert result is not None
        assert result["root_cause"] == "fenced bug"

    def test_markdown_with_extra_text(self):
        raw = 'Here is my analysis:\n\n```json\n{"root_cause": "md bug", "affected_files": ["a.py", "b.py"], "fix_suggestion": "md fix", "confidence": "low"}\n```\n\nHope that helps.'
        result = _parse_diagnosis_json(raw)
        assert result is not None
        assert result["root_cause"] == "md bug"
        assert len(result["affected_files"]) == 2

    def test_error_response(self):
        assert _parse_diagnosis_json("ERROR: timeout") is None

    def test_empty_response(self):
        assert _parse_diagnosis_json("") is None

    def test_garbage_response(self):
        assert _parse_diagnosis_json("blah blah not json at all") is None


# ------------------------------------------------------------------ #
#  LLM call
# ------------------------------------------------------------------ #

class TestCallLlm:
    def test_successful_call(self):
        """Mock httpx.Client by replacing it in the module's namespace."""
        import luckyd_code.feedback_analyzer as fa

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"root_cause":"x"}'}}]
        }
        mock_response.raise_for_status.return_value = None

        # httpx.Client is used both as context manager AND directly.
        # The code does: client = Client(...) ; resp = client.post(...)
        # NOT: with Client(...) as client: resp = client.post(...)
        # So FakeClient needs .post() directly.
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self._mock_resp = mock_response
            def post(self, *args, **kwargs):
                return self._mock_resp
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch.object(fa.httpx, "Client", FakeClient):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = _call_llm("sys", "user", "fake-key")
                assert "root_cause" in result
                assert isinstance(result, str)

    def test_http_error(self):
        import luckyd_code.feedback_analyzer as fa
        import httpx as real_httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        http_err = real_httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = http_err

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self._mock_resp = mock_response
            def post(self, *args, **kwargs):
                return self._mock_resp
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch.object(fa.httpx, "Client", FakeClient):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = _call_llm("sys", "user", "fake-key")
                assert result.startswith("ERROR:")

    def test_timeout(self):
        import luckyd_code.feedback_analyzer as fa
        import httpx as real_httpx

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            def post(self, *args, **kwargs):
                raise real_httpx.TimeoutException("too slow")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch.object(fa.httpx, "Client", FakeClient):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = _call_llm("sys", "user", "fake-key")
                assert "timed out" in result


# ------------------------------------------------------------------ #
#  Relevant files extraction
# ------------------------------------------------------------------ #

class TestGetRelevantFiles:
    def test_extracts_files_from_traceback(self, tmp_path):
        # Create a fake project structure
        (tmp_path / "luckyd_code").mkdir(parents=True)
        (tmp_path / "luckyd_code" / "foo.py").write_text("# foo module", encoding="utf-8")
        (tmp_path / "luckyd_code" / "bar.py").write_text("# bar module", encoding="utf-8")

        error_data = {
            "error_type": "ValueError",
            "error_message": "something broke",
            "traceback": 'File "luckyd_code/foo.py", line 42, in do_stuff\n    raise ValueError("bad")\n'
        }

        files = _get_relevant_files(error_data, str(tmp_path))
        assert "luckyd_code/foo.py" in files
        assert "foo module" in files["luckyd_code/foo.py"]

    def test_truncates_large_files(self, tmp_path):
        (tmp_path / "luckyd_code").mkdir(parents=True)
        big_content = "\n".join([f"# line {i}" for i in range(500)])
        (tmp_path / "luckyd_code" / "big.py").write_text(big_content, encoding="utf-8")

        error_data = {
            "error_type": "Error",
            "error_message": "",
            "traceback": 'File "luckyd_code/big.py"'
        }

        files = _get_relevant_files(error_data, str(tmp_path))
        content = files["luckyd_code/big.py"]
        assert "truncated" in content
        assert content.count("\n") < 250  # less than 200 lines + header

    def test_falls_back_to_error_message(self, tmp_path):
        (tmp_path / "luckyd_code").mkdir(parents=True)
        (tmp_path / "luckyd_code" / "target.py").write_text("# target", encoding="utf-8")

        error_data = {
            "error_type": "ImportError",
            "error_message": "cannot import from luckyd_code/target.py",
            "traceback": "",  # No traceback
        }

        files = _get_relevant_files(error_data, str(tmp_path))
        assert any("target.py" in k for k in files)

    def test_limit_five_files(self, tmp_path):
        (tmp_path / "luckyd_code").mkdir(parents=True)
        for i in range(10):
            (tmp_path / "luckyd_code" / f"mod{i}.py").write_text(f"# mod{i}", encoding="utf-8")

        tb_lines = []
        for i in range(10):
            tb_lines.append(f'File "luckyd_code/mod{i}.py", line 1, in fn')
        error_data = {
            "error_type": "Error",
            "error_message": "",
            "traceback": "\n".join(tb_lines),
        }

        files = _get_relevant_files(error_data, str(tmp_path))
        assert len(files) <= 5


# ------------------------------------------------------------------ #
#  Full analyze_error
# ------------------------------------------------------------------ #

class TestAnalyzeError:
    def test_returns_none_on_llm_error(self):
        with patch("luckyd_code.feedback_analyzer._call_llm") as mock_call:
            mock_call.return_value = "ERROR: HTTP 500: server error"

            result = analyze_error(
                ValueError("test error"),
                api_key="fake-key",
                project_root="/tmp",
            )
            assert result is None

    def test_returns_none_on_unparseable_response(self):
        with patch("luckyd_code.feedback_analyzer._call_llm") as mock_call:
            mock_call.return_value = "Here is some unstructured analysis..."

            result = analyze_error(
                ValueError("test error"),
                api_key="fake-key",
                project_root="/tmp",
            )
            assert result is None

    def test_returns_diagnosis_on_success(self, tmp_path):
        (tmp_path / "luckyd_code").mkdir(parents=True, exist_ok=True)

        with patch("luckyd_code.feedback_analyzer._call_llm") as mock_call:
            mock_call.return_value = json.dumps({
                "root_cause": "A None value was not checked before use",
                "affected_files": ["luckyd_code/foo.py"],
                "fix_suggestion": "Add `if x is not None:` guard clause",
                "confidence": "high",
            })

            result = analyze_error(
                ValueError("test error"),
                api_key="fake-key",
                project_root=str(tmp_path),
            )
            assert result is not None
            assert result.root_cause == "A None value was not checked before use"
            assert result.confidence == "high"
            assert "luckyd_code/foo.py" in result.affected_files

    def test_accepts_error_dict(self, tmp_path):
        error_data = {
            "error_type": "TypeError",
            "error_message": "NoneType + int",
            "traceback": 'File "luckyd_code/x.py", line 10\n    return x + 1',
            "python_version": "3.10",
            "os": "Linux",
            "app_version": "1.0",
        }

        with patch("luckyd_code.feedback_analyzer._call_llm") as mock_call:
            mock_call.return_value = json.dumps({
                "root_cause": "type mismatch",
                "affected_files": [],
                "fix_suggestion": "cast it",
                "confidence": "medium",
            })

            result = analyze_error(
                error_data,
                api_key="fake-key",
                project_root=str(tmp_path),
            )
            assert result is not None
            assert result.error_type == "TypeError"
