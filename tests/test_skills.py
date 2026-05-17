"""Tests for luckyd_code.skills — security and review skills."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.skills.security import (
    SecurityFinding,
    _analyse_diff,
    _format_findings,
    security_review,
)
from luckyd_code.skills.review import review_changes


# ---------------------------------------------------------------------------
# SecurityFinding dataclass
# ---------------------------------------------------------------------------

class TestSecurityFinding:
    def test_fields(self) -> None:
        f = SecurityFinding(
            severity="HIGH",
            pattern="eval() call",
            line="eval(user_input)",
            context="app.py",
        )
        assert f.severity == "HIGH"
        assert f.pattern == "eval() call"
        assert f.line == "eval(user_input)"
        assert f.context == "app.py"

    def test_all_severities_accepted(self) -> None:
        for sev in ("HIGH", "MEDIUM", "LOW"):
            f = SecurityFinding(severity=sev, pattern="x", line="y", context="z")
            assert f.severity == sev


# ---------------------------------------------------------------------------
# _analyse_diff — unit tests for each pattern category
# ---------------------------------------------------------------------------

def _make_diff(filename: str, added_lines: list[str]) -> str:
    """Build a minimal unified diff that adds the given lines to filename."""
    header = f"+++ b/{filename}\n"
    body = "\n".join(f"+{line}" for line in added_lines)
    return header + body + "\n"


class TestAnalyseDiff:
    # ── secrets ──────────────────────────────────────────────────────────────

    def test_hardcoded_api_key(self) -> None:
        diff = _make_diff("config.py", ['API_KEY = "sk-abc123supersecretvalue"'])
        findings = _analyse_diff(diff)
        assert any(f.severity == "HIGH" for f in findings)

    def test_sk_style_key(self) -> None:
        diff = _make_diff("secrets.py", ["token = sk-AbCdEfGhIjKlMnOpQrStUvWx"])
        findings = _analyse_diff(diff)
        assert any("sk-" in f.pattern for f in findings)

    def test_hardcoded_password(self) -> None:
        diff = _make_diff("db.py", ['password = "hunter2abc"'])  # gitleaks:allow
        findings = _analyse_diff(diff)
        assert any(f.severity == "HIGH" and "password" in f.pattern.lower() for f in findings)

    # ── dangerous execution ───────────────────────────────────────────────────

    def test_eval_detected(self) -> None:
        diff = _make_diff("main.py", ["result = eval(user_code)"])
        findings = _analyse_diff(diff)
        patterns = [f.pattern for f in findings]
        assert any("eval" in p for p in patterns)

    def test_exec_detected(self) -> None:
        diff = _make_diff("main.py", ["exec(compiled_code)"])
        findings = _analyse_diff(diff)
        assert any("exec" in f.pattern for f in findings)

    def test_os_system_detected(self) -> None:
        diff = _make_diff("runner.py", ["os.system(cmd)"])
        findings = _analyse_diff(diff)
        assert any("os.system" in f.pattern for f in findings)

    def test_shell_true_detected(self) -> None:
        diff = _make_diff("runner.py", ['subprocess.run(cmd, shell=True)'])
        findings = _analyse_diff(diff)
        assert any("shell=True" in f.pattern for f in findings)

    def test_pickle_loads_detected(self) -> None:
        diff = _make_diff("data.py", ["obj = pickle.loads(data)"])
        findings = _analyse_diff(diff)
        assert any("pickle" in f.pattern for f in findings)
        assert any(f.severity == "MEDIUM" for f in findings)

    # ── path safety ───────────────────────────────────────────────────────────

    def test_path_traversal_detected(self) -> None:
        diff = _make_diff("files.py", ['path = base + "/../secret"'])
        findings = _analyse_diff(diff)
        assert any("traversal" in f.pattern.lower() for f in findings)

    # ── injection ─────────────────────────────────────────────────────────────

    def test_sql_format_injection_detected(self) -> None:
        diff = _make_diff("db.py", ['cursor.execute("SELECT * FROM users WHERE id=%s" % uid)'])
        findings = _analyse_diff(diff)
        assert any("SQL" in f.pattern for f in findings)

    def test_insecure_http_detected(self) -> None:
        diff = _make_diff("client.py", ['url = "http://api.example.com/data"'])
        findings = _analyse_diff(diff)
        assert any("HTTP" in f.pattern for f in findings)

    def test_localhost_http_not_flagged(self) -> None:
        diff = _make_diff("dev.py", ['url = "http://localhost:8080/api"'])
        findings = _analyse_diff(diff)
        http_findings = [f for f in findings if "HTTP" in f.pattern]
        assert not http_findings

    # ── crypto ────────────────────────────────────────────────────────────────

    def test_weak_random_detected(self) -> None:
        diff = _make_diff("token.py", ["token = random.randint(0, 999999)"])
        findings = _analyse_diff(diff)
        assert any("random" in f.pattern.lower() for f in findings)

    def test_md5_detected(self) -> None:
        diff = _make_diff("hash.py", ["h = hashlib.md5(data)"])
        findings = _analyse_diff(diff)
        assert any("MD5" in f.pattern for f in findings)

    # ── clean code ────────────────────────────────────────────────────────────

    def test_clean_code_no_findings(self) -> None:
        diff = _make_diff("clean.py", [
            "def greet(name: str) -> str:",
            '    return f"Hello, {name}"',
        ])
        assert _analyse_diff(diff) == []

    def test_removed_lines_not_scanned(self) -> None:
        # Lines starting with '-' are removals — should not trigger findings
        diff = "+++ b/old.py\n-API_KEY = 'sk-removed_secret_12345678'\n"
        assert _analyse_diff(diff) == []

    def test_comment_lines_skipped(self) -> None:
        diff = _make_diff("notes.py", ["# eval(dangerous) — never do this"])
        assert _analyse_diff(diff) == []

    def test_file_context_captured(self) -> None:
        diff = _make_diff("src/auth.py", ["exec(payload)"])
        findings = _analyse_diff(diff)
        assert findings[0].context == "src/auth.py"

    def test_long_line_truncated_to_120(self) -> None:
        long_line = "x = eval(" + "a" * 200 + ")"
        diff = _make_diff("long.py", [long_line])
        findings = _analyse_diff(diff)
        assert all(len(f.line) <= 120 for f in findings)


# ---------------------------------------------------------------------------
# _format_findings
# ---------------------------------------------------------------------------

class TestFormatFindings:
    def test_no_findings_returns_ok(self) -> None:
        result = _format_findings([])
        assert "No security patterns" in result
        assert "✅" in result

    def test_findings_sorted_high_first(self) -> None:
        findings = [
            SecurityFinding("LOW", "MD5", "hashlib.md5(x)", "a.py"),
            SecurityFinding("HIGH", "eval() call", "eval(x)", "b.py"),
            SecurityFinding("MEDIUM", "pickle", "pickle.loads(x)", "c.py"),
        ]
        result = _format_findings(findings)
        high_pos = result.index("HIGH")
        medium_pos = result.index("MEDIUM")
        low_pos = result.index("LOW")
        assert high_pos < medium_pos < low_pos

    def test_summary_line_counts(self) -> None:
        findings = [
            SecurityFinding("HIGH", "eval() call", "eval(x)", "a.py"),
            SecurityFinding("HIGH", "exec() call", "exec(x)", "b.py"),
            SecurityFinding("LOW", "MD5", "hashlib.md5(x)", "c.py"),
        ]
        result = _format_findings(findings)
        assert "2 HIGH" in result
        assert "0 MEDIUM" in result
        assert "1 LOW" in result

    def test_high_severity_warning_shown(self) -> None:
        findings = [SecurityFinding("HIGH", "eval() call", "eval(x)", "a.py")]
        result = _format_findings(findings)
        assert "HIGH findings should be resolved" in result

    def test_no_high_no_warning(self) -> None:
        findings = [SecurityFinding("LOW", "MD5", "hashlib.md5(x)", "a.py")]
        result = _format_findings(findings)
        assert "HIGH findings should be resolved" not in result


# ---------------------------------------------------------------------------
# security_review() — integration (mocked subprocess)
# ---------------------------------------------------------------------------

class TestSecurityReview:
    def _mock_run(self, stdout: str):  # type: ignore[return]
        """Return a factory that produces a mock subprocess result."""
        result = MagicMock()
        result.stdout = stdout
        return result

    def test_returns_ok_for_clean_diff(self) -> None:
        clean = _make_diff("clean.py", ['def hello() -> str:', '    return "hi"'])
        with patch("luckyd_code.skills.security.subprocess.run",
                   return_value=self._mock_run(clean)):
            out = security_review()
        assert "✅" in out

    def test_detects_eval_in_diff(self) -> None:
        dangerous = _make_diff("bad.py", ["result = eval(user_input)"])
        with patch("luckyd_code.skills.security.subprocess.run",
                   return_value=self._mock_run(dangerous)):
            out = security_review()
        assert "HIGH" in out
        assert "eval" in out.lower()

    def test_no_diff_falls_back_to_cached(self) -> None:
        cached = _make_diff("cached.py", ["exec(payload)"])
        responses = [self._mock_run(""), self._mock_run(cached)]
        with patch("luckyd_code.skills.security.subprocess.run",
                   side_effect=responses):
            out = security_review()
        assert "HIGH" in out

    def test_no_diff_at_all_returns_message(self) -> None:
        with patch("luckyd_code.skills.security.subprocess.run",
                   return_value=self._mock_run("")):
            out = security_review()
        assert "No pending changes" in out

    def test_subprocess_error_handled_gracefully(self) -> None:
        with patch("luckyd_code.skills.security.subprocess.run",
                   side_effect=OSError("git not found")):
            out = security_review()
        assert "Error" in out


# ---------------------------------------------------------------------------
# review_changes() — basic contract
# ---------------------------------------------------------------------------

class TestReviewChanges:
    def _mock_run(self, stdout: str):  # type: ignore[return]
        result = MagicMock()
        result.stdout = stdout
        return result

    def test_returns_diff_block_when_changes_exist(self) -> None:
        diff = "diff --git a/foo.py b/foo.py\n+new line\n"
        with patch("luckyd_code.skills.review.subprocess.run",
                   return_value=self._mock_run(diff)):
            out = review_changes()
        assert "```diff" in out
        assert "new line" in out

    def test_fallback_to_cached_when_empty(self) -> None:
        cached = "+some cached change\n"
        responses = [self._mock_run(""), self._mock_run(cached)]
        with patch("luckyd_code.skills.review.subprocess.run",
                   side_effect=responses):
            out = review_changes()
        assert "cached change" in out

    def test_no_changes_message(self) -> None:
        with patch("luckyd_code.skills.review.subprocess.run",
                   return_value=self._mock_run("")):
            out = review_changes()
        assert "No changes" in out

    def test_subprocess_error_handled(self) -> None:
        with patch("luckyd_code.skills.review.subprocess.run",
                   side_effect=OSError("git missing")):
            out = review_changes()
        assert "Error" in out
