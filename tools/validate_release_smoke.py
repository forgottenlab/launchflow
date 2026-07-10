"""
Build and smoke-test the LaunchFlow editor release artifact.

This script validates the user-facing release loop without generating real
licenses or reading private keys. It builds dist/LaunchFlow.exe, checks that
forbidden secret/license artifacts are not present in dist, and performs a
short startup probe that is safely terminated by process handle.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_editor_release import build_editor_release, ensure_runtime_data


FORBIDDEN_PATTERNS = [
    "private/private_key.pem",
    "generated_licenses/*.lic",
    "*.lic",
]


def _check_forbidden_release_files(dist_dir: Path) -> None:
    if not dist_dir.exists():
        raise FileNotFoundError(dist_dir)

    forbidden_hits: list[Path] = []
    for pattern in FORBIDDEN_PATTERNS:
        forbidden_hits.extend(dist_dir.rglob(pattern))

    if forbidden_hits:
        raise AssertionError(
            "Forbidden files found in release dist: "
            + ", ".join(str(path) for path in forbidden_hits)
        )


def _stop_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def _short_startup_probe(exe_path: Path) -> str:
    proc = subprocess.Popen([str(exe_path)], cwd=exe_path.parent)
    try:
        time.sleep(4)
        if proc.poll() is not None:
            return f"process exited early with code {proc.returncode}"
        return "process stayed alive for startup probe; likely showing activation window"
    finally:
        _stop_process_tree(proc)


def main() -> None:
    ensure_runtime_data(PROJECT_ROOT)
    exe_path = build_editor_release(PROJECT_ROOT, "LaunchFlow")
    if not exe_path.exists():
        raise FileNotFoundError(exe_path)

    dist_dir = PROJECT_ROOT / "dist"
    _check_forbidden_release_files(dist_dir)

    probe_result = _short_startup_probe(exe_path)
    _check_forbidden_release_files(dist_dir)

    print("release smoke ok")
    print(f"exe_path={exe_path}")
    print(f"exe_size_bytes={exe_path.stat().st_size}")
    print(f"probe={probe_result}")


if __name__ == "__main__":
    main()
