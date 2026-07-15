"""Shared schema and compatibility helpers for versioned LaunchFlow licenses."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


LICENSE_SCHEMA = "lflic-1"
PRODUCT_ID = "launchflow"
NEW_LICENSE_FIELDS = (
    "schema",
    "license_id",
    "request_id",
    "product",
    "machine_id",
    "customer",
    "edition",
    "features",
    "issued_at",
    "expires_at",
    "request_app_version",
    "min_app_version",
    "max_app_version",
    "signature",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_new_license_shape(license_data: dict[str, Any]) -> None:
    missing = [field for field in NEW_LICENSE_FIELDS if field not in license_data]
    if missing:
        raise ValueError("授权文件缺少字段: " + ", ".join(missing))
    if license_data.get("schema") != LICENSE_SCHEMA:
        raise ValueError(f"不支持的 license schema: {license_data.get('schema')}")
    if str(license_data.get("product", "")).lower() != PRODUCT_ID:
        raise ValueError(f"授权产品不匹配: {license_data.get('product')}")
    if not isinstance(license_data.get("features"), list):
        raise ValueError("features 必须是列表")
    if not str(license_data.get("machine_id", "")).strip():
        raise ValueError("machine_id 不能为空")
    if not str(license_data.get("customer", "")).strip():
        raise ValueError("customer 不能为空")
    if not str(license_data.get("min_app_version", "")).strip():
        raise ValueError("min_app_version 不能为空")
    minimum_key = _version_key(str(license_data["min_app_version"]))
    maximum = license_data.get("max_app_version")
    if maximum is not None:
        maximum_key = _version_key(str(maximum))
        if maximum_key < minimum_key:
            raise ValueError("max_app_version 不能小于 min_app_version")
    parse_iso_datetime(str(license_data.get("issued_at", "")))
    parse_iso_datetime(str(license_data.get("expires_at", "")))


def _version_key(version: str) -> tuple[int, int, int, int, str]:
    match = re.fullmatch(r"\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.+))?\s*", version)
    if not match:
        raise ValueError(f"版本号格式无效: {version}")
    major, minor, patch = (int(match.group(index) or 0) for index in range(1, 4))
    prerelease = match.group(4) or ""
    return major, minor, patch, 0 if prerelease else 1, prerelease.lower()


def app_version_allowed(app_version: str, minimum: str, maximum: str | None) -> bool:
    current_key = _version_key(app_version)
    if current_key < _version_key(minimum):
        return False
    if maximum and current_key > _version_key(maximum):
        return False
    return True


def is_expired(expires_at: str, *, now: datetime | None = None) -> bool:
    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc) > parse_iso_datetime(expires_at)
