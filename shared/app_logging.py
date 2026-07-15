"""Best-effort rotating disk logging for LaunchFlow."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from shared.app_paths import get_logs_dir


LOGGER_NAME = "launchflow"


def get_app_logger() -> logging.Logger:
    """Return a logger that never makes application startup depend on disk logging."""
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_launchflow_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logs_dir = get_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            logs_dir / "launchflow.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())

    logger._launchflow_configured = True
    return logger


def reset_app_logger_for_tests() -> None:
    """Close LaunchFlow handlers so isolated tests can switch data roots safely."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    if hasattr(logger, "_launchflow_configured"):
        delattr(logger, "_launchflow_configured")
