"""
Build and smoke-test the LaunchFlow editor release artifact.

This script validates the user-facing release loop without generating real
licenses or reading private keys. It builds dist/LaunchFlow.exe, checks that
forbidden secret/license artifacts are not present in dist, and performs a
short startup probe that is safely terminated by process handle.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import os
import shutil
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_editor_release import build_editor_command, build_editor_release, ensure_runtime_data
from shared.app_paths import APP_SUBDIRECTORIES
from licensing.crypto import load_public_key, load_public_key_from_bytes


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


def _check_icon_build_contract() -> Path:
    icon_path = PROJECT_ROOT / "assets" / "launchflow.ico"
    if not icon_path.exists() or icon_path.stat().st_size < 1024:
        raise AssertionError(f"Windows icon is missing or too small: {icon_path}")
    if icon_path.read_bytes()[:4] != b"\x00\x00\x01\x00":
        raise AssertionError(f"Windows icon has an invalid ICO header: {icon_path}")

    command = build_editor_command(PROJECT_ROOT, "LaunchFlow")
    if "--icon" not in command or str(icon_path) not in command:
        raise AssertionError("PyInstaller command does not include --icon")
    if "--add-data" not in command or not any("launchflow.ico" in item and "assets" in item for item in command):
        raise AssertionError("PyInstaller command does not bundle the runtime icon")
    public_key_path = PROJECT_ROOT / "data" / "public_key.pem"
    public_key_bundled = any("public_key.pem" in item and "data" in item for item in command)
    if public_key_path.is_file() != public_key_bundled:
        raise AssertionError("public-key bundling does not match the available read-only resource")
    return icon_path


def _check_public_key_contract() -> str:
    """Validate the existing trust key without generating or exposing key data."""
    embedded_key = load_public_key()
    if getattr(embedded_key, "key_size", 0) < 2048:
        raise AssertionError("embedded client public key is missing or unexpectedly small")

    public_key_path = PROJECT_ROOT / "data" / "public_key.pem"
    if not public_key_path.is_file():
        return "embedded"

    resource_key = load_public_key_from_bytes(public_key_path.read_bytes())
    if resource_key.public_numbers() != embedded_key.public_numbers():
        raise AssertionError("data/public_key.pem does not match the existing embedded client trust key")
    return "embedded+data_resource"


def _stop_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
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
                f"startup probe process {proc.pid} did not stop; "
                f"taskkill_returncode={result.returncode}; taskkill_output={detail}"
            ) from exc
        return

    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def _short_startup_probe(exe_path: Path, app_data_dir: Path) -> str:
    licenses_dir = app_data_dir / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)
    (licenses_dir / "license.lic").write_text(
        json.dumps(
            {
                "license_id": "example-license",
                "tester_name": "Smoke Test",
                "machine_id": "EXAMPLE-MACHINE-ID",
                "edition": "beta",
                "expire_at": "2099-01-01 00:00:00",
                "created_at": "2026-01-01 00:00:00",
                "signature": "AA==",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["LAUNCHFLOW_DATA_DIR"] = str(app_data_dir)
    proc = subprocess.Popen([str(exe_path)], cwd=exe_path.parent, env=env)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"process exited early with code {proc.returncode}")
            if all((app_data_dir / name).is_dir() for name in APP_SUBDIRECTORIES):
                log_path = app_data_dir / "logs" / "launchflow.log"
                if log_path.is_file() and "License check result: invalid_signature" in log_path.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    return (
                        "all isolated data directories created; frozen embedded public key parsed; "
                        "invalid test signature rejected; activation window remained alive"
                    )
            time.sleep(0.25)
        missing = [name for name in APP_SUBDIRECTORIES if not (app_data_dir / name).is_dir()]
        raise AssertionError(f"startup did not initialize isolated data directories: {missing}")
    finally:
        _stop_process_tree(proc)


def main() -> None:
    icon_path = _check_icon_build_contract()
    public_key_source = _check_public_key_contract()
    ensure_runtime_data(PROJECT_ROOT)
    exe_path = build_editor_release(PROJECT_ROOT, "LaunchFlow")
    if not exe_path.exists():
        raise FileNotFoundError(exe_path)

    dist_dir = PROJECT_ROOT / "dist"
    _check_forbidden_release_files(dist_dir)

    probe_root = Path(tempfile.gettempdir()) / f"launchflow-release-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    probe_root.mkdir(parents=True)
    try:
        probe_result = _short_startup_probe(exe_path, probe_root / "测试 AppData")
        _check_forbidden_release_files(dist_dir)
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)

    print("release smoke ok")
    print(f"exe_path={exe_path}")
    print(f"exe_size_bytes={exe_path.stat().st_size}")
    print(f"icon_path={icon_path}")
    print("icon_build_contract=ok")
    print(f"public_key_validation={public_key_source}:parse_ok")
    print(
        "public_key_bundle="
        + ("included" if (PROJECT_ROOT / "data" / "public_key.pem").is_file() else "source_resource_missing")
    )
    print(f"probe={probe_result}")


if __name__ == "__main__":
    main()
