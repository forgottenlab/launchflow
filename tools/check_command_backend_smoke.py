"""Verify Phase 1b CommandBackend behavior and Windows equivalence."""

from __future__ import annotations

import ast
import inspect
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

from runtime.command_runner import CommandResult, build_command_args, execute_command, friendly_command_error
from shared.platform.base import PlatformInfo
from shared.platform.detection import detect_platform
from shared.platform.process import (
    CommandBackend,
    LegacyPosixCommandBackend,
    WindowsCommandBackend,
    get_command_backend,
)
from tools.build_single_exe import _prepare_embedded_plan_and_assets


CMD_PREFIX = ("cmd.exe", "/d", "/s", "/c")
POWERSHELL_PREFIX = (
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeStartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = -1


def _platform(system: str, sys_platform: str, os_name: str = "posix") -> PlatformInfo:
    return detect_platform(
        system=system,
        machine="x86_64",
        os_name=os_name,
        sys_platform=sys_platform,
    )


def _windows_backend() -> WindowsCommandBackend:
    info = _platform("Windows", "win32", "nt")
    backend = get_command_backend(
        platform_info=info,
        startupinfo_factory=FakeStartupInfo,
        quote_token_factory=lambda: "FIXEDTOKEN",
    )
    require(isinstance(backend, WindowsCommandBackend), "Windows backend was not selected")
    require(isinstance(backend, CommandBackend), "Windows backend does not satisfy Protocol")
    return backend


def _assert_backend_selection() -> None:
    windows = _windows_backend()
    require(windows.supported_shells == ("cmd", "powershell"), "Windows shell capability changed")
    require(windows.default_shell == "cmd", "Windows default shell changed")

    factory_calls: list[bool] = []

    def forbidden_startupinfo() -> object:
        factory_calls.append(True)
        raise AssertionError("non-Windows backend accessed Windows startupinfo")

    for system, sys_platform in (("Linux", "linux"), ("Darwin", "darwin"), ("Other", "other")):
        backend = get_command_backend(
            platform_info=_platform(system, sys_platform),
            startupinfo_factory=forbidden_startupinfo,
        )
        require(isinstance(backend, LegacyPosixCommandBackend), f"legacy backend not selected: {system}")
        require(backend.supported_shells == (), f"legacy backend claimed shell support: {system}")
        spec = backend.build_launch_spec("echo legacy", "cmd")
        require(spec.command_args == ("/bin/sh", "-c", "echo legacy"), "legacy fallback changed")
        require(spec.creationflags == 0 and spec.startupinfo is None, "legacy backend used Windows flags")
    require(factory_calls == [], "non-Windows injection touched Windows-only construction")


def _assert_cmd_specs() -> None:
    backend = _windows_backend()
    commands = (
        "echo hello",
        r'"C:\Program Files\Demo\demo.exe" --flag',
        "echo 中文",
        "echo %PATH%",
        "echo one & echo two",
        "echo one | findstr one",
        "echo text > output.txt",
        "echo ^&",
        "echo first\necho second",
        "",
    )
    for command in commands:
        spec = backend.build_launch_spec(command, "cmd")
        require(spec.command_args == (*CMD_PREFIX, command), f"cmd argv changed: {command!r}")
        require(spec.creationflags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "hidden flag missing")
        require(spec.startupinfo is not None, "startupinfo missing")
        require(
            spec.startupinfo.dwFlags & getattr(subprocess, "STARTF_USESHOWWINDOW", 1),
            "STARTF_USESHOWWINDOW missing",
        )
        require(spec.startupinfo.wShowWindow == getattr(subprocess, "SW_HIDE", 0), "SW_HIDE changed")

        if '"' in command:
            expected = command.replace('"', "%__LAUNCHFLOW_DQ_FIXEDTOKEN%")
            require(spec.process_args == (*CMD_PREFIX, expected), "cmd quote workaround changed")
            require(
                spec.environment_overrides == (("__LAUNCHFLOW_DQ_FIXEDTOKEN", '"'),),
                "cmd quote environment changed",
            )
        else:
            require(spec.process_args == spec.command_args, "unquoted cmd text was rewritten")
            require(spec.environment_overrides == (), "unquoted cmd gained environment mutation")

    for shell in ("", "unknown", "CMD"):
        require(
            backend.build_launch_spec("echo fallback", shell).command_args == (*CMD_PREFIX, "echo fallback"),
            f"non-PowerShell fallback changed: {shell!r}",
        )
    require(build_command_args("echo public", "cmd") == [*CMD_PREFIX, "echo public"], "public cmd API changed")


def _assert_powershell_specs() -> None:
    backend = _windows_backend()
    commands = (
        "Write-Output 'simple'",
        'Write-Output "double quoted"',
        "Write-Output '中文'",
        "$env:PATH",
        "& 'C:\\Program Files\\Demo\\demo.exe'",
        "Write-Output 'first'\nWrite-Output 'second'",
        "",
    )
    for command in commands:
        spec = backend.build_launch_spec(command, " PowerShell ")
        require(spec.command_args == (*POWERSHELL_PREFIX, command), f"PowerShell argv changed: {command!r}")
        require(spec.process_args == spec.command_args, "PowerShell text was rewritten")
        require(spec.environment_overrides == (), "PowerShell gained environment mutation")
    require(
        build_command_args("Write-Output public", "powershell")
        == [*POWERSHELL_PREFIX, "Write-Output public"],
        "public PowerShell API changed",
    )


def _assert_decode_and_errors() -> None:
    backend = _windows_backend()
    utf8_text = "中文 output"
    require(backend.decode_output(utf8_text.encode("utf-8")) == utf8_text, "UTF-8 Chinese decode changed")
    invalid = backend.decode_output(b"valid\xffinvalid")
    require(isinstance(invalid, str) and invalid, "invalid bytes lost the output")
    try:
        backend.decode_output("already text")  # type: ignore[arg-type]
    except AttributeError:
        pass
    else:
        raise AssertionError("str input unexpectedly changed the bytes-only decode contract")

    require(backend.classify_launch_error(FileNotFoundError("missing")) == "not_found", "FileNotFoundError changed")
    require(backend.classify_launch_error(PermissionError("denied")) == "permission_denied", "PermissionError changed")
    require(backend.classify_launch_error(OSError("other")) == "system_error", "generic OSError changed")
    require("PATH" in backend.explain_failure(9009, None), "9009 explanation changed")
    require("路径" in backend.explain_failure(-1, "not_found"), "not-found explanation changed")
    require("权限" in backend.explain_failure(-1, "permission_denied"), "permission explanation changed")
    require("退出码" in backend.explain_failure(7, None), "generic nonzero explanation changed")

    raw_stderr = "RAW_STDERR_MUST_REMAIN"
    result = CommandResult(["cmd.exe"], 9009, "RAW_STDOUT", raw_stderr)
    require(friendly_command_error(result) is not None, "nonzero result lost friendly explanation")
    require(result.stderr == raw_stderr and result.returncode == 9009, "friendly explanation replaced raw result")


def _assert_runtime_popen_contract() -> None:
    import runtime.command_runner as command_runner

    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 7

        def communicate(self) -> tuple[bytes, bytes]:
            captured["communicate"] = True
            return "标准输出".encode("utf-8"), "标准错误".encode("utf-8")

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    original_popen = command_runner.subprocess.Popen
    original_environment = os.environ.copy()
    command_runner.subprocess.Popen = fake_popen  # type: ignore[assignment]
    try:
        result = execute_command('echo "中文 路径"', "cmd", "C:/working dir")
    finally:
        command_runner.subprocess.Popen = original_popen  # type: ignore[assignment]

    require(captured.get("communicate") is True, "runtime stopped using communicate()")
    kwargs = captured.get("kwargs")
    require(isinstance(kwargs, dict), "runtime Popen kwargs were not captured")
    require(kwargs.get("cwd") == "C:/working dir", "cwd forwarding changed")
    require(kwargs.get("stdin") is subprocess.DEVNULL, "stdin is not DEVNULL")
    require(kwargs.get("stdout") is subprocess.PIPE, "stdout is not PIPE")
    require(kwargs.get("stderr") is subprocess.PIPE, "stderr is not PIPE")
    require(kwargs.get("shell") is False, "shell=False changed")
    require(kwargs.get("creationflags", 0) & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "Popen hidden flag missing")
    startupinfo = kwargs.get("startupinfo")
    require(startupinfo is not None, "Popen startupinfo missing")
    child_env = kwargs.get("env")
    require(isinstance(child_env, dict) and child_env is not os.environ, "quoted cmd did not get a child-only env")
    quote_keys = [key for key in child_env if key.startswith("__LAUNCHFLOW_DQ_")]
    require(len(quote_keys) == 1 and child_env[quote_keys[0]] == '"', "quote environment contract changed")
    require(os.environ == original_environment, "execute_command modified the parent environment")
    require(result.returncode == 7 and not result.succeeded, "nonzero result semantics changed")
    require(result.stdout == "标准输出" and result.stderr == "标准错误", "captured streams changed")
    require(result.launch_error is None and result.error_kind is None, "nonzero exit became a launch exception")


def _assert_export_contract() -> None:
    original = {
        "plan_name": "backend export contract",
        "steps": [
            {
                "type": "command",
                "command": 'echo %PATH% & echo "中文 路径"',
                "shell": "cmd",
                "working_dir": "",
            },
            {
                "type": "command",
                "command": "Write-Output '$env:PATH'",
                "shell": "powershell",
                "working_dir": "",
            },
        ],
    }
    prepared, assets = _prepare_embedded_plan_and_assets(original)
    require(assets == [], "Command contract unexpectedly created an asset")
    require("_command_launch" not in original["steps"][0], "export preparation mutated the source plan")
    for source_step, prepared_step in zip(original["steps"], prepared["steps"]):
        launch = prepared_step.get("_command_launch")
        require(isinstance(launch, dict), "exported Command did not receive shared LaunchSpec")
        expected = build_command_args(source_step["command"].strip(), source_step["shell"])
        require(launch["command_args"] == expected, "exported argv diverged from runtime backend")
        require(launch["creationflags"] & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "export hidden flag missing")
        require(launch["use_startupinfo"], "export startupinfo contract missing")


def _assert_public_api() -> None:
    import runtime.command_runner as command_runner

    expected = {
        "friendly_command_error": "(result: 'CommandResult') -> 'str | None'",
        "build_command_args": "(command: 'str', shell: 'str') -> 'list[str]'",
        "windows_hidden_process_options": "() -> 'dict[str, Any]'",
        "execute_command": "(command: 'str', shell: 'str' = 'cmd', working_dir: 'str' = '') -> 'CommandResult'",
    }
    for name, signature in expected.items():
        require(str(inspect.signature(getattr(command_runner, name))) == signature, f"public signature changed: {name}")
    require(
        tuple(CommandResult.__dataclass_fields__)
        == ("command_args", "returncode", "stdout", "stderr", "launch_error", "error_kind"),
        "CommandResult fields changed",
    )


def _assert_import_side_effects(temp_root: Path) -> None:
    alternate_cwd = temp_root / "alternate-cwd"
    alternate_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    probe = (
        "import os,subprocess; before=dict(os.environ); cwd=os.getcwd(); "
        "subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Popen called')); "
        "import shared.platform.process; "
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
    require(list(alternate_cwd.iterdir()) == [], "process import wrote into cwd")


def _assert_stdlib_boundary() -> None:
    path = PROJECT_ROOT / "shared" / "platform" / "process.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= (set(sys.stdlib_module_names) | {"shared"}), f"non-stdlib import found: {imports}")
    text = path.read_text(encoding="utf-8")
    require("PySide" not in text and "QStandardPaths" not in text, "Qt dependency found")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-command-backend-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    try:
        _assert_backend_selection()
        _assert_cmd_specs()
        _assert_powershell_specs()
        _assert_decode_and_errors()
        _assert_runtime_popen_contract()
        _assert_export_contract()
        _assert_public_api()
        _assert_import_side_effects(temp_root)
        _assert_stdlib_boundary()
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    require(not temp_root.exists(), "command backend smoke left temporary data")
    print("command backend smoke ok")
    print("backend=windows,legacy-posix,unknown-not-windows")
    print("cmd_argv=exact,special-chars,quotes,percent,multiline,unicode,empty")
    print("powershell_argv=exact,quotes,env,multiline,unicode,empty")
    print("hidden_window=CREATE_NO_WINDOW,STARTF_USESHOWWINDOW,SW_HIDE")
    print("decode=utf8,unicode,invalid-bytes-fallback,bytes-only")
    print("errors=9009,not-found,permission,generic,raw-preserved")
    print("popen=list,shell-false,devnull,two-pipes,child-env,communicate")
    print("runtime_api=compatible")
    print("export_contract=shared-launch-spec,source-plan-unchanged")
    print("side_effects=import:none,process:none,cwd:none,environment:none")
    print("dependencies=stdlib-only,no-qt")


if __name__ == "__main__":
    main()
