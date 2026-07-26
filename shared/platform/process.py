"""Side-effect-free command launch contracts for platform runtimes."""

from __future__ import annotations

import locale
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


_NOT_FOUND_WINERRORS = frozenset({2, 3, 267})
_PERMISSION_WINERRORS = frozenset({5})
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
_SW_HIDE = getattr(subprocess, "SW_HIDE", 0)


@dataclass(frozen=True)
class CommandLaunchSpec:
    """Describe one command launch without starting a process."""

    command_args: tuple[str, ...]
    process_args: tuple[str, ...]
    environment_overrides: tuple[tuple[str, str], ...]
    creationflags: int
    startupinfo: object | None
    fallback_encodings: tuple[str, ...]


@runtime_checkable
class CommandBackend(Protocol):
    """Construct and interpret commands while leaving execution to runtime."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    @property
    def supported_shells(self) -> tuple[str, ...]:
        ...

    @property
    def default_shell(self) -> str:
        ...

    def build_launch_spec(self, command: str, shell: str) -> CommandLaunchSpec:
        ...

    def decode_output(self, data: bytes) -> str:
        ...

    def classify_launch_error(self, error: OSError) -> str:
        ...

    def explain_failure(self, returncode: int, error_kind: str | None) -> str:
        ...


def _failure_explanation(returncode: int, error_kind: str | None) -> str:
    if returncode == 9009:
        return "未找到可执行命令，请检查程序是否安装或是否加入 PATH。"
    if error_kind == "not_found":
        return "找不到目标文件，请检查路径。"
    if error_kind == "permission_denied":
        return "没有权限执行该操作。"
    return "命令执行失败，请查看退出码和错误输出。"


def _classify_launch_error(error: OSError) -> str:
    if isinstance(error, FileNotFoundError):
        return "not_found"
    if isinstance(error, PermissionError):
        return "permission_denied"
    winerror = getattr(error, "winerror", None)
    error_number = getattr(error, "errno", None)
    if winerror in _NOT_FOUND_WINERRORS or error_number == 2:
        return "not_found"
    if winerror in _PERMISSION_WINERRORS or error_number == 13:
        return "permission_denied"
    return "system_error"


def _decode_with_fallbacks(data: bytes, fallback_encodings: tuple[str, ...]) -> str:
    preferred = locale.getpreferredencoding(False) or "utf-8"
    seen: set[str] = set()
    for encoding in (preferred, *fallback_encodings):
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode(preferred, errors="replace")


def _new_quote_token() -> str:
    return uuid.uuid4().hex.upper()


def _new_windows_startupinfo() -> object:
    return subprocess.STARTUPINFO()


@dataclass(frozen=True)
class WindowsCommandBackend:
    """Preserve the current Windows cmd and Windows PowerShell contract."""

    platform_info: PlatformInfo
    startupinfo_factory: Callable[[], object] = _new_windows_startupinfo
    quote_token_factory: Callable[[], str] = _new_quote_token

    @property
    def supported_shells(self) -> tuple[str, ...]:
        return ("cmd", "powershell")

    @property
    def default_shell(self) -> str:
        return "cmd"

    def build_launch_spec(self, command: str, shell: str) -> CommandLaunchSpec:
        shell_name = shell.strip().lower()
        if shell_name == "powershell":
            command_args = (
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            )
        else:
            command_args = ("cmd.exe", "/d", "/s", "/c", command)

        process_args = command_args
        environment_overrides: tuple[tuple[str, str], ...] = ()
        if shell_name != "powershell" and '"' in command:
            quote_variable = f"__LAUNCHFLOW_DQ_{self.quote_token_factory()}"
            while f"%{quote_variable}%" in command:
                quote_variable = f"__LAUNCHFLOW_DQ_{self.quote_token_factory()}"
            process_args = (*command_args[:4], command.replace('"', f"%{quote_variable}%"))
            environment_overrides = ((quote_variable, '"'),)

        startupinfo = self.startupinfo_factory()
        startupinfo.dwFlags |= _STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = _SW_HIDE
        return CommandLaunchSpec(
            command_args=command_args,
            process_args=process_args,
            environment_overrides=environment_overrides,
            creationflags=_CREATE_NO_WINDOW,
            startupinfo=startupinfo,
            fallback_encodings=("utf-8", "mbcs", "cp936"),
        )

    def decode_output(self, data: bytes) -> str:
        return _decode_with_fallbacks(data, ("utf-8", "mbcs", "cp936"))

    def classify_launch_error(self, error: OSError) -> str:
        return _classify_launch_error(error)

    def explain_failure(self, returncode: int, error_kind: str | None) -> str:
        return _failure_explanation(returncode, error_kind)


@dataclass(frozen=True)
class LegacyPosixCommandBackend:
    """Preserve the old `/bin/sh` fallback without claiming shell support."""

    platform_info: PlatformInfo

    @property
    def supported_shells(self) -> tuple[str, ...]:
        return ()

    @property
    def default_shell(self) -> str:
        return "cmd"

    def build_launch_spec(self, command: str, shell: str) -> CommandLaunchSpec:
        command_args = ("/bin/sh", "-c", command)
        return CommandLaunchSpec(
            command_args=command_args,
            process_args=command_args,
            environment_overrides=(),
            creationflags=0,
            startupinfo=None,
            fallback_encodings=("utf-8",),
        )

    def decode_output(self, data: bytes) -> str:
        return _decode_with_fallbacks(data, ("utf-8",))

    def classify_launch_error(self, error: OSError) -> str:
        return _classify_launch_error(error)

    def explain_failure(self, returncode: int, error_kind: str | None) -> str:
        return _failure_explanation(returncode, error_kind)


def get_command_backend(
    *,
    platform_info: PlatformInfo | None = None,
    startupinfo_factory: Callable[[], object] | None = None,
    quote_token_factory: Callable[[], str] | None = None,
) -> CommandBackend:
    """Select a command backend without executing a command."""

    info = platform_info if platform_info is not None else current_platform_info()
    if info.system == "windows":
        return WindowsCommandBackend(
            info,
            startupinfo_factory or _new_windows_startupinfo,
            quote_token_factory or _new_quote_token,
        )
    return LegacyPosixCommandBackend(info)
