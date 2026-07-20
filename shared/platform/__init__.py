"""Side-effect-free platform information and mutable-path providers."""

from shared.platform.base import PlatformInfo, PlatformPathProvider
from shared.platform.detection import current_platform_info, detect_platform
from shared.platform.paths import (
    LegacyFallbackPlatformPaths,
    WindowsPlatformPaths,
    get_platform_path_provider,
)

__all__ = (
    "LegacyFallbackPlatformPaths",
    "PlatformInfo",
    "PlatformPathProvider",
    "WindowsPlatformPaths",
    "current_platform_info",
    "detect_platform",
    "get_platform_path_provider",
)
