"""Shared data directory for LuckyD Code.

All persistent state lives under ``~/.luckyd-code/`` (user-global)
or ``<project>/.luckyd-code/`` (project-local).
"""

import logging
import os
import shutil
from pathlib import Path

_logger = logging.getLogger("luckyd_code._data_dir")

__all__ = [
    "DATA_DIR",
    "ensure_data_dir",
    "data_path",
    "legacy_path",
    "project_data_path",
    "project_legacy_path",
]

# ---------- user-global paths ----------

DATA_DIR = Path.home() / ".luckyd-code"

_LEGACY_DIR = Path.home() / ".deepseek-code"


def ensure_data_dir() -> Path:
    if _LEGACY_DIR.exists() and not DATA_DIR.exists():
        _migrate_from_legacy()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def data_path(*parts: str) -> Path:
    return ensure_data_dir() / Path(*parts)


def legacy_path(*parts: str) -> Path:
    return _LEGACY_DIR / Path(*parts)


# ---------- project-local paths ----------

_PROJECT_DATA_NAME = ".luckyd-code"
_LEGACY_PROJECT_DATA_NAME = ".deepseek-code"


def _ensure_project_data_dir(project_root: str | Path | None = None) -> Path:
    root = Path(project_root) if project_root else Path(os.getcwd())
    new_dir = root / _PROJECT_DATA_NAME
    legacy_dir = root / _LEGACY_PROJECT_DATA_NAME
    if legacy_dir.exists() and not new_dir.exists():
        try:
            _logger.info("Migrating project data from %s to %s", legacy_dir, new_dir)
            shutil.copytree(legacy_dir, new_dir, dirs_exist_ok=True)
        except Exception:
            _logger.warning(
                "Could not auto-migrate project data from %s", legacy_dir, exc_info=True
            )
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def project_data_path(*parts: str, root: str | Path | None = None) -> Path:
    return _ensure_project_data_dir(root) / Path(*parts)


def project_legacy_path(*parts: str, root: str | Path | None = None) -> Path:
    r = Path(root) if root else Path(os.getcwd())
    return r / _LEGACY_PROJECT_DATA_NAME / Path(*parts)


def _migrate_from_legacy() -> None:
    try:
        _logger.info("Migrating data from %s to %s", _LEGACY_DIR, DATA_DIR)
        shutil.copytree(_LEGACY_DIR, DATA_DIR, dirs_exist_ok=True)
        _logger.info("Migration complete")
    except Exception:
        _logger.warning("Could not auto-migrate from %s", _LEGACY_DIR, exc_info=True)
