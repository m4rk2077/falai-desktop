"""
App logging utilities.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.utils.app_paths import get_log_dir, get_log_path


def _get_log_dir() -> Path:
    return get_log_dir()


def setup_logging() -> Path:
    """
    Configure root logging to file and console.
    Returns log file path.
    """
    root_logger = logging.getLogger()
    if getattr(root_logger, "_falai_configured", False):
        for handler in root_logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                return Path(handler.baseFilename)
        return get_log_path()

    log_dir = _get_log_dir()
    log_path = get_log_path()

    level_name = os.getenv("FALAI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    root_logger._falai_configured = True  # type: ignore[attr-defined]
    return log_path


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "falai")
