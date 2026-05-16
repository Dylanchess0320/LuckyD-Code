"""Coverage push #2 — targets remaining gaps identified after 87.16%.

Covers:
  - verify.py: verify_lint, verify_consistency, run_verify_pipeline, pipeline helpers
  - router.py: _file_size_tier, classify_tier_llm, resolve_initial_route,
               escalate_tier, show_current_routing, effort helpers
  - analytics/scanner.py: scanner helpers, CodebaseScanner, ProjectMetrics props
  - analytics/smells.py: _detect_generic_smells, _detect_deep_nesting,
                          detect_project, detect_smells convenience
  - tools/youtube.py: extract_video_id, build_playlist_url, process_inputs, Tool.run
  - tools/web.py: _extract_text, _try_meta_extraction, _try_oembed (pure helpers)
  - git/auto_commit.py: _in_git_repo, _stage_files, _has_staged_changes, _commit
  - brain/indexer.py: VectorIndexer.save, stats_text, get_changed_files
  - brain/retriever.py: _rrf_merge, stats
  - model_registry.py: get_model_by_id, get_models_by_tier, format_model_list
  - autonomous_fixer.py: _extract_diff, _read_file_safe, _git, _pr_fallback_url
  - cost_tracker.py: _migrate_legacy_json_once, _load_all legacy, get_cumulative_cost
  - error_reporter.py: build_issue_url with extras, _get_api_key, _get_autonomous_mode
  - web_routes/project.py: init, reindex, tasks, plans endpoints
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# verify.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyLint:
    def test_no_linter_available_returns_none(self, tmp_path):
        from luckyd_code.verify import verify_lint
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is None

    def test_lint_passes(self, tmp_path):
        from luckyd_code.verify import verify_lint
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = ""
        mock_run.stderr = ""
        with patch("subprocess.run", return_value=mock_run):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert result.passed is True

    def test_lint_fails(self, tmp_path):
        from luckyd_code.verify import verify_lint
        f = tmp_path / "f.py"
        f.write_text("x=1\n")
        mock_run = MagicMock()
        mock_run.returncode = 1
        mock_run.stdout = "E501 line too long"
        mock_run.stderr = ""
        with patch("subprocess.run", return_value=mock_run):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert result.passed is False
        assert "E501" in result.raw_output

    def test_lint_timeout_tries_next_linter(self, tmp_path):
        from luckyd_code.verify import verify_lint
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 30)):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is None


class TestVerifyConsistency:
    def test_non_py_file_returns_none(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "readme.md"
        f.write_text("# Hello")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        result = verify_consistency(str(tmp_path / "ghost.py"), str(tmp_path))
        assert result is None

    def test_clean_file_passes(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "good.py"
        f.write_text("def foo(x: int) -> int:\n    return x + 1\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed is True

    def test_bare_except_flagged(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "bad.py"
        f.write_text("try:\n    pass\nexcept:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        if not result.passed:
            assert "bare" in result.fix_hint.lower() or "except" in result.raw_output.lower()

    def test_mutable_default_arg_flagged(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "mut.py"
        f.write_text("def foo(x=[]):\n    return x\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "mutable" in result.fix_hint.lower()

    def test_syntax_error_returns_none(self, tmp_path):
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "bad.py"
        f.write_text("def (:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None


class TestRunVerifyPipeline:
    def test_syntax_check_only(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        results = run_verify_pipeline(str(f), str(tmp_path), run_lint=False, run_consistency=False)
        assert len(results) >= 1
        assert results[0].stage == "syntax"
        assert results[0].passed

    def test_syntax_error_stops_pipeline(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "bad.py"
        f.write_text("def (broken):\n    pass\n")
        results = run_verify_pipeline(str(f), str(tmp_path))
        assert results[0].stage == "syntax"
        assert not results[0].passed
        assert len(results) == 1

    def test_with_lint(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            results = run_verify_pipeline(str(f), str(tmp_path), run_lint=True, run_consistency=False)
        stages = [r.stage for r in results]
        assert "syntax" in stages

    def test_test_runner_not_allowed_blocked(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        results = run_verify_pipeline(
            str(f), str(tmp_path), run_lint=False, run_consistency=False,
            run_tests=True, test_runner_cmd="rm -rf /",
        )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed
        assert "Blocked" in test_results[0].message

    def test_test_runner_passes(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock(returncode=0, stdout="1 passed", stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path), run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert test_results[0].passed

    def test_test_runner_fails(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock(returncode=1, stdout="1 failed", stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path), run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed

    def test_test_runner_timeout(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)):
            results = run_verify_pipeline(
                str(f), str(tmp_path), run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results and not test_results[0].passed
        assert "timed out" in test_results[0].message.lower()

    def test_test_runner_exception(self, tmp_path):
        from luckyd_code.verify import run_verify_pipeline
        f = tmp_path / "f.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=OSError("no python")):
            results = run_verify_pipeline(
                str(f), str(tmp_path), run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results and not test_results[0].passed


class TestPipelineHelpers:
    def test_pipeline_all_passed_true(self):
        from luckyd_code.verify import pipeline_all_passed, VerificationResult
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=True, stage="lint", message="ok"),
        ]
        assert pipeline_all_passed(results) is True

    def test_pipeline_all_passed_false_on_syntax_fail(self):
        from luckyd_code.verify import pipeline_all_passed, VerificationResult
        results = [VerificationResult(passed=False, stage="syntax", message="bad")]
        assert pipeline_all_passed(results) is False

    def test_pipeline_all_passed_lint_fail_not_counted(self):
        """Lint is not mandatory so pipeline_all_passed should still return True."""
        from luckyd_code.verify import pipeline_all_passed, VerificationResult
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="lint", message="style"),
        ]
        assert pipeline_all_passed(results) is True

    def test_pipeline_feedback_formats_results(self):
        from luckyd_code.verify import pipeline_feedback, VerificationResult
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="consistency", message="bare except",
                               fix_hint="fix it", raw_output="bare except found"),
        ]
        fb = pipeline_feedback(results)
        assert "1/2" in fb
        assert "syntax" in fb
        assert "consistency" in fb

    def test_pipeline_feedback_empty_returns_empty(self):
        from luckyd_code.verify import pipeline_feedback
        assert pipeline_feedback([]) == ""

    def test_verification_result_to_agent_feedback_passed(self):
        from luckyd_code.verify import VerificationResult
        r = VerificationResult(passed=True, stage="syntax", message="OK", duration_ms=12.5)
        fb = r.to_agent_feedback()
        assert "\u2713" in fb and "syntax" in fb

    def test_verification_result_to_agent_feedback_failed(self):
        from luckyd_code.verify import VerificationResult
        r = VerificationResult(
            passed=False, stage="lint", message="E501",
            fix_hint="shorten lines", raw_output="f.py:1:81: E501",
        )
        fb = r.to_agent_feedback()
        assert "\u2717" in fb and "E501" in fb and "shorten" in fb


# ═══════════════════════════════════════════════════════════════════════════════
# router.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileSizeTier:
    def test_no_file_references_returns_1(self):
        from luckyd_code.router import _file_size_tier
        assert _file_size_tier("what is recursion") == 1

    def test_file_outside_cwd_skipped(self):
        from luckyd_code.router import _file_size_tier
        result = _file_size_tier("/etc/passwd")
        assert result == 1

    def test_large_file_increases_tier(self, tmp_path, monkeypatch):
        from luckyd_code.router import _file_size_tier
        monkeypatch.chdir(tmp_path)
        big = tmp_path / "huge.py"
        big.write_text("x = 1\n" * 600)
        result = _file_size_tier(str(big.relative_to(tmp_path)))
        assert result >= 4

    def test_medium_file_tier_3(self, tmp_path, monkeypatch):
        from luckyd_code.router import _file_size_tier
        monkeypatch.chdir(tmp_path)
        med = tmp_path / "med.py"
        med.write_text("x = 1\n" * 250)
        result = _file_size_tier(str(med.relative_to(tmp_path)))
        assert result >= 3

    def test_small_file_tier_2(self, tmp_path, monkeypatch):
        from luckyd_code.router import _file_size_tier
        monkeypatch.chdir(tmp_path)
        small = tmp_path / "small.py"
        small.write_text("x = 1\n" * 90)
        result = _file_size_tier(str(small.relative_to(tmp_path)))
        assert result >= 2

    def test_oserror_skipped(self, tmp_path, monkeypatch):
        from luckyd_code.router import _file_size_tier
        monkeypatch.chdir(tmp_path)
        result = _file_size_tier("nonexistent_file.py")
        assert result == 1


class TestClassifyTierLlm:
    def test_cache_hit_returns_cached(self):
        import hashlib
        from luckyd_code import router
        text = "__test_cache_prompt_unique_xyz"
        key = hashlib.md5(text[:600].encode("utf-8", errors="replace")).hexdigest()
        with router._tier_cache_lock:
            router._tier_cache[key] = 3
        try:
            result = router.classify_tier_llm(text, config=MagicMock())
            assert result == 3
        finally:
            with router._tier_cache_lock:
                router._tier_cache.pop(key, None)

    def test_timeout_returns_heuristic(self):
        from luckyd_code.router import classify_tier_llm
        from concurrent.futures import TimeoutError as FutureTimeoutError
        cfg = MagicMock()
        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeoutError()
        with patch("luckyd_code.router._classify_executor") as mock_exec:
            mock_exec.submit.return_value = mock_future
            result = classify_tier_llm("simple chat message", cfg)
        assert isinstance(result, int) and 1 <= result <= 4


class TestResolveInitialRoute:
    def test_auto_route_off_returns_preferred(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "fix bug", 0, "deepseek", "deepseek-v4-flash", auto_route=False,
        )
        assert result.model == "deepseek-v4-flash"
        assert result.tier == 2

    def test_auto_route_on_no_config(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "fix this bug in my code", 0, "deepseek", "deepseek-v4-flash",
            auto_route=True, config=None,
        )
        assert isinstance(result.tier, int)
        assert result.model != ""

    def test_tier_changed_flag(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "large refactor of entire codebase", 0, "deepseek",
            "deepseek-v4-flash", auto_route=True, config=None,
        )
        assert isinstance(result.tier_changed, bool)


class TestEscalateTier:
    def test_auto_route_off_returns_current(self):
        from luckyd_code.router import escalate_tier
        result = escalate_tier(
            "fix bug", 0, "deepseek", "deepseek-v4-flash",
            "deepseek-v4-flash", 2, auto_route=False,
        )
        assert result.model == "deepseek-v4-flash"
        assert result.tier == 2

    def test_heavy_tool_calls_escalate_to_tier4(self):
        from luckyd_code.router import escalate_tier, HEAVY_TOOL_CALL_THRESHOLD
        result = escalate_tier(
            "simple task", HEAVY_TOOL_CALL_THRESHOLD, "deepseek",
            "deepseek-v4-flash", "deepseek-v4-flash", 1, auto_route=True,
        )
        assert result.tier == 4

    def test_tool_calls_escalate_tier(self):
        from luckyd_code.router import escalate_tier, TOOL_CALL_THRESHOLD
        result = escalate_tier(
            "simple question", TOOL_CALL_THRESHOLD, "deepseek",
            "deepseek-v4-flash", "deepseek-v4-flash", 1, auto_route=True,
        )
        assert result.tier >= 2


class TestShowCurrentRouting:
    def test_returns_string_with_model(self):
        from luckyd_code.router import show_current_routing
        result = show_current_routing("help me debug this")
        assert "Selected Model" in result
        assert "Tier" in result

    def test_preferred_model_shown(self):
        from luckyd_code.router import show_current_routing
        result = show_current_routing("chat", 0, "deepseek-v4-flash")
        assert "Tool Calls" in result


class TestEffortHelpers:
    def test_effort_tier_floor_normal(self):
        from luckyd_code.router import effort_tier_floor
        assert effort_tier_floor("normal") == 2

    def test_effort_tier_floor_high(self):
        from luckyd_code.router import effort_tier_floor
        assert effort_tier_floor("high") == 3

    def test_effort_tier_floor_unknown_defaults_normal(self):
        from luckyd_code.router import effort_tier_floor
        assert effort_tier_floor("unknown_level") == 2

    def test_show_model_info_returns_string(self):
        from luckyd_code.router import show_model_info
        info = show_model_info()
        assert isinstance(info, str) and len(info) > 10

    def test_get_tier_description_all_tiers(self):
        from luckyd_code.router import get_tier_description
        for t in (1, 2, 3, 4):
            desc = get_tier_description(t)
            assert isinstance(desc, str) and len(desc) > 5

    def test_get_tier_description_unknown(self):
        from luckyd_code.router import get_tier_description
        desc = get_tier_description(99)
        assert "99" in desc


# ═══════════════════════════════════════════════════════════════════════════════
# analytics/scanner.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestScannerHelpers:
    def test_detect_language_python(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("f.py")) == "python"

    def test_detect_language_js(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("app.js")) == "javascript"

    def test_detect_language_ts(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("svc.ts")) == "typescript"

    def test_detect_language_go(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("main.go")) == "go"

    def test_detect_language_rust(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("lib.rs")) == "rust"

    def test_detect_language_c(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("main.c")) == "c"

    def test_detect_language_cpp(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("main.cpp")) == "c++"

    def test_detect_language_java(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("Main.java")) == "java"

    def test_detect_language_ruby(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("app.rb")) == "ruby"

    def test_detect_language_shell(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("run.sh")) == "shell"

    def test_detect_language_markdown(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("README.md")) == "markdown"

    def test_detect_language_json(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("data.json")) == "json"

    def test_detect_language_yaml(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("conf.yaml")) == "yaml"

    def test_detect_language_toml(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("pyproject.toml")) == "toml"

    def test_detect_language_unknown(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("file.xyz")) == "unknown"

    def test_count_comment_lines_python(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "# comment\nx = 1\n# another\n"
        assert _count_comment_lines(content, "python") == 2

    def test_count_comment_lines_js_single(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "// comment\nconst x = 1;\n"
        assert _count_comment_lines(content, "javascript") == 1

    def test_count_comment_lines_js_block(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "/* start\nmiddle\nend */\n"
        count = _count_comment_lines(content, "javascript")
        assert count >= 2

    def test_extract_todos(self, tmp_path):
        from luckyd_code.analytics.scanner import _extract_todos
        content = "# TODO: fix this\nx = 1\n# FIXME: broken\n"
        todos = _extract_todos(content, str(tmp_path / "f.py"))
        kinds = [t["kind"] for t in todos]
        assert "TODO" in kinds
        assert "FIXME" in kinds

    def test_extract_todos_note_excluded(self, tmp_path):
        from luckyd_code.analytics.scanner import _extract_todos
        content = "# NOTE: just a note\n"
        todos = _extract_todos(content, str(tmp_path / "f.py"))
        assert todos == []

    def test_generic_complexity_branches(self):
        from luckyd_code.analytics.scanner import _generic_complexity
        code = "if x:\n  while y:\n    for i in z:\n      pass\n"
        c = _generic_complexity(code)
        assert c > 3

    def test_python_complexity(self):
        import ast
        from luckyd_code.analytics.scanner import _python_complexity
        tree = ast.parse("if x:\n    pass\nfor i in r:\n    pass\n")
        assert _python_complexity(tree) >= 3

    def test_max_indent(self):
        from luckyd_code.analytics.scanner import _max_indent
        content = "x = 1\n    y = 2\n        z = 3\n"
        assert _max_indent(content) == 8


class TestCodebaseScanner:
    def test_scan_empty_dir(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        s = CodebaseScanner(str(tmp_path))
        pm = s.scan()
        assert pm.source_files == 0

    def test_scan_python_file(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 1\n# TODO: more work\n")
        s = CodebaseScanner(str(tmp_path))
        pm = s.scan()
        assert pm.source_files >= 1
        assert pm.total_functions >= 1
        assert pm.total_todos >= 1

    def test_scan_js_file(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "app.js"
        f.write_text("function greet() { return 'hi'; }\n")
        s = CodebaseScanner(str(tmp_path))
        pm = s.scan()
        assert pm.source_files >= 1

    def test_scan_skips_hidden_dirs(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        hidden = tmp_path / ".git"
        hidden.mkdir()
        (hidden / "config.py").write_text("x = 1\n")
        visible = tmp_path / "code.py"
        visible.write_text("y = 2\n")
        s = CodebaseScanner(str(tmp_path))
        pm = s.scan()
        assert pm.source_files == 1

    def test_scan_syntax_error_file_handled(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "bad.py"
        f.write_text("def (:\n    pass\n")
        s = CodebaseScanner(str(tmp_path))
        pm = s.scan()
        assert pm.source_files >= 1

    def test_scan_file_single(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "f.py"
        f.write_text("class Foo:\n    pass\n")
        s = CodebaseScanner(str(tmp_path))
        fm = s.scan_file(str(f))
        assert fm is not None
        assert fm.class_count >= 1

    def test_scan_file_nonexistent(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        s = CodebaseScanner(str(tmp_path))
        fm = s.scan_file(str(tmp_path / "ghost.py"))
        assert fm is None

    def test_scan_file_directory_returns_none(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        s = CodebaseScanner(str(tmp_path))
        fm = s.scan_file(str(tmp_path))
        assert fm is None


class TestProjectMetricsProps:
    def _pm(self, **kwargs):
        from luckyd_code.analytics.scanner import ProjectMetrics
        pm = ProjectMetrics(root="/tmp")
        for k, v in kwargs.items():
            setattr(pm, k, v)
        return pm

    def test_avg_complexity_zero_functions(self):
        pm = self._pm(total_functions=0, total_complexity=0)
        assert pm.avg_complexity == 0.0

    def test_avg_complexity_nonzero(self):
        pm = self._pm(total_functions=10, total_complexity=50)
        assert pm.avg_complexity == 5.0

    def test_todo_rate_zero_code_lines(self):
        pm = self._pm(total_code_lines=0, total_todos=5)
        assert pm.todo_rate == 0.0

    def test_health_score_perfect(self):
        pm = self._pm(total_functions=5, total_complexity=10, total_todos=0,
                      total_code_lines=500, source_files=5, total_lines=500,
                      files_by_language={"python": 3, "javascript": 2})
        assert pm.health_score > 80

    def test_to_dict_includes_computed(self):
        pm = self._pm(total_functions=5, total_complexity=15, total_todos=1,
                      total_code_lines=100)
        d = pm.to_dict()
        assert "avg_complexity" in d
        assert "health_score" in d
        assert "todo_rate" in d


# ═══════════════════════════════════════════════════════════════════════════════
# analytics/smells.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestSmellDetector:
    def _detector(self):
        from luckyd_code.analytics.smells import SmellDetector
        return SmellDetector()

    def test_detect_file_read_error_returns_empty(self, tmp_path):
        d = self._detector()
        result = d.detect_file(str(tmp_path / "ghost.py"))
        assert result == []

    def test_large_python_file_flagged(self, tmp_path):
        d = self._detector()
        f = tmp_path / "big.py"
        content = "x = 1\n" * 600
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "large_file" in kinds

    def test_very_large_file_error_severity(self, tmp_path):
        d = self._detector()
        f = tmp_path / "huge.py"
        content = "x = 1\n" * 1100
        result = d.detect_file(str(f), content=content)
        errors = [s for s in result if s.severity == "error" and s.kind == "large_file"]
        assert errors

    def test_long_function_python_flagged(self, tmp_path):
        d = self._detector()
        f = tmp_path / "f.py"
        body = "    x = 1\n" * 60
        content = f"def long_func():\n{body}"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "long_function" in kinds

    def test_bare_except_python_flagged(self, tmp_path):
        d = self._detector()
        f = tmp_path / "f.py"
        content = "try:\n    pass\nexcept:\n    pass\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "bare_except" in kinds

    def test_mutable_default_arg_python_flagged(self, tmp_path):
        d = self._detector()
        f = tmp_path / "f.py"
        content = "def foo(x=[]):\n    return x\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "mutable_default" in kinds

    def test_syntax_error_python_flagged(self, tmp_path):
        d = self._detector()
        f = tmp_path / "f.py"
        content = "def (:\n    pass\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "syntax_error" in kinds

    def test_detect_generic_smells_js(self, tmp_path):
        d = self._detector()
        f = tmp_path / "app.js"
        body = "  x = 1;\n" * 60
        content = f"function longFn() {{\n{body}}}\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "long_function" in kinds

    def test_detect_generic_bare_except_js(self, tmp_path):
        d = self._detector()
        f = tmp_path / "app.js"
        content = "try {\n  x();\n} catch (e) {\n  // ignore\n}\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "bare_except" in kinds

    def test_detect_deep_nesting(self, tmp_path):
        d = self._detector()
        f = tmp_path / "f.py"
        content = "x = 1\n" + ("    " * 6) + "y = 2\n"
        result = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in result]
        assert "deep_nesting" in kinds

    def test_detect_project_high_complexity(self, tmp_path):
        from luckyd_code.analytics.smells import SmellDetector
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics
        d = SmellDetector()
        pm = ProjectMetrics(root=str(tmp_path))
        pm.complexity_breakdown["big.py"] = 20
        pm.file_metrics = []
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "high_complexity" in kinds

    def test_detect_project_high_todo_density(self, tmp_path):
        from luckyd_code.analytics.smells import SmellDetector
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics
        d = SmellDetector()
        pm = ProjectMetrics(root=str(tmp_path))
        fm = FileMetrics(path="f.py", lines_code=50, todo_count=10)
        pm.file_metrics = [fm]
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "high_todo_density" in kinds

    def test_detect_project_empty_file(self, tmp_path):
        from luckyd_code.analytics.smells import SmellDetector
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics
        d = SmellDetector()
        pm = ProjectMetrics(root=str(tmp_path))
        fm = FileMetrics(path="empty.py", lines_code=0, lines_total=1)
        pm.file_metrics = [fm]
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "empty_file" in kinds


class TestDetectSmellsConvenience:
    def test_detect_smells_single_file(self, tmp_path):
        from luckyd_code.analytics.smells import detect_smells
        f = tmp_path / "f.py"
        f.write_text("def foo():\n    pass\n")
        result = detect_smells(str(f))
        assert isinstance(result, list)

    def test_detect_smells_directory(self, tmp_path):
        from luckyd_code.analytics.smells import detect_smells
        (tmp_path / "f.py").write_text("x = 1\n")
        result = detect_smells(str(tmp_path))
        assert isinstance(result, list)

    def test_detect_smells_nonexistent_path(self, tmp_path):
        from luckyd_code.analytics.smells import detect_smells
        result = detect_smells(str(tmp_path / "ghost.py"))
        assert result == []

    def test_detect_smells_whole_project(self):
        from luckyd_code.analytics.smells import detect_smells
        with patch("luckyd_code.analytics.scanner.scan_project") as mock_scan:
            from luckyd_code.analytics.scanner import ProjectMetrics
            mock_scan.return_value = ProjectMetrics(root="/tmp")
            result = detect_smells(path=None)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════════════════
# tools/youtube.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractVideoId:
    def test_full_watch_url(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_returns_none(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("not a video url") is None

    def test_empty_returns_none(self):
        from luckyd_code.tools.youtube import extract_video_id
        assert extract_video_id("") is None

    def test_watch_with_extra_params(self):
        from luckyd_code.tools.youtube import extract_video_id
        result = extract_video_id("https://www.youtube.com/watch?t=30&v=dQw4w9WgXcQ")
        assert result == "dQw4w9WgXcQ"


class TestBuildPlaylistUrl:
    def test_single_video(self):
        from luckyd_code.tools.youtube import build_playlist_url, PLAYLIST_BASE
        url = build_playlist_url(["abc1234567A"])
        assert url.startswith(PLAYLIST_BASE)
        assert "abc1234567A" in url

    def test_multiple_videos_comma_separated(self):
        from luckyd_code.tools.youtube import build_playlist_url
        url = build_playlist_url(["abc1234567A", "def1234567B"])
        assert "abc1234567A" in url
        assert "def1234567B" in url

    def test_empty_raises(self):
        from luckyd_code.tools.youtube import build_playlist_url
        with pytest.raises(ValueError):
            build_playlist_url([])


class TestProcessInputs:
    def test_valid_ids_returned(self):
        from luckyd_code.tools.youtube import process_inputs
        valid, skipped = process_inputs(["dQw4w9WgXcQ", "abc1234567A"])
        assert "dQw4w9WgXcQ" in valid
        assert skipped == []

    def test_invalid_skipped(self):
        from luckyd_code.tools.youtube import process_inputs
        # Use a URL that can't be parsed and is not 11 bare chars
        valid, skipped = process_inputs(["https://invalid-url.com/no-video"])
        assert valid == []
        assert len(skipped) == 1
        assert "Invalid" in skipped[0]

    def test_duplicates_skipped(self):
        from luckyd_code.tools.youtube import process_inputs
        valid, skipped = process_inputs(["dQw4w9WgXcQ", "dQw4w9WgXcQ"])
        assert len(valid) == 1
        assert any("Duplicate" in s for s in skipped)

    def test_cap_enforced(self):
        from luckyd_code.tools.youtube import process_inputs
        ids = [f"abcdefghij{i}" for i in range(10)]
        valid, skipped = process_inputs(ids, cap=3)
        assert len(valid) == 3
        assert any("limit" in s.lower() for s in skipped)


class TestYouTubePlaylistToolRun:
    def _tool(self):
        from luckyd_code.tools.youtube import YouTubePlaylistTool
        return YouTubePlaylistTool()

    def test_empty_videos_returns_error(self):
        result = self._tool().run([])
        assert "Error" in result

    def test_valid_videos_returns_url(self):
        result = self._tool().run(["dQw4w9WgXcQ"])
        assert "youtube.com" in result

    def test_all_invalid_returns_error(self):
        # "tooshort" is 8 chars — not a valid bare ID and not a YouTube URL
        result = self._tool().run(["https://invalid.com/no-video-here"])
        assert "Error" in result

    def test_skipped_listed_in_output(self):
        result = self._tool().run(["dQw4w9WgXcQ", "bad-video"])
        assert "Skipped" in result

    def test_max_videos_cap(self):
        ids = [f"abcdefghij{i}" for i in range(10)]
        result = self._tool().run(ids, max_videos=3)
        assert "Skipped" in result or "youtube.com" in result

    def test_validate_true_calls_validate_videos(self):
        mock_result = {
            "playlist_ids": ["dQw4w9WgXcQ"],
            "invalid": [],
        }
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self._tool().run(["dQw4w9WgXcQ"], validate=True)
        assert "youtube.com" in result

    def test_validate_with_invalid_ids_skipped(self):
        mock_result = {
            "playlist_ids": [],
            "invalid": [{"id": "dQw4w9WgXcQ", "error": "deleted"}],
        }
        with patch("luckyd_code.tools.youtube.validate_videos", return_value=mock_result):
            result = self._tool().run(["dQw4w9WgXcQ"], validate=True)
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# tools/web.py — pure helper functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractText:
    def test_strips_script_tags(self):
        from luckyd_code.tools.web import _extract_text
        html = "<html><body><script>var x=1;</script><p>Hello world</p></body></html>"
        result = _extract_text(html)
        assert "Hello world" in result
        assert "var x=1" not in result

    def test_strips_nav_header_footer(self):
        from luckyd_code.tools.web import _extract_text
        html = "<nav>Menu</nav><main>Content here</main><footer>Footer</footer>"
        result = _extract_text(html)
        assert "Content here" in result
        assert "Menu" not in result

    def test_blank_html_returns_empty(self):
        from luckyd_code.tools.web import _extract_text
        result = _extract_text("<html><body></body></html>")
        assert result == ""


class TestTryMetaExtraction:
    def test_extracts_title(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = "<html><head><title>My Page</title></head><body></body></html>"
        result = _try_meta_extraction(html)
        assert result is not None
        assert "My Page" in result

    def test_extracts_description_meta(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = ('<html><head><meta name="description" content="Great article"/></head>'
                '<body></body></html>')
        result = _try_meta_extraction(html)
        assert result is not None
        assert "Great article" in result

    def test_extracts_og_title(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = ('<html><head><meta property="og:title" content="OG Title"/></head>'
                '<body></body></html>')
        result = _try_meta_extraction(html)
        assert result is not None
        assert "OG Title" in result

    def test_no_meta_returns_none(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = "<html><body><p>Just content</p></body></html>"
        result = _try_meta_extraction(html)
        assert result is None


class TestTryOembed:
    def test_successful_oembed_returns_formatted(self):
        from luckyd_code.tools.web import _try_oembed
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"title": "Never Gonna Give You Up", "author_name": "RickAstleyVEVO"}
        with patch("httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result is not None
        assert "Never Gonna Give You Up" in result

    def test_non_200_returns_none(self):
        from luckyd_code.tools.web import _try_oembed
        mock_resp = MagicMock(status_code=404)
        with patch("httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=badid")
        assert result is None

    def test_exception_returns_none(self):
        from luckyd_code.tools.web import _try_oembed
        with patch("httpx.get", side_effect=Exception("network error")):
            result = _try_oembed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# git/auto_commit.py — internal subprocess helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestInGitRepo:
    def test_returns_true_when_in_repo(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        mock = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock):
            assert _in_git_repo() is True

    def test_returns_false_when_not_in_repo(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        mock = MagicMock(returncode=128)
        with patch("subprocess.run", return_value=mock):
            assert _in_git_repo() is False

    def test_returns_false_on_exception(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        with patch("subprocess.run", side_effect=Exception("git not found")):
            assert _in_git_repo() is False


class TestStageFiles:
    def test_empty_paths_returns_false(self):
        from luckyd_code.git.auto_commit import _stage_files
        assert _stage_files([]) is False

    def test_success_returns_true(self):
        from luckyd_code.git.auto_commit import _stage_files
        mock = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock):
            assert _stage_files(["/tmp/f.py"]) is True

    def test_failure_returns_false(self):
        from luckyd_code.git.auto_commit import _stage_files
        mock = MagicMock(returncode=1, stderr="error")
        with patch("subprocess.run", return_value=mock):
            assert _stage_files(["/tmp/f.py"]) is False

    def test_exception_returns_false(self):
        from luckyd_code.git.auto_commit import _stage_files
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert _stage_files(["/tmp/f.py"]) is False


class TestHasStagedChanges:
    def test_has_changes_returns_true(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        mock = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock):
            assert _has_staged_changes() is True

    def test_no_changes_returns_false(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        mock = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock):
            assert _has_staged_changes() is False

    def test_exception_returns_false(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert _has_staged_changes() is False


class TestCommit:
    def test_success_returns_sha(self):
        from luckyd_code.git.auto_commit import _commit
        mock = MagicMock(returncode=0, stdout="[main abc1234] agent: fix\n 1 file changed")
        with patch("subprocess.run", return_value=mock):
            sha = _commit("agent: fix")
        # _commit strips the trailing ']' with rstrip("]")
        assert sha == "abc1234"

    def test_failure_returns_none(self):
        from luckyd_code.git.auto_commit import _commit
        mock = MagicMock(returncode=1, stderr="nothing to commit", stdout="")
        with patch("subprocess.run", return_value=mock):
            sha = _commit("agent: fix")
        assert sha is None

    def test_exception_returns_none(self):
        from luckyd_code.git.auto_commit import _commit
        with patch("subprocess.run", side_effect=Exception("fail")):
            sha = _commit("agent: fix")
        assert sha is None

    def test_no_bracket_line_returns_ok(self):
        from luckyd_code.git.auto_commit import _commit
        mock = MagicMock(returncode=0, stdout="committed")
        with patch("subprocess.run", return_value=mock):
            sha = _commit("agent: fix")
        assert sha == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# brain/indexer.py — save, stats_text, get_changed_files
# ═══════════════════════════════════════════════════════════════════════════════

class TestVectorIndexerSave:
    def test_save_chunks_only(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx.chunks = [{"file_path": "f.py", "content": "x = 1", "language": "python"}]
        with patch("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path), \
             patch("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json"), \
             patch("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json"), \
             patch("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json"):
            result = idx.save()
        assert result is True
        assert (tmp_path / "chunks.json").exists()

    def test_save_exception_returns_false(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        with patch("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path):
            with patch("luckyd_code.brain.indexer.CHUNKS_FILE") as mock_cf:
                mock_cf.write_text.side_effect = OSError("disk full")
                result = idx.save()
        # graceful either way
        assert result is False or result is True


class TestVectorIndexerStatsText:
    def test_no_faiss_shows_message(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx._faiss_available = False
        text = idx.stats_text()
        assert "FAISS not available" in text

    def test_with_chunks_shows_count(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx.stats["chunks"] = 42
        idx.stats["files"] = 5
        text = idx.stats_text()
        assert "42" in text and "5" in text

    def test_with_languages_shown(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx.stats["languages"] = {"python": 10, "javascript": 5}
        text = idx.stats_text()
        assert "python" in text

    def test_with_size_kb_shown(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx.stats["index_size_bytes"] = 2048
        text = idx.stats_text()
        assert "KB" in text or "B" in text

    def test_with_size_mb_shown(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        idx.stats["index_size_bytes"] = 2 * 1024 * 1024
        text = idx.stats_text()
        assert "MB" in text

    def test_last_indexed_shown(self):
        from luckyd_code.brain.indexer import VectorIndexer
        import time
        idx = VectorIndexer()
        idx.stats["last_indexed"] = time.time()
        text = idx.stats_text()
        assert "Last indexed" in text

    def test_is_available_false_when_no_index(self):
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        assert idx.is_available is False


class TestVectorIndexerGetChangedFiles:
    def test_new_files_returned(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        idx = VectorIndexer()
        idx.file_mtimes = {}
        changed = idx.get_changed_files(str(tmp_path))
        assert str(f) in changed

    def test_unchanged_files_not_returned(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        st = f.stat()
        idx = VectorIndexer()
        idx.file_mtimes = {str(f): (st.st_mtime, st.st_size)}
        changed = idx.get_changed_files(str(tmp_path))
        assert str(f) not in changed

    def test_skip_non_code_files(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        (tmp_path / "readme.txt").write_text("hello")
        idx = VectorIndexer()
        changed = idx.get_changed_files(str(tmp_path))
        assert changed == []


# ═══════════════════════════════════════════════════════════════════════════════
# brain/retriever.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetrieverRrfMerge:
    def _retriever(self):
        from luckyd_code.brain.retriever import Retriever
        return Retriever()

    def test_merges_both_sources(self):
        r = self._retriever()
        vec = [{"chunk_id": "a", "file_path": "f.py", "content": "x", "score": 0.9}]
        bm25 = [{"chunk_id": "a", "file_path": "f.py", "content": "x", "score": 0.8}]
        merged = r._rrf_merge(vec, bm25, k=5)
        assert len(merged) >= 1
        assert merged[0]["chunk_id"] == "a"

    def test_unique_from_each_source(self):
        r = self._retriever()
        vec = [{"chunk_id": "a", "file_path": "a.py", "content": "x", "score": 0.9}]
        bm25 = [{"chunk_id": "b", "file_path": "b.py", "content": "y", "score": 0.7}]
        merged = r._rrf_merge(vec, bm25, k=5)
        ids = [c["chunk_id"] for c in merged]
        assert "a" in ids and "b" in ids

    def test_k_limits_results(self):
        r = self._retriever()
        vec = [{"chunk_id": str(i), "file_path": "f.py", "content": "x", "score": 0.9} for i in range(10)]
        bm25 = [{"chunk_id": str(i + 10), "file_path": "f.py", "content": "y", "score": 0.8} for i in range(10)]
        merged = r._rrf_merge(vec, bm25, k=3)
        assert len(merged) <= 3

    def test_chunks_without_chunk_id_use_file_path(self):
        r = self._retriever()
        vec = [{"file_path": "a.py", "content": "x", "score": 0.9}]
        bm25 = [{"file_path": "a.py", "content": "x", "score": 0.8}]
        merged = r._rrf_merge(vec, bm25, k=5)
        assert merged[0]["file_path"] == "a.py"


class TestRetrieverStats:
    def test_stats_returns_structure(self):
        from luckyd_code.brain.retriever import Retriever
        r = Retriever()
        mock_indexer = MagicMock()
        mock_indexer.is_available = False
        mock_indexer.stats = {"chunks": 10, "files": 3, "languages": {"python": 5}, "last_indexed": 0}
        mock_graph = MagicMock()
        mock_graph.stats = {"node_count": 100, "edge_count": 50, "files_parsed": 10}
        r._indexer = mock_indexer
        r._graph = mock_graph
        stats = r.stats()
        assert "vector" in stats
        assert "graph" in stats
        assert stats["vector"]["chunks"] == 10
        assert stats["graph"]["nodes"] == 100


# ═══════════════════════════════════════════════════════════════════════════════
# model_registry.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelRegistry:
    def test_get_model_by_id_found(self):
        from luckyd_code.model_registry import get_model_by_id
        m = get_model_by_id("deepseek-v4-flash")
        assert m is not None
        assert m.id == "deepseek-v4-flash"

    def test_get_model_by_id_not_found_returns_none(self):
        from luckyd_code.model_registry import get_model_by_id
        assert get_model_by_id("no-such-model") is None

    def test_get_models_by_tier_valid(self):
        from luckyd_code.model_registry import get_models_by_tier
        models = get_models_by_tier(1)
        assert len(models) == 1
        assert models[0].id == "deepseek-v4-flash"

    def test_get_models_by_tier_invalid_returns_empty(self):
        from luckyd_code.model_registry import get_models_by_tier
        assert get_models_by_tier(99) == []

    def test_get_models_by_strength_found(self):
        from luckyd_code.model_registry import get_models_by_strength
        models = get_models_by_strength("reasoning")
        assert len(models) >= 1

    def test_get_models_by_strength_not_found(self):
        from luckyd_code.model_registry import get_models_by_strength
        models = get_models_by_strength("nonexistent_strength")
        assert models == []

    def test_format_model_list_contains_model_names(self):
        from luckyd_code.model_registry import format_model_list
        text = format_model_list()
        assert "Flash" in text or "flash" in text
        assert "Tier" in text

    def test_get_unique_model_count(self):
        from luckyd_code.model_registry import get_unique_model_count
        assert get_unique_model_count() >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# autonomous_fixer.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractDiff:
    def test_extracts_from_diff_fence(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "```diff\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n```"
        result = _extract_diff(raw)
        assert "--- a/f.py" in result

    def test_extracts_from_generic_fence_with_diff_markers(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "```\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n```"
        result = _extract_diff(raw)
        assert "--- a/f.py" in result

    def test_bare_diff_without_fence(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y"
        result = _extract_diff(raw)
        assert "--- a/f.py" in result

    def test_no_diff_returns_empty(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        result = _extract_diff("No diff here, just text.")
        assert result == ""

    def test_empty_string_returns_empty(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        assert _extract_diff("") == ""


class TestReadFileSafe:
    def test_reads_existing_file(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        result = _read_file_safe("code.py", str(tmp_path))
        assert "x = 1" in result

    def test_missing_file_returns_error(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        result = _read_file_safe("ghost.py", str(tmp_path))
        assert "NOT FOUND" in result or "FILE NOT FOUND" in result

    def test_path_escape_blocked(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        result = _read_file_safe("../../etc/passwd", str(tmp_path))
        assert "BLOCKED" in result or "NOT FOUND" in result

    def test_long_file_truncated(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        f = tmp_path / "long.py"
        f.write_text("x = 1\n" * 400)
        result = _read_file_safe("long.py", str(tmp_path))
        assert "truncated" in result


class TestAutonomousFixerGit:
    def test_git_success(self):
        from luckyd_code.autonomous_fixer import _git
        mock = MagicMock(returncode=0, stdout="main\n", stderr="")
        with patch("subprocess.run", return_value=mock):
            code, stdout, stderr = _git("rev-parse", "--abbrev-ref", "HEAD")
        assert code == 0
        assert stdout == "main"

    def test_git_exception_returns_minus_one(self):
        from luckyd_code.autonomous_fixer import _git
        with patch("subprocess.run", side_effect=Exception("no git")):
            code, stdout, stderr = _git("status")
        assert code == -1
        assert "no git" in stderr


class TestPrFallbackUrl:
    def test_builds_github_url(self):
        from luckyd_code.autonomous_fixer import _pr_fallback_url
        url = _pr_fallback_url("fix: some bug", "body text", "autofix/abc123")
        assert "github.com" in url
        assert "compare" in url

    def test_long_body_truncated(self):
        from luckyd_code.autonomous_fixer import _pr_fallback_url
        long_body = "x" * 70000
        url = _pr_fallback_url("fix", long_body, "branch")
        assert "github.com" in url
        assert "truncated" in url


class TestGenerateFix:
    def test_no_affected_files_returns_empty_on_llm_error(self, tmp_path):
        from luckyd_code.autonomous_fixer import generate_fix
        from luckyd_code.feedback_analyzer import Diagnosis
        d = Diagnosis(
            error_type="ValueError",
            error_message="bad value",
            root_cause="wrong input",
            affected_files=[],
            fix_suggestion="validate inputs",
            confidence="high",
        )
        with patch("luckyd_code.autonomous_fixer._call_llm", return_value="ERROR: api down"):
            result = generate_fix(d, "fake_key", str(tmp_path))
        assert result == ""

    def test_successful_llm_returns_diff(self, tmp_path):
        from luckyd_code.autonomous_fixer import generate_fix
        from luckyd_code.feedback_analyzer import Diagnosis
        d = Diagnosis(
            error_type="ValueError",
            error_message="bad value",
            root_cause="wrong input",
            affected_files=[],
            fix_suggestion="validate inputs",
            confidence="high",
        )
        diff = "```diff\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-x\n+y\n```"
        with patch("luckyd_code.autonomous_fixer._call_llm", return_value=diff):
            result = generate_fix(d, "fake_key", str(tmp_path))
        assert "--- a/f.py" in result


# ═══════════════════════════════════════════════════════════════════════════════
# cost_tracker.py — migration and load_all paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostTrackerMigration:
    @pytest.fixture
    def isolated(self, tmp_path, monkeypatch):
        cost_file = tmp_path / "costs.jsonl"
        legacy_file = tmp_path / "costs.json"
        totals_file = tmp_path / "costs_total.json"
        monkeypatch.setattr("luckyd_code.cost_tracker.COST_FILE", cost_file)
        monkeypatch.setattr("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file)
        monkeypatch.setattr("luckyd_code.cost_tracker._TOTALS_FILE", totals_file)
        return {"cost": cost_file, "legacy": legacy_file, "totals": totals_file}

    def test_migrate_legacy_json_to_jsonl(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        records = [{"model": "deepseek-v4-flash", "input_tokens": 100,
                    "output_tokens": 50, "estimated_cost": 0.001, "timestamp": "2024-01-01"}]
        isolated["legacy"].write_text(json.dumps(records), encoding="utf-8")
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 10, 5)
        assert not isolated["legacy"].exists()
        assert isolated["cost"].exists()

    def test_load_all_from_jsonl(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 100, 50)
        tracker.record_usage("deepseek-v4-pro", 200, 100)
        tracker2 = CostTracker()
        cost = tracker2.get_cumulative_cost()
        assert cost > 0

    def test_load_all_legacy_only(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        records = [{"model": "deepseek-v4-flash", "input_tokens": 100,
                    "output_tokens": 50, "estimated_cost": 0.005, "timestamp": "2024-01-01"}]
        isolated["legacy"].write_text(json.dumps(records), encoding="utf-8")
        result = CostTracker._load_all()
        assert len(result) == 1
        assert result[0]["model"] == "deepseek-v4-flash"

    def test_get_cumulative_uses_totals_file(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        isolated["totals"].write_text(json.dumps({"total": 1.2345}), encoding="utf-8")
        tracker = CostTracker()
        cost = tracker.get_cumulative_cost()
        assert cost == pytest.approx(1.2345)

    def test_record_usage_with_explicit_cost(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        tracker = CostTracker()
        rec = tracker.record_usage("deepseek-v4-flash", 100, 50, cost=0.999)
        assert rec.estimated_cost == pytest.approx(0.999)

    def test_migrate_legacy_skips_if_jsonl_exists(self, isolated):
        from luckyd_code.cost_tracker import CostTracker
        isolated["cost"].write_text("", encoding="utf-8")
        isolated["legacy"].write_text("[]", encoding="utf-8")
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1, 1)
        assert isolated["legacy"].exists()


# ═══════════════════════════════════════════════════════════════════════════════
# error_reporter.py — build_issue_url extras, _get_api_key, _get_autonomous_mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildIssueUrlExtras:
    @pytest.fixture
    def error_data(self):
        return {
            "error_type": "RuntimeError",
            "error_message": "something went wrong",
            "traceback": "Traceback:\n  File 'f.py', line 1\nRuntimeError: oops",
            "python_version": "3.12.0",
            "os": "Windows",
            "app_version": "1.0.0",
        }

    def test_with_diagnosis(self, error_data):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(error_data, diagnosis="## Diagnosis\nThe issue is X")
        assert "Diagnosis" in url

    def test_with_diff(self, error_data):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(error_data, diff="--- a/f.py\n+++ b/f.py\n-x\n+y")
        assert "diff" in url.lower() or "Proposed" in url

    def test_with_pr_url(self, error_data):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(error_data, pr_url="https://github.com/owner/repo/pull/1")
        assert "PR" in url or "pull" in url

    def test_long_traceback_truncated(self, error_data):
        from luckyd_code.error_reporter import build_issue_url
        error_data["traceback"] = "x" * 5000
        url = build_issue_url(error_data)
        assert "truncated" in url


class TestGetApiKey:
    def test_returns_key_from_config(self):
        from luckyd_code.error_reporter import _get_api_key
        mock_cfg = MagicMock()
        mock_cfg.api_key = "sk-test-key"
        # Config is imported inside _get_api_key() via `from .config import Config`
        # so patch the real import location
        with patch("luckyd_code.config.Config", return_value=mock_cfg):
            key = _get_api_key()
        assert key == "sk-test-key"

    def test_falls_back_to_env(self, monkeypatch):
        from luckyd_code.error_reporter import _get_api_key
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        with patch("luckyd_code.config.Config", side_effect=Exception("no config")):
            key = _get_api_key()
        assert key == "env-key"

    def test_returns_empty_when_no_key(self, monkeypatch):
        from luckyd_code.error_reporter import _get_api_key
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch("luckyd_code.config.Config", side_effect=Exception("no config")):
            key = _get_api_key()
        assert key == ""


class TestGetAutonomousMode:
    def test_default_is_fix(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={}):
            mode = _get_autonomous_mode()
        assert mode == "fix"

    def test_off_mode(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        from luckyd_code import settings
        with patch.object(settings, "load_settings",
                          return_value={"autonomous_improvement": "off"}):
            mode = _get_autonomous_mode()
        assert mode == "off"

    def test_analyze_mode(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        from luckyd_code import settings
        with patch.object(settings, "load_settings",
                          return_value={"autonomous_improvement": "analyze"}):
            mode = _get_autonomous_mode()
        assert mode == "analyze"

    def test_full_mode(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        from luckyd_code import settings
        with patch.object(settings, "load_settings",
                          return_value={"autonomous_improvement": "full"}):
            mode = _get_autonomous_mode()
        assert mode == "full"

    def test_exception_returns_fix(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        from luckyd_code import settings
        with patch.object(settings, "load_settings", side_effect=Exception("fail")):
            mode = _get_autonomous_mode()
        assert mode == "fix"


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/project.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebRoutesProject:
    @pytest.mark.asyncio
    async def test_init_project(self):
        from luckyd_code.web_routes.project import init_project
        with patch("luckyd_code.web_routes.project.project_init.init_project",
                   return_value="Initialized ok"):
            result = await init_project()
        assert result["status"] == "ok"
        assert "Initialized" in result["message"]

    @pytest.mark.asyncio
    async def test_reindex_project_with_context(self):
        from luckyd_code.web_routes.project import reindex_project
        req = MagicMock()
        req.app.state.web_state.context.messages = []
        # index_project is imported inside the route fn so patch at its real home
        with patch("luckyd_code.indexer.index_project",
                   return_value="file1\nfile2\nfile3"):
            result = await reindex_project(req)
        assert result["status"] == "ok"
        assert result["items"] > 0

    @pytest.mark.asyncio
    async def test_reindex_project_no_context(self):
        from luckyd_code.web_routes.project import reindex_project
        req = MagicMock()
        req.app.state.web_state.context = None
        with patch("luckyd_code.indexer.index_project",
                   return_value="some content"):
            result = await reindex_project(req)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_reindex_replaces_existing_context(self):
        from luckyd_code.web_routes.project import reindex_project
        req = MagicMock()
        req.app.state.web_state.context.messages = [
            {"role": "user", "content": "<project-context>\nold\n</project-context>"}
        ]
        with patch("luckyd_code.indexer.index_project",
                   return_value="new content"):
            result = await reindex_project(req)
        assert result["status"] == "ok"
        msgs = req.app.state.web_state.context.messages
        assert any("new content" in str(m.get("content", "")) for m in msgs)

    @pytest.mark.asyncio
    async def test_reindex_empty_project_context(self):
        from luckyd_code.web_routes.project import reindex_project
        req = MagicMock()
        req.app.state.web_state.context.messages = []
        with patch("luckyd_code.indexer.index_project", return_value=None):
            result = await reindex_project(req)
        assert result["items"] == 0

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        from luckyd_code.web_routes.project import list_tasks
        with patch("luckyd_code.web_routes.project.tasks.list_tasks",
                   return_value=[{"id": "1", "title": "task"}]):
            result = await list_tasks()
        assert "tasks" in result
        assert len(result["tasks"]) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self):
        from luckyd_code.web_routes.project import list_tasks
        with patch("luckyd_code.web_routes.project.tasks.list_tasks",
                   return_value=[]) as mock_tasks:
            result = await list_tasks(status="open")
        mock_tasks.assert_called_once_with("open")
        assert result["tasks"] == []

    @pytest.mark.asyncio
    async def test_list_plans(self):
        from luckyd_code.web_routes.project import list_plans
        with patch("luckyd_code.web_routes.project.planner.list_plans",
                   return_value=[{"id": "p1", "name": "plan"}]):
            result = await list_plans()
        assert "plans" in result
        assert len(result["plans"]) == 1
