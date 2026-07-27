"""Side-effect-free platform information and mutable-path providers."""

from shared.platform.base import PlatformInfo, PlatformPathProvider
from shared.platform.detection import current_platform_info, detect_platform
from shared.platform.desktop import (
    DesktopIntegration,
    LegacyPosixDesktopIntegration,
    WindowsDesktopIntegration,
    get_desktop_integration,
)
from shared.platform.diagnostics import (
    DiagnosticPathAlias,
    DiagnosticsPresentation,
    DiagnosticsPresentationProvider,
    LegacyPosixDiagnosticsPresentationProvider,
    WindowsDiagnosticsPresentationProvider,
    get_diagnostics_presentation_provider,
)
from shared.platform.paths import (
    LegacyFallbackPlatformPaths,
    WindowsPlatformPaths,
    get_platform_path_provider,
)
from shared.platform.applications import (
    ApplicationLauncher,
    ApplicationLaunchSpec,
    LegacyPosixApplicationLauncher,
    WindowsApplicationLauncher,
    get_application_launcher,
)
from shared.platform.process import (
    CommandBackend,
    CommandLaunchSpec,
    LegacyPosixCommandBackend,
    WindowsCommandBackend,
    get_command_backend,
)
from shared.platform.urls import (
    LegacyPosixUrlOpener,
    UrlOpener,
    UrlOpenSpec,
    WindowsUrlOpener,
    get_url_opener,
)
from shared.platform.shortcuts import (
    LegacyShortcutPolicy,
    ShortcutPolicy,
    ShortcutProfile,
    WindowsShortcutPolicy,
    get_shortcut_policy,
)

__all__ = (
    "ApplicationLauncher",
    "ApplicationLaunchSpec",
    "LegacyFallbackPlatformPaths",
    "LegacyPosixApplicationLauncher",
    "LegacyPosixCommandBackend",
    "LegacyPosixUrlOpener",
    "LegacyShortcutPolicy",
    "CommandBackend",
    "CommandLaunchSpec",
    "DesktopIntegration",
    "DiagnosticPathAlias",
    "DiagnosticsPresentation",
    "DiagnosticsPresentationProvider",
    "LegacyPosixDesktopIntegration",
    "LegacyPosixDiagnosticsPresentationProvider",
    "PlatformInfo",
    "PlatformPathProvider",
    "ShortcutPolicy",
    "ShortcutProfile",
    "UrlOpener",
    "UrlOpenSpec",
    "WindowsPlatformPaths",
    "WindowsShortcutPolicy",
    "WindowsApplicationLauncher",
    "WindowsCommandBackend",
    "WindowsDesktopIntegration",
    "WindowsDiagnosticsPresentationProvider",
    "WindowsUrlOpener",
    "current_platform_info",
    "detect_platform",
    "get_platform_path_provider",
    "get_shortcut_policy",
    "get_application_launcher",
    "get_command_backend",
    "get_desktop_integration",
    "get_diagnostics_presentation_provider",
    "get_url_opener",
)
