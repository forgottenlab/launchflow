"""Verify Phase 1c ApplicationLauncher behavior and Windows equivalence."""

from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.launcher_runtime import RuntimeExecutor, application_popen_options
from shared.models import AppStep
from shared.platform.applications import (
    ApplicationLaunchSpec,
    ApplicationLauncher,
    LegacyPosixApplicationLauncher,
    WindowsApplicationLauncher,
    get_application_launcher,
)
from shared.platform.base import PlatformInfo
from shared.platform.detection import detect_platform
from tools.build_single_exe import (
    APPLICATION_ASSET_DIR,
    APPLICATION_ASSET_PREFIX,
    APPLICATION_LAUNCH_SCHEMA,
    EMBEDDED_TEMPLATE,
    _prepare_embedded_plan_and_assets,
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


class FakePaths:
    def __init__(self) -> None:
        self.existing: set[str] = set()
        self.directories: set[str] = set()

    def exists(self, path: str) -> bool:
        return path in self.existing

    def is_directory(self, path: str) -> bool:
        return path in self.directories


def _windows_launcher(paths: FakePaths) -> WindowsApplicationLauncher:
    launcher = get_application_launcher(
        platform_info=_platform("Windows", "win32", "nt"),
        path_exists=paths.exists,
        path_is_directory=paths.is_directory,
    )
    require(isinstance(launcher, WindowsApplicationLauncher), "Windows launcher was not selected")
    require(isinstance(launcher, ApplicationLauncher), "Windows launcher does not satisfy Protocol")
    return launcher


def _assert_backend_selection() -> None:
    paths = FakePaths()
    windows = _windows_launcher(paths)
    require("shortcut" in windows.supported_target_kinds, "Windows shortcut capability missing")

    for system, sys_platform in (("Linux", "linux"), ("Darwin", "darwin"), ("Other", "other")):
        launcher = get_application_launcher(
            platform_info=_platform(system, sys_platform),
            path_exists=lambda _path: True,
            path_is_directory=lambda _path: False,
        )
        require(isinstance(launcher, LegacyPosixApplicationLauncher), f"legacy launcher missing: {system}")
        require(launcher.supported_target_kinds == (), f"legacy launcher claimed support: {system}")
        spec = launcher.build_launch_spec("/tmp/tool", ("--flag",), "", True)
        require(spec.command_args == ("/tmp/tool", "--flag"), "legacy direct Popen fallback changed")
        require(spec.creationflags == 0 and not spec.use_startupinfo, "legacy launcher used Windows flags")


def _assert_target_classification() -> None:
    paths = FakePaths()
    samples = {
        r"C:\Apps\Demo.EXE": "executable",
        r"C:\Apps\tool.CoM": "com",
        r"C:\Apps\setup.BAT": "batch",
        r"C:\Apps\run.CmD": "command_script",
        r"C:\Apps\task.PS1": "powershell_script",
        r"C:\Apps\Demo.LNK": "shortcut",
        r"C:\Apps\native-tool": "no_extension",
        r"C:\Apps\document.xyz": "other",
        r"C:\Apps\folder": "directory",
    }
    paths.existing.update(samples)
    paths.directories.add(r"C:\Apps\folder")
    launcher = _windows_launcher(paths)
    for path, expected in samples.items():
        require(launcher.classify_target(path) == expected, f"classification changed: {path}")
    require(launcher.classify_target(r"C:\missing.exe") == "missing", "missing target was not classified first")


def _assert_exact_specs() -> None:
    paths = FakePaths()
    direct_targets = {
        "executable": r"C:\Program Files\应用\demo.exe",
        "com": r"C:\Apps\tool.com",
        "batch": r"C:\Apps\setup.bat",
        "command_script": r"C:\Apps\run.cmd",
        "no_extension": r"C:\Apps\native-tool",
        "other": r"C:\Apps\custom.xyz",
    }
    paths.existing.update(direct_targets.values())
    ps1 = r"C:\Scripts 中文\run.ps1"
    shortcut = r"C:\Links\Demo.lnk"
    paths.existing.update((ps1, shortcut))
    launcher = _windows_launcher(paths)
    arguments = (
        "",
        "one",
        "two words",
        "中文参数",
        'double"quote',
        "single'quote",
        "%TEMP%",
        "C:\\path with space\\",
        "trailing\\",
    )
    cwd = r"C:\Working Dir 中文\not-normalized\.."

    for expected_kind, target in direct_targets.items():
        spec = launcher.build_launch_spec(target, arguments, cwd, False)
        require(spec.target_kind == expected_kind and spec.launch_mode == "process", f"kind changed: {target}")
        require(spec.executable == target, f"executable changed: {target}")
        require(spec.command_args == (target, *arguments), f"direct argv changed: {target}")
        require(spec.cwd == cwd, "cwd was expanded, resolved, or rewritten")
        require(spec.creationflags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "hidden flag missing")
        require(not spec.use_startupinfo, "non-minimized launch gained startupinfo")
        require(spec.use_stdin_devnull and spec.use_stdout_devnull and spec.use_stderr_devnull, "DEVNULL contract changed")

    empty_cwd = launcher.build_launch_spec(direct_targets["executable"], (), "", False)
    require(empty_cwd.cwd is None and empty_cwd.command_args == (direct_targets["executable"],), "empty args/cwd changed")

    ps_spec = launcher.build_launch_spec(ps1, arguments, cwd, False)
    require(
        ps_spec.command_args == ("powershell", "-ExecutionPolicy", "Bypass", "-File", ps1, *arguments),
        "PowerShell Application argv changed",
    )
    require(ps_spec.executable == "powershell", "PowerShell executable changed")

    link_spec = launcher.build_launch_spec(shortcut, arguments, cwd, True)
    require(link_spec.launch_mode == "shell_open" and link_spec.target_kind == "shortcut", "shortcut mode changed")
    require(link_spec.resolved_target == shortcut and link_spec.command_args == (), "shortcut target changed")
    require(link_spec.executable is None and link_spec.cwd is None, "shortcut gained process fields")
    require(link_spec.creationflags == 0 and not link_spec.use_startupinfo, "shortcut gained process options")
    require(not link_spec.use_stdin_devnull, "shortcut incorrectly claims process stream control")

    minimized = launcher.build_launch_spec(direct_targets["executable"], (), "", True)
    require(minimized.use_startupinfo, "start-minimized startupinfo missing")
    require(
        minimized.startupinfo_dw_flags & getattr(subprocess, "STARTF_USESHOWWINDOW", 1),
        "STARTF_USESHOWWINDOW missing",
    )
    require(minimized.startupinfo_show_window == 6, "existing wShowWindow=6 contract changed")

    script_minimized = launcher.build_launch_spec(ps1, (), "", True)
    require(script_minimized.startupinfo_show_window == 6, "script start-minimized contract changed")


def _assert_runtime_fire_and_forget(temp_root: Path) -> None:
    import runtime.launcher_runtime as launcher_runtime

    target = temp_root / "Application 中文.exe"
    target.write_bytes(b"fixture")
    captured: dict[str, object] = {"calls": 0}
    get_application_launcher()

    class FakeProcess:
        def wait(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("Application runtime called wait()")

        def communicate(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("Application runtime called communicate()")

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        captured["calls"] = int(captured["calls"]) + 1
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    original_popen = launcher_runtime.subprocess.Popen
    launcher_runtime.subprocess.Popen = fake_popen  # type: ignore[assignment]
    try:
        result = RuntimeExecutor(log_callback=lambda _message: None).run_app_step(
            AppStep(
                name="runtime fixture",
                path=str(target),
                args=["--one", "two words", "中文"],
                working_dir=str(temp_root / "missing cwd remains untouched"),
                start_minimized=True,
            )
        )
    finally:
        launcher_runtime.subprocess.Popen = original_popen  # type: ignore[assignment]

    require(result is None and captured["calls"] == 1, "Application was not one-shot fire-and-forget")
    require(captured["args"] == [str(target), "--one", "two words", "中文"], "runtime argv changed")
    kwargs = captured["kwargs"]
    require(isinstance(kwargs, dict), "runtime kwargs missing")
    require(kwargs.get("cwd") == str(temp_root / "missing cwd remains untouched"), "runtime cwd changed")
    for stream in ("stdin", "stdout", "stderr"):
        require(kwargs.get(stream) is subprocess.DEVNULL, f"runtime {stream} is not DEVNULL")
    require("env" not in kwargs, "Application runtime unexpectedly modified environment")
    require(kwargs.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, "runtime hidden flag missing")
    startupinfo = kwargs.get("startupinfo")
    require(startupinfo is not None and startupinfo.wShowWindow == 6, "runtime minimized startupinfo changed")

    shortcut = temp_root / "shortcut.lnk"
    shortcut.write_bytes(b"fixture")
    opened: list[str] = []
    original_startfile = launcher_runtime.os.startfile
    launcher_runtime.os.startfile = opened.append  # type: ignore[attr-defined]
    try:
        RuntimeExecutor(log_callback=lambda _message: None).run_app_step(
            AppStep(name="shortcut", path=str(shortcut), args=["ignored"], working_dir="ignored", start_minimized=True)
        )
    finally:
        launcher_runtime.os.startfile = original_startfile  # type: ignore[attr-defined]
    require(opened == [str(shortcut)], "shortcut no longer uses one shell-open call")
    require(captured["calls"] == 1, "shortcut unexpectedly used Popen")


def _assert_errors(temp_root: Path) -> None:
    import runtime.launcher_runtime as launcher_runtime

    launcher = get_application_launcher(
        platform_info=_platform("Windows", "win32", "nt"),
        path_exists=lambda _path: False,
        path_is_directory=lambda _path: False,
    )
    missing = r"C:\missing\app.exe"
    try:
        launcher.build_launch_spec(missing, (), "", False)
    except FileNotFoundError as exc:
        require(str(exc) == f"程序路径不存在: {missing}", "missing-path exception text changed")
    else:
        raise AssertionError("missing target did not raise FileNotFoundError")

    messages = {
        FileNotFoundError("missing"): "路径",
        PermissionError("denied"): "权限",
        IsADirectoryError("directory"): "目录",
        OSError("other"): "系统错误",
    }
    for error, expected in messages.items():
        require(expected in launcher.explain_launch_error(error), f"friendly launch error missing: {error}")

    target = temp_root / "raises.exe"
    target.write_bytes(b"fixture")
    original_popen = launcher_runtime.subprocess.Popen
    for error in (
        FileNotFoundError("invalid cwd"),
        PermissionError("denied"),
        IsADirectoryError("directory"),
        OSError("system"),
    ):
        launcher_runtime.subprocess.Popen = lambda *_args, _error=error, **_kwargs: (_ for _ in ()).throw(_error)  # type: ignore[assignment]
        try:
            RuntimeExecutor().run_app_step(AppStep(path=str(target)))
        except BaseException as caught:
            require(caught is error, f"runtime replaced original launch exception: {error}")
        else:
            raise AssertionError(f"runtime swallowed launch exception: {error}")
    launcher_runtime.subprocess.Popen = original_popen  # type: ignore[assignment]

    shortcut = temp_root / "raises.lnk"
    shortcut.write_bytes(b"fixture")
    shell_error = OSError("shell launch failed")
    original_startfile = launcher_runtime.os.startfile
    launcher_runtime.os.startfile = lambda *_args: (_ for _ in ()).throw(shell_error)  # type: ignore[attr-defined]
    try:
        RuntimeExecutor().run_app_step(AppStep(path=str(shortcut)))
    except OSError as caught:
        require(caught is shell_error, "shortcut shell error was replaced")
    else:
        raise AssertionError("shortcut shell error was swallowed")
    finally:
        launcher_runtime.os.startfile = original_startfile  # type: ignore[attr-defined]


def _assert_export_contract(temp_root: Path) -> None:
    cmd_path = temp_root / "asset app.cmd"
    ps1_path = temp_root / "asset script.ps1"
    cmd_path.write_text("@exit /b 0\n", encoding="utf-8")
    ps1_path.write_text("exit 0\n", encoding="utf-8")
    original = {
        "plan_name": "application export contract",
        "steps": [
            {"type": "app", "path": str(cmd_path), "args": ["two words", "中文"], "working_dir": "", "start_minimized": True},
            {"type": "app", "path": str(ps1_path), "args": ["%TEMP%"], "working_dir": r"C:\explicit cwd", "start_minimized": False},
            {"type": "app", "path": r"C:\links\demo.lnk", "args": ["ignored"], "working_dir": "ignored", "start_minimized": True},
        ],
    }
    snapshot = json.dumps(original, sort_keys=True)
    prepared, assets = _prepare_embedded_plan_and_assets(original)
    require(json.dumps(original, sort_keys=True) == snapshot, "export preparation mutated the source plan")
    require(len(assets) == 2, "packable Application asset set changed")
    cmd_launch, ps_launch, link_launch = (step["_application_launch"] for step in prepared["steps"])
    require(cmd_launch["schema"] == APPLICATION_LAUNCH_SCHEMA, "Application contract schema missing")
    require(cmd_launch["target_kind"] == "command_script", "bundled cmd classification changed")
    require(cmd_launch["command_args"][0].startswith(APPLICATION_ASSET_PREFIX), "bundled target token missing")
    require(cmd_launch["cwd"] == APPLICATION_ASSET_DIR, "bundled empty cwd no longer uses asset parent")
    require(cmd_launch["use_startupinfo"] and cmd_launch["startupinfo_show_window"] == 6, "bundled minimized contract changed")
    require(ps_launch["command_args"][:4] == ["powershell", "-ExecutionPolicy", "Bypass", "-File"], "bundled ps1 argv changed")
    require(ps_launch["cwd"] == r"C:\explicit cwd", "explicit bundled cwd was replaced")
    require(link_launch["launch_mode"] == "shell_open" and "_embedded_asset" not in prepared["steps"][2], "shortcut export changed")

    old_data_root = os.environ.get("LAUNCHFLOW_DATA_DIR")
    try:
        os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp_root / "embedded data")
        script = EMBEDDED_TEMPLATE.replace("__PLAN_DATA__", repr(prepared))
        namespace = {"__name__": "launchflow_application_embedded_smoke", "__file__": str(temp_root / "launcher.py")}
        exec(compile(script, "<application_embedded_smoke>", "exec"), namespace)
        embedded_asset = str(prepared["steps"][0]["_embedded_asset"])
        runtime_asset = temp_root / embedded_asset
        runtime_asset.parent.mkdir(parents=True, exist_ok=True)
        runtime_asset.write_bytes(b"fixture")
        captured: dict[str, object] = {}

        class FakeStartupInfo:
            def __init__(self) -> None:
                self.dwFlags = 0
                self.wShowWindow = 0

        class FakeSubprocess:
            DEVNULL = subprocess.DEVNULL
            STARTUPINFO = FakeStartupInfo

            @staticmethod
            def Popen(args: list[str], **kwargs: object) -> object:
                captured["args"] = args
                captured["kwargs"] = kwargs
                return object()

        namespace["subprocess"] = FakeSubprocess
        namespace["run_app_step"](prepared["steps"][0])
        require(captured["args"][0] == str(runtime_asset), "embedded target was not relocated")
        kwargs = captured["kwargs"]
        require(isinstance(kwargs, dict) and kwargs.get("cwd") == str(runtime_asset.parent), "embedded cwd relocation changed")
        for stream in ("stdin", "stdout", "stderr"):
            require(kwargs.get(stream) is subprocess.DEVNULL, f"embedded {stream} is not DEVNULL")
    finally:
        if old_data_root is None:
            os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
        else:
            os.environ["LAUNCHFLOW_DATA_DIR"] = old_data_root


def _assert_public_and_dependency_contract() -> None:
    require(str(inspect.signature(application_popen_options)) == "(start_minimized: 'bool' = False) -> 'dict'", "runtime compatibility signature changed")
    require(
        tuple(ApplicationLaunchSpec.__dataclass_fields__)
        == (
            "launch_mode",
            "target_kind",
            "executable",
            "command_args",
            "cwd",
            "creationflags",
            "use_startupinfo",
            "startupinfo_dw_flags",
            "startupinfo_show_window",
            "use_stdin_devnull",
            "use_stdout_devnull",
            "use_stderr_devnull",
            "resolved_target",
        ),
        "ApplicationLaunchSpec fields changed",
    )
    path = PROJECT_ROOT / "shared" / "platform" / "applications.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= (set(sys.stdlib_module_names) | {"shared"}), f"non-stdlib import found: {imports}")
    require("PySide" not in text and "shared.models" not in text, "platform layer imported UI or model code")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        require(name not in {"subprocess.Popen", "os.startfile"}, f"platform layer executes targets: {name}")


def _assert_import_side_effects(temp_root: Path) -> None:
    alternate_cwd = temp_root / "alternate cwd"
    alternate_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    probe = (
        "import os,subprocess; before=dict(os.environ); cwd=os.getcwd(); "
        "subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Popen called')); "
        "os.startfile=lambda *a,**k: (_ for _ in ()).throw(AssertionError('startfile called')); "
        "import shared.platform.applications; "
        "assert os.getcwd()==cwd and dict(os.environ)==before"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=alternate_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    require(completed.returncode == 0, f"side-effect import failed: {completed.stderr}")
    require(list(alternate_cwd.iterdir()) == [], "Application import wrote into cwd")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-application-backend-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    try:
        _assert_backend_selection()
        _assert_target_classification()
        _assert_exact_specs()
        _assert_runtime_fire_and_forget(temp_root)
        _assert_errors(temp_root)
        _assert_export_contract(temp_root)
        _assert_public_and_dependency_contract()
        _assert_import_side_effects(temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    require(not temp_root.exists(), "Application backend smoke left temporary data")
    print("application backend smoke ok")
    print("backend=windows,legacy-posix,unknown-not-windows")
    print("classification=exe,com,bat,cmd,ps1,lnk,no-extension,other,directory,missing,case-insensitive")
    print("argv=direct-process,powershell-file,arguments-exact,no-shlex")
    print("cwd=explicit,none,unresolved,bundled-parent")
    print("start_minimized=false,true,gui,script,wShowWindow-6")
    print("fire_and_forget=popen-once,no-wait,no-communicate,no-env,no-thread")
    print("streams=stdin-devnull,stdout-devnull,stderr-devnull")
    print("shortcut=shell-open,no-process-options")
    print("errors=missing,permission,directory,invalid-cwd,oserror,shell-open,raw-preserved")
    print("export_contract=json-safe,versioned,asset-relocated,source-plan-unchanged")
    print("side_effects=import:none,process:none,cwd:none,environment:none,registry:none")
    print("dependencies=stdlib-only,no-qt,no-model")


if __name__ == "__main__":
    main()
