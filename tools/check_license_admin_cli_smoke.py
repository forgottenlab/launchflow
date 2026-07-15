"""End-to-end smoke test for the author-only License Admin CLI."""

from __future__ import annotations

import base64
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

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import licensing.crypto as crypto_module
import licensing.license_manager as license_manager_module
from licensing.license_manager import LicenseManager
from licensing.license_schema import parse_iso_datetime, utc_now
from licensing.request_token import generate_request_token, mask_machine_id, parse_request_token
from shared.app_paths import APP_DATA_ENV
from shared.app_info import APP_VERSION
from shared.utils import read_json, write_json
from tools.license_admin_core import build_license_payload
from tools.license_generator import sign_payload


ADMIN_CLI = PROJECT_ROOT / "tools" / "license_admin.py"


def _run(*args: str, stdin: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ADMIN_CLI), *args],
        cwd=PROJECT_ROOT,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


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


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-license-admin-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    private_path = temp_root / "test-only-private.pem"
    public_path = temp_root / "test-only-public.pem"
    output_dir = temp_root / "generated test licenses"
    history_file = temp_root / "audit" / "history.jsonl"
    machine_id = "A1B2C3D4E5F60718293A4B5C6D7E8F90"
    token = generate_request_token(machine_id)
    old_data_root = os.environ.get(APP_DATA_ENV)
    original_embedded_public_key = crypto_module.EMBEDDED_PUBLIC_KEY_PEM
    original_machine_id = license_manager_module.get_machine_id

    try:
        _create_test_keys(private_path, public_path)

        inspected = _run("inspect", "--request", token)
        if inspected.returncode != 0 or APP_VERSION not in inspected.stdout:
            raise AssertionError(f"inspect failed: {inspected.stdout}\n{inspected.stderr}")
        if machine_id in inspected.stdout or mask_machine_id(machine_id) not in inspected.stdout:
            raise AssertionError("inspect did not mask machine_id")

        issued = _run(
            "issue",
            "--request-stdin",
            "--customer",
            "临时测试用户",
            "--edition",
            "beta",
            "--days",
            "90",
            "--feature",
            "export",
            "--private-key",
            str(private_path),
            "--output-dir",
            str(output_dir),
            "--history-file",
            str(history_file),
            stdin=token,
        )
        if issued.returncode != 0:
            raise AssertionError(f"stdin issue failed: {issued.stdout}\n{issued.stderr}")
        licenses = sorted(output_dir.glob("*.lic"))
        if len(licenses) != 1 or any(character in licenses[0].name for character in '<>:"/\\|?*'):
            raise AssertionError(f"unsafe or missing license output: {licenses}")
        license_data = read_json(licenses[0])
        if license_data["schema"] != "lflic-1" or license_data["request_app_version"] != APP_VERSION:
            raise AssertionError("issued license schema/version fields are incorrect")
        if license_data["edition"] != "beta" or license_data["features"] != ["export"]:
            raise AssertionError("server-selected edition/features were not preserved")

        dev_output = temp_root / "Developer LocalAppData" / "LaunchFlow-Dev" / "licenses" / "license.lic"
        dev_token = generate_request_token(machine_id)
        issued_dev = _run(
            "issue-dev",
            "--request",
            dev_token,
            "--customer",
            "LaunchFlow Developer",
            "--feature",
            "export",
            "--private-key",
            str(private_path),
            "--output",
            str(dev_output),
            "--history-file",
            str(history_file),
        )
        if issued_dev.returncode != 0 or not dev_output.is_file():
            raise AssertionError(f"issue-dev failed: {issued_dev.stdout}\n{issued_dev.stderr}")
        dev_license = read_json(dev_output)
        if dev_license["edition"] != "developer" or dev_license["features"] != ["export"]:
            raise AssertionError("issue-dev did not enforce developer edition/features")
        dev_duration = parse_iso_datetime(dev_license["expires_at"]) - parse_iso_datetime(dev_license["issued_at"])
        if dev_duration.days != 1095:
            raise AssertionError(f"issue-dev default duration changed: {dev_duration.days} days")

        replacement_token = generate_request_token(machine_id)
        refused_overwrite = _run(
            "issue-dev",
            "--request",
            replacement_token,
            "--private-key",
            str(private_path),
            "--output",
            str(dev_output),
            "--history-file",
            str(history_file),
        )
        if refused_overwrite.returncode == 0 or "--force" not in refused_overwrite.stderr:
            raise AssertionError("issue-dev overwrote an existing license without --force")

        forced_dev_env = os.environ.copy()
        forced_dev_env["LAUNCHFLOW_SIGNING_KEY"] = str(private_path)
        forced_dev = _run(
            "issue-dev",
            "--request",
            replacement_token,
            "--output",
            str(dev_output),
            "--history-file",
            str(history_file),
            "--force",
            env=forced_dev_env,
        )
        if forced_dev.returncode != 0 or read_json(dev_output)["edition"] != "developer":
            raise AssertionError(f"forced issue-dev failed: {forced_dev.stdout}\n{forced_dev.stderr}")

        os.environ[APP_DATA_ENV] = str(temp_root / "client AppData")
        crypto_module.EMBEDDED_PUBLIC_KEY_PEM = public_path.read_bytes()
        license_manager_module.get_machine_id = lambda: machine_id
        manager = LicenseManager(PROJECT_ROOT)
        current_result = manager.validate_license_data(license_data)
        if not current_result.is_valid:
            raise AssertionError(f"client rejected lflic-1 test license: {current_result}")

        legacy_payload = {
            "license_id": "LEGACY-TEST",
            "tester_name": "Legacy Test",
            "machine_id": machine_id,
            "edition": "beta",
            "expire_at": "2099-12-31 23:59:59",
            "created_at": "2026-07-10 00:00:00",
        }
        legacy_result = manager.validate_license_data(
            {**legacy_payload, "signature": sign_payload(private_path, legacy_payload)}
        )
        if not legacy_result.is_valid:
            raise AssertionError(f"legacy license compatibility failed: {legacy_result}")

        incompatible_payload = {key: value for key, value in license_data.items() if key != "signature"}
        incompatible_payload["min_app_version"] = "9.0.0"
        incompatible = manager.validate_license_data(
            {**incompatible_payload, "signature": sign_payload(private_path, incompatible_payload)}
        )
        if incompatible.code != "app_version_not_allowed":
            raise AssertionError(f"client version range was not enforced: {incompatible}")
        unsupported = manager.validate_license_data({"schema": "lflic-2"})
        if unsupported.code != "unsupported_license_schema":
            raise AssertionError(f"unknown license schema was not rejected: {unsupported}")

        duplicate = _run(
            "issue",
            "--request",
            token,
            "--customer",
            "临时测试用户",
            "--edition",
            "beta",
            "--days",
            "90",
            "--private-key",
            str(private_path),
            "--output-dir",
            str(output_dir),
            "--history-file",
            str(history_file),
        )
        if duplicate.returncode == 0 or "已签发" not in duplicate.stderr:
            raise AssertionError("duplicate request_id was not rejected")

        forced_env = os.environ.copy()
        forced_env["LAUNCHFLOW_SIGNING_KEY"] = str(private_path)
        forced = _run(
            "issue",
            "--request",
            token,
            "--customer",
            "临时测试用户",
            "--edition",
            "beta",
            "--days",
            "90",
            "--output-dir",
            str(output_dir),
            "--history-file",
            str(history_file),
            "--force",
            env=forced_env,
        )
        if forced.returncode != 0 or "forced_duplicate=true" not in forced.stdout:
            raise AssertionError(f"forced duplicate failed: {forced.stdout}\n{forced.stderr}")

        verified = _run(
            "verify",
            "--license",
            str(licenses[0]),
            "--public-key",
            str(public_path),
            "--app-version",
            APP_VERSION,
        )
        if verified.returncode != 0 or "valid=true" not in verified.stdout:
            raise AssertionError(f"verify failed: {verified.stdout}\n{verified.stderr}")

        history = _run("history", "--history-file", str(history_file))
        if history.returncode != 0 or "history_count=4" not in history.stdout:
            raise AssertionError(f"history failed: {history.stdout}\n{history.stderr}")
        if machine_id in history.stdout or mask_machine_id(machine_id) not in history.stdout:
            raise AssertionError("history exposed full machine_id or omitted masked value")
        if private_path.name in history.stdout:
            raise AssertionError("history recorded private-key information")
        if history.stdout.count('"action": "issue-dev"') != 2:
            raise AssertionError("developer license issuance was not audited")

        damaged = token[:-1] + ("0" if token[-1] != "0" else "1")
        invalid = _run("inspect", "--request", damaged)
        if invalid.returncode == 0 or "校验和" not in invalid.stderr:
            raise AssertionError("damaged request was not isolated")

        legacy_raw = json.dumps({"machine_id": machine_id, "generated_at": "2026-07-10 00:00:00"}).encode()
        legacy_token = base64.urlsafe_b64encode(legacy_raw).decode("ascii")
        legacy = _run("inspect", "--request", legacy_token)
        if legacy.returncode != 0 or "legacy=true" not in legacy.stdout:
            raise AssertionError("legacy inspect compatibility failed")

        now = utc_now()
        expired_payload = build_license_payload(
            parse_request_token(generate_request_token(machine_id)),
            customer="过期测试",
            edition="beta",
            features=[],
            issued_at=now - timedelta(days=10),
            expires_at=now - timedelta(days=1),
            min_app_version=APP_VERSION,
            max_app_version=None,
        )
        expired_path = temp_root / "expired-test.lic"
        write_json(expired_path, {**expired_payload, "signature": sign_payload(private_path, expired_payload)})
        expired = _run("verify", "--license", str(expired_path), "--public-key", str(public_path))
        if expired.returncode != 1 or "expired=true" not in expired.stdout:
            raise AssertionError("expired license was not rejected")
    finally:
        crypto_module.EMBEDDED_PUBLIC_KEY_PEM = original_embedded_public_key
        license_manager_module.get_machine_id = original_machine_id
        if old_data_root is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_data_root
        shutil.rmtree(temp_root, ignore_errors=True)

    if private_path.exists() or public_path.exists():
        raise AssertionError("temporary test keys were not deleted")

    print("license admin cli smoke ok")
    print("inspect_machine_masked=true")
    print("request_stdin_issue=true")
    print("duplicate_rejected=true")
    print("force_duplicate_audited=true")
    print("issue_dev_signed_machine_bound=true")
    print("issue_dev_explicit_output_and_force=true")
    print("signature_verify=true")
    print("expired_license_rejected=true")
    print("client_lflic1_validation=true")
    print("legacy_license_validation=true")
    print("client_version_range_enforced=true")
    print("unknown_license_schema_rejected=true")
    print("legacy_request_supported=true")
    print("temporary_test_keys_deleted=true")


if __name__ == "__main__":
    main()
