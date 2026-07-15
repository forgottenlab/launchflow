"""Validate developer data isolation without touching the production signing key."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from PySide6.QtWidgets import QApplication

import licensing.activation_service as activation_service_module
import licensing.crypto as crypto_module
import licensing.license_manager as license_manager_module
from editor.ui.activation_window import ActivationWindow
from licensing.license_manager import LicenseManager
from licensing.request_token import build_request_payload
from licensing.license_schema import utc_now
from shared.app_logging import reset_app_logger_for_tests
from shared.app_paths import APP_DATA_ENV, APP_SUBDIRECTORIES, ensure_app_directories, get_app_data_dir
from shared.utils import write_json
from tools.license_admin_core import issue_license, load_history


DEV_SCRIPT = PROJECT_ROOT / "tools" / "run_editor_dev.ps1"
EXPECTED_MACHINE_ID = "A1B2C3D4E5F60718293A4B5C6D7E8F90"


def _create_test_keys(private_path: Path, public_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _issue_test_developer_license(
    *,
    private_path: Path,
    license_path: Path,
    history_path: Path,
    machine_id: str,
    days: int,
    now=None,
    force: bool = False,
) -> dict:
    result = issue_license(
        build_request_payload(machine_id),
        customer="LaunchFlow Developer Smoke",
        edition="developer",
        days=days,
        private_key_path=private_path,
        output_dir=license_path.parent,
        output_path=license_path,
        history_file=history_path,
        features=["export"],
        force=force,
        audit_action="issue-dev-smoke",
        now=now,
    )
    return result.license_data


def _assert_dev_license_validation(
    temp_root: Path,
    private_path: Path,
    public_path: Path,
) -> None:
    dev_root = temp_root / "Local AppData 中文 空格" / "LaunchFlow-Dev"
    os.environ[APP_DATA_ENV] = str(dev_root)
    paths = ensure_app_directories()
    if paths["root"] != dev_root or any(not paths[name].is_dir() for name in APP_SUBDIRECTORIES):
        raise AssertionError("LaunchFlow-Dev directory contract was not created")

    license_path = dev_root / "licenses" / "license.lic"
    history_path = temp_root / "audit" / "developer-history.jsonl"
    valid_data = _issue_test_developer_license(
        private_path=private_path,
        license_path=license_path,
        history_path=history_path,
        machine_id=EXPECTED_MACHINE_ID,
        days=1095,
    )
    manager = LicenseManager(PROJECT_ROOT)
    valid = manager.validate_current_license()
    if not valid.is_valid or valid.license_data is None or valid.license_data.get("edition") != "developer":
        raise AssertionError(f"valid developer license was rejected: {valid}")

    write_json(license_path, {**valid_data, "signature": "AA=="})
    invalid = manager.validate_current_license()
    if invalid.code != "invalid_signature":
        raise AssertionError(f"invalid developer signature bypassed validation: {invalid}")

    expired_data = _issue_test_developer_license(
        private_path=private_path,
        license_path=license_path,
        history_path=history_path,
        machine_id=EXPECTED_MACHINE_ID,
        days=1,
        now=utc_now() - timedelta(days=10),
        force=True,
    )
    expired = manager.validate_current_license()
    if expired.code != "license_expired" or expired_data.get("edition") != "developer":
        raise AssertionError(f"expired developer license was not rejected: {expired}")

    _issue_test_developer_license(
        private_path=private_path,
        license_path=license_path,
        history_path=history_path,
        machine_id="FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
        days=1095,
        force=True,
    )
    foreign = manager.validate_current_license()
    if foreign.code != "machine_not_match":
        raise AssertionError(f"foreign-machine developer license was not rejected: {foreign}")

    license_path.unlink()
    missing = manager.validate_current_license()
    if missing.code != "missing_license":
        raise AssertionError(f"missing developer license did not enter activation state: {missing}")

    app = QApplication.instance() or QApplication([])
    activation = ActivationWindow(PROJECT_ROOT)
    activation.close()
    app.processEvents()

    history = load_history(history_path)
    if len(history) != 3 or any(record.get("edition") != "developer" for record in history):
        raise AssertionError("developer license audit history is incomplete")
    if any("private" in json.dumps(record, ensure_ascii=False).lower() for record in history):
        raise AssertionError("developer audit history exposed private-key information")


def _make_fake_python(fake_path: Path) -> None:
    real_python = str(Path(sys.executable))
    code = (
        "import json,os,pathlib,sys;"
        "pathlib.Path(os.environ['FAKE_CAPTURE']).write_text("
        "json.dumps({'cwd':os.getcwd(),'args':sys.argv[1:],'data':os.environ.get('LAUNCHFLOW_DATA_DIR')},"
        "ensure_ascii=False),encoding='utf-8')"
    )
    fake_path.write_text(
        f'@echo off\n"{real_python}" -c "{code}" %*\nexit /b %ERRORLEVEL%\n',
        encoding="utf-8",
    )


def _assert_dev_script(temp_root: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        raise AssertionError("PowerShell is required for run_editor_dev.ps1 smoke")

    fake_python = temp_root / "fake tools 中文" / "python.cmd"
    fake_python.parent.mkdir(parents=True)
    _make_fake_python(fake_python)
    local_app_data = temp_root / "Script LocalAppData 中文 空格"
    other_cwd = temp_root / "other cwd 中文 空格"
    other_cwd.mkdir(parents=True)
    parent_data_before = os.environ.get(APP_DATA_ENV)

    for index, cwd in enumerate((PROJECT_ROOT, other_cwd), start=1):
        expected_dev_root_path = local_app_data / "LaunchFlow-Dev"
        expected_license_path = expected_dev_root_path / "licenses" / "license.lic"
        if index == 2:
            expected_license_path.parent.mkdir(parents=True, exist_ok=True)
            expected_license_path.write_text("{}", encoding="utf-8")
        capture_path = temp_root / f"script-capture-{index}.json"
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(local_app_data)
        env["FAKE_CAPTURE"] = str(capture_path)
        env.pop(APP_DATA_ENV, None)
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(DEV_SCRIPT),
                "-PythonCommand",
                str(fake_python),
            ],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not capture_path.is_file():
            raise AssertionError(
                f"run_editor_dev.ps1 failed from {cwd}: rc={completed.returncode}, "
                f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
            )
        combined_output = completed.stdout + completed.stderr
        if index == 1 and "license.lic" not in combined_output:
            raise AssertionError("missing developer license path was not shown")
        if index == 2 and "Developer license found" not in combined_output:
            raise AssertionError("existing developer license was not reported")
        captured = json.loads(capture_path.read_text(encoding="utf-8"))
        expected_dev_root = str(expected_dev_root_path)
        if Path(captured["cwd"]).resolve() != PROJECT_ROOT.resolve():
            raise AssertionError(f"developer script did not enter source root: {captured}")
        if captured["args"] != ["-m", "editor.main"]:
            raise AssertionError(f"developer script did not use module entrypoint: {captured}")
        if captured["data"] != expected_dev_root:
            raise AssertionError(f"developer script data root mismatch: {captured}")

    import_probe = subprocess.run(
        [sys.executable, "-c", "import editor.main, shared, licensing, runtime"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if import_probe.returncode != 0:
        raise AssertionError(f"module entrypoint imports failed: {import_probe.stderr}")

    failing_python = temp_root / "fake tools 中文" / "python-fail.cmd"
    failing_python.write_text("@echo off\nexit /b 7\n", encoding="utf-8")
    failure_env = os.environ.copy()
    failure_env["LOCALAPPDATA"] = str(local_app_data)
    failure = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DEV_SCRIPT),
            "-PythonCommand",
            str(failing_python),
        ],
        cwd=other_cwd,
        env=failure_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if failure.returncode == 0 or "7" not in (failure.stdout + failure.stderr):
        raise AssertionError("developer script did not report a readable nonzero editor exit")

    if os.environ.get(APP_DATA_ENV) != parent_data_before:
        raise AssertionError("developer script modified the parent/global environment")

    script_text = DEV_SCRIPT.read_text(encoding="utf-8")
    if "SetEnvironmentVariable" in script_text or '"User"' in script_text or '"Machine"' in script_text:
        raise AssertionError("developer script writes a persistent environment variable")


def _assert_no_license_bypass() -> None:
    forbidden = "--skip" + "-license"
    for path in [*PROJECT_ROOT.rglob("*.py"), *PROJECT_ROOT.rglob("*.ps1")]:
        if any(part in {".git", "build", "dist", ".tmp", ".gui-smoke-tmp"} for part in path.parts):
            continue
        if path == Path(__file__).resolve():
            continue
        if forbidden in path.read_text(encoding="utf-8", errors="replace"):
            raise AssertionError(f"license bypass option found in source: {path}")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-dev-mode-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    private_path = temp_root / "temporary-test-private.pem"
    public_path = temp_root / "temporary-test-public.pem"
    old_data_root = os.environ.get(APP_DATA_ENV)
    old_local_app_data = os.environ.get("LOCALAPPDATA")
    original_embedded_key = crypto_module.EMBEDDED_PUBLIC_KEY_PEM
    original_license_machine_id = license_manager_module.get_machine_id
    original_activation_machine_id = activation_service_module.get_machine_id
    try:
        _create_test_keys(private_path, public_path)
        crypto_module.EMBEDDED_PUBLIC_KEY_PEM = public_path.read_bytes()
        license_manager_module.get_machine_id = lambda: EXPECTED_MACHINE_ID
        activation_service_module.get_machine_id = lambda: EXPECTED_MACHINE_ID

        formal_local_app_data = temp_root / "Formal LocalAppData"
        os.environ.pop(APP_DATA_ENV, None)
        os.environ["LOCALAPPDATA"] = str(formal_local_app_data)
        if get_app_data_dir() != formal_local_app_data / "LaunchFlow":
            raise AssertionError("formal LaunchFlow data root changed unexpectedly")

        _assert_dev_license_validation(temp_root, private_path, public_path)
        _assert_dev_script(temp_root)
        _assert_no_license_bypass()
    finally:
        reset_app_logger_for_tests()
        crypto_module.EMBEDDED_PUBLIC_KEY_PEM = original_embedded_key
        license_manager_module.get_machine_id = original_license_machine_id
        activation_service_module.get_machine_id = original_activation_machine_id
        if old_data_root is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_data_root
        if old_local_app_data is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_local_app_data
        shutil.rmtree(temp_root, ignore_errors=True)

    if private_path.exists() or public_path.exists() or temp_root.exists():
        raise AssertionError("developer smoke temporary keys/data were not deleted")

    print("developer mode smoke ok")
    print("dev_data_root=LaunchFlow-Dev")
    print("formal_dev_data_isolation=ok")
    print("valid_developer_license=accepted")
    print("invalid_expired_foreign_developer_license=rejected")
    print("missing_license=activation_window")
    print("run_editor_dev_entrypoint=python -m editor.main")
    print("run_editor_dev_cwd=source,other")
    print("persistent_environment_write=none")
    print("nonzero_editor_exit=readable-error")
    print("skip_license_backdoor=absent")
    print("temporary_test_keys_and_data=deleted")


if __name__ == "__main__":
    main()
