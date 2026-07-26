"""Side-effect-free Application launch contracts for platform runtimes."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
_SW_MINIMIZE = 6

_WINDOWS_TARGET_KINDS = (
    "executable",
    "com",
    "batch",
    "command_script",
    "powershell_script",
    "shortcut",
    "no_extension",
    "other",
)


@dataclass(frozen=True)
class ApplicationLaunchSpec:
    """Describe one Application launch without starting or retaining a process."""

    launch_mode: str
    target_kind: str
    executable: str | None
    command_args: tuple[str, ...]
    cwd: str | None
    creationflags: int
    use_startupinfo: bool
    startupinfo_dw_flags: int
    startupinfo_show_window: int
    use_stdin_devnull: bool
    use_stdout_devnull: bool
    use_stderr_devnull: bool
    resolved_target: str


@runtime_checkable
class ApplicationLauncher(Protocol):
    """Construct Application launches while leaving execution to runtime."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    @property
    def supported_target_kinds(self) -> tuple[str, ...]:
        ...

    def classify_target(self, path: str) -> str:
        ...

    def build_launch_spec(
        self,
        path: str,
        arguments: Sequence[str],
        working_dir: str,
        start_minimized: bool,
    ) -> ApplicationLaunchSpec:
        ...

    def explain_launch_error(self, error: BaseException) -> str:
        ...


def _classify_target(
    path: str,
    path_exists: Callable[[str], bool],
    path_is_directory: Callable[[str], bool],
) -> str:
    if not path_exists(path):
        return "missing"
    if path_is_directory(path):
        return "directory"
    suffix = Path(path).suffix.lower()
    return {
        ".exe": "executable",
        ".com": "com",
        ".bat": "batch",
        ".cmd": "command_script",
        ".ps1": "powershell_script",
        ".lnk": "shortcut",
        "": "no_extension",
    }.get(suffix, "other")


def _explain_launch_error(error: BaseException) -> str:
    if isinstance(error, IsADirectoryError):
        return "目标路径是目录，不能作为应用启动。"
    if isinstance(error, FileNotFoundError):
        return "找不到目标文件，请检查路径。"
    if isinstance(error, PermissionError):
        return "没有权限启动该应用。"
    if isinstance(error, AttributeError):
        return "当前系统不支持该应用启动方式。"
    return "启动应用时发生系统错误，请检查原始错误信息。"


def _build_launch_spec(
    *,
    target_kind: str,
    path: str,
    arguments: Sequence[str],
    working_dir: str,
    start_minimized: bool,
    windows: bool,
) -> ApplicationLaunchSpec:
    if target_kind == "missing":
        raise FileNotFoundError(f"程序路径不存在: {path}")

    if target_kind == "shortcut":
        return ApplicationLaunchSpec(
            launch_mode="shell_open",
            target_kind=target_kind,
            executable=None,
            command_args=(),
            cwd=None,
            creationflags=0,
            use_startupinfo=False,
            startupinfo_dw_flags=0,
            startupinfo_show_window=0,
            use_stdin_devnull=False,
            use_stdout_devnull=False,
            use_stderr_devnull=False,
            resolved_target=path,
        )

    if target_kind == "powershell_script":
        command_args = (
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            path,
            *tuple(arguments),
        )
    else:
        command_args = (path, *tuple(arguments))

    minimized = bool(start_minimized and windows)
    return ApplicationLaunchSpec(
        launch_mode="process",
        target_kind=target_kind,
        executable=command_args[0],
        command_args=command_args,
        cwd=working_dir or None,
        creationflags=_CREATE_NO_WINDOW if windows else 0,
        use_startupinfo=minimized,
        startupinfo_dw_flags=_STARTF_USESHOWWINDOW if minimized else 0,
        startupinfo_show_window=_SW_MINIMIZE if minimized else 0,
        use_stdin_devnull=True,
        use_stdout_devnull=True,
        use_stderr_devnull=True,
        resolved_target=path,
    )


@dataclass(frozen=True)
class WindowsApplicationLauncher:
    """Preserve the current Windows Application launch contract."""

    platform_info: PlatformInfo
    path_exists: Callable[[str], bool] = os.path.exists
    path_is_directory: Callable[[str], bool] = os.path.isdir

    @property
    def supported_target_kinds(self) -> tuple[str, ...]:
        return _WINDOWS_TARGET_KINDS

    def classify_target(self, path: str) -> str:
        return _classify_target(path, self.path_exists, self.path_is_directory)

    def build_launch_spec(
        self,
        path: str,
        arguments: Sequence[str],
        working_dir: str,
        start_minimized: bool,
    ) -> ApplicationLaunchSpec:
        return _build_launch_spec(
            target_kind=self.classify_target(path),
            path=path,
            arguments=arguments,
            working_dir=working_dir,
            start_minimized=start_minimized,
            windows=True,
        )

    def explain_launch_error(self, error: BaseException) -> str:
        return _explain_launch_error(error)


@dataclass(frozen=True)
class LegacyPosixApplicationLauncher:
    """Preserve the old generic Popen path without claiming native support."""

    platform_info: PlatformInfo
    path_exists: Callable[[str], bool] = os.path.exists
    path_is_directory: Callable[[str], bool] = os.path.isdir

    @property
    def supported_target_kinds(self) -> tuple[str, ...]:
        return ()

    def classify_target(self, path: str) -> str:
        return _classify_target(path, self.path_exists, self.path_is_directory)

    def build_launch_spec(
        self,
        path: str,
        arguments: Sequence[str],
        working_dir: str,
        start_minimized: bool,
    ) -> ApplicationLaunchSpec:
        return _build_launch_spec(
            target_kind=self.classify_target(path),
            path=path,
            arguments=arguments,
            working_dir=working_dir,
            start_minimized=start_minimized,
            windows=False,
        )

    def explain_launch_error(self, error: BaseException) -> str:
        return _explain_launch_error(error)


def get_application_launcher(
    *,
    platform_info: PlatformInfo | None = None,
    path_exists: Callable[[str], bool] | None = None,
    path_is_directory: Callable[[str], bool] | None = None,
) -> ApplicationLauncher:
    """Select an Application launcher without probing or launching a target."""

    info = platform_info if platform_info is not None else current_platform_info()
    exists = path_exists if path_exists is not None else os.path.exists
    is_directory = path_is_directory if path_is_directory is not None else os.path.isdir
    if info.system == "windows":
        return WindowsApplicationLauncher(info, exists, is_directory)
    return LegacyPosixApplicationLauncher(info, exists, is_directory)
