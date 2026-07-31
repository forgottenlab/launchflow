"""Behavior-equivalent legacy-v1 hardware identity collection boundary.

This module owns platform-sensitive collection only.  Request/license schemas,
signing, persistence, logging, and identity migration remain outside this
boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import getpass
import hashlib
import os
import platform
import socket
import sys
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


@runtime_checkable
class CommandResultLike(Protocol):
    """The only command-result field required by legacy volume collection."""

    @property
    def stdout(self) -> str | None:
        ...


CommandExecutor = Callable[[str, str], CommandResultLike]
IdentityReader = Callable[[], str]


@dataclass(frozen=True)
class HardwareIdentityParts:
    """Frozen internal value matching the historical five-field dictionary."""

    machine_guid: str
    volume_serial: str
    fallback: str
    python: str
    platform: str

    def to_legacy_dict(self) -> dict[str, str]:
        """Return the exact historical key names and insertion order."""

        return {
            "machine_guid": self.machine_guid,
            "volume_serial": self.volume_serial,
            "fallback": self.fallback,
            "python": self.python,
            "platform": self.platform,
        }


@runtime_checkable
class HardwareIdentityProvider(Protocol):
    """Collect legacy-compatible identity parts without hashing or storage."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    def collect_parts(self) -> HardwareIdentityParts:
        ...


def read_windows_machine_guid(*, os_name: str | None = None) -> str:
    """Read the historical Windows MachineGuid value, or return an empty value."""

    selected_os_name = os.name if os_name is None else os_name
    if selected_os_name != "nt":
        return ""

    try:
        import winreg

        registry_path = r"SOFTWARE\Microsoft\Cryptography"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
    except Exception:
        return ""


def read_windows_volume_stdout(
    command_executor: CommandExecutor,
    *,
    os_name: str | None = None,
) -> str:
    """Return the complete stripped stdout from the historical volume command."""

    selected_os_name = os.name if os_name is None else os_name
    if selected_os_name != "nt":
        return ""

    try:
        result = command_executor(r"vol C:", "cmd")
        return (result.stdout or "").strip()
    except Exception:
        return ""


def read_legacy_machine_fallback(
    *,
    system_reader: Callable[[], object] | None = None,
    release_reader: Callable[[], object] | None = None,
    version_reader: Callable[[], object] | None = None,
    hostname_reader: Callable[[], object] | None = None,
    username_reader: Callable[[], object] | None = None,
) -> str:
    """Collect and join the five historical fallback sources in exact order."""

    if system_reader is None:
        system_reader = platform.system
    if release_reader is None:
        release_reader = platform.release
    if version_reader is None:
        version_reader = platform.version
    if hostname_reader is None:
        hostname_reader = socket.gethostname
    if username_reader is None:
        username_reader = getpass.getuser

    parts = [
        system_reader(),
        release_reader(),
        version_reader(),
        hostname_reader(),
        username_reader(),
    ]
    return "|".join(str(part) for part in parts if part)


def _legacy_value(
    parts: HardwareIdentityParts | Mapping[str, str],
    key: str,
) -> str:
    if isinstance(parts, Mapping):
        return parts.get(key, "")
    return getattr(parts, key)


def serialize_legacy_v1(
    parts: HardwareIdentityParts | Mapping[str, str],
) -> str:
    """Serialize only the three fields used by the frozen legacy-v1 hash."""

    return "||".join(
        (
            _legacy_value(parts, "machine_guid"),
            _legacy_value(parts, "volume_serial"),
            _legacy_value(parts, "fallback"),
        )
    )


def hash_legacy_v1_serialized(serialized: str) -> str:
    """Hash a legacy-v1 serialization using the frozen UTF-8/SHA-256 contract."""

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest().upper()


def build_legacy_v1_machine_id(
    parts: HardwareIdentityParts | Mapping[str, str],
) -> str:
    """Build a machine ID without collecting, mutating, caching, or persisting."""

    return hash_legacy_v1_serialized(serialize_legacy_v1(parts))


def _empty_identity_reader() -> str:
    return ""


def _default_python_reader() -> str:
    return sys.version.split()[0]


def _default_platform_reader() -> str:
    return platform.platform()


@dataclass(frozen=True)
class WindowsHardwareIdentityProvider:
    """Collect the exact legacy-v1 Windows inputs through injected readers."""

    platform_info: PlatformInfo
    command_executor: CommandExecutor
    machine_guid_reader: IdentityReader | None = None
    volume_reader: IdentityReader | None = None
    fallback_reader: IdentityReader | None = None
    python_version_reader: IdentityReader | None = None
    platform_metadata_reader: IdentityReader | None = None

    def __post_init__(self) -> None:
        if self.command_executor is None:
            raise ValueError("Windows HardwareIdentityProvider requires command_executor")

    def collect_parts(self) -> HardwareIdentityParts:
        machine_guid_reader = self.machine_guid_reader
        if machine_guid_reader is None:
            machine_guid_reader = lambda: read_windows_machine_guid(os_name="nt")

        volume_reader = self.volume_reader
        if volume_reader is None:
            volume_reader = lambda: read_windows_volume_stdout(
                self.command_executor,
                os_name="nt",
            )

        fallback_reader = self.fallback_reader
        if fallback_reader is None:
            fallback_reader = read_legacy_machine_fallback

        python_version_reader = self.python_version_reader
        if python_version_reader is None:
            python_version_reader = _default_python_reader

        platform_metadata_reader = self.platform_metadata_reader
        if platform_metadata_reader is None:
            platform_metadata_reader = _default_platform_reader

        machine_guid = machine_guid_reader()
        volume_serial = volume_reader()
        fallback = fallback_reader()
        python_version = python_version_reader()
        platform_metadata = platform_metadata_reader()

        return HardwareIdentityParts(
            machine_guid=machine_guid,
            volume_serial=volume_serial,
            fallback=fallback,
            python=python_version,
            platform=platform_metadata,
        )


@dataclass(frozen=True)
class LegacyPosixHardwareIdentityProvider:
    """Preserve the historical non-Windows fallback without native support."""

    platform_info: PlatformInfo
    machine_guid_reader: IdentityReader = _empty_identity_reader
    volume_reader: IdentityReader = _empty_identity_reader
    fallback_reader: IdentityReader | None = None
    python_version_reader: IdentityReader | None = None
    platform_metadata_reader: IdentityReader | None = None

    def collect_parts(self) -> HardwareIdentityParts:
        fallback_reader = self.fallback_reader
        if fallback_reader is None:
            fallback_reader = read_legacy_machine_fallback

        python_version_reader = self.python_version_reader
        if python_version_reader is None:
            python_version_reader = _default_python_reader

        platform_metadata_reader = self.platform_metadata_reader
        if platform_metadata_reader is None:
            platform_metadata_reader = _default_platform_reader

        machine_guid = self.machine_guid_reader()
        volume_serial = self.volume_reader()
        fallback = fallback_reader()
        python_version = python_version_reader()
        platform_metadata = platform_metadata_reader()

        return HardwareIdentityParts(
            machine_guid=machine_guid,
            volume_serial=volume_serial,
            fallback=fallback,
            python=python_version,
            platform=platform_metadata,
        )


def get_hardware_identity_provider(
    *,
    platform_info: PlatformInfo | None = None,
    command_executor: CommandExecutor | None = None,
    machine_guid_reader: IdentityReader | None = None,
    volume_reader: IdentityReader | None = None,
    fallback_reader: IdentityReader | None = None,
    python_version_reader: IdentityReader | None = None,
    platform_metadata_reader: IdentityReader | None = None,
) -> HardwareIdentityProvider:
    """Select a fresh collection provider without collecting any source value."""

    info = platform_info or current_platform_info()
    if info.system == "windows":
        if command_executor is None:
            raise ValueError("Windows HardwareIdentityProvider requires command_executor")
        return WindowsHardwareIdentityProvider(
            platform_info=info,
            command_executor=command_executor,
            machine_guid_reader=machine_guid_reader,
            volume_reader=volume_reader,
            fallback_reader=fallback_reader,
            python_version_reader=python_version_reader,
            platform_metadata_reader=platform_metadata_reader,
        )

    return LegacyPosixHardwareIdentityProvider(
        platform_info=info,
        machine_guid_reader=machine_guid_reader or _empty_identity_reader,
        volume_reader=volume_reader or _empty_identity_reader,
        fallback_reader=fallback_reader,
        python_version_reader=python_version_reader,
        platform_metadata_reader=platform_metadata_reader,
    )
