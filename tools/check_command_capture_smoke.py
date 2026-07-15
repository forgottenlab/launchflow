"""Regression-test cmd pipes, output capture, quoting, and no-window behavior."""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.command_runner import (
    CommandResult,
    build_command_args,
    execute_command,
    friendly_command_error,
    windows_hidden_process_options,
)
from runtime.launcher_runtime import RuntimeExecutor
from licensing.hwid import _read_volume_serial
from shared.models import CommandStep
from tools.build_single_exe import EMBEDDED_TEMPLATE


def _cmd_pids() -> set[int]:
    if os.name != "nt":
        return set()
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq cmd.exe", "/FO", "CSV", "/NH"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **windows_hidden_process_options(),
    )
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2 and row[0].lower() == "cmd.exe":
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def _assert_windows_contract() -> None:
    if os.name != "nt":
        return
    cmd_args = build_command_args("vol C:", "cmd")
    if cmd_args != ["cmd.exe", "/d", "/s", "/c", "vol C:"]:
        raise AssertionError(f"unexpected cmd invocation: {cmd_args}")
    options = windows_hidden_process_options()
    if not options.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW:
        raise AssertionError("CREATE_NO_WINDOW is missing")
    startupinfo = options.get("startupinfo")
    if startupinfo is None or not startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW:
        raise AssertionError("STARTF_USESHOWWINDOW is missing")
    if startupinfo.wShowWindow != subprocess.SW_HIDE:
        raise AssertionError("SW_HIDE is missing")


def _assert_success(command: str, expected: str) -> None:
    result = execute_command(command, "cmd")
    combined = result.stdout + result.stderr
    if result.returncode != 0 or expected not in combined or result.launch_error:
        raise AssertionError(f"command failed: {command!r}, rc={result.returncode}, output={combined[:500]!r}")


def _check_embedded_runner_contract(temp_root: Path) -> None:
    old_data_root = os.environ.get("LAUNCHFLOW_DATA_DIR")
    try:
        os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp_root / "embedded AppData")
        script = EMBEDDED_TEMPLATE.replace(
            "__PLAN_DATA__",
            repr({"plan_name": "embedded smoke", "steps": []}),
        )
        namespace = {"__name__": "launchflow_embedded_smoke"}
        exec(compile(script, "<embedded_launcher_smoke>", "exec"), namespace)
        app_options = namespace["application_popen_options"]()
        if any(
            app_options.get(stream_name) is not subprocess.DEVNULL
            for stream_name in ("stdin", "stdout", "stderr")
        ):
            raise AssertionError("embedded Application process did not isolate standard streams")
        run_command_step = namespace["run_command_step"]
        run_command_step({"command": "vol C:", "shell": "cmd", "working_dir": ""})
        run_command_step(
            {
                "command": 'python -c "print(\'embedded-quoted-command\')"',
                "shell": "cmd",
                "working_dir": "",
            }
        )
        run_command_step(
            {
                "command": "launchflow-embedded-command-does-not-exist",
                "shell": "cmd",
                "working_dir": "",
            }
        )
        run_command_step({"command": "exit /b 9009", "shell": "cmd", "working_dir": ""})
        log_path = namespace["LOG_PATH"]
        log_text = log_path.read_text(encoding="utf-8")
        if "embedded-quoted-command" not in log_text or "[退出码] 0" not in log_text:
            raise AssertionError("embedded runner did not capture quoted command output")
        if "0x800700" in log_text or "[失败] 命令执行失败" not in log_text:
            raise AssertionError("embedded runner pipe/nonzero contract failed")
        if "未找到可执行命令，请检查程序是否安装或是否加入 PATH。" not in log_text:
            raise AssertionError("embedded runner did not explain return code 9009")
    finally:
        if old_data_root is None:
            os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
        else:
            os.environ["LAUNCHFLOW_DATA_DIR"] = old_data_root


def main() -> None:
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    _assert_windows_contract()
    before_cmd_pids = _cmd_pids()

    volume = execute_command("vol C:", "cmd")
    volume_output = volume.stdout + volume.stderr
    if volume.returncode != 0 or "Volume" not in volume_output or "0x800700" in volume_output:
        raise AssertionError(f"vol C: pipe regression: rc={volume.returncode}, output={volume_output!r}")
    if not _read_volume_serial():
        raise AssertionError("HWID volume probe did not reuse a successful hidden command path")

    _assert_success("echo LaunchFlow", "LaunchFlow")
    _assert_success("python --version", "Python ")
    _assert_success("where python", "python")
    _assert_success("echo LaunchFlow中文输出", "中文")
    _assert_success("exit /b 0", "")

    missing_command = "launchflow-command-that-does-not-exist-7f4c"
    logs: list[str] = []
    missing_result = RuntimeExecutor(log_callback=logs.append).run_command_step(
        CommandStep(name="Missing", command=missing_command, shell="cmd")
    )
    if missing_result.returncode == 0 or "[失败]" not in "\n".join(logs):
        raise AssertionError("nonzero command was not returned and logged normally")
    not_found_hint = friendly_command_error(CommandResult([], 9009, "", "raw stderr"))
    if not_found_hint != "未找到可执行命令，请检查程序是否安装或是否加入 PATH。":
        raise AssertionError("return code 9009 did not map to the expected user hint")
    permission_hint = friendly_command_error(
        CommandResult([], -1, "", "raw permission error", "raw permission error", "permission_denied")
    )
    if permission_hint != "没有权限执行该操作。":
        raise AssertionError("permission failure did not map to the expected user hint")

    large_command = (
        'python -c "import sys;print(\'O\'*200000);'
        'print(\'E\'*200000,file=sys.stderr)"'
    )
    large = execute_command(large_command, "cmd")
    if large.returncode != 0 or len(large.stdout) < 200000 or len(large.stderr) < 200000:
        raise AssertionError(
            f"large pipe capture incomplete: rc={large.returncode}, stdout={len(large.stdout)}, stderr={len(large.stderr)}"
        )

    started = time.monotonic()
    delayed = execute_command('python -c "import time;time.sleep(1);print(\'delayed\')"', "cmd")
    elapsed = time.monotonic() - started
    if delayed.returncode != 0 or "delayed" not in delayed.stdout or elapsed < 0.8:
        raise AssertionError(f"communicate returned before delayed process completed: elapsed={elapsed:.3f}")

    quote_root = PROJECT_ROOT / ".tmp" / f"command-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    quote_root.mkdir(parents=True)
    try:
        quoted_marker = quote_root / "中文 path marker.txt"
        quoted = execute_command(f'echo quoted-path> "{quoted_marker}"', "cmd")
        if quoted.returncode != 0 or not quoted_marker.exists():
            raise AssertionError(f"quoted path command failed: {quoted.stderr!r}")
        launch_error = execute_command("echo should-not-run", "cmd", str(quote_root / "missing-dir"))
        if launch_error.returncode != -1 or not launch_error.launch_error:
            raise AssertionError("FileNotFoundError was not converted to a readable result")
        if friendly_command_error(launch_error) != "找不到目标文件，请检查路径。":
            raise AssertionError("missing target did not map to the expected user hint")
        _check_embedded_runner_contract(quote_root)
    finally:
        shutil.rmtree(quote_root, ignore_errors=True)

    time.sleep(0.2)
    residual = _cmd_pids() - before_cmd_pids
    if residual:
        raise AssertionError(f"residual cmd.exe processes: {sorted(residual)}")

    print("command capture smoke ok")
    print("vol_c_pipe=ok")
    print("where_python=ok")
    print("hwid_volume_probe=shared-runner")
    print("stdout_bytes>=200000")
    print("stderr_bytes>=200000")
    print("quick_exit=ok")
    print(f"delayed_exit_seconds={elapsed:.3f}")
    print("nonzero_return=normal-result")
    print("friendly_error_hints=9009,not_found,permission_denied")
    print("launch_errors=readable-result")
    print("residual_cmd_processes=0")
    print("embedded_launcher_command_contract=ok")
    print(f"no_window_contract={'true' if os.name == 'nt' else 'not-applicable'}")
    print("formal_release_command=hidden-terminal,output-in-launchflow-log")


if __name__ == "__main__":
    main()
