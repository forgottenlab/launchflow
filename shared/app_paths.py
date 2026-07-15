"""Centralized paths for LaunchFlow mutable user data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DATA_ENV = "LAUNCHFLOW_DATA_DIR"
APP_DIR_NAME = "LaunchFlow"
APP_SUBDIRECTORIES = ("config", "data", "licenses", "logs", "plans", "cache", "temp")


class AppPathError(RuntimeError):
    """Raised when LaunchFlow cannot resolve or create its user data path."""


def get_app_data_dir() -> Path:
    """Return the user-writable LaunchFlow root without using cwd or the EXE directory."""
    override = os.environ.get(APP_DATA_ENV, "").strip()
    if override:
        path = Path(os.path.expandvars(override)).expanduser()
        if not path.is_absolute():
            raise AppPathError(f"{APP_DATA_ENV} 必须是绝对路径: {override}")
        return path

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME

    return Path.home() / ".local" / "share" / APP_DIR_NAME


def get_config_dir() -> Path:
    return get_app_data_dir() / "config"


def get_data_dir() -> Path:
    return get_app_data_dir() / "data"


def get_license_dir() -> Path:
    return get_app_data_dir() / "licenses"


def get_logs_dir() -> Path:
    return get_app_data_dir() / "logs"


def get_plans_dir() -> Path:
    return get_app_data_dir() / "plans"


def get_cache_dir() -> Path:
    return get_app_data_dir() / "cache"


def get_temp_dir() -> Path:
    return get_app_data_dir() / "temp"


def ensure_app_directories() -> dict[str, Path]:
    """Create all mutable app directories and return them by logical name."""
    root = get_app_data_dir()
    paths = {name: root / name for name in APP_SUBDIRECTORIES}
    try:
        root.mkdir(parents=True, exist_ok=True)
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AppPathError(f"无法创建 LaunchFlow 用户数据目录 {root}: {exc}") from exc
    return {"root": root, **paths}
