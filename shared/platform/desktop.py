"""Minimal desktop-integration boundary for Windows-equivalent actions."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


DirectoryPath = str | os.PathLike[str]
DirectoryOpener = Callable[[str], object]
ApplicationIdentitySetter = Callable[[str], object]


def _windows_shell_open(path: str) -> object:
    """Resolve and call the Windows shell opener only when an action is requested."""

    return os.startfile(path)  # type: ignore[attr-defined]


def _windows_application_identity_setter(app_id: str) -> object:
    """Resolve shell32 only when process identity is explicitly configured."""

    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    return shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


@runtime_checkable
class DesktopIntegration(Protocol):
    """Perform the currently supported desktop operations for one platform."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    def open_directory(self, path: DirectoryPath) -> None:
        ...

    def configure_application_identity(self, app_id: str) -> bool:
        ...


@dataclass(frozen=True)
class WindowsDesktopIntegration:
    """Preserve the existing Windows desktop-integration behavior."""

    platform_info: PlatformInfo
    shell_opener: DirectoryOpener = _windows_shell_open
    identity_setter: ApplicationIdentitySetter = _windows_application_identity_setter

    def open_directory(self, path: DirectoryPath) -> None:
        self.shell_opener(str(path))

    def configure_application_identity(self, app_id: str) -> bool:
        try:
            self.identity_setter(app_id)
            return True
        except (AttributeError, OSError):
            return False


@dataclass(frozen=True)
class LegacyPosixDesktopIntegration:
    """Preserve the previous non-Windows silent no-op without claiming support."""

    platform_info: PlatformInfo

    def open_directory(self, path: DirectoryPath) -> None:
        return None

    def configure_application_identity(self, app_id: str) -> bool:
        return False


def get_desktop_integration(
    *,
    platform_info: PlatformInfo | None = None,
    shell_opener: DirectoryOpener | None = None,
    identity_setter: ApplicationIdentitySetter | None = None,
) -> DesktopIntegration:
    """Select a desktop integration without performing a desktop action."""

    info = platform_info if platform_info is not None else current_platform_info()
    if info.system == "windows":
        opener = shell_opener if shell_opener is not None else _windows_shell_open
        setter = (
            identity_setter
            if identity_setter is not None
            else _windows_application_identity_setter
        )
        return WindowsDesktopIntegration(info, opener, setter)
    return LegacyPosixDesktopIntegration(info)
