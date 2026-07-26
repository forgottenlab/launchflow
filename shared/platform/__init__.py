"""Side-effect-free platform information and mutable-path providers."""

from shared.platform.base import PlatformInfo, PlatformPathProvider
from shared.platform.detection import current_platform_info, detect_platform
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

__all__ = (
    "ApplicationLauncher",
    "ApplicationLaunchSpec",
    "LegacyFallbackPlatformPaths",
    "LegacyPosixApplicationLauncher",
    "LegacyPosixCommandBackend",
    "CommandBackend",
    "CommandLaunchSpec",
    "PlatformInfo",
    "PlatformPathProvider",
    "WindowsPlatformPaths",
    "WindowsApplicationLauncher",
    "WindowsCommandBackend",
    "current_platform_info",
    "detect_platform",
    "get_platform_path_provider",
    "get_application_launcher",
    "get_command_backend",
)
