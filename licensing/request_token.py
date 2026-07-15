"""Encode, validate, and transition LaunchFlow license request tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from shared.app_info import APP_VERSION


REQUEST_PREFIX = "LFREQ1"
REQUEST_SCHEMA = "lfreq-1"
PRODUCT_ID = "launchflow"
CHECKSUM_LENGTH = 12


class RequestTokenError(ValueError):
    """Raised when a request token is malformed, damaged, or unsupported."""


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _base64url_decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RequestTokenError("申请码 Base64URL 数据无效") from exc


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:CHECKSUM_LENGTH]


def build_request_payload(machine_id: str) -> dict[str, Any]:
    """Create a non-secret, versioned request payload for the current client."""
    normalized_machine_id = machine_id.strip().upper()
    if not normalized_machine_id:
        raise RequestTokenError("machine_id 不能为空")
    return {
        "schema": REQUEST_SCHEMA,
        "product": PRODUCT_ID,
        "app_version": APP_VERSION,
        "machine_id": normalized_machine_id,
        "request_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def encode_request_token(payload: dict[str, Any]) -> str:
    """Encode a validated request payload as LFREQ1.base64url.checksum."""
    normalized = _validate_current_payload(payload)
    raw = _canonical_payload_bytes(normalized)
    return f"{REQUEST_PREFIX}.{_base64url_encode(raw)}.{_checksum(raw)}"


def generate_request_token(machine_id: str) -> str:
    return encode_request_token(build_request_payload(machine_id))


def _validate_current_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestTokenError("申请码载荷必须是 JSON 对象")
    required = ("schema", "product", "app_version", "machine_id", "request_id", "created_at")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise RequestTokenError("申请码缺少字段: " + ", ".join(missing))
    if payload["schema"] != REQUEST_SCHEMA:
        raise RequestTokenError(f"不支持的申请码 schema: {payload['schema']}")
    if str(payload["product"]).lower() != PRODUCT_ID:
        raise RequestTokenError(f"申请码产品不匹配: {payload['product']}")
    try:
        UUID(str(payload["request_id"]))
    except ValueError as exc:
        raise RequestTokenError("request_id 不是有效 UUID") from exc
    try:
        datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequestTokenError("created_at 不是有效 ISO-8601 时间") from exc
    normalized = dict(payload)
    normalized["machine_id"] = str(payload["machine_id"]).strip().upper()
    normalized["product"] = PRODUCT_ID
    return normalized


def _parse_legacy_token(token: str) -> dict[str, Any]:
    raw = _base64url_decode(token)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestTokenError("旧申请码不是有效 UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not str(payload.get("machine_id", "")).strip():
        raise RequestTokenError("旧申请码中缺少 machine_id")
    created_at = str(payload.get("generated_at") or payload.get("created_at") or "legacy-unknown")
    return {
        "schema": "legacy",
        "product": str(payload.get("product") or "VisualLauncher"),
        "app_version": str(payload.get("app_version") or "legacy"),
        "machine_id": str(payload["machine_id"]).strip().upper(),
        "request_id": "legacy-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32],
        "created_at": created_at,
        "legacy": True,
    }


def parse_request_token(token: str) -> dict[str, Any]:
    """Parse LFREQ1 tokens and legacy base64 JSON request codes."""
    normalized_token = token.strip()
    if not normalized_token or any(character.isspace() for character in normalized_token):
        raise RequestTokenError("申请码必须是单行非空文本")
    if not normalized_token.startswith(f"{REQUEST_PREFIX}."):
        return _parse_legacy_token(normalized_token)

    parts = normalized_token.split(".")
    if len(parts) != 3:
        raise RequestTokenError("LFREQ1 申请码结构无效")
    raw = _base64url_decode(parts[1])
    if not hmac.compare_digest(_checksum(raw), parts[2].lower()):
        raise RequestTokenError("申请码校验和不匹配，文本可能已损坏")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestTokenError("申请码载荷不是有效 UTF-8 JSON") from exc
    return _validate_current_payload(payload)


def mask_machine_id(machine_id: str) -> str:
    """Return an audit-safe representation without exposing the full identifier."""
    value = "".join(character for character in machine_id if character.isalnum()).upper()
    if len(value) <= 8:
        return "*" * max(len(value), 1)
    return f"{value[:4]}...{value[-4:]}"
