"""Centralized paths for LaunchFlow mutable user data."""

from __future__ import annotations

import os
from pathlib import Path

from shared.platform.paths import (
    DATA_DIR_OVERRIDE_ENV as _DATA_DIR_OVERRIDE_ENV,
    get_platform_path_provider as _get_platform_path_provider,
)


APP_DATA_ENV = _DATA_DIR_OVERRIDE_ENV
APP_DIR_NAME = "LaunchFlow"
BASIC_APP_DIR_NAME = "LaunchFlow-Basic"
APP_SUBDIRECTORIES = ("config", "data", "licenses", "logs", "plans", "cache", "temp")


class AppPathError(RuntimeError):
    """Raised when LaunchFlow cannot resolve or create its user data path."""


def get_active_app_dir_name() -> str:
    """Return the edition-specific mutable data directory name."""

    from shared.edition_policy import is_basic_edition_active

    if is_basic_edition_active():
        return BASIC_APP_DIR_NAME
    return APP_DIR_NAME


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _professional_default_roots(provider) -> tuple[Path, ...]:
    return (
        provider.default_app_root(APP_DIR_NAME, False),
        provider.default_app_root(APP_DIR_NAME, True),
    )


def _is_professional_data_root(path: Path, provider) -> bool:
    target = _normalized_path(path)
    return any(target == _normalized_path(root) for root in _professional_default_roots(provider))


def get_app_data_dir() -> Path:
    """Return the user-writable LaunchFlow root without using cwd or the EXE directory.

    The current Professional path keeps %LOCALAPPDATA%\\LaunchFlow. An active
    Basic edition context uses %LOCALAPPDATA%\\LaunchFlow-Basic and fails
    closed instead of falling back to the Professional directory.
    """
    provider = _get_platform_path_provider(environment=os.environ)
    override = os.environ.get(APP_DATA_ENV, "")
    try:
        root = provider.resolve_app_root(
            get_active_app_dir_name(),
            False,
            override,
        )
    except ValueError as exc:
        raise AppPathError(str(exc)) from exc

    from shared.edition_policy import is_basic_edition_active

    if is_basic_edition_active() and _is_professional_data_root(root, provider):
        raise AppPathError(
            "Basic edition refused to use the Professional data directory "
            f"{root}"
        )
    return root


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
