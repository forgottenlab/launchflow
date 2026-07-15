"""Author-only license issuing core shared by the CLI and a future admin UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives import serialization

from licensing.crypto import verify_signature_with_key
from licensing.license_schema import (
    LICENSE_SCHEMA,
    PRODUCT_ID,
    app_version_allowed,
    format_utc,
    is_expired,
    utc_now,
    validate_new_license_shape,
)
from licensing.request_token import mask_machine_id
from shared.utils import read_json, write_json
from tools.license_generator import sign_payload


@dataclass(frozen=True)
class IssueResult:
    license_data: dict[str, Any]
    output_path: Path
    forced_duplicate: bool


def load_history(history_file: Path) -> list[dict[str, Any]]:
    if not history_file.is_file():
        return []
    records: list[dict[str, Any]] = []
    with history_file.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"签发历史第 {line_number} 行损坏") from exc
            if not isinstance(record, dict):
                raise ValueError(f"签发历史第 {line_number} 行不是对象")
            records.append(record)
    return records


def append_history(history_file: Path, record: dict[str, Any]) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def request_was_issued(history_file: Path, request_id: str) -> bool:
    return any(record.get("request_id") == request_id for record in load_history(history_file))


def build_license_payload(
    request_payload: dict[str, Any],
    *,
    customer: str,
    edition: str,
    features: list[str],
    issued_at: datetime,
    expires_at: datetime,
    min_app_version: str,
    max_app_version: str | None,
    license_id: str | None = None,
) -> dict[str, Any]:
    if not customer.strip():
        raise ValueError("customer 不能为空")
    if not edition.strip():
        raise ValueError("edition 不能为空")
    request_id = str(request_payload.get("request_id", "")).strip()
    machine_id = str(request_payload.get("machine_id", "")).strip().upper()
    request_app_version = str(request_payload.get("app_version", "legacy")).strip() or "legacy"
    if not request_id or not machine_id:
        raise ValueError("申请码缺少 request_id 或 machine_id")
    return {
        "schema": LICENSE_SCHEMA,
        "license_id": license_id or f"LF-{issued_at:%Y%m%d}-{uuid4().hex[:12].upper()}",
        "request_id": request_id,
        "product": PRODUCT_ID,
        "machine_id": machine_id,
        "customer": customer.strip(),
        "edition": edition.strip(),
        "features": sorted(set(feature.strip() for feature in features if feature.strip())),
        "issued_at": format_utc(issued_at),
        "expires_at": format_utc(expires_at),
        "request_app_version": request_app_version,
        "min_app_version": min_app_version,
        "max_app_version": max_app_version,
    }


def issue_license(
    request_payload: dict[str, Any],
    *,
    customer: str,
    edition: str,
    days: int,
    private_key_path: Path,
    output_dir: Path,
    history_file: Path,
    output_path: Path | None = None,
    features: list[str] | None = None,
    min_app_version: str | None = None,
    max_app_version: str | None = None,
    force: bool = False,
    audit_action: str = "issue",
    now: datetime | None = None,
) -> IssueResult:
    if days <= 0:
        raise ValueError("days 必须大于 0")
    if not private_key_path.is_file():
        raise FileNotFoundError(f"签名私钥文件不存在: {private_key_path}")
    request_id = str(request_payload.get("request_id", "")).strip()
    duplicate = request_was_issued(history_file, request_id)
    if duplicate and not force:
        raise ValueError(f"request_id 已签发，默认拒绝重复签发: {request_id}")

    issued_at = now or utc_now()
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    request_version = str(request_payload.get("app_version", "")).strip()
    minimum = min_app_version or (request_version if request_version and request_version != "legacy" else "0.0.0")
    payload = build_license_payload(
        request_payload,
        customer=customer,
        edition=edition,
        features=features or [],
        issued_at=issued_at,
        expires_at=issued_at + timedelta(days=days),
        min_app_version=minimum,
        max_app_version=max_app_version,
    )
    signature = sign_payload(private_key_path, payload)
    license_data = {**payload, "signature": signature}
    validate_new_license_shape(license_data)

    target_path = output_path or output_dir / f"{payload['license_id']}.lic"
    if target_path.suffix.lower() != ".lic":
        raise ValueError(f"license 输出路径必须使用 .lic 扩展名: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not force:
        raise FileExistsError(f"输出文件已存在，使用 --force 才能覆盖: {target_path}")
    write_json(target_path, license_data)

    append_history(
        history_file,
        {
            "license_id": payload["license_id"],
            "request_id": request_id,
            "machine_id": mask_machine_id(payload["machine_id"]),
            "customer": payload["customer"],
            "edition": payload["edition"],
            "issued_at": payload["issued_at"],
            "output_file": str(target_path),
            "forced_duplicate": bool(duplicate and force),
            "action": audit_action,
        },
    )
    return IssueResult(license_data, target_path, bool(duplicate and force))


def verify_license_file(
    license_path: Path,
    public_key_path: Path,
    *,
    app_version: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    license_data = read_json(license_path)
    if not isinstance(license_data, dict):
        raise ValueError("license 文件必须是 JSON 对象")
    validate_new_license_shape(license_data)
    if not public_key_path.is_file():
        raise FileNotFoundError(f"公钥文件不存在: {public_key_path}")
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    signature = str(license_data["signature"])
    payload = {key: value for key, value in license_data.items() if key != "signature"}
    signature_valid = verify_signature_with_key(public_key, payload, signature)
    expired = is_expired(str(license_data["expires_at"]), now=now)
    version_allowed = True
    if app_version:
        version_allowed = app_version_allowed(
            app_version,
            str(license_data["min_app_version"]),
            license_data.get("max_app_version"),
        )
    return {
        "valid": bool(signature_valid and not expired and version_allowed),
        "signature_valid": signature_valid,
        "expired": expired,
        "version_allowed": version_allowed,
        "license": license_data,
    }
