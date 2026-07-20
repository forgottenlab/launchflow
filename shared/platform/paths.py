"""Platform path providers that preserve the current LaunchFlow path contract."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from shared.platform.base import PlatformInfo, PlatformPathProvider
from shared.platform.detection import current_platform_info


DATA_DIR_OVERRIDE_ENV = "LAUNCHFLOW_DATA_DIR"


def _app_directory_name(app_name: str, development: bool) -> str:
    return f"{app_name}-Dev" if development else app_name


def _explicit_root(explicit_override: str | None) -> Path | None:
    override = str(explicit_override or "").strip()
    if not override:
        return None
    path = Path(os.path.expandvars(override)).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{DATA_DIR_OVERRIDE_ENV} 必须是绝对路径: {override}")
    return path


@dataclass(frozen=True)
class WindowsPlatformPaths:
    """Preserve the Windows `%LOCALAPPDATA%` mutable-root behavior."""

    platform_info: PlatformInfo
    environment: Mapping[str, str]
    home: Path | None = None

    def default_app_root(self, app_name: str, development: bool) -> Path:
        directory_name = _app_directory_name(app_name, development)
        local_app_data = str(self.environment.get("LOCALAPPDATA", "")).strip()
        if local_app_data:
            return Path(local_app_data) / directory_name
        home = self.home if self.home is not None else Path.home()
        return home / "AppData" / "Local" / directory_name

    def resolve_app_root(
        self,
        app_name: str,
        development: bool,
        explicit_override: str | None,
    ) -> Path:
        override = _explicit_root(explicit_override)
        if override is not None:
            return override
        return self.default_app_root(app_name, development)


@dataclass(frozen=True)
class LegacyFallbackPlatformPaths:
    """Temporary compatibility backend for the pre-Phase-1a non-Windows fallback."""

    platform_info: PlatformInfo
    environment: Mapping[str, str]
    home: Path | None = None

    def default_app_root(self, app_name: str, development: bool) -> Path:
        directory_name = _app_directory_name(app_name, development)
        home = self.home if self.home is not None else Path.home()
        return home / ".local" / "share" / directory_name

    def resolve_app_root(
        self,
        app_name: str,
        development: bool,
        explicit_override: str | None,
    ) -> Path:
        override = _explicit_root(explicit_override)
        if override is not None:
            return override
        return self.default_app_root(app_name, development)


def get_platform_path_provider(
    *,
    platform_info: PlatformInfo | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> PlatformPathProvider:
    """Select one path provider without creating directories."""

    info = platform_info if platform_info is not None else current_platform_info()
    env = environment if environment is not None else os.environ
    if info.system == "windows":
        return WindowsPlatformPaths(info, env, home)
    return LegacyFallbackPlatformPaths(info, env, home)
