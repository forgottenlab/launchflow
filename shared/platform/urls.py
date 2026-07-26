"""Side-effect-free URL opening contracts for platform runtimes."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shared.platform.base import PlatformInfo
from shared.platform.detection import current_platform_info


@dataclass(frozen=True)
class UrlOpenSpec:
    """Describe one URL open request without opening it or starting a process."""

    open_mode: str
    url: str
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


@runtime_checkable
class UrlOpener(Protocol):
    """Construct URL open requests while leaving execution to runtime."""

    @property
    def platform_info(self) -> PlatformInfo:
        ...

    @property
    def supported_open_modes(self) -> tuple[str, ...]:
        ...

    def build_open_spec(
        self,
        url: str,
        browser_path: str | None = None,
    ) -> UrlOpenSpec:
        ...

    def explain_open_error(self, error: BaseException) -> str:
        ...


def _process_spec(url: str, browser_path: str) -> UrlOpenSpec:
    return UrlOpenSpec(
        open_mode="process",
        url=url,
        executable=browser_path,
        command_args=(browser_path, url),
        cwd=None,
        creationflags=0,
        use_startupinfo=False,
        startupinfo_dw_flags=0,
        startupinfo_show_window=0,
        use_stdin_devnull=False,
        use_stdout_devnull=False,
        use_stderr_devnull=False,
    )


def _shell_open_spec(url: str) -> UrlOpenSpec:
    return UrlOpenSpec(
        open_mode="shell_open",
        url=url,
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
    )


def _explain_open_error(error: BaseException) -> str:
    if isinstance(error, IsADirectoryError):
        return "浏览器路径是目录，不能作为可执行文件启动。"
    if isinstance(error, FileNotFoundError):
        return "找不到浏览器程序，请检查路径。"
    if isinstance(error, PermissionError):
        return "没有权限启动浏览器。"
    if isinstance(error, (AttributeError, NotImplementedError)):
        return "当前系统不支持默认浏览器打开方式。"
    return "打开网址时发生系统错误，请检查原始错误信息。"


@dataclass(frozen=True)
class WindowsUrlOpener:
    """Preserve Windows default-browser and explicit-browser behavior."""

    platform_info: PlatformInfo
    path_exists: Callable[[str], bool] = os.path.exists

    @property
    def supported_open_modes(self) -> tuple[str, ...]:
        return ("shell_open", "process")

    def build_open_spec(
        self,
        url: str,
        browser_path: str | None = None,
    ) -> UrlOpenSpec:
        if browser_path:
            if not self.path_exists(browser_path):
                raise FileNotFoundError(f"浏览器路径不存在: {browser_path}")
            return _process_spec(url, browser_path)
        return _shell_open_spec(url)

    def explain_open_error(self, error: BaseException) -> str:
        return _explain_open_error(error)


@dataclass(frozen=True)
class LegacyPosixUrlOpener:
    """Retain explicit-browser Popen only; native default opening is unsupported."""

    platform_info: PlatformInfo
    path_exists: Callable[[str], bool] = os.path.exists

    @property
    def supported_open_modes(self) -> tuple[str, ...]:
        return ("process",)

    def build_open_spec(
        self,
        url: str,
        browser_path: str | None = None,
    ) -> UrlOpenSpec:
        if not browser_path:
            raise NotImplementedError("当前平台尚未支持默认浏览器打开 URL。")
        if not self.path_exists(browser_path):
            raise FileNotFoundError(f"浏览器路径不存在: {browser_path}")
        return _process_spec(url, browser_path)

    def explain_open_error(self, error: BaseException) -> str:
        return _explain_open_error(error)


def get_url_opener(
    *,
    platform_info: PlatformInfo | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> UrlOpener:
    """Select a URL opener without opening a URL or starting a process."""

    info = platform_info if platform_info is not None else current_platform_info()
    exists = path_exists if path_exists is not None else os.path.exists
    if info.system == "windows":
        return WindowsUrlOpener(info, exists)
    return LegacyPosixUrlOpener(info, exists)
