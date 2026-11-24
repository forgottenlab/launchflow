"""Windows drive and path locality classification.

Lexical drive-letter paths are not treated as local by themselves. This
adapter asks the operating system for the volume type so mapped network
drives and other remote volumes can be identified.

The classifier does not launch targets, write files, change system
state, or read licensing or hardware identity.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from shared.basic_policy import DriveLocality


DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

_LOCAL_DRIVE_TYPES = frozenset(
    {DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_CDROM, DRIVE_RAMDISK}
)

GetVolumePathName = Callable[[str], str | None]
GetDriveType = Callable[[str], int]


def _load_kernel32():
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise RuntimeError("Windows drive APIs are unavailable on this host") from exc


def _windows_get_volume_path_name(path: str) -> str | None:
    kernel32 = _load_kernel32()
    kernel32.GetVolumePathNameW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetVolumePathNameW.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    ok = kernel32.GetVolumePathNameW(path, buffer, len(buffer))
    if not ok:
        return None
    root = buffer.value
    return root or None


def _windows_get_drive_type(root_path: str) -> int:
    kernel32 = _load_kernel32()
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    return int(kernel32.GetDriveTypeW(root_path))


def _lexical_drive_root(path: str) -> str | None:
    text = str(path or "").strip().strip('"')
    if len(text) >= 2 and text[0].isalpha() and text[1] == ":":
        return f"{text[0].upper()}:\\"
    unified = text.replace("/", "\\")
    if unified.startswith("\\\\") and not unified.startswith("\\\\?\\") and not unified.startswith("\\\\.\\"):
        parts = [part for part in unified.split("\\") if part]
        if len(parts) >= 2:
            return f"\\\\{parts[0]}\\{parts[1]}\\"
    return None


def _normalize_root(root: str) -> str:
    return root.replace("/", "\\").rstrip("\\") + "\\"


@dataclass(frozen=True)
class WindowsDriveClassifier:
    """Classify a path using Windows volume APIs, or injected stand-ins."""

    get_volume_path_name: GetVolumePathName | None = None
    get_drive_type: GetDriveType | None = None

    def classify_drive(self, path: str) -> DriveLocality:
        raw = str(path or "").strip()
        if not raw:
            return DriveLocality.UNKNOWN

        volume_lookup = self.get_volume_path_name or _windows_get_volume_path_name
        type_lookup = self.get_drive_type or _windows_get_drive_type

        root: str | None = None
        try:
            root = volume_lookup(raw)
        except Exception:
            root = None

        if not root:
            root = _lexical_drive_root(raw)
        if not root:
            return DriveLocality.UNAVAILABLE

        try:
            drive_type = int(type_lookup(_normalize_root(root)))
        except Exception:
            return DriveLocality.UNAVAILABLE

        if drive_type == DRIVE_REMOTE:
            return DriveLocality.REMOTE
        if drive_type in _LOCAL_DRIVE_TYPES:
            return DriveLocality.LOCAL
        if drive_type == DRIVE_NO_ROOT_DIR:
            return DriveLocality.UNAVAILABLE
        return DriveLocality.UNKNOWN
