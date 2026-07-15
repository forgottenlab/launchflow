"""Smoke-test LFREQ1 encoding, integrity checks, and legacy compatibility."""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from licensing.request_token import RequestTokenError, generate_request_token, parse_request_token
from licensing.activation_service import ActivationService
from shared.app_info import APP_VERSION
from shared.app_paths import APP_DATA_ENV


def main() -> None:
    machine_id = "ABCD1234EFGH5678IJKL9012MNOP3456"
    first = generate_request_token(machine_id)
    second = generate_request_token(machine_id)
    if first == second or "\n" in first or not first.startswith("LFREQ1."):
        raise AssertionError("LFREQ1 token uniqueness or single-line contract failed")
    payload = parse_request_token(first)
    if payload["app_version"] != APP_VERSION or payload["product"] != "launchflow":
        raise AssertionError(f"automatic version/product fields failed: {payload}")
    if payload["machine_id"] != machine_id or payload["request_id"] == parse_request_token(second)["request_id"]:
        raise AssertionError("machine compatibility or request_id uniqueness failed")
    if any(key in payload for key in ("private_key", "signature", "license")):
        raise AssertionError("request token contains secret/license fields")

    damaged = first[:-1] + ("0" if first[-1] != "0" else "1")
    try:
        parse_request_token(damaged)
    except RequestTokenError as exc:
        if "校验和" not in str(exc):
            raise
    else:
        raise AssertionError("damaged LFREQ1 token was accepted")

    legacy_payload = {
        "machine_id": machine_id,
        "generated_at": "2026-07-10 12:00:00",
        "product": "VisualLauncher",
        "edition": "beta",
    }
    legacy = base64.urlsafe_b64encode(
        json.dumps(legacy_payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    parsed_legacy = parse_request_token(legacy)
    if not parsed_legacy.get("legacy") or parsed_legacy["machine_id"] != machine_id:
        raise AssertionError("legacy request compatibility failed")

    for invalid in ("", "LFREQ1.invalid.deadbeef", "not-base64"):
        try:
            parse_request_token(invalid)
        except RequestTokenError:
            pass
        else:
            raise AssertionError(f"invalid request token was accepted: {invalid!r}")

    temp_root = Path(tempfile.gettempdir()) / f"launchflow-request-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    old_data_root = os.environ.get(APP_DATA_ENV)
    try:
        os.environ[APP_DATA_ENV] = str(temp_root / "测试 AppData")
        client_token = ActivationService(PROJECT_ROOT).generate_request_code()
        client_payload = parse_request_token(client_token)
        if client_payload["app_version"] != APP_VERSION or not client_payload["machine_id"]:
            raise AssertionError("real client request path omitted version or existing machine identifier")
    finally:
        if old_data_root is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_data_root
        shutil.rmtree(temp_root, ignore_errors=True)

    print("license request smoke ok")
    print(f"app_version={APP_VERSION}")
    print("request_id_unique=true")
    print("checksum_damage_rejected=true")
    print("legacy_request_supported=true")
    print("secret_fields=absent")
    print("activation_service_path=ok")


if __name__ == "__main__":
    main()
