"""Tests for the Docker sandbox module."""

import subprocess
from unittest.mock import patch, MagicMock


from luckyd_code.sandbox import (
    check_docker,
    Sandbox,
    get_sandbox,
    is_sandbox_available,
)


class TestCheckDocker:
    def test_docker_available(self):
        """check_docker should return True when docker is found."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", return_value=mock_result):
            available, version = check_docker()
            assert available is True
            assert "Docker version" in version

    def test_docker_not_found(self):
        """check_docker should return False when docker binary doesn't exist."""
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            available, version = check_docker()
            assert available is False
            assert "not found" in version.lower()

    def test_docker_timed_out(self):
        """check_docker should return False when docker times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)):
            available, version = check_docker()
            assert available is False

    def test_docker_nonzero_return(self):
        """check_docker should return False when docker returns non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            available, version = check_docker()
            assert available is False


class TestSandbox:
    def test_init_sets_available(self):
        """Sandbox.__init__ should check docker availability."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", return_value=mock_result):
            sb = Sandbox()
            assert sb.available is True

    def test_init_sets_unavailable(self):
        """Sandbox.__init__ should set available False when docker missing."""
        with patch("subprocess.run", side_effect=FileNotFoundError("")):
            sb = Sandbox()
            assert sb.available is False

    def test_run_docker_success(self):
        """Sandbox.run with docker should execute and return output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello from container"
        mock_result.stderr = ""

        docker_check = MagicMock()
        docker_check.returncode = 0
        docker_check.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", side_effect=[docker_check, mock_result]):
            sb = Sandbox()
            stdout, stderr, rc = sb.run("echo hello")
            assert rc == 0
            assert stdout == "hello from container"

    def test_run_docker_timeout(self):
        """Sandbox.run with docker should handle timeout."""
        docker_check = MagicMock()
        docker_check.returncode = 0
        docker_check.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", side_effect=[docker_check, subprocess.TimeoutExpired("docker", 5)]):
            sb = Sandbox()
            stdout, stderr, rc = sb.run("sleep 100", timeout=5)
            assert rc == -1
            assert "timed out" in stderr.lower()

    def test_run_docker_os_error(self):
        """Sandbox.run with docker should handle OSError."""
        docker_check = MagicMock()
        docker_check.returncode = 0
        docker_check.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", side_effect=[docker_check, OSError("docker daemon not running")]):
            sb = Sandbox()
            stdout, stderr, rc = sb.run("echo hello")
            assert rc == -1
            assert "Sandbox error" in stderr

    def test_run_direct_fallback(self):
        """Sandbox.run should fall back to direct execution when docker unavailable."""
        with patch("subprocess.run", side_effect=FileNotFoundError("")) as mock_run:
            # First call is _check (docker --version), second is _run_direct
            # But _check caches result, need separate approach
            pass

        # Better approach: create Sandbox with docker unavailable, then test _run_direct
        with patch.object(Sandbox, "_check", lambda self: setattr(self, "available", False)):
            sb = Sandbox()
            assert sb.available is False

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "direct result"
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result) as mock_run:
                stdout, stderr, rc = sb.run("echo direct", timeout=10)
                assert rc == 0
                assert stdout == "direct result"
                # Verify it used shell=True (direct execution path)
                assert mock_run.call_args[1].get("shell") is True

    def test_run_direct_timeout(self):
        """Direct execution should handle timeout."""
        with patch.object(Sandbox, "_check", lambda self: setattr(self, "available", False)):
            sb = Sandbox()
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
                stdout, stderr, rc = sb.run("sleep 100", timeout=5)
                assert rc == -1
                assert "timed out" in stderr.lower()

    def test_run_direct_exception(self):
        """Direct execution should handle unexpected exceptions."""
        with patch.object(Sandbox, "_check", lambda self: setattr(self, "available", False)):
            sb = Sandbox()
            with patch("subprocess.run", side_effect=PermissionError("access denied")):
                stdout, stderr, rc = sb.run("somecommand")
                assert "Error:" in stderr

    def test_pull_image_success(self):
        """pull_image should return success message."""
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "Docker version 24.0.7"

        mock_pull = MagicMock()
        mock_pull.returncode = 0
        mock_pull.stdout = "Pulled"
        mock_pull.stderr = ""

        with patch("subprocess.run", side_effect=[mock_check, mock_pull]):
            sb = Sandbox()
            result = sb.pull_image()
            assert "Pulled" in result

    def test_pull_image_not_available(self):
        """pull_image should return early when docker unavailable."""
        with patch.object(Sandbox, "_check", lambda self: setattr(self, "available", False)):
            sb = Sandbox()
            result = sb.pull_image()
            assert "not available" in result.lower()

    def test_pull_image_fail(self):
        """pull_image should handle pull failure."""
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "Docker version 24.0.7"

        mock_pull = MagicMock()
        mock_pull.returncode = 1
        mock_pull.stdout = ""
        mock_pull.stderr = "Error response from daemon"

        with patch("subprocess.run", side_effect=[mock_check, mock_pull]):
            sb = Sandbox()
            result = sb.pull_image()
            assert "Failed" in result

    def test_pull_image_timeout(self):
        """pull_image should handle timeout."""
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "Docker version 24.0.7"

        with patch("subprocess.run", side_effect=[mock_check, subprocess.TimeoutExpired("docker pull", 120)]):
            sb = Sandbox()
            result = sb.pull_image()
            assert "timed out" in result.lower()

    def test_ensure_image_returns_true(self):
        """ensure_image should return True when image is available."""
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "Docker version 24.0.7"

        mock_inspect = MagicMock()
        mock_inspect.returncode = 0
        mock_inspect.stdout = "found"
        mock_inspect.stderr = ""

        with patch("subprocess.run", side_effect=[mock_check, mock_inspect]):
            sb = Sandbox()
            assert sb.ensure_image() is True

    def test_ensure_image_not_available(self):
        """ensure_image should return False when docker unavailable."""
        with patch.object(Sandbox, "_check", lambda self: setattr(self, "available", False)):
            sb = Sandbox()
            assert sb.ensure_image() is False

    def test_ensure_image_pulls_when_missing(self):
        """ensure_image should pull when image is missing locally."""
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "Docker version 24.0.7"

        mock_inspect_fail = MagicMock()
        mock_inspect_fail.returncode = 1
        mock_inspect_fail.stdout = ""
        mock_inspect_fail.stderr = "No such image"

        mock_pull = MagicMock()
        mock_pull.returncode = 0
        mock_pull.stdout = "Pulled"
        mock_pull.stderr = ""

        mock_inspect_ok = MagicMock()
        mock_inspect_ok.returncode = 0
        mock_inspect_ok.stdout = "found"
        mock_inspect_ok.stderr = ""

        with patch("subprocess.run", side_effect=[mock_check, mock_inspect_fail, mock_pull, mock_inspect_ok]):
            sb = Sandbox()
            assert sb.ensure_image() is True


class TestSandboxSingleton:
    def test_get_sandbox_returns_instance(self):
        """get_sandbox should return a Sandbox instance."""
        with patch("luckyd_code.sandbox.Sandbox._check", lambda self: setattr(self, "available", False)):
            sb = get_sandbox()
            assert isinstance(sb, Sandbox)

    def test_get_sandbox_returns_same(self):
        """get_sandbox should return the same instance each time."""
        with patch("luckyd_code.sandbox.Sandbox._check", lambda self: setattr(self, "available", False)):
            sb1 = get_sandbox()
            sb2 = get_sandbox()
            assert sb1 is sb2

    def test_is_sandbox_available_returns_bool(self):
        """is_sandbox_available should return a boolean."""
        with patch("luckyd_code.sandbox.Sandbox._check", lambda self: setattr(self, "available", False)):
            result = is_sandbox_available()
            assert result is False


    def test_sandbox_uses_custom_image(self):
        """Sandbox should accept a custom image name."""
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="Docker 24.0.7")):
            sb = Sandbox(image="ubuntu:22.04")
            assert sb.image == "ubuntu:22.04"
