"""Minimal platform contracts shared by path detection and compatibility code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


_SYSTEM_VALUES = frozenset({"windows", "linux", "macos", "unknown"})
_ARCHITECTURE_VALUES = frozenset({"x86_64", "arm64", "x86", "unknown"})


@dataclass(frozen=True)
class PlatformInfo:
    """Normalized host identity only; it does not imply feature support."""

    system: str
    architecture: str
    os_name: str
    sys_platform: str

    def __post_init__(self) -> None:
        if self.system not in _SYSTEM_VALUES:
            raise ValueError(f"不支持的平台标识: {self.system}")
        if self.architecture not in _ARCHITECTURE_VALUES:
            raise ValueError(f"不支持的架构标识: {self.architecture}")


@runtime_checkable
class PlatformPathProvider(Protocol):
    """Compute mutable app roots without creating directories."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    def default_app_root(self, app_name: str, development: bool) -> Path:
        ...

    def resolve_app_root(
        self,
        app_name: str,
        development: bool,
        explicit_override: str | None,
    ) -> Path:
        ...
