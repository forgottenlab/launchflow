"""
Build and run a minimal LaunchFlow exported launcher.

The smoke test creates temporary .cmd and .ps1 app steps, builds a one-file
launcher through tools.build_single_exe, runs it, and verifies that both
scripts execute from PyInstaller's extracted launchflow_assets directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_single_exe import build_single_file_exe, writable_temporary_directory


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


def main() -> None:
    smoke_parent = PROJECT_ROOT / "dist" / ".export-smoke-runtime"
    with writable_temporary_directory("launchflow-export-smoke-", smoke_parent) as tmp_dir:
        cmd_script = tmp_dir / "smoke_cmd.cmd"
        ps1_script = tmp_dir / "smoke_ps1.ps1"
        cmd_marker = tmp_dir / "cmd_marker.txt"
        ps1_marker = tmp_dir / "ps1_marker.txt"
        cmd_command_marker = tmp_dir / "cmd_command_marker.txt"
        ps_command_marker = tmp_dir / "ps_command_marker.txt"
        output_exe = tmp_dir / "LaunchFlowSmoke.exe"
        app_data_dir = tmp_dir / "测试 AppData"

        cmd_script.write_text(
            '@echo off\r\necho %~f0> "%~1"\r\nexit /b 0\r\n',
            encoding="utf-8",
        )
        ps1_script.write_text(
            'Set-Content -LiteralPath $args[0] -Value $PSCommandPath -Encoding UTF8\n',
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
        for command_contract in ["CREATE_NO_WINDOW", '"cmd.exe", "/d", "/s", "/c"', '"-NonInteractive"']:
            if command_contract not in debug_text:
                raise AssertionError(f"Embedded command runner is missing: {command_contract}")

        if json.dumps(original_plan, sort_keys=True) != original_snapshot:
            raise AssertionError("build_single_file_exe mutated the original plan")

        runtime_env = os.environ.copy()
        runtime_env["LAUNCHFLOW_DATA_DIR"] = str(app_data_dir)
        proc = subprocess.Popen([str(output_exe)], cwd=tmp_dir, env=runtime_env)
        try:
            try:
                _wait_for_files([cmd_marker, ps1_marker, cmd_command_marker, ps_command_marker])
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
        if (tmp_dir / "logs").exists():
            raise AssertionError("Exported launcher polluted its own directory with logs")
        runtime_logs = sorted(
            (app_data_dir / "logs" / "launchers" / "LaunchFlowSmoke").glob("runtime_*.log")
        )
        if not runtime_logs:
            raise AssertionError("Exported launcher did not write its AppData runtime log")

        print("export smoke ok")
        print(f"exe_size_bytes={output_exe.stat().st_size}")
        print(f"cmd_origin={cmd_origin}")
        print(f"ps1_origin={ps1_origin}")
        print("command_steps=cmd,powershell")
        print("command_no_window_contract=ok")
        print(f"runtime_log={runtime_logs[-1]}")
        print("launcher_directory_pollution=none")


if __name__ == "__main__":
    main()
