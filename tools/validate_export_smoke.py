"""
Build and run a minimal LaunchFlow exported launcher.

The smoke test creates temporary .cmd and .ps1 app steps, builds a one-file
launcher through tools.build_single_exe, runs it, and verifies that both
scripts execute from PyInstaller's extracted launchflow_assets directory.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_single_exe import (
    APPLICATION_ASSET_DIR,
    APPLICATION_ASSET_PREFIX,
    APPLICATION_LAUNCH_SCHEMA,
    URL_OPEN_SCHEMA,
    build_single_file_exe,
    writable_temporary_directory,
)


def _wait_for_files(paths: list[Path], timeout_seconds: float = 35.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if all(path.exists() for path in paths):
            return
        time.sleep(0.25)
    missing = [str(path) for path in paths if not path.exists()]
    raise TimeoutError("Timed out waiting for marker files: " + ", ".join(missing))


def _stop_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
        )
        if result.returncode != 0 and proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired as exc:
            detail = (result.stdout + result.stderr).strip()
            raise RuntimeError(
                f"export smoke process {proc.pid} did not stop; "
                f"taskkill_returncode={result.returncode}; taskkill_output={detail}"
            ) from exc
        return

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _process_pids(image_name: str) -> set[int]:
    if os.name != "nt":
        return set()
    completed = subprocess.run(
        ["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) >= 2 and row[0].lower() == image_name.lower():
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def main() -> None:
    smoke_parent = PROJECT_ROOT / "dist" / ".export-smoke-runtime"
    with writable_temporary_directory("launchflow-export-smoke-", smoke_parent) as tmp_dir:
        cmd_script = tmp_dir / "smoke_cmd.cmd"
        ps1_script = tmp_dir / "smoke_ps1.ps1"
        cmd_marker = tmp_dir / "cmd_marker.txt"
        ps1_marker = tmp_dir / "ps1_marker.txt"
        cmd_command_marker = tmp_dir / "cmd_command_marker.txt"
        ps_command_marker = tmp_dir / "ps_command_marker.txt"
        url_marker = tmp_dir / "url_marker.txt"
        browser_script = tmp_dir / "smoke_browser.cmd"
        output_exe = tmp_dir / "LaunchFlowSmoke.exe"
        app_data_dir = tmp_dir / "测试 AppData"

        cmd_script.write_text(
            '@echo off\r\necho APP_STDOUT_POLLUTION\r\necho APP_STDERR_POLLUTION 1>&2\r\necho %~f0> "%~1"\r\nexit /b 0\r\n',
            encoding="utf-8",
        )
        ps1_script.write_text(
            'Write-Output "APP_STDOUT_POLLUTION"\n'
            '[Console]::Error.WriteLine("APP_STDERR_POLLUTION")\n'
            'Set-Content -LiteralPath $args[0] -Value $PSCommandPath -Encoding UTF8\n',
            encoding="utf-8",
        )
        explicit_url = "launchflow-smoke://explicit-browser/value"
        browser_script.write_text(
            '@echo off\r\n'
            f'> "{url_marker}" <nul set /p "=%~1"\r\n'
            'exit /b 0\r\n',
            encoding="utf-8",
        )

        original_plan = {
            "plan_name": "LaunchFlow Export Smoke",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "step-cmd",
                    "type": "app",
                    "name": "Smoke CMD",
                    "enabled": True,
                    "delay_after": 0.1,
                    "path": str(cmd_script),
                    "args": [str(cmd_marker)],
                    "working_dir": "",
                    "start_minimized": False,
                },
                {
                    "id": "step-command-cmd",
                    "type": "command",
                    "name": "Smoke command CMD",
                    "enabled": True,
                    "delay_after": 0.0,
                    "command": f'echo command-cmd> "{cmd_command_marker}"',
                    "shell": "cmd",
                    "working_dir": "",
                    "new_window": True,
                },
                {
                    "id": "step-command-powershell",
                    "type": "command",
                    "name": "Smoke command PowerShell",
                    "enabled": True,
                    "delay_after": 0.0,
                    "command": f"Set-Content -LiteralPath '{ps_command_marker}' -Value 'command-powershell' -Encoding UTF8",
                    "shell": "powershell",
                    "working_dir": "",
                    "new_window": True,
                },
                {
                    "id": "step-url-default",
                    "type": "url",
                    "name": "Smoke default browser contract",
                    "enabled": False,
                    "delay_after": 0.0,
                    "url": "launchflow-smoke://default-browser/value",
                    "browser_path": "",
                },
                {
                    "id": "step-url-explicit",
                    "type": "url",
                    "name": "Smoke explicit browser substitute",
                    "enabled": True,
                    "delay_after": 0.0,
                    "url": explicit_url,
                    "browser_path": str(browser_script),
                },
                {
                    "id": "step-wait",
                    "type": "wait",
                    "name": "Short Wait",
                    "enabled": True,
                    "delay_after": 0.0,
                    "seconds": 0.2,
                },
                {
                    "id": "step-ps1",
                    "type": "app",
                    "name": "Smoke PS1",
                    "enabled": True,
                    "delay_after": 0.1,
                    "path": str(ps1_script),
                    "args": [str(ps1_marker)],
                    "working_dir": "",
                    "start_minimized": False,
                },
            ],
        }
        original_snapshot = json.dumps(original_plan, sort_keys=True)

        build_single_file_exe(original_plan, output_exe)
        if not output_exe.exists():
            raise FileNotFoundError(output_exe)

        debug_script = tmp_dir / "LaunchFlowSmoke_embedded_debug.py"
        debug_text = debug_script.read_text(encoding="utf-8")
        if "launchflow_assets" not in debug_text or "_embedded_asset" not in debug_text:
            raise AssertionError("Embedded debug script does not reference bundled assets")
        debug_tree = ast.parse(debug_text, filename=str(debug_script))
        embedded_plan = None
        for node in debug_tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "EMBEDDED_PLAN" for target in node.targets)
            ):
                embedded_plan = ast.literal_eval(node.value)
                break
        if not isinstance(embedded_plan, dict):
            raise AssertionError("Embedded debug script does not contain a literal plan")
        application_steps = [step for step in embedded_plan.get("steps", []) if step.get("type") == "app"]
        if len(application_steps) != 2:
            raise AssertionError("Embedded plan does not contain both Application steps")
        cmd_application = application_steps[0].get("_application_launch", {})
        ps1_application = application_steps[1].get("_application_launch", {})
        for launch in (cmd_application, ps1_application):
            if launch.get("schema") != APPLICATION_LAUNCH_SCHEMA:
                raise AssertionError("Embedded Application launch schema is missing")
            if launch.get("launch_mode") != "process":
                raise AssertionError("Bundled Application no longer uses process mode")
            if not launch.get("resolved_target", "").startswith(APPLICATION_ASSET_PREFIX):
                raise AssertionError("Bundled Application target token is missing")
            if launch.get("cwd") != APPLICATION_ASSET_DIR:
                raise AssertionError("Bundled Application cwd no longer follows the asset directory")
            if not all(
                launch.get(name, False)
                for name in ("use_stdin_devnull", "use_stdout_devnull", "use_stderr_devnull")
            ):
                raise AssertionError("Embedded Application DEVNULL contract is incomplete")
            if not launch.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW:
                raise AssertionError("Embedded Application is missing CREATE_NO_WINDOW")
        if cmd_application.get("target_kind") != "command_script":
            raise AssertionError("Bundled cmd Application classification changed")
        if ps1_application.get("target_kind") != "powershell_script":
            raise AssertionError("Bundled ps1 Application classification changed")
        if ps1_application.get("command_args", [])[:4] != [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ]:
            raise AssertionError("Embedded ps1 Application argv changed")
        if "def run_url_step" not in debug_text or "os.startfile(url)" not in debug_text or "_url_open" not in debug_text:
            raise AssertionError("Embedded URL contract is missing")
        if "def run_wait_step" not in debug_text or "time.sleep(seconds)" not in debug_text:
            raise AssertionError("Embedded Wait behavior changed")
        command_steps = [step for step in embedded_plan.get("steps", []) if step.get("type") == "command"]
        if len(command_steps) != 2:
            raise AssertionError("Embedded plan does not contain both Command steps")
        cmd_launch = command_steps[0].get("_command_launch", {})
        powershell_launch = command_steps[1].get("_command_launch", {})
        if cmd_launch.get("command_args", [])[:4] != ["cmd.exe", "/d", "/s", "/c"]:
            raise AssertionError("Embedded cmd argv does not match CommandBackend")
        if powershell_launch.get("command_args", [])[:7] != [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
        ]:
            raise AssertionError("Embedded PowerShell argv does not match CommandBackend")
        for launch in (cmd_launch, powershell_launch):
            if not launch.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW:
                raise AssertionError("Embedded Command is missing CREATE_NO_WINDOW")
            if not launch.get("startupinfo_dw_flags", 0) & subprocess.STARTF_USESHOWWINDOW:
                raise AssertionError("Embedded Command is missing STARTF_USESHOWWINDOW")
            if launch.get("startupinfo_show_window") != subprocess.SW_HIDE:
                raise AssertionError("Embedded Command is missing SW_HIDE")

        url_steps = [step for step in embedded_plan.get("steps", []) if step.get("type") == "url"]
        if len(url_steps) != 2:
            raise AssertionError("Embedded plan does not contain both URL steps")
        default_url_step, explicit_url_step = url_steps
        default_url_launch = default_url_step.get("_url_open", {})
        explicit_url_launch = explicit_url_step.get("_url_open", {})
        if default_url_launch.get("schema") != URL_OPEN_SCHEMA:
            raise AssertionError("Embedded default URL launch schema is missing")
        if default_url_launch.get("open_mode") != "shell_open":
            raise AssertionError("Embedded default URL no longer uses shell-open mode")
        if default_url_launch.get("url") != default_url_step.get("url"):
            raise AssertionError("Embedded default URL value changed")
        if default_url_launch.get("command_args") or default_url_launch.get("executable") is not None:
            raise AssertionError("Embedded default URL gained process fields")
        if explicit_url_launch.get("schema") != URL_OPEN_SCHEMA:
            raise AssertionError("Embedded explicit URL launch schema is missing")
        if explicit_url_launch.get("open_mode") != "process":
            raise AssertionError("Embedded explicit URL no longer uses process mode")
        if explicit_url_launch.get("command_args") != [str(browser_script), explicit_url]:
            raise AssertionError("Embedded explicit-browser argv changed")
        if explicit_url_launch.get("cwd") is not None:
            raise AssertionError("Embedded explicit browser gained a cwd")
        if explicit_url_launch.get("creationflags", 0) or explicit_url_launch.get("use_startupinfo", False):
            raise AssertionError("Embedded explicit browser gained hidden-window process flags")
        if any(
            explicit_url_launch.get(name, False)
            for name in ("use_stdin_devnull", "use_stdout_devnull", "use_stderr_devnull")
        ):
            raise AssertionError("Embedded explicit browser gained DEVNULL streams")
        if "_embedded_asset" in explicit_url_step:
            raise AssertionError("Explicit browser path was bundled as an Application asset")

        old_data_root = os.environ.get("LAUNCHFLOW_DATA_DIR")
        try:
            os.environ["LAUNCHFLOW_DATA_DIR"] = str(app_data_dir / "mocked-default")
            namespace = {
                "__name__": "launchflow_export_url_contract_smoke",
                "__file__": str(debug_script),
            }
            exec(compile(debug_text, str(debug_script), "exec"), namespace)
            mocked_default_calls: list[str] = []

            class MockPath:
                @staticmethod
                def exists(_path: str) -> bool:
                    return True

            class MockOs:
                path = MockPath()

                @staticmethod
                def startfile(url: str) -> None:
                    mocked_default_calls.append(url)

            namespace["os"] = MockOs
            namespace["run_url_step"](default_url_step)
            if mocked_default_calls != [default_url_launch["url"]]:
                raise AssertionError("Embedded default-browser contract did not call shell-open exactly once")
        finally:
            if old_data_root is None:
                os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
            else:
                os.environ["LAUNCHFLOW_DATA_DIR"] = old_data_root

        if json.dumps(original_plan, sort_keys=True) != original_snapshot:
            raise AssertionError("build_single_file_exe mutated the original plan")

        runtime_env = os.environ.copy()
        runtime_env["LAUNCHFLOW_DATA_DIR"] = str(app_data_dir)
        monitored_images = ("LaunchFlowSmoke.exe", "cmd.exe", "powershell.exe")
        before_pids = {name: _process_pids(name) for name in monitored_images}
        proc = subprocess.Popen(
            [str(output_exe)],
            cwd=tmp_dir,
            env=runtime_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            try:
                _wait_for_files([cmd_marker, ps1_marker, cmd_command_marker, ps_command_marker, url_marker])
            except Exception as exc:
                runtime_logs = sorted(
                    (app_data_dir / "logs" / "launchers" / "LaunchFlowSmoke").glob("runtime_*.log")
                )
                log_text = "\n".join(
                    path.read_text(encoding="utf-8", errors="replace")
                    for path in runtime_logs
                )
                task_detail = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {proc.pid}", "/V", "/FO", "LIST"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    check=False,
                ).stdout.strip()
                raise RuntimeError(
                    f"exported launcher markers missing; process_returncode={proc.poll()}; "
                    f"runtime_log={log_text or '<missing>'}; process_detail={task_detail}"
                ) from exc
        finally:
            _stop_process_tree(proc)
        parent_stdout, parent_stderr = proc.communicate(timeout=5)
        combined_parent_output = parent_stdout + parent_stderr
        if b"APP_STDOUT_POLLUTION" in combined_parent_output or b"APP_STDERR_POLLUTION" in combined_parent_output:
            raise AssertionError("Application output polluted the exported launcher parent streams")
        time.sleep(0.5)
        after_pids = {name: _process_pids(name) for name in monitored_images}
        residual = {
            name: sorted(after_pids[name] - before_pids[name])
            for name in monitored_images
            if after_pids[name] - before_pids[name]
        }
        if residual:
            raise AssertionError(f"export smoke left residual processes: {residual}")

        cmd_origin = cmd_marker.read_text(encoding="utf-8", errors="replace").strip()
        ps1_origin = ps1_marker.read_text(encoding="utf-8", errors="replace").strip()
        for origin in [cmd_origin, ps1_origin]:
            normalized = origin.replace("\\", "/")
            if "/launchflow_assets/" not in normalized:
                raise AssertionError(f"Marker did not come from bundled asset path: {origin}")
            if "_MEI" not in normalized:
                raise AssertionError(f"Marker did not come from PyInstaller extraction dir: {origin}")

        if "command-cmd" not in cmd_command_marker.read_text(encoding="utf-8", errors="replace"):
            raise AssertionError("Exported cmd Command step did not complete")
        if "command-powershell" not in ps_command_marker.read_text(encoding="utf-8-sig", errors="replace"):
            raise AssertionError("Exported PowerShell Command step did not complete")
        if url_marker.read_text(encoding="utf-8", errors="replace").strip() != explicit_url:
            raise AssertionError("Exported explicit-browser URL step did not preserve its URL argument")
        if (tmp_dir / "logs").exists():
            raise AssertionError("Exported launcher polluted its own directory with logs")
        runtime_logs = sorted(
            (app_data_dir / "logs" / "launchers" / "LaunchFlowSmoke").glob("runtime_*.log")
        )
        if not runtime_logs:
            raise AssertionError("Exported launcher did not write its AppData runtime log")
        runtime_log_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in runtime_logs
        )
        if f"[成功] 已打开网址: {explicit_url}" not in runtime_log_text:
            raise AssertionError("Exported launcher lacks URL branch execution evidence")

        print("export smoke ok")
        print(f"exe_size_bytes={output_exe.stat().st_size}")
        print(f"cmd_origin={cmd_origin}")
        print(f"ps1_origin={ps1_origin}")
        print("command_steps=cmd,powershell")
        print("command_no_window_contract=ok")
        print("application_contract=shared-launch-spec,cmd,ps1,devnull,hidden")
        print("application_parent_output_pollution=none")
        print("url_contract=shared-open-spec,default-mocked,explicit-local-marker,no-browser-asset")
        print("browser_safety=no-network,no-real-browser")
        print("url_wait_contract=delay-owned-by-embedded-loop")
        print("residual_processes=0")
        print(f"runtime_log={runtime_logs[-1]}")
        print("launcher_directory_pollution=none")


if __name__ == "__main__":
    main()
