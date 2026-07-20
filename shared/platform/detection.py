"""Normalize platform metadata without probing APIs or creating files."""

from __future__ import annotations

import os
import platform
import sys

from shared.platform.base import PlatformInfo


def _normalize_system(system: str, os_name: str, sys_platform: str) -> str:
    values = {
        str(system).strip().lower(),
        str(os_name).strip().lower(),
        str(sys_platform).strip().lower(),
    }
    if values & {"windows", "win32", "nt"}:
        return "windows"
    if values & {"linux", "linux2"}:
        return "linux"
    if values & {"darwin", "macos", "mac"}:
        return "macos"
    return "unknown"


def _normalize_architecture(machine: str) -> str:
    value = str(machine).strip().lower()
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"x86", "i386", "i686"}:
        return "x86"
    return "unknown"


def detect_platform(
    *,
    system: str,
    machine: str,
    os_name: str,
    sys_platform: str,
) -> PlatformInfo:
    """Normalize injected platform values without consulting the current host."""

    return PlatformInfo(
        system=_normalize_system(system, os_name, sys_platform),
        architecture=_normalize_architecture(machine),
        os_name=str(os_name),
        sys_platform=str(sys_platform),
    )


def current_platform_info() -> PlatformInfo:
    """Read the current host metadata at call time."""

    return detect_platform(
        system=platform.system(),
        machine=platform.machine(),
        os_name=os.name,
        sys_platform=sys.platform,
    )
