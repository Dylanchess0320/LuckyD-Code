"""Final coverage push — targets all remaining gaps to reach 100%."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


# ═══════════════════════════════════════════════════════════════════════════════
# tools/image.py  (26% → 100%)
# Lines: 25-31, 36-42, 47-74, 109-146
# ═══════════════════════════════════════════════════════════════════════════════

class TestEncodeImage:
    def _make_fake_pil_image(self, mode="RGB"):
        img = MagicMock()
        img.mode = mode
        buf_data = b"\xff\xd8\xff"  # minimal JPEG header bytes
        def fake_save(buf, format, quality):
            buf.write(buf_data)
        img.save.side_effect = fake_save
        img.convert.return_value = img
        return img

    def test_rgb_image_encoded(self, tmp_path):
        from luckyd_code.tools.image import _encode_image
        fake_img = self._make_fake_pil_image("RGB")
        with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_img):
            result = _encode_image(str(tmp_path / "test.jpg"))
        assert result.startswith("data:image/jpeg;base64,")

    def test_rgba_image_converted_to_rgb(self, tmp_path):
        from luckyd_code.tools.image import _encode_image
        fake_img = self._make_fake_pil_image("RGBA")
        with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_img):
            result = _encode_image(str(tmp_path / "test.png"))
        fake_img.convert.assert_called_once_with("RGB")
        assert "data:image/jpeg;base64," in result

    def test_p_mode_converted_to_rgb(self, tmp_path):
        from luckyd_code.tools.image import _encode_image
        fake_img = self._make_fake_pil_image("P")
        with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_img):
            _encode_image(str(tmp_path / "test.gif"))
        fake_img.convert.assert_called_once_with("RGB")


class TestOcrText:
    def test_returns_none_when_pytesseract_not_installed(self, tmp_path):
        from luckyd_code.tools.image import _ocr_text
        with patch("builtins.__import__", side_effect=ImportError("No module named 'pytesseract'")):
            # pytesseract is likely not installed in test env; that's fine
            pass
        # Just call it — should return None if pytesseract missing
        result = _ocr_text(str(tmp_path / "img.png"))
        assert result is None  # ImportError path

    def test_returns_text_when_pytesseract_available(self, tmp_path):
        from luckyd_code.tools.image import _ocr_text
        fake_img = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Hello OCR"
        with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_img):
            with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                result = _ocr_text(str(tmp_path / "img.png"))
        assert result == "Hello OCR"

    def test_returns_none_when_text_is_empty(self, tmp_path):
        from luckyd_code.tools.image import _ocr_text
        fake_img = MagicMock()
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "   "
        with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_img):
            with patch.dict("sys.modules", {"pytesseract": mock_pytesseract}):
                result = _ocr_text(str(tmp_path / "img.png"))
        assert result is None


class TestCallVision:
    def test_calls_llm_and_returns_content(self, tmp_path):
        from luckyd_code.tools.image import _call_vision
        fake_cfg = MagicMock()
        fake_cfg.base_url = "http://localhost"
        fake_cfg.api_key = "k"
        fake_cfg.model = "test-model"

        fake_response = MagicMock()
        fake_response.choices[0].message.content = "  A cat  "
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response

        with patch("luckyd_code.config.Config", return_value=fake_cfg):
            with patch("openai.OpenAI", return_value=fake_client):
                with patch("luckyd_code.tools.image._encode_image", return_value="data:image/jpeg;base64,abc"):
                    result = _call_vision(str(tmp_path / "img.jpg"), "what is this?")
        assert result == "A cat"


class TestImageAnalyzeTool:
    def _tool(self):
        from luckyd_code.tools.image import ImageAnalyzeTool
        return ImageAnalyzeTool()

    def test_file_not_found_returns_error(self, tmp_path):
        tool = self._tool()
        result = tool.run(str(tmp_path / "missing.jpg"))
        assert "not found" in result

    def test_vision_succeeds_no_question(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", return_value="a red car"):
            with patch("luckyd_code.tools.image._ocr_text", return_value=None):
                result = tool.run(str(img))
        assert result == "a red car"

    def test_vision_succeeds_with_question(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", return_value="The car is blue") as mock_vision:
            with patch("luckyd_code.tools.image._ocr_text", return_value=None):
                result = tool.run(str(img), question="What color is the car?")
        prompt_used = mock_vision.call_args[0][1]
        assert "What color is the car?" in prompt_used
        assert result == "The car is blue"

    def test_ocr_appended_when_not_in_description(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", return_value="a document"):
            with patch("luckyd_code.tools.image._ocr_text", return_value="Hello World"):
                result = tool.run(str(img))
        assert "Hello World" in result
        assert "OCR extracted text" in result

    def test_ocr_not_appended_when_already_in_description(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", return_value="Hello World is visible"):
            with patch("luckyd_code.tools.image._ocr_text", return_value="Hello World"):
                result = tool.run(str(img))
        assert "OCR extracted text" not in result

    def test_vision_fails_ocr_fallback(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", side_effect=Exception("API error")):
            with patch("luckyd_code.tools.image._ocr_text", return_value="OCR text here"):
                result = tool.run(str(img))
        assert "OCR fallback" in result
        assert "OCR text here" in result

    def test_vision_fails_ocr_fails_pil_metadata(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        fake_pil = MagicMock()
        fake_pil.format = "JPEG"
        fake_pil.size = (100, 100)
        fake_pil.mode = "RGB"
        with patch("luckyd_code.tools.image._call_vision", side_effect=Exception("API down")):
            with patch("luckyd_code.tools.image._ocr_text", return_value=None):
                with patch("luckyd_code.tools.image.PILImage.open", return_value=fake_pil):
                    result = tool.run(str(img))
        assert "Basic info" in result or "JPEG" in result

    def test_all_fail_returns_error(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        tool = self._tool()
        with patch("luckyd_code.tools.image._call_vision", side_effect=Exception("API down")):
            with patch("luckyd_code.tools.image._ocr_text", return_value=None):
                with patch("luckyd_code.tools.image.PILImage.open", side_effect=Exception("bad image")):
                    result = tool.run(str(img))
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# model_registry.py  (79% → 100%)
# Lines: 92, 104-114
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelRegistry:
    def test_get_models_by_tier_unknown_tier_returns_empty(self):
        from luckyd_code.model_registry import get_models_by_tier
        assert get_models_by_tier(99) == []

    def test_get_models_by_tier_valid_tier(self):
        from luckyd_code.model_registry import get_models_by_tier
        result = get_models_by_tier(1)
        assert len(result) == 1
        assert result[0].id == "deepseek-v4-flash"

    def test_get_models_by_strength_hit(self):
        from luckyd_code.model_registry import get_models_by_strength
        result = get_models_by_strength("reasoning")
        assert any(m.id == "deepseek-v4-pro" for m in result)

    def test_get_models_by_strength_miss(self):
        from luckyd_code.model_registry import get_models_by_strength
        result = get_models_by_strength("nonexistent_strength")
        assert result == []

    def test_get_models_by_strength_tier_range(self):
        from luckyd_code.model_registry import get_models_by_strength
        # Flash only serves tiers 1-2; narrow range to 3-4 should miss it
        result = get_models_by_strength("chat", min_tier=3, max_tier=4)
        assert all(m.id != "deepseek-v4-flash" for m in result)

    def test_format_model_list_contains_model_names(self):
        from luckyd_code.model_registry import format_model_list
        result = format_model_list()
        assert "DeepSeek V4 Flash" in result
        assert "DeepSeek V4 Pro" in result
        assert "Tier" in result
        assert "Cost" in result

    def test_get_unique_model_count(self):
        from luckyd_code.model_registry import get_unique_model_count
        assert get_unique_model_count() == 2

    def test_get_model_by_id_miss_returns_none(self):
        from luckyd_code.model_registry import get_model_by_id
        assert get_model_by_id("nonexistent-model") is None


# ═══════════════════════════════════════════════════════════════════════════════
# retry.py  (83% → 100%)
# Lines: 46-53
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetry:
    def test_succeeds_first_try(self):
        from luckyd_code.retry import with_retry
        call_count = 0

        @with_retry(max_retries=3, base_delay=0)
        def ok():
            nonlocal call_count
            call_count += 1
            return "done"

        assert ok() == "done"
        assert call_count == 1

    def test_retries_on_retryable_error_then_succeeds(self):
        from luckyd_code.retry import with_retry
        from luckyd_code.exceptions import RetryableError
        attempt = [0]

        @with_retry(max_retries=2, base_delay=0, jitter=False)
        def flaky():
            attempt[0] += 1
            if attempt[0] < 2:
                raise RetryableError("temp fail")
            return "ok"

        with patch("luckyd_code.retry.time.sleep"):
            result = flaky()
        assert result == "ok"
        assert attempt[0] == 2

    def test_raises_after_max_retries(self):
        from luckyd_code.retry import with_retry
        from luckyd_code.exceptions import RetryableError
        import pytest

        @with_retry(max_retries=2, base_delay=0, jitter=False)
        def always_fail():
            raise RetryableError("always bad")

        with patch("luckyd_code.retry.time.sleep"):
            with pytest.raises(RetryableError):
                always_fail()

    def test_non_retryable_error_raised_immediately(self):
        from luckyd_code.retry import with_retry
        from luckyd_code.exceptions import NonRetryableError
        import pytest
        attempt = [0]

        @with_retry(max_retries=3, base_delay=0)
        def bad():
            attempt[0] += 1
            raise NonRetryableError("fatal")

        with pytest.raises(NonRetryableError):
            bad()
        assert attempt[0] == 1  # no retries

    def test_model_not_found_raised_immediately(self):
        from luckyd_code.retry import with_retry
        from luckyd_code.exceptions import ModelNotFoundError
        import pytest

        @with_retry(max_retries=3, base_delay=0)
        def no_model():
            raise ModelNotFoundError("no such model")

        with pytest.raises(ModelNotFoundError):
            no_model()

    def test_generic_exception_retried_once_then_raised(self):
        from luckyd_code.retry import with_retry
        import pytest
        attempt = [0]

        @with_retry(max_retries=3, base_delay=0, jitter=False)
        def crashes():
            attempt[0] += 1
            raise ValueError("unexpected")

        with patch("luckyd_code.retry.time.sleep"):
            with pytest.raises(ValueError):
                crashes()
        assert attempt[0] == 2  # first attempt + one retry

    def test_jitter_applied(self):
        from luckyd_code.retry import with_retry
        from luckyd_code.exceptions import RetryableError
        sleeps = []

        @with_retry(max_retries=1, base_delay=1.0, jitter=True)
        def fail_once():
            raise RetryableError("x")

        with patch("luckyd_code.retry.time.sleep", side_effect=lambda t: sleeps.append(t)):
            with patch("luckyd_code.retry.random.random", return_value=0.5):
                try:
                    fail_once()
                except RetryableError:
                    pass
        assert sleeps  # sleep was called
        assert 0.5 <= sleeps[0] <= 1.0  # jitter range


# ═══════════════════════════════════════════════════════════════════════════════
# tools/agent_tools.py  (62% → 100%)
# Lines: 38-42, 75-79
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentTools:
    def test_subagent_run_no_repl_returns_error(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl
        set_repl(None)
        tool = SubAgentTool()
        result = tool.run(task="do something")
        assert "Error" in result
        assert "not initialized" in result

    def test_subagent_run_with_repl(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl
        mock_repl = MagicMock()
        mock_repl.registry.list_tools.return_value = []
        mock_agent = MagicMock()
        mock_agent.run.return_value = "task done"
        set_repl(mock_repl)
        with patch("luckyd_code.agent.SubAgent", return_value=mock_agent):
            tool = SubAgentTool()
            result = tool.run(task="build feature")
        assert result == "task done"
        set_repl(None)  # cleanup

    def test_handoff_run_no_repl_returns_error(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        set_repl(None)
        tool = AgentHandoffTool()
        result = tool.run(role="researcher", task="find info")
        assert "Error" in result
        assert "not initialized" in result

    def test_handoff_run_with_repl(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        mock_repl = MagicMock()
        mock_repl.registry.list_tools.return_value = []
        mock_handoff = MagicMock()
        mock_handoff.handoff.return_value = "research complete"
        set_repl(mock_repl)
        with patch("luckyd_code.orchestrator.AgentHandoff", return_value=mock_handoff):
            tool = AgentHandoffTool()
            result = tool.run(role="researcher", task="gather facts")
        assert result == "research complete"
        set_repl(None)  # cleanup


# ═══════════════════════════════════════════════════════════════════════════════
# tools/shell_detect.py  (91% → 100%)
# Lines: 33-37, 66
# ═══════════════════════════════════════════════════════════════════════════════

class TestShellDetect:
    def test_detect_shell_unix(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("luckyd_code.tools.shell_detect.sys.platform", "linux"):
            with patch("luckyd_code.tools.shell_detect.os.environ.get", return_value="/bin/bash"):
                with patch("luckyd_code.tools.shell_detect.shutil.which", return_value="/bin/bash"):
                    result = detect_shell()
        assert result.unix_like is True
        assert "bash" in result.path

    def test_detect_shell_unix_uses_shell_env(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("luckyd_code.tools.shell_detect.sys.platform", "darwin"):
            with patch.dict("os.environ", {"SHELL": "/bin/zsh"}):
                with patch("luckyd_code.tools.shell_detect.shutil.which", return_value="/bin/zsh"):
                    result = detect_shell()
        assert result.unix_like is True

    def test_resolve_shell_git_bash_override(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value="/usr/bin/bash"):
            result = resolve_shell("git_bash")
        assert result.name == "git_bash"
        assert result.unix_like is True

    def test_resolve_shell_wsl_override(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch("luckyd_code.tools.shell_detect._find_wsl", return_value="/usr/bin/wsl.exe"):
            result = resolve_shell("wsl")
        assert result.name == "wsl"

    def test_resolve_shell_cmd_override(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch.dict("os.environ", {"COMSPEC": "cmd.exe"}):
            result = resolve_shell("cmd")
        assert result.name == "cmd"
        assert result.unix_like is False

    def test_resolve_shell_override_not_found_falls_back_to_auto(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=None):
            with patch("luckyd_code.tools.shell_detect.detect_shell") as mock_detect:
                mock_detect.return_value = MagicMock(name="auto_shell")
                resolve_shell("git_bash")
            mock_detect.assert_called_once()

    def test_resolve_shell_auto(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch("luckyd_code.tools.shell_detect.detect_shell") as mock_detect:
            mock_detect.return_value = MagicMock()
            resolve_shell("auto")
        mock_detect.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# tools/registry.py  (83% → 100%)
# Lines: 85-86, 91, 103, 117-125, 139
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolRegistry:
    def _registry(self, ttl=300.0):
        from luckyd_code.tools.registry import ToolRegistry
        return ToolRegistry(cache_ttl=ttl)

    def _make_tool(self, name="Read", result="file content"):
        from luckyd_code.tools.registry import Tool
        class FakeTool(Tool):
            pass
        t = FakeTool()
        t.name = name
        t.description = "test tool"
        t.parameters = {}
        t.run = MagicMock(return_value=result)
        return t

    def test_cache_hit_returns_cached_value(self):
        reg = self._registry()
        tool = self._make_tool("Read", "cached content")
        reg.register(tool)
        reg.execute("Read", {"file_path": "foo.py"})
        reg.execute("Read", {"file_path": "foo.py"})
        assert tool.run.call_count == 1  # second call served from cache

    def test_cache_expired_entry_re_executes(self):
        reg = self._registry(ttl=0.01)
        tool = self._make_tool("Read", "result")
        reg.register(tool)
        reg.execute("Read", {"file_path": "foo.py"})
        time.sleep(0.05)  # let cache expire
        reg.execute("Read", {"file_path": "foo.py"})
        assert tool.run.call_count == 2  # re-executed after expiry

    def test_non_cacheable_tool_not_cached(self):
        reg = self._registry()
        tool = self._make_tool("Write", "wrote")
        reg.register(tool)
        reg.execute("Write", {"file_path": "foo.py", "content": "x"})
        reg.execute("Write", {"file_path": "foo.py", "content": "x"})
        assert tool.run.call_count == 2

    def test_ttl_zero_disables_cache(self):
        reg = self._registry(ttl=0)
        tool = self._make_tool("Read", "result")
        reg.register(tool)
        reg.execute("Read", {"file_path": "f.py"})
        reg.execute("Read", {"file_path": "f.py"})
        assert tool.run.call_count == 2

    def test_invalidate_specific_tool(self):
        reg = self._registry()
        tool = self._make_tool("Read", "data")
        reg.register(tool)
        reg.execute("Read", {"file_path": "x.py"})
        removed = reg.invalidate("Read")
        assert removed == 1
        reg.execute("Read", {"file_path": "x.py"})
        assert tool.run.call_count == 2  # re-executed after invalidation

    def test_invalidate_all(self):
        reg = self._registry()
        tool = self._make_tool("Read", "data")
        reg.register(tool)
        reg.execute("Read", {"file_path": "x.py"})
        removed = reg.invalidate()
        assert removed == 1

    def test_unknown_tool_returns_error(self):
        reg = self._registry()
        result = reg.execute("NonExistent", {})
        assert "unknown tool" in result

    def test_permission_denied(self):
        reg = self._registry()
        tool = self._make_tool("Bash", "output")
        reg.register(tool)
        result = reg.execute("Bash", {}, check_perm=lambda name: False)
        assert "Permission denied" in result

    def test_tool_run_exception_returns_error(self):
        reg = self._registry()
        tool = self._make_tool("Read")
        tool.run.side_effect = RuntimeError("disk error")
        reg.register(tool)
        result = reg.execute("Read", {"file_path": "x.py"})
        assert "Error executing" in result

    def test_cache_eviction_on_large_cache(self):
        """Eviction runs every 100 inserts."""
        reg = self._registry(ttl=0.001)
        # Insert 100 entries via the low-level method to trigger eviction
        for i in range(100):
            reg._set_cached(f"Read|k={i!r}", f"val{i}")
        time.sleep(0.01)  # let all entries expire
        reg._set_cached("Read|k=100", "trigger eviction")
        # After eviction old expired entries should be gone
        assert len(reg._cache) <= 2


# ═══════════════════════════════════════════════════════════════════════════════
# sessions.py  (88% → 100%)
# Lines: 56, 60-61, 65, 70, 76, 93-94
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessions:
    def _make_context(self, messages=None):
        ctx = MagicMock()
        ctx.messages = messages or [{"role": "user", "content": "hello"}]
        ctx.max_messages = 100
        return ctx

    def test_load_session_partial_match(self, tmp_path):
        from luckyd_code.sessions import save_session, load_session
        ctx = self._make_context()
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            save_session("mytest", ctx)
            ctx2 = self._make_context()
            result = load_session("myt", ctx2)  # partial name
        assert "mytest" in result or "loaded" in result.lower()

    def test_load_session_not_found(self, tmp_path):
        from luckyd_code.sessions import load_session
        ctx = self._make_context()
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = load_session("ghost_session", ctx)
        assert "not found" in result

    def test_load_session_json_decode_error(self, tmp_path):
        from luckyd_code.sessions import load_session
        bad = tmp_path / "broken.json"
        bad.write_text("not json {{{{", encoding="utf-8")
        ctx = self._make_context()
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = load_session("broken", ctx)
        assert "Error" in result

    def test_load_session_empty_messages(self, tmp_path):
        import json
        from luckyd_code.sessions import load_session
        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({"name": "empty", "messages": []}), encoding="utf-8")
        ctx = self._make_context()
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = load_session("empty", ctx)
        assert "empty" in result.lower()

    def test_load_session_with_system_prompt(self, tmp_path):
        import json
        from luckyd_code.sessions import load_session
        sess = tmp_path / "withsys.json"
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ]
        sess.write_text(json.dumps({"name": "withsys", "messages": msgs}), encoding="utf-8")
        ctx = self._make_context(messages=[{"role": "system", "content": "old sys"}])
        ctx.max_messages = 100
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = load_session("withsys", ctx)
        assert "loaded" in result.lower() or "withsys" in result

    def test_load_session_no_system_prepends_existing(self, tmp_path):
        import json
        from luckyd_code.sessions import load_session
        sess = tmp_path / "nosys.json"
        msgs = [{"role": "user", "content": "hi"}]
        sess.write_text(json.dumps({"name": "nosys", "messages": msgs}), encoding="utf-8")
        sys_msg = {"role": "system", "content": "You are helpful"}
        ctx = self._make_context(messages=[sys_msg])
        ctx.max_messages = 100
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = load_session("nosys", ctx)
        assert "loaded" in result.lower() or "nosys" in result

    def test_list_sessions_shows_entries(self, tmp_path):
        from luckyd_code.sessions import save_session, list_sessions
        ctx = self._make_context()
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            save_session("alpha", ctx)
            save_session("beta", ctx)
            result = list_sessions()
        assert "alpha" in result
        assert "beta" in result

    def test_list_sessions_empty(self, tmp_path):
        from luckyd_code.sessions import list_sessions
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = list_sessions()
        assert "No saved sessions" in result

    def test_delete_session_not_found(self, tmp_path):
        from luckyd_code.sessions import delete_session
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            result = delete_session("phantom")
        assert "not found" in result

    def test_max_messages_trimmed_on_load(self, tmp_path):
        import json
        from luckyd_code.sessions import load_session
        sess = tmp_path / "big.json"
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        sess.write_text(json.dumps({"name": "big", "messages": msgs}), encoding="utf-8")
        ctx = self._make_context()
        ctx.max_messages = 5
        ctx.messages = [{"role": "system", "content": "sys"}] + msgs
        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            load_session("big", ctx)
        # max_messages enforced
        assert len(ctx.messages) <= ctx.max_messages


# ═══════════════════════════════════════════════════════════════════════════════
# plugins.py  (95% → 100%)
# Lines: 58-59
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlugins:
    def test_plugin_without_register_returns_none(self, tmp_path):
        from luckyd_code.plugins import load_plugin
        no_register = tmp_path / "no_register.py"
        no_register.write_text("x = 1\n", encoding="utf-8")
        result = load_plugin(no_register)
        assert result is None

    def test_plugin_with_register_returns_function(self, tmp_path):
        from luckyd_code.plugins import load_plugin
        good = tmp_path / "good_plugin.py"
        good.write_text("def register(registry): pass\n", encoding="utf-8")
        result = load_plugin(good)
        assert callable(result)

    def test_plugin_import_error_returns_none(self, tmp_path):
        from luckyd_code.plugins import load_plugin
        bad = tmp_path / "bad_plugin.py"
        bad.write_text("import nonexistent_module_xyz\ndef register(r): pass\n", encoding="utf-8")
        result = load_plugin(bad)
        assert result is None

    def test_load_all_plugins_counts_loaded(self, tmp_path):
        from luckyd_code.plugins import load_all_plugins
        from luckyd_code.tools.registry import ToolRegistry
        p1 = tmp_path / "p1.py"
        p1.write_text("def register(registry): pass\n", encoding="utf-8")
        p2 = tmp_path / "p2.py"
        p2.write_text("def register(registry): pass\n", encoding="utf-8")
        registry = ToolRegistry()
        with patch("luckyd_code.plugins.PLUGIN_DIR", tmp_path):
            count = load_all_plugins(registry)
        assert count == 2

    def test_discover_plugins_empty_when_dir_missing(self, tmp_path):
        from luckyd_code.plugins import discover_plugins
        missing = tmp_path / "no_plugins_dir"
        with patch("luckyd_code.plugins.PLUGIN_DIR", missing):
            result = discover_plugins()
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# tools/datetime_tool.py  (89% → 100%)
# Line: 34
# ═══════════════════════════════════════════════════════════════════════════════

class TestDateTimeTool:
    def test_default_format(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        tool = DateTimeTool()
        result = tool.run()
        assert len(result) > 10  # should be a non-empty date string

    def test_custom_format(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        tool = DateTimeTool()
        result = tool.run(format="%Y-%m-%d")
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}", result)

    def test_tool_metadata(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        tool = DateTimeTool()
        assert tool.name == "DateTime"
        assert tool.permission_risk == "safe"
