"""Platform-owned labels and path aliases for diagnostic presentation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


_LEGACY_WINDOWS_LABEL = "Windows"


@dataclass(frozen=True)
class DiagnosticPathAlias:
    """One literal source prefix and its user-facing diagnostic alias."""

    source: str
    replacement: str


@dataclass(frozen=True)
class DiagnosticsPresentation:
    """Platform-owned values consumed by the neutral diagnostic formatter."""

    platform_label: str
    path_aliases: tuple[DiagnosticPathAlias, ...]


@runtime_checkable
class DiagnosticsPresentationProvider(Protocol):
    """Build diagnostic presentation values without formatting the report."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    @property
    def platform_label(self) -> str:
        ...

    def build_presentation(
        self,
        environment: Mapping[str, str] | None = None,
        home_path: str | Path | None = None,
    ) -> DiagnosticsPresentation:
        ...


def _build_legacy_windows_presentation(
    *,
    platform_label: str,
    environment: Mapping[str, str],
    home_path: str | Path,
) -> DiagnosticsPresentation:
    aliases: list[DiagnosticPathAlias] = []
    local_app_data = environment.get("LOCALAPPDATA", "")
    if local_app_data:
        aliases.append(DiagnosticPathAlias(local_app_data, "%LOCALAPPDATA%"))
    home_source = str(home_path)
    if home_source:
        aliases.append(DiagnosticPathAlias(home_source, "%USERPROFILE%"))
    return DiagnosticsPresentation(platform_label, tuple(aliases))


@dataclass(frozen=True)
class WindowsDiagnosticsPresentationProvider:
    """Preserve the Windows Beta diagnostic labels and alias order."""

    platform_info: PlatformInfo
    environment: Mapping[str, str] | None = None
    home_path: str | Path | None = None

    @property
    def platform_label(self) -> str:
        return _LEGACY_WINDOWS_LABEL

    def build_presentation(
        self,
        environment: Mapping[str, str] | None = None,
        home_path: str | Path | None = None,
    ) -> DiagnosticsPresentation:
        environment = environment if environment is not None else self.environment
        if environment is None:
            environment = os.environ
        home_path = home_path if home_path is not None else self.home_path
        if home_path is None:
            home_path = Path.home()
        return _build_legacy_windows_presentation(
            platform_label=self.platform_label,
            environment=environment,
            home_path=home_path,
        )


@dataclass(frozen=True)
class LegacyPosixDiagnosticsPresentationProvider:
    """Retain historical non-Windows output without claiming native support."""

    platform_info: PlatformInfo
    environment: Mapping[str, str] | None = None
    home_path: str | Path | None = None

    @property
    def platform_label(self) -> str:
        return _LEGACY_WINDOWS_LABEL

    def build_presentation(
        self,
        environment: Mapping[str, str] | None = None,
        home_path: str | Path | None = None,
    ) -> DiagnosticsPresentation:
        environment = environment if environment is not None else self.environment
        if environment is None:
            environment = os.environ
        home_path = home_path if home_path is not None else self.home_path
        if home_path is None:
            home_path = Path.home()
        return _build_legacy_windows_presentation(
            platform_label=self.platform_label,
            environment=environment,
            home_path=home_path,
        )


def get_diagnostics_presentation_provider(
    platform_info: PlatformInfo | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    home_path: str | Path | None = None,
) -> DiagnosticsPresentationProvider:
    """Select the provider while allowing deterministic source injection."""

    info = platform_info or current_platform_info()
    provider_type = (
        WindowsDiagnosticsPresentationProvider
        if info.system == "windows"
        else LegacyPosixDiagnosticsPresentationProvider
    )
    return provider_type(info, environment, home_path)
