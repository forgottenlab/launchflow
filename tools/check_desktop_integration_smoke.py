"""Verify DesktopIntegration directory and application-identity equivalence."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import shared.diagnostics as diagnostics
import shared.platform.desktop as desktop
from shared.platform.base import PlatformInfo
from shared.platform.detection import detect_platform
from shared.platform.desktop import (
    DesktopIntegration,
    LegacyPosixDesktopIntegration,
    WindowsDesktopIntegration,
    get_desktop_integration,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _platform(system: str, sys_platform: str, os_name: str = "posix") -> PlatformInfo:
    return detect_platform(
        system=system,
        machine="x86_64",
        os_name=os_name,
        sys_platform=sys_platform,
    )


class RecordingPath:
    def __init__(self, value: str, events: list[object]) -> None:
        self.value = value
        self.events = events

    def mkdir(self, *, parents: bool, exist_ok: bool) -> None:
        self.events.append(("mkdir", parents, exist_ok))

    def __str__(self) -> str:
        self.events.append(("str", self.value))
        return self.value


def _assert_backend_selection() -> None:
    opener_calls: list[str] = []
    identity_calls: list[str] = []
    windows = get_desktop_integration(
        platform_info=_platform("Windows", "win32", "nt"),
        shell_opener=opener_calls.append,
        identity_setter=identity_calls.append,
    )
    require(isinstance(windows, WindowsDesktopIntegration), "Windows desktop integration was not selected")
    require(isinstance(windows, DesktopIntegration), "Windows integration does not satisfy Protocol")
    require(opener_calls == [], "Windows factory opened a directory")
    require(identity_calls == [], "Windows factory configured application identity")

    for system, sys_platform in (("Linux", "linux"), ("Darwin", "darwin"), ("Other", "other")):
        calls: list[str] = []
        identity_calls = []
        integration = get_desktop_integration(
            platform_info=_platform(system, sys_platform),
            shell_opener=calls.append,
            identity_setter=identity_calls.append,
        )
        require(
            isinstance(integration, LegacyPosixDesktopIntegration),
            f"legacy desktop integration was not selected: {system}",
        )
        events: list[object] = []
        path = RecordingPath("must-not-be-converted", events)
        require(integration.open_directory(path) is None, "legacy open-directory return changed")
        require(
            integration.configure_application_identity("must.not.be.used") is False,
            "legacy application-identity return changed",
        )
        require(
            calls == [] and identity_calls == [] and events == [],
            f"legacy backend performed a desktop action: {system}",
        )


def _assert_windows_directory_open() -> None:
    calls: list[str] = []
    integration = WindowsDesktopIntegration(
        _platform("Windows", "win32", "nt"),
        calls.append,
    )
    samples = (
        r"C:\Test\logs",
        r"C:\Test Data\logs folder",
        r"C:\测试用户\日志 目录",
        r"relative logs\nested",
        r"C:\missing target\logs",
    )
    before_cwd = Path.cwd()
    before_environment = os.environ.copy()
    before_threads = tuple(thread.ident for thread in threading.enumerate())
    for path in samples:
        require(integration.open_directory(path) is None, "Windows open-directory return changed")
    require(calls == list(samples), "Windows path string/order/call count changed")

    events: list[object] = []
    path_like = RecordingPath(r"C:\PathLike 中文\logs", events)
    integration.open_directory(path_like)
    require(
        events == [("str", r"C:\PathLike 中文\logs")]
        and calls[-1] == r"C:\PathLike 中文\logs",
        "Windows integration did not preserve str(path) forwarding",
    )
    require(Path.cwd() == before_cwd, "Windows integration changed cwd")
    require(os.environ == before_environment, "Windows integration changed the environment")
    require(
        tuple(thread.ident for thread in threading.enumerate()) == before_threads,
        "Windows integration created a thread",
    )

    frozen = WindowsDesktopIntegration(_platform("Windows", "win32", "nt"), calls.append)
    try:
        frozen.shell_opener = lambda _path: None  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("WindowsDesktopIntegration is not frozen")


def _assert_error_identity_and_delayed_opener() -> None:
    windows_info = _platform("Windows", "win32", "nt")
    for error in (
        FileNotFoundError("raw missing"),
        PermissionError("raw denied"),
        OSError("raw system"),
    ):
        integration = WindowsDesktopIntegration(
            windows_info,
            lambda _path, error=error: (_ for _ in ()).throw(error),
        )
        try:
            integration.open_directory(r"C:\Test\logs")
        except BaseException as caught:
            require(caught is error, f"desktop integration replaced {type(error).__name__}")
        else:
            raise AssertionError(f"desktop integration swallowed {type(error).__name__}")

    original_startfile = desktop.os.startfile
    delattr(desktop.os, "startfile")
    try:
        integration = WindowsDesktopIntegration(windows_info)
        try:
            integration.open_directory(r"C:\Test\logs")
        except AttributeError as exc:
            require("startfile" in str(exc), "unavailable opener error lost its raw detail")
        else:
            raise AssertionError("unavailable default opener did not raise AttributeError")
    finally:
        desktop.os.startfile = original_startfile  # type: ignore[attr-defined]


def _assert_windows_application_identity() -> None:
    windows_info = _platform("Windows", "win32", "nt")
    calls: list[str] = []
    integration = WindowsDesktopIntegration(
        windows_info,
        lambda _path: None,
        calls.append,
    )
    before_cwd = Path.cwd()
    before_environment = os.environ.copy()
    before_threads = tuple(thread.ident for thread in threading.enumerate())
    require(
        integration.configure_application_identity("forgottenlab.launchflow.editor") is True,
        "Windows application-identity success return changed",
    )
    require(
        integration.configure_application_identity("custom.launchflow.identity") is True,
        "Windows explicit application-identity return changed",
    )
    require(
        calls == ["forgottenlab.launchflow.editor", "custom.launchflow.identity"],
        "Windows application identity value/order/call count changed",
    )
    require(Path.cwd() == before_cwd, "application identity changed cwd")
    require(os.environ == before_environment, "application identity changed the environment")
    require(
        tuple(thread.ident for thread in threading.enumerate()) == before_threads,
        "application identity created a thread",
    )

    for error in (AttributeError("raw missing"), OSError("raw system")):
        error_calls: list[str] = []

        def raise_handled(app_id: str, error: BaseException = error) -> object:
            error_calls.append(app_id)
            raise error

        handled = WindowsDesktopIntegration(windows_info, lambda _path: None, raise_handled)
        require(
            handled.configure_application_identity("handled.identity") is False,
            f"Windows identity no longer handles {type(error).__name__}",
        )
        require(error_calls == ["handled.identity"], "handled identity setter call count changed")

    sentinel = RuntimeError("raw identity failure")

    def raise_other(_app_id: str) -> object:
        raise sentinel

    unhandled = WindowsDesktopIntegration(windows_info, lambda _path: None, raise_other)
    try:
        unhandled.configure_application_identity("unhandled.identity")
    except BaseException as caught:
        require(caught is sentinel, "Windows identity replaced an unhandled error")
    else:
        raise AssertionError("Windows identity swallowed an unhandled error")

    original_ctypes = desktop.ctypes
    desktop.ctypes = object()  # type: ignore[assignment]
    try:
        require(
            WindowsDesktopIntegration(windows_info).configure_application_identity("missing.windll") is False,
            "missing ctypes.windll no longer maps to False",
        )
    finally:
        desktop.ctypes = original_ctypes  # type: ignore[assignment]

    frozen = WindowsDesktopIntegration(windows_info, lambda _path: None, calls.append)
    try:
        frozen.identity_setter = lambda _app_id: None  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("WindowsDesktopIntegration identity setter is not frozen")


def _assert_diagnostics_compatibility() -> None:
    require(str(inspect.signature(diagnostics.open_logs_directory)) == "() -> 'Path'", "public signature changed")

    original_get_logs_dir = diagnostics.get_logs_dir
    original_factory = diagnostics.get_desktop_integration
    try:
        events: list[object] = []
        logs_dir = RecordingPath(r"relative logs\中文 目录", events)
        factory_calls: list[bool] = []

        class RecordingIntegration:
            def open_directory(self, path: object) -> None:
                events.append(("open_directory", path))

        diagnostics.get_logs_dir = lambda: logs_dir  # type: ignore[assignment]
        diagnostics.get_desktop_integration = (  # type: ignore[assignment]
            lambda: factory_calls.append(True) or RecordingIntegration()
        )
        returned = diagnostics.open_logs_directory()
        require(returned is logs_dir, "open_logs_directory stopped returning its original path")
        require(factory_calls == [True], "diagnostics did not call the platform factory exactly once")
        require(
            events == [("mkdir", True, True), ("open_directory", logs_dir)],
            "diagnostics directory-create/open order changed",
        )

        for error in (
            FileNotFoundError("raw missing"),
            PermissionError("raw denied"),
            OSError("raw system"),
        ):
            error_events: list[object] = []
            error_path = RecordingPath("error logs", error_events)

            class RaisingIntegration:
                def open_directory(self, _path: object, error: BaseException = error) -> None:
                    raise error

            diagnostics.get_logs_dir = lambda error_path=error_path: error_path  # type: ignore[assignment]
            diagnostics.get_desktop_integration = lambda: RaisingIntegration()  # type: ignore[assignment]
            try:
                diagnostics.open_logs_directory()
            except BaseException as caught:
                require(caught is error, f"diagnostics replaced {type(error).__name__}")
            else:
                raise AssertionError(f"diagnostics swallowed {type(error).__name__}")
            require(error_events == [("mkdir", True, True)], "diagnostics changed mkdir-before-open ordering")

        mkdir_error = PermissionError("raw mkdir denied")
        factory_called: list[bool] = []

        class RaisingPath(RecordingPath):
            def mkdir(self, *, parents: bool, exist_ok: bool) -> None:
                raise mkdir_error

        diagnostics.get_logs_dir = lambda: RaisingPath("mkdir error", [])  # type: ignore[assignment]
        diagnostics.get_desktop_integration = (  # type: ignore[assignment]
            lambda: factory_called.append(True) or RecordingIntegration()
        )
        try:
            diagnostics.open_logs_directory()
        except PermissionError as caught:
            require(caught is mkdir_error, "diagnostics replaced the mkdir exception")
        else:
            raise AssertionError("diagnostics swallowed the mkdir exception")
        require(factory_called == [], "desktop factory ran before directory creation completed")

        legacy_events: list[object] = []
        legacy_path = RecordingPath("legacy logs", legacy_events)
        legacy = LegacyPosixDesktopIntegration(_platform("Linux", "linux"))
        diagnostics.get_logs_dir = lambda: legacy_path  # type: ignore[assignment]
        diagnostics.get_desktop_integration = lambda: legacy  # type: ignore[assignment]
        require(diagnostics.open_logs_directory() is legacy_path, "non-Windows diagnostics return changed")
        require(legacy_events == [("mkdir", True, True)], "non-Windows diagnostics stopped being a silent no-op")
    finally:
        diagnostics.get_logs_dir = original_get_logs_dir  # type: ignore[assignment]
        diagnostics.get_desktop_integration = original_factory  # type: ignore[assignment]

    source = inspect.getsource(diagnostics.open_logs_directory)
    require("get_logs_dir()" in source, "logs directory source changed")
    require("os.startfile" not in source and "os.name" not in source, "diagnostics retained direct Windows coupling")
    require("get_desktop_integration()" in source, "diagnostics bypassed DesktopIntegration")


def _assert_import_and_dependency_boundaries(probe_cwd: Path) -> None:
    path = PROJECT_ROOT / "shared" / "platform" / "desktop.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= (set(sys.stdlib_module_names) | {"shared"}), f"non-stdlib import found: {imports}")
    forbidden = (
        "PySide",
        "QDesktopServices",
        "explorer.exe",
        "cmd /c start",
        "shell=True",
        "xdg-open",
        "gio open",
        "Finder",
        "subprocess",
        "threading",
        "winreg",
    )
    require(not any(value in text for value in forbidden), "desktop integration gained a forbidden dependency/opener")
    require(
        text.count("ctypes.windll.shell32") == 1
        and text.count("shell32.SetCurrentProcessExplicitAppUserModelID(app_id)") == 1,
        "desktop integration lost the exact delayed shell32 identity call",
    )

    before_environment = os.environ.copy()
    before_cwd = Path.cwd()
    injected_calls: list[str] = []
    injected_identity_calls: list[str] = []
    get_desktop_integration(
        platform_info=_platform("Windows", "win32", "nt"),
        shell_opener=injected_calls.append,
        identity_setter=injected_identity_calls.append,
    )
    require(injected_calls == [], "factory opened a directory")
    require(injected_identity_calls == [], "factory configured application identity")
    require(os.environ == before_environment and Path.cwd() == before_cwd, "factory changed process state")

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    before_entries = tuple(sorted(path.name for path in probe_cwd.iterdir()))
    probe = (
        "import os,sys; before=dict(os.environ); cwd=os.getcwd(); calls=[]; before_modules=set(sys.modules); "
        "os.startfile=lambda path: calls.append(path); "
        "import shared.platform.desktop as desktop; "
        "from shared.platform.base import PlatformInfo; "
        "info=PlatformInfo('windows','x86_64','nt','win32'); identity_calls=[]; "
        "desktop.get_desktop_integration(platform_info=info,identity_setter=identity_calls.append); "
        "assert calls==[] and identity_calls==[] and os.getcwd()==cwd and dict(os.environ)==before; "
        "added=set(sys.modules)-before_modules; "
        "assert not any(name.startswith('PySide') or name=='winreg' for name in added)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=probe_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    require(completed.returncode == 0, f"side-effect import probe failed: {completed.stderr}")
    require(
        tuple(sorted(path.name for path in probe_cwd.iterdir())) == before_entries,
        "desktop import/factory wrote into cwd",
    )


def main() -> None:
    _assert_backend_selection()
    _assert_windows_directory_open()
    _assert_error_identity_and_delayed_opener()
    _assert_windows_application_identity()
    _assert_diagnostics_compatibility()
    _assert_import_and_dependency_boundaries(PROJECT_ROOT)
    print("desktop integration smoke ok")
    print("backend=windows,legacy-posix,unknown-not-windows")
    print("windows=startfile-once,path-string-exact,no-existence-probe")
    print("identity=shell32-once,value-exact,true-false-and-error-compatible")
    print("non_windows=mkdir-then-silent-no-op,no-support-claim")
    print("diagnostics=public-api,path-source,mkdir-order,return-value-compatible")
    print("errors=mkdir,startfile,not-found,permission,oserror,raw-preserved")
    print("side_effects=import:none,construct:none,factory:none,cwd:none,environment:none,registry:none")
    print("forbidden=explorer,cmd-start,shell,qdesktopservices,xdg,gio,macos-open")
    print("dependencies=stdlib-only,no-qt")


if __name__ == "__main__":
    main()
