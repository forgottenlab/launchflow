"""Validate that the packaged editor writes only to isolated user data."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.app_paths import APP_DATA_ENV, APP_SUBDIRECTORIES
from tools.build_editor_release import build_editor_release, ensure_runtime_data
from tools.validate_release_smoke import _check_forbidden_release_files, _stop_process_tree


def _git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")
    return result.stdout


def main() -> None:
    before_status = _git_status()
    ensure_runtime_data(PROJECT_ROOT)
    source_exe = PROJECT_ROOT / "dist" / "LaunchFlow.exe"
    if not source_exe.is_file():
        source_exe = build_editor_release(PROJECT_ROOT, "LaunchFlow")
    _check_forbidden_release_files(source_exe.parent)

    temp_root = Path(tempfile.gettempdir()) / f"launchflow-release-isolation-{os.getpid()}-{uuid.uuid4().hex}"
    desktop_dir = temp_root / "桌面 模拟"
    app_root = temp_root / "测试 AppData 空格"
    desktop_dir.mkdir(parents=True)
    desktop_exe = desktop_dir / "LaunchFlow.exe"
    shutil.copy2(source_exe, desktop_exe)
    proc: subprocess.Popen | None = None
    try:
        env = os.environ.copy()
        env[APP_DATA_ENV] = str(app_root)
        proc = subprocess.Popen([str(desktop_exe)], cwd=desktop_dir, env=env)
        startup = ""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"packaged editor exited early with code {proc.returncode}")
            if all((app_root / name).is_dir() for name in APP_SUBDIRECTORIES):
                startup = "all data directories created while process stayed alive"
                break
            time.sleep(0.25)
        else:
            missing = [name for name in APP_SUBDIRECTORIES if not (app_root / name).is_dir()]
            raise AssertionError(f"timed out waiting for app data directories: {missing}")
        _stop_process_tree(proc)
        proc = None

        desktop_entries = sorted(path.name for path in desktop_dir.iterdir())
        if desktop_entries != ["LaunchFlow.exe"]:
            raise AssertionError(f"desktop directory polluted: {desktop_entries}")
        missing = [name for name in APP_SUBDIRECTORIES if not (app_root / name).is_dir()]
        if missing:
            raise AssertionError(f"isolated data directories missing: {missing}")
        after_status = _git_status()
        if after_status != before_status:
            raise AssertionError("source git status changed during packaged isolation smoke")
    finally:
        if proc is not None:
            _stop_process_tree(proc)
        shutil.rmtree(temp_root, ignore_errors=True)

    print("release data isolation ok")
    print(f"source_exe={source_exe}")
    print(f"desktop_entries={desktop_entries}")
    print(f"app_data_directories={','.join(APP_SUBDIRECTORIES)}")
    print(f"startup={startup}")
    print("source_git_status=unchanged")


if __name__ == "__main__":
    main()
