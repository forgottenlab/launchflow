"""Minimal desktop-integration boundary for opening directories."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


DirectoryPath = str | os.PathLike[str]
DirectoryOpener = Callable[[str], object]


def _windows_shell_open(path: str) -> object:
    """Resolve and call the Windows shell opener only when an action is requested."""

    return os.startfile(path)  # type: ignore[attr-defined]


@runtime_checkable
class DesktopIntegration(Protocol):
    """Perform the currently supported desktop operation for one platform."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    def open_directory(self, path: DirectoryPath) -> None:
        ...


@dataclass(frozen=True)
class WindowsDesktopIntegration:
    """Preserve the existing Windows ``os.startfile(str(path))`` behavior."""

    platform_info: PlatformInfo
    shell_opener: DirectoryOpener = _windows_shell_open

    def open_directory(self, path: DirectoryPath) -> None:
        self.shell_opener(str(path))


@dataclass(frozen=True)
class LegacyPosixDesktopIntegration:
    """Preserve the previous non-Windows silent no-op without claiming support."""

    platform_info: PlatformInfo

    def open_directory(self, path: DirectoryPath) -> None:
        return None


def get_desktop_integration(
    *,
    platform_info: PlatformInfo | None = None,
    shell_opener: DirectoryOpener | None = None,
) -> DesktopIntegration:
    """Select a desktop integration without opening a directory."""

    info = platform_info if platform_info is not None else current_platform_info()
    if info.system == "windows":
        opener = shell_opener if shell_opener is not None else _windows_shell_open
        return WindowsDesktopIntegration(info, opener)
    return LegacyPosixDesktopIntegration(info)
