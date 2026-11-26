"""Smoke tests for exported Professional command-step console visibility."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build_single_exe import (  # noqa: E402
    CREATE_NEW_CONSOLE,
    EMBEDDED_TEMPLATE,
    _prepare_embedded_plan_and_assets,
    _serialized_command_launch,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_serialized_launch() -> None:
    launch = _serialized_command_launch("echo hello", "cmd")
    require(launch["creationflags"] & CREATE_NEW_CONSOLE, "serialized command is missing CREATE_NEW_CONSOLE")
    require(launch["inherit_stdio"] is True, "serialized command does not inherit stdio")
    require(launch["use_startupinfo"] is False, "serialized command still uses hidden STARTUPINFO")
    require(launch["startupinfo_show_window"] == 0, "serialized command still sets a hide show-window flag")

    prepared, assets = _prepare_embedded_plan_and_assets(
        {
            "plan_name": "console",
            "steps": [
                {"type": "command", "command": "echo hello", "shell": "cmd", "working_dir": ""},
                {"type": "command", "command": "Write-Output hi", "shell": "powershell", "working_dir": ""},
            ],
        }
    )
    require(assets == [], "command export unexpectedly created an asset")
    for step in prepared["steps"]:
        item = step["_command_launch"]
        require(item["creationflags"] & CREATE_NEW_CONSOLE, "prepared command is missing CREATE_NEW_CONSOLE")
        require(item["inherit_stdio"] is True, "prepared command does not inherit stdio")
        require(not item["use_startupinfo"], "prepared command still hides the console")


def check_template_uses_visible_console() -> None:
    require("inherit_stdio" in EMBEDDED_TEMPLATE, "Professional template lost inherit_stdio")
    require("process.wait()" in EMBEDDED_TEMPLATE, "Professional template does not wait on an inherited console")
    require("if inherit_stdio:" in EMBEDDED_TEMPLATE, "template lost the inherit_stdio branch")
    require("run_wait_step" in EMBEDDED_TEMPLATE, "Professional template lost Wait runner support")


def check_create_new_console_shows_window() -> None:
    if os.name != "nt":
        print("create_new_console live check skipped: not Windows")
        return
    if not hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        raise AssertionError("subprocess.CREATE_NEW_CONSOLE is unavailable")

    with tempfile.TemporaryDirectory(prefix="lf-console-") as temp_dir:
        marker = Path(temp_dir) / "console_ok.txt"
        child = Path(temp_dir) / "probe_console.py"
        child.write_text(
            textwrap.dedent(
                """
                import ctypes
                import sys
                from pathlib import Path

                marker = Path(sys.argv[1])
                hwnd = 0
                try:
                    hwnd = int(ctypes.windll.kernel32.GetConsoleWindow() or 0)
                except Exception:
                    hwnd = 0
                ok = bool(hwnd) or sys.stdout.isatty()
                if ok:
                    payload = "ok"
                else:
                    payload = "no hwnd=%s tty=%s" % (hwnd, sys.stdout.isatty())
                marker.write_text(payload, encoding="utf-8")
                """
            ).lstrip(),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(child), str(marker)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            timeout=20,
            check=False,
        )
        require(completed.returncode == 0, "CREATE_NEW_CONSOLE child exited %s" % completed.returncode)
        require(marker.exists(), "CREATE_NEW_CONSOLE child did not write a marker")
        payload = marker.read_text(encoding="utf-8")
        require(payload == "ok", "child had no console window: %s" % payload)


def main() -> int:
    check_serialized_launch()
    check_template_uses_visible_console()
    check_create_new_console_shows_window()
    print("export command console smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
