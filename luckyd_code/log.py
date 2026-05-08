"""Structured logging for DeepSeek Code."""

import sys
import logging
from pathlib import Path
from datetime import datetime

from ._data_dir import data_path

_LOG_DIR = data_path("logs")
_initialized = False


def setup_logging(level: str = "INFO", log_file: str | None = None) -> logging.Logger:
    """Initialize logging system. Safe to call multiple times."""
    global _initialized

    logger = logging.getLogger("luckyd_code")
    if _initialized:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler (warnings and above)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)

    # File handler (all levels)
    if log_file:
        log_path = Path(log_file)
    else:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    try:
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setLevel(getattr(logging, level.upper(), logging.INFO))
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(fh)
        logger.info(f"Logging initialized: {log_path}")
    except Exception as e:
        logger.warning(f"Could not create log file: {e}")

    _initialized = True
    return logger


def get_logger() -> logging.Logger:
    """Get the project logger. Initializes with defaults if not already set up."""
    return setup_logging()
