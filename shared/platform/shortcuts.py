"""Platform-owned shortcut strings for the editor's existing QAction set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


@dataclass(frozen=True)
class ShortcutProfile:
    """Immutable shortcut labels consumed by the Qt editor layer."""

    save: str
    save_as: str
    trial_run: str
    export: str
    delete_step: str
    move_up: str
    move_down: str


@runtime_checkable
class ShortcutPolicy(Protocol):
    """Provide shortcut values without importing Qt or constructing actions."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    @property
    def profile(self) -> ShortcutProfile:
        ...


_LEGACY_SHORTCUT_PROFILE = ShortcutProfile(
    save="Ctrl+S",
    save_as="Ctrl+Shift+S",
    trial_run="Ctrl+R",
    export="Ctrl+E",
    delete_step="Delete",
    move_up="Alt+Up",
    move_down="Alt+Down",
)


@dataclass(frozen=True)
class WindowsShortcutPolicy:
    """Preserve the exact Windows Beta shortcut strings."""

    platform_info: PlatformInfo

    @property
    def profile(self) -> ShortcutProfile:
        return _LEGACY_SHORTCUT_PROFILE


@dataclass(frozen=True)
class LegacyShortcutPolicy:
    """Retain historical Ctrl bindings without claiming native support."""

    platform_info: PlatformInfo

    @property
    def profile(self) -> ShortcutProfile:
        return _LEGACY_SHORTCUT_PROFILE


def get_shortcut_policy(
    platform_info: PlatformInfo | None = None,
) -> ShortcutPolicy:
    """Select a shortcut policy without creating UI objects or side effects."""

    info = platform_info if platform_info is not None else current_platform_info()
    policy_type = WindowsShortcutPolicy if info.system == "windows" else LegacyShortcutPolicy
    return policy_type(info)
