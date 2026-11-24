"""Windows IShellLink / COM shortcut resolution adapter.

This module inspects shortcut files through the Shell Link COM interface.
It never executes a resolved target, never calls os.startfile, and never
treats a shortcut extension as proof that the target is a local EXE.

Resolver and COM failures are fail-closed: callers receive an unresolved
result or an exception, and Basic policy must reject the plan.
"""

from __future__ import annotations

import ctypes
from ctypes import HRESULT, POINTER, Structure, byref, c_void_p, c_wchar_p, wintypes
from collections.abc import Callable
from dataclasses import dataclass

from shared.basic_policy import ShortcutResolution


CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2
STGM_READ = 0x00000000
SLGP_RAWPATH = 0x4
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106
_PATH_BUFFER_CHARS = 32768

_TARGET_KIND_BY_SUFFIX = {
    ".exe": "executable",
    ".com": "com",
    ".bat": "batch",
    ".cmd": "command_script",
    ".ps1": "powershell_script",
    ".lnk": "shortcut",
    "": "no_extension",
}


class GUID(Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    @classmethod
    def from_text(cls, value: str) -> "GUID":
        hex_value = value.strip().strip("{}").replace("-", "")
        if len(hex_value) != 32:
            raise ValueError(f"invalid GUID: {value}")
        data4 = (wintypes.BYTE * 8)(
            *[int(hex_value[i : i + 2], 16) for i in range(16, 32, 2)]
        )
        return cls(
            int(hex_value[0:8], 16),
            int(hex_value[8:12], 16),
            int(hex_value[12:16], 16),
            data4,
        )


CLSID_SHELL_LINK = GUID.from_text("00021401-0000-0000-C000-000000000046")
IID_ISHELL_LINK_W = GUID.from_text("000214F9-0000-0000-C000-000000000046")
IID_IPERSIST_FILE = GUID.from_text("0000010b-0000-0000-C000-000000000046")


def _load_ole32():
    try:
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise RuntimeError("Windows COM APIs are unavailable on this host") from exc
    ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        POINTER(GUID),
        c_void_p,
        wintypes.DWORD,
        POINTER(GUID),
        POINTER(c_void_p),
    ]
    ole32.CoCreateInstance.restype = HRESULT
    return ole32


def _hr_code(hr: int) -> int:
    return int(hr) & 0xFFFFFFFF


def _hr_succeeded(hr: int) -> bool:
    return _hr_code(hr) in {S_OK, S_FALSE}


def _hr_hex(hr: int) -> str:
    return f"0x{_hr_code(hr):08X}"


def _vtable_func(this: int, index: int, prototype):
    vtbl = ctypes.cast(c_void_p(this), POINTER(c_void_p)).contents.value
    address = ctypes.cast(c_void_p(vtbl), POINTER(c_void_p))[index]
    return prototype(address)


def _query_interface(this: int, iid: GUID) -> int:
    proto = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
    queried = c_void_p()
    hr = _vtable_func(this, 0, proto)(this, byref(iid), byref(queried))
    if not _hr_succeeded(hr) or not queried.value:
        raise OSError(f"QueryInterface failed: {_hr_hex(hr)}")
    return int(queried.value)


def _release(this: int) -> None:
    proto = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
    _vtable_func(this, 2, proto)(this)


def _persist_load(this: int, path: str) -> None:
    proto = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, wintypes.DWORD)
    hr = _vtable_func(this, 5, proto)(this, path, STGM_READ)
    if not _hr_succeeded(hr):
        raise OSError(f"IPersistFile.Load failed: {_hr_hex(hr)}")


def _persist_save(this: int, path: str) -> None:
    proto = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, wintypes.BOOL)
    hr = _vtable_func(this, 6, proto)(this, path, True)
    if not _hr_succeeded(hr):
        raise OSError(f"IPersistFile.Save failed: {_hr_hex(hr)}")


def _shell_get_path(this: int) -> str:
    proto = ctypes.WINFUNCTYPE(
        HRESULT,
        c_void_p,
        c_wchar_p,
        ctypes.c_int,
        c_void_p,
        wintypes.DWORD,
    )
    for flags in (SLGP_RAWPATH, 0):
        buffer = ctypes.create_unicode_buffer(_PATH_BUFFER_CHARS)
        hr = _vtable_func(this, 3, proto)(
            this, buffer, _PATH_BUFFER_CHARS, None, flags
        )
        if _hr_succeeded(hr) and buffer.value:
            return buffer.value
    return ""


def _shell_get_string(this: int, index: int) -> str:
    proto = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, ctypes.c_int)
    buffer = ctypes.create_unicode_buffer(_PATH_BUFFER_CHARS)
    hr = _vtable_func(this, index, proto)(this, buffer, _PATH_BUFFER_CHARS)
    if not _hr_succeeded(hr):
        raise OSError(f"IShellLink string query failed: {_hr_hex(hr)}")
    return buffer.value or ""


def _shell_set_string(this: int, index: int, value: str) -> None:
    proto = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
    hr = _vtable_func(this, index, proto)(this, value)
    if not _hr_succeeded(hr):
        raise OSError(f"IShellLink string update failed: {_hr_hex(hr)}")


def _create_shell_link(ole32) -> int:
    pointer = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(CLSID_SHELL_LINK),
        None,
        CLSCTX_INPROC_SERVER,
        byref(IID_ISHELL_LINK_W),
        byref(pointer),
    )
    if not _hr_succeeded(hr) or not pointer.value:
        raise OSError(f"CoCreateInstance(IShellLinkW) failed: {_hr_hex(hr)}")
    return int(pointer.value)


class _ComApartment:
    def __init__(self) -> None:
        self._ole32 = _load_ole32()
        self._should_uninitialize = False

    def __enter__(self) -> "_ComApartment":
        hr = self._ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        code = _hr_code(hr)
        if code == RPC_E_CHANGED_MODE:
            return self
        if code not in {S_OK, S_FALSE}:
            raise OSError(f"CoInitializeEx failed: {_hr_hex(hr)}")
        self._should_uninitialize = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._should_uninitialize:
            self._ole32.CoUninitialize()

    @property
    def ole32(self):
        return self._ole32


class _ShellLinkSession:
    def __init__(self, ole32) -> None:
        self._link = _create_shell_link(ole32)
        self._persist = _query_interface(self._link, IID_IPERSIST_FILE)

    def close(self) -> None:
        if self._persist:
            _release(self._persist)
            self._persist = 0
        if self._link:
            _release(self._link)
            self._link = 0

    def __enter__(self) -> "_ShellLinkSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def load(self, path: str) -> None:
        _persist_load(self._persist, path)

    def save(self, path: str) -> None:
        _persist_save(self._persist, path)

    def get_path(self) -> str:
        return _shell_get_path(self._link)

    def get_arguments(self) -> str:
        return _shell_get_string(self._link, 10)

    def get_working_directory(self) -> str:
        return _shell_get_string(self._link, 8)

    def set_path(self, path: str) -> None:
        _shell_set_string(self._link, 20, path)

    def set_arguments(self, arguments: str) -> None:
        _shell_set_string(self._link, 11, arguments)

    def set_working_directory(self, working_directory: str) -> None:
        _shell_set_string(self._link, 9, working_directory)


def _suffix(path: str) -> str:
    name = str(path or "").replace("/", "\\").rsplit("\\", 1)[-1]
    if "." not in name or name.startswith("."):
        _, dot, remainder = name.partition(".")
        if not dot or not remainder or "\\" in remainder:
            return ""
    index = name.rfind(".")
    if index <= 0:
        return ""
    return name[index:].lower()


def classify_shortcut_target_kind(target_path: str) -> str:
    """Describe a resolved shortcut target from its suffix only."""

    text = str(target_path or "").strip()
    if not text:
        return ""
    return _TARGET_KIND_BY_SUFFIX.get(_suffix(text), "other")


def _unresolved(status: str = "unresolved") -> ShortcutResolution:
    return ShortcutResolution(
        target_path="",
        target_kind="",
        arguments=(),
        working_directory="",
        status=status,
    )


def _to_resolution(target: str, arguments: str, working_directory: str) -> ShortcutResolution:
    target_path = str(target or "").strip()
    if not target_path:
        return _unresolved("unresolved")
    argument_text = str(arguments or "").strip()
    return ShortcutResolution(
        target_path=target_path,
        target_kind=classify_shortcut_target_kind(target_path),
        arguments=(argument_text,) if argument_text else (),
        working_directory=str(working_directory or "").strip(),
        status="resolved",
    )


def read_windows_shortcut(path: str) -> ShortcutResolution:
    """Resolve one shortcut through IShellLink. The target is not executed."""

    raw_path = str(path or "").strip()
    if not raw_path:
        raise ValueError("shortcut path is empty")

    with _ComApartment() as apartment, _ShellLinkSession(apartment.ole32) as session:
        session.load(raw_path)
        return _to_resolution(
            session.get_path(),
            session.get_arguments(),
            session.get_working_directory(),
        )


def write_windows_shortcut(
    path: str,
    target_path: str,
    *,
    arguments: str = "",
    working_directory: str = "",
) -> None:
    """Create a shortcut file for tests or tooling. The target is not executed."""

    raw_path = str(path or "").strip()
    raw_target = str(target_path or "").strip()
    if not raw_path:
        raise ValueError("shortcut path is empty")
    if not raw_target:
        raise ValueError("shortcut target path is empty")

    with _ComApartment() as apartment, _ShellLinkSession(apartment.ole32) as session:
        session.set_path(raw_target)
        session.set_arguments(str(arguments or ""))
        session.set_working_directory(str(working_directory or ""))
        session.save(raw_path)


@dataclass(frozen=True)
class WindowsShortcutResolver:
    """Production ShortcutResolver adapter around IShellLink / COM."""

    reader: Callable[[str], ShortcutResolution] | None = None

    def resolve_shortcut(self, path: str) -> ShortcutResolution:
        reader = self.reader or read_windows_shortcut
        return reader(path)
