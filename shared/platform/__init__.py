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
from shared.platform.identity import (
    CommandExecutor,
    CommandResultLike,
    HardwareIdentityParts,
    HardwareIdentityProvider,
    LegacyPosixHardwareIdentityProvider,
    WindowsHardwareIdentityProvider,
    build_legacy_v1_machine_id,
    get_hardware_identity_provider,
    hash_legacy_v1_serialized,
    read_legacy_machine_fallback,
    read_windows_machine_guid,
    read_windows_volume_stdout,
    serialize_legacy_v1,
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
    "CommandExecutor",
    "CommandLaunchSpec",
    "CommandResultLike",
    "DesktopIntegration",
    "DiagnosticPathAlias",
    "DiagnosticsPresentation",
    "DiagnosticsPresentationProvider",
    "LegacyPosixDesktopIntegration",
    "LegacyPosixDiagnosticsPresentationProvider",
    "LegacyPosixHardwareIdentityProvider",
    "HardwareIdentityParts",
    "HardwareIdentityProvider",
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
    "WindowsHardwareIdentityProvider",
    "WindowsUrlOpener",
    "build_legacy_v1_machine_id",
    "current_platform_info",
    "detect_platform",
    "get_platform_path_provider",
    "get_shortcut_policy",
    "get_application_launcher",
    "get_command_backend",
    "get_desktop_integration",
    "get_diagnostics_presentation_provider",
    "get_hardware_identity_provider",
    "get_url_opener",
    "hash_legacy_v1_serialized",
    "read_legacy_machine_fallback",
    "read_windows_machine_guid",
    "read_windows_volume_stdout",
    "serialize_legacy_v1",
)
