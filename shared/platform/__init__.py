"""Side-effect-free platform information and mutable-path providers."""

from shared.platform.base import PlatformInfo, PlatformPathProvider
from shared.platform.detection import current_platform_info, detect_platform
from shared.platform.paths import (
    LegacyFallbackPlatformPaths,
    WindowsPlatformPaths,
    get_platform_path_provider,
)
from shared.platform.process import (
    CommandBackend,
    CommandLaunchSpec,
    LegacyPosixCommandBackend,
    WindowsCommandBackend,
    get_command_backend,
)

__all__ = (
    "LegacyFallbackPlatformPaths",
    "LegacyPosixCommandBackend",
    "CommandBackend",
    "CommandLaunchSpec",
    "PlatformInfo",
    "PlatformPathProvider",
    "WindowsPlatformPaths",
    "WindowsCommandBackend",
    "current_platform_info",
    "detect_platform",
    "get_platform_path_provider",
    "get_command_backend",
)
