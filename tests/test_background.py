"""Tests for the background autonomous agent module."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock


from luckyd_code.background import (
    BackgroundTask,
    BackgroundAgent,
)


class TestBackgroundTask:
    def test_init_sets_defaults(self):
        """BackgroundTask should initialize with pending status."""
        task = BackgroundTask("bg_1", "Test description")
        assert task.task_id == "bg_1"
        assert task.description == "Test description"
        assert task.status == "pending"
        assert task.result == ""
        assert task.error == ""
        assert task.started_at is None
        assert task.finished_at is None

    def test_status_transitions(self):
        """BackgroundTask status should be assignable."""
        task = BackgroundTask("bg_1", "desc")
        task.status = "running"
        assert task.status == "running"
        task.status = "done"
        assert task.status == "done"
        task.status = "error"
        assert task.status == "error"


class TestBackgroundAgent:
    def test_init_creates_background_dir(self):
        """BackgroundAgent should create the background directory."""
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            config = MagicMock()
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                _ = BackgroundAgent(config)
                assert bg_dir.exists()

    def test_start_task_returns_id(self):
        """start_task should return a task ID."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                task_id = agent.start_task("do something")
                assert task_id.startswith("bg_")

    def test_start_task_creates_pending_task(self):
        """start_task should register a pending task."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                task_id = agent.start_task("do something")
                statuses = agent.get_status(task_id)
                assert len(statuses) == 1
                assert statuses[0]["status"] in ("pending", "running", "error")
                assert statuses[0]["description"] == "do something"

    def test_get_status_all(self):
        """get_status with no task_id should return all tasks."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                agent.start_task("task 1")
                agent.start_task("task 2")
                all_statuses = agent.get_status()
                assert len(all_statuses) == 2

    def test_get_status_unknown(self):
        """get_status with unknown task_id should return empty list."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                statuses = agent.get_status("nonexistent_id")
                assert statuses == []

    def test_get_result_before_completion(self):
        """get_result should return None for unfinished tasks."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                task_id = agent.start_task("task")
                result = agent.get_result(task_id)
                assert result is None  # Not done yet

    def test_get_result_unknown(self):
        """get_result for unknown task should return None."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                assert agent.get_result("unknown") is None

    def test_task_lifecycle_done(self):
        """Task should transition through pending -> running -> done."""
        config = MagicMock()

        mock_agent = MagicMock()
        mock_agent.run.return_value = "Task completed successfully"

        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                with patch("luckyd_code.background.SubAgent", return_value=mock_agent):
                    agent = BackgroundAgent(config)
                    task_id = agent.start_task("test task")
                    # Wait a tiny bit for the thread to complete
                    time.sleep(0.5)
                    statuses = agent.get_status(task_id)
                    assert statuses[0]["status"] == "done"
                    assert mock_agent.run.called

                    # Get full result
                    result = agent.get_result(task_id)
                    assert result == "Task completed successfully"

    def test_task_lifecycle_error(self):
        """Task should transition to error when SubAgent raises."""
        config = MagicMock()

        mock_agent = MagicMock()
        mock_agent.run.side_effect = RuntimeError("Something went wrong")

        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                with patch("luckyd_code.background.SubAgent", return_value=mock_agent):
                    agent = BackgroundAgent(config)
                    task_id = agent.start_task("failing task")
                    time.sleep(0.5)
                    statuses = agent.get_status(task_id)
                    assert statuses[0]["status"] == "error"
                    assert statuses[0]["error"] == "Something went wrong"

    def test_save_task_persists_to_disk(self):
        """_save_task should write a JSON file."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                task_id = "bg_test_123"
                task = BackgroundTask(task_id, "test task")
                task.status = "done"
                task.result = "success"
                agent.tasks[task_id] = task
                agent._save_task(task_id)

                saved_file = bg_dir / f"{task_id}.json"
                assert saved_file.exists()
                data = json.loads(saved_file.read_text(encoding="utf-8"))
                assert data["id"] == task_id
                assert data["status"] == "done"
                assert data["result"] == "success"

    def test_save_task_nonexistent(self):
        """_save_task with unknown task_id should not raise."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                # Should not raise
                agent._save_task("nonexistent")

    def test_load_history_restores_tasks(self):
        """load_history should reconstruct tasks from disk."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            bg_dir.mkdir(parents=True)
            # Create a saved task file
            task_data = {
                "id": "bg_prev_1",
                "description": "previous task",
                "status": "done",
                "result": "completed",
                "error": "",
                "started_at": "2025-01-01T00:00:00",
                "finished_at": "2025-01-01T00:01:00",
            }
            (bg_dir / "bg_prev_1.json").write_text(json.dumps(task_data), encoding="utf-8")

            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                agent.load_history()
                assert "bg_prev_1" in agent.tasks
                assert agent.tasks["bg_prev_1"].description == "previous task"
                assert agent.tasks["bg_prev_1"].status == "done"

    def test_load_history_empty(self):
        """load_history with no saved files should not raise."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                agent.load_history()  # Should not raise
                assert len(agent.tasks) == 0

    def test_load_history_skips_corrupted(self):
        """load_history should skip corrupted JSON files."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            bg_dir.mkdir(parents=True)
            (bg_dir / "bg_bad.json").write_text("not json", encoding="utf-8")

            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                agent.load_history()  # Should not raise
                assert len(agent.tasks) == 0

    def test_status_includes_task_details(self):
        """get_status should include all relevant fields."""
        config = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            bg_dir = Path(tmp) / ".claude" / "background"
            with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
                agent = BackgroundAgent(config)
                task_id = agent.start_task("test task")
                time.sleep(0.1)
                statuses = agent.get_status(task_id)
                entry = statuses[0]
                assert "id" in entry
                assert "description" in entry
                assert "status" in entry
                assert "started_at" in entry
                assert "started_at" != ""
