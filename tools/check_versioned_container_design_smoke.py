"""Static and synthetic gate for the Phase 1l container design freeze.

This script deliberately does not import production licensing, identity,
runtime, editor, cryptography, or admin modules.  It reads a bounded set of
source files as text/AST, runs a local canonicalizer against visibly synthetic
fixtures, and performs no signing, host-identity access, network access, key
access, license access, or file write.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable
from uuid import RFC_4122, UUID


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "docs" / "versioned-request-license-container-design.md"
REQUEST_PATH = ROOT / "licensing" / "request_token.py"
LICENSE_SCHEMA_PATH = ROOT / "licensing" / "license_schema.py"
LICENSE_MANAGER_PATH = ROOT / "licensing" / "license_manager.py"
HWID_PATH = ROOT / "licensing" / "hwid.py"
ADMIN_CORE_PATH = ROOT / "tools" / "license_admin_core.py"
LEGACY_GENERATOR_PATH = ROOT / "tools" / "license_generator.py"

V1_REQUEST_FIELDS = (
    "schema",
    "product",
    "app_version",
    "machine_id",
    "request_id",
    "created_at",
)
V1_LICENSE_FIELDS = (
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
V1_UNSIGNED_LICENSE_FIELDS = V1_LICENSE_FIELDS[:-1]
V1_LEGACY_LICENSE_FIELDS = (
    "license_id",
    "tester_name",
    "machine_id",
    "edition",
    "expire_at",
    "created_at",
    "signature",
)

REQUEST_PREFIX = "LFREQ2"
REQUEST_SCHEMA = "lfreq-2"
LICENSE_PREFIX = "LFLIC2"
LICENSE_SCHEMA = "lflic-2"
SIGNING_ALGORITHM = "rsa-pkcs1v15-sha256"
SUPPORTED_IDENTITY_ALGORITHMS = frozenset({"legacy-v1"})
SYNTHETIC_RECOGNIZED_EDITIONS = frozenset({"beta"})
SYNTHETIC_RECOGNIZED_ENTITLEMENTS = frozenset({"launch", "workflow-export"})
REQUEST_AUTHORIZATION_FIELDS = frozenset(
    {
        "customer",
        "edition",
        "entitlements",
        "issued_at",
        "expires_at",
        "min_app_version",
        "max_app_version",
        "signing_algorithm",
        "key_id",
        "admin_policy",
    }
)

REQUEST_FIELDS = frozenset(
    {
        "container_type",
        "container_version",
        "schema",
        "product",
        "app_version",
        "request_id",
        "created_at",
        "identity_algorithm",
        "identity_value",
    }
)
LICENSE_FIELDS = frozenset(
    {
        "container_type",
        "container_version",
        "schema",
        "signing_algorithm",
        "key_id",
        "license_id",
        "request_id",
        "product",
        "identity_algorithm",
        "identity_value",
        "customer",
        "edition",
        "entitlements",
        "issued_at",
        "expires_at",
        "min_app_version",
        "max_app_version",
    }
)

REQUEST_VECTOR: dict[str, Any] = {
    "container_type": "request",
    "container_version": 2,
    "schema": "lfreq-2",
    "product": "launchflow",
    "app_version": "0.1.0-beta.2",
    "request_id": "00000000-0000-4000-8000-000000000001",
    "created_at": 1767225600,
    "identity_algorithm": "legacy-v1",
    "identity_value": "A" * 64,
}
LICENSE_VECTOR: dict[str, Any] = {
    "container_type": "license",
    "container_version": 2,
    "schema": "lflic-2",
    "signing_algorithm": "rsa-pkcs1v15-sha256",
    "key_id": "spki-sha256:" + "0" * 64,
    "license_id": "00000000-0000-4000-8000-000000000002",
    "request_id": "00000000-0000-4000-8000-000000000001",
    "product": "launchflow",
    "identity_algorithm": "legacy-v1",
    "identity_value": "A" * 64,
    "customer": "测试用户",
    "edition": "beta",
    "entitlements": ["launch", "workflow-export"],
    "issued_at": 1767225600,
    "expires_at": 1798761600,
    "min_app_version": "0.1.0-beta.2",
    "max_app_version": None,
}
SYNTHETIC_TRUSTED_KEY_REGISTRY = {
    (SIGNING_ALGORITHM, LICENSE_VECTOR["key_id"]): 256,
}
SYNTHETIC_ISSUANCE_MODES = {
    ("legacy-unprefixed", "legacy-lflic-1"): "lflic-1",
    ("LFREQ1", "legacy-lflic-1"): "lflic-1",
    ("LFREQ2", "versioned-lflic-2"): "LFLIC2",
}

REQUEST_CANONICAL_TEXT = (
    '{"app_version":"0.1.0-beta.2","container_type":"request",'
    '"container_version":2,"created_at":1767225600,'
    '"identity_algorithm":"legacy-v1",'
    '"identity_value":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",'
    '"product":"launchflow",'
    '"request_id":"00000000-0000-4000-8000-000000000001",'
    '"schema":"lfreq-2"}'
)
LICENSE_CANONICAL_TEXT = (
    '{"container_type":"license","container_version":2,'
    '"customer":"测试用户","edition":"beta",'
    '"entitlements":["launch","workflow-export"],'
    '"expires_at":1798761600,"identity_algorithm":"legacy-v1",'
    '"identity_value":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",'
    '"issued_at":1767225600,'
    '"key_id":"spki-sha256:0000000000000000000000000000000000000000000000000000000000000000",'
    '"license_id":"00000000-0000-4000-8000-000000000002",'
    '"max_app_version":null,"min_app_version":"0.1.0-beta.2",'
    '"product":"launchflow",'
    '"request_id":"00000000-0000-4000-8000-000000000001",'
    '"schema":"lflic-2","signing_algorithm":"rsa-pkcs1v15-sha256"}'
)
EXPECTED_REQUEST_PAYLOAD_SHA256 = "116218713468c1615ad89d95a1fa3fd43938d9ae88c777dbed6d99ce43adeb2c"
EXPECTED_REQUEST_CHECKSUM = "836771f1261aae50e88eb35ace56a36a7c1e36d8d03f3ac88273dd388d057250"
EXPECTED_LICENSE_PAYLOAD_SHA256 = "5213820461142872a6275b0c98f2e4db5c4004f11a5c50faee08fbdb8f64cf2c"
EXPECTED_LICENSE_SIGNING_SHA256 = "e2fa2e92eb8a11a9d1ef69fb87b42f3729e769e6f4d0d941419d31e0cccf82c6"
EXPECTED_LEGACY_V1_DIGEST = "92FD6B08959D22BC7EB9FEC57E6471C701CB7BDE158D48128D6BC403666DAC4D"
PLACEHOLDER_SIGNATURE = "<NON-PRODUCTION-SIGNATURE>"

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
IDENTITY_ALGORITHM_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
EDITION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
ENTITLEMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class DesignError(ValueError):
    """Raised by the local, non-production design validator."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_raises(function: Callable[[], Any], message: str) -> None:
    try:
        function()
    except (DesignError, UnicodeError, ValueError, json.JSONDecodeError):
        return
    raise AssertionError(message)


def _validate_unicode(value: Any) -> None:
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise DesignError("string is not NFC")
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise DesignError("string contains a forbidden Unicode category")
        return
    if value is None:
        return
    if isinstance(value, bool) or isinstance(value, float):
        raise DesignError("Boolean and float values are forbidden")
    if isinstance(value, int):
        return
    if isinstance(value, list):
        for item in value:
            _validate_unicode(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise DesignError("object key must be a string")
            _validate_unicode(key)
            _validate_unicode(item)
        return
    raise DesignError(f"unsupported JSON type: {type(value).__name__}")


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    _validate_unicode(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DesignError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(_text: str) -> float:
    raise DesignError("float JSON number is forbidden")


def _reject_constant(_text: str) -> float:
    raise DesignError("non-finite JSON number is forbidden")


def strict_json_object(raw: bytes, *, require_canonical: bool = True) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="strict")
    if text.startswith("\ufeff"):
        raise DesignError("UTF-8 BOM is forbidden")
    value = json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise DesignError("top-level JSON value must be an object")
    _validate_unicode(value)
    if require_canonical and canonical_json_bytes(value) != raw:
        raise DesignError("payload bytes are not canonical")
    return value


def base64url_without_padding(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def strict_base64url_decode(segment: str) -> bytes:
    if not segment or not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise DesignError("invalid Base64URL alphabet")
    if "=" in segment or len(segment) % 4 == 1:
        raise DesignError("invalid Base64URL padding/length")
    raw = base64.urlsafe_b64decode((segment + "=" * (-len(segment) % 4)).encode("ascii"))
    if base64url_without_padding(raw) != segment:
        raise DesignError("non-canonical Base64URL segment")
    return raw


def _require_exact_keys(payload: dict[str, Any], expected: frozenset[str]) -> None:
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        unknown = sorted(set(payload) - expected)
        raise DesignError(f"field set mismatch: missing={missing}, unknown={unknown}")


def _require_uuid_v4(value: Any, field: str) -> None:
    if not isinstance(value, str) or not UUID_V4_RE.fullmatch(value):
        raise DesignError(f"{field} is not canonical lowercase UUIDv4")
    parsed = UUID(value)
    if parsed.version != 4 or parsed.variant != RFC_4122 or str(parsed) != value:
        raise DesignError(f"{field} UUID semantics changed")


def _semver(value: Any, field: str) -> tuple[int, int, int, list[str] | None]:
    if not isinstance(value, str) or not value.isascii() or not 1 <= len(value) <= 64:
        raise DesignError(f"{field} must be 1..64 ASCII bytes")
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        raise DesignError(f"{field} is not canonical SemVer")
    prerelease = match.group(4).split(".") if match.group(4) is not None else None
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease


def _compare_semver(left: str, right: str) -> int:
    left_major, left_minor, left_patch, left_pre = _semver(left, "left version")
    right_major, right_minor, right_patch, right_pre = _semver(right, "right version")
    left_core = (left_major, left_minor, left_patch)
    right_core = (right_major, right_minor, right_patch)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre is None or right_pre is None:
        if left_pre is right_pre:
            return 0
        return 1 if left_pre is None else -1
    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def _validate_identity_syntax(algorithm: Any, value: Any) -> None:
    if not isinstance(algorithm, str) or not IDENTITY_ALGORITHM_RE.fullmatch(algorithm):
        raise DesignError("identity algorithm token is invalid")
    if not isinstance(value, str) or not value.isascii() or not 1 <= len(value) <= 512:
        raise DesignError("identity value exceeds the global ASCII limit")
    if algorithm == "legacy-v1" and re.fullmatch(r"[0-9A-F]{64}", value) is None:
        raise DesignError("legacy-v1 identity value is not canonical")


def require_supported_identity_algorithm(algorithm: Any) -> None:
    if algorithm not in SUPPORTED_IDENTITY_ALGORITHMS:
        raise DesignError("identity algorithm is unsupported")


def simulate_post_signature_identity_dispatch(
    payload: dict[str, Any],
    *,
    signature_valid: bool,
    resolver: Callable[[], str],
) -> str:
    """Model only the trust gate; no signature or production resolver is used."""

    if not signature_valid:
        raise DesignError("signature invalid")
    require_supported_identity_algorithm(payload["identity_algorithm"])
    return resolver()


def evaluate_synthetic_license_policy(payload: dict[str, Any]) -> None:
    """Fail closed against the vector-only policy registry."""

    if payload["edition"] not in SYNTHETIC_RECOGNIZED_EDITIONS:
        raise DesignError("unsupported license edition")
    if any(item not in SYNTHETIC_RECOGNIZED_ENTITLEMENTS for item in payload["entitlements"]):
        raise DesignError("unsupported license entitlement")


def select_synthetic_issuance_mode(request_kind: str, mode: str | None) -> str:
    """Model explicit admin selection only; no license is generated."""

    if mode is None:
        return "inspect-only"
    try:
        return SYNTHETIC_ISSUANCE_MODES[(request_kind, mode)]
    except KeyError as exc:
        raise DesignError("request kind and explicit issuance mode are incompatible") from exc


def simulate_admin_issuance_review(
    request_kind: str,
    request_payload: dict[str, Any],
    *,
    mode: str | None,
    externally_authorized: bool,
    replay_state: str | None,
    timestamp_acceptable: bool,
    issuer: Callable[[str, tuple[str, str]], str],
) -> str:
    """Model inspect/authorization gates; it performs no signing or identity read."""

    output = select_synthetic_issuance_mode(request_kind, mode)
    if output == "inspect-only":
        return output
    if not externally_authorized:
        raise DesignError("external administrator authorization is required")
    if replay_state is None:
        raise DesignError("administrator replay state is unavailable")
    if replay_state != "new":
        raise DesignError("request ID is already processed or conflicting")
    if not timestamp_acceptable:
        raise DesignError("request time needs explicit administrator review")

    if request_kind == "LFREQ2":
        validate_request_payload(request_payload)
        require_supported_identity_algorithm(request_payload["identity_algorithm"])
        identity_pair = (request_payload["identity_algorithm"], request_payload["identity_value"])
    else:
        machine_id = request_payload.get("machine_id")
        if not isinstance(machine_id, str) or not machine_id.strip():
            raise DesignError("legacy request machine_id is missing")
        identity_pair = ("legacy-v1", machine_id.strip().upper())
    return issuer(output, identity_pair)


def synthetic_license_wire(payload: dict[str, Any], *, signature_length: int = 256) -> str:
    payload_segment = base64url_without_padding(canonical_json_bytes(payload))
    signature_segment = base64url_without_padding(bytes(signature_length))
    return f"{LICENSE_PREFIX}.{payload_segment}.{signature_segment}"


def simulate_lflic2_validation_order(
    wire: str,
    *,
    signature_valid: bool,
    now: int,
    app_version: str,
    resolver_registry: dict[str, Callable[[], str]],
    key_lookups: list[tuple[str, str]],
    trace: list[str],
) -> tuple[str, ...]:
    """Model the complete frozen trust order with synthetic metadata only."""

    trace.append("framing")
    if not isinstance(wire, str) or not wire.isascii() or any(character.isspace() for character in wire):
        raise DesignError("license framing is not exact ASCII")
    if len(wire.encode("ascii")) > 16384:
        raise DesignError("license container exceeds total limit")
    parts = wire.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_PREFIX:
        raise DesignError("license prefix or segment count is invalid")
    _, payload_segment, signature_segment = parts

    trace.append("encoded_limits")
    if len(payload_segment) > 10923 or len(signature_segment) > 1024:
        raise DesignError("license encoded segment limit exceeded")

    trace.append("base64url_decode")
    payload_raw = strict_base64url_decode(payload_segment)
    signature_raw = strict_base64url_decode(signature_segment)
    if len(payload_raw) > 8192 or len(signature_raw) > 768:
        raise DesignError("license decoded segment limit exceeded")

    trace.append("json_duplicate_reject")
    payload = strict_json_object(payload_raw, require_canonical=False)

    trace.append("canonical_equality")
    if canonical_json_bytes(payload) != payload_raw:
        raise DesignError("license payload is not canonical")

    trace.append("field_binding")
    validate_license_payload_structure(payload)
    validate_binding(LICENSE_PREFIX, payload)

    trace.append("trusted_key_lookup")
    pair = (payload.get("signing_algorithm"), payload.get("key_id"))
    key_lookups.append(pair)
    modulus_length = SYNTHETIC_TRUSTED_KEY_REGISTRY.get(pair)
    if modulus_length is None:
        raise DesignError("unknown trusted signing algorithm/key pair")

    trace.append("signature_length_check")
    if len(signature_raw) != modulus_length:
        raise DesignError("signature length does not match selected key")

    trace.append("signature_check")
    if not signature_valid:
        raise DesignError("signature invalid")

    trace.append("signed_semantics")
    trace.append("product_policy")
    if payload.get("product") != "launchflow":
        raise DesignError("wrong product")

    trace.append("validity")
    if not payload["issued_at"] <= now < payload["expires_at"]:
        raise DesignError("license is not currently effective")

    trace.append("app_version")
    _semver(app_version, "current app_version")
    if _compare_semver(app_version, payload["min_app_version"]) < 0:
        raise DesignError("app version is below minimum")
    maximum = payload["max_app_version"]
    if maximum is not None and _compare_semver(app_version, maximum) > 0:
        raise DesignError("app version is above maximum")

    trace.append("edition_entitlement_policy")
    evaluate_synthetic_license_policy(payload)

    trace.append("identity_algorithm_policy")
    require_supported_identity_algorithm(payload["identity_algorithm"])

    trace.append("identity_registry_lookup")
    resolver = resolver_registry.get(payload["identity_algorithm"])
    if resolver is None:
        raise DesignError("supported identity algorithm has no trusted resolver")

    trace.append("identity_acquire")
    current_identity = resolver()

    trace.append("identity_compare")
    if not hmac.compare_digest(current_identity, payload["identity_value"]):
        raise DesignError("identity mismatch")

    trace.append("entitlements_exposed")
    return tuple(payload["entitlements"])


def validate_size_contract(
    kind: str,
    *,
    wire_length: int,
    encoded_payload_length: int,
    decoded_payload_length: int,
    signature_segment_length: int = 0,
    decoded_signature_length: int = 0,
    modulus_length: int = 0,
) -> None:
    if kind == "request":
        if wire_length > 4096 or encoded_payload_length > 2731 or decoded_payload_length > 2048:
            raise DesignError("request size limit exceeded")
        if signature_segment_length or decoded_signature_length or modulus_length:
            raise DesignError("request has an unexpected signature size")
        return
    if kind == "license":
        if (
            wire_length > 16384
            or encoded_payload_length > 10923
            or decoded_payload_length > 8192
            or signature_segment_length > 1024
            or decoded_signature_length > 768
        ):
            raise DesignError("license size limit exceeded")
        if decoded_signature_length != modulus_length:
            raise DesignError("decoded signature does not match the selected modulus")
        return
    raise DesignError("unknown size-contract kind")


def validate_request_payload(payload: dict[str, Any]) -> None:
    _require_exact_keys(payload, REQUEST_FIELDS)
    require(payload["container_type"] == "request", "request container type changed")
    require(type(payload["container_version"]) is int and payload["container_version"] == 2, "request version changed")
    require(payload["schema"] == REQUEST_SCHEMA, "request schema changed")
    require(payload["product"] == "launchflow", "request product changed")
    _semver(payload["app_version"], "app_version")
    _require_uuid_v4(payload["request_id"], "request_id")
    if type(payload["created_at"]) is not int or not 0 <= payload["created_at"] <= 253402300799:
        raise DesignError("created_at is not a bounded integer epoch")
    _validate_identity_syntax(payload["identity_algorithm"], payload["identity_value"])
    raw = canonical_json_bytes(payload)
    if len(raw) > 2048:
        raise DesignError("request payload exceeds 2048 bytes")


def validate_license_payload_structure(payload: dict[str, Any]) -> None:
    _require_exact_keys(payload, LICENSE_FIELDS)
    if not isinstance(payload["container_type"], str):
        raise DesignError("license container type must be a string")
    if type(payload["container_version"]) is not int:
        raise DesignError("license container version must be an exact integer")
    if not isinstance(payload["schema"], str) or not isinstance(payload["product"], str):
        raise DesignError("license schema/product must be strings")
    signing_algorithm = payload["signing_algorithm"]
    if (
        not isinstance(signing_algorithm, str)
        or not signing_algorithm.isascii()
        or re.fullmatch(r"[a-z0-9-]{1,64}", signing_algorithm) is None
    ):
        raise DesignError("signing algorithm syntax is invalid")
    if not isinstance(payload["key_id"], str) or re.fullmatch(r"spki-sha256:[0-9a-f]{64}", payload["key_id"]) is None:
        raise DesignError("key_id is invalid")
    _require_uuid_v4(payload["license_id"], "license_id")
    _require_uuid_v4(payload["request_id"], "request_id")
    _validate_identity_syntax(payload["identity_algorithm"], payload["identity_value"])

    customer = payload["customer"]
    if not isinstance(customer, str) or not 1 <= len(customer) <= 128 or len(customer.encode("utf-8")) > 256:
        raise DesignError("customer exceeds its size limit")
    _validate_unicode(customer)
    if not isinstance(payload["edition"], str) or EDITION_RE.fullmatch(payload["edition"]) is None:
        raise DesignError("edition is invalid")
    entitlements = payload["entitlements"]
    if not isinstance(entitlements, list) or len(entitlements) > 64:
        raise DesignError("entitlements is invalid")
    if any(not isinstance(item, str) or ENTITLEMENT_RE.fullmatch(item) is None for item in entitlements):
        raise DesignError("entitlement token is invalid")
    if entitlements != sorted(set(entitlements)):
        raise DesignError("entitlements must be sorted and unique")

    issued_at = payload["issued_at"]
    expires_at = payload["expires_at"]
    if type(issued_at) is not int or type(expires_at) is not int:
        raise DesignError("license timestamps must be exact integers")
    if not 0 <= issued_at < expires_at <= 253402300799:
        raise DesignError("license validity interval is invalid")
    _semver(payload["min_app_version"], "min_app_version")
    maximum = payload["max_app_version"]
    if maximum is not None:
        _semver(maximum, "max_app_version")
        if _compare_semver(maximum, payload["min_app_version"]) < 0:
            raise DesignError("max_app_version is below min_app_version")
    raw = canonical_json_bytes(payload)
    if len(raw) > 8192:
        raise DesignError("license payload exceeds 8192 bytes")


def validate_license_payload(payload: dict[str, Any]) -> None:
    validate_license_payload_structure(payload)
    require(payload["container_type"] == "license", "license container type changed")
    require(type(payload["container_version"]) is int and payload["container_version"] == 2, "license version changed")
    require(payload["schema"] == LICENSE_SCHEMA, "license schema changed")
    require(payload["product"] == "launchflow", "license product changed")
    require(payload["signing_algorithm"] == SIGNING_ALGORITHM, "signing algorithm changed")


def request_checksum(payload: dict[str, Any]) -> tuple[str, str]:
    payload_segment = base64url_without_padding(canonical_json_bytes(payload))
    checksum = hashlib.sha256((REQUEST_PREFIX + "." + payload_segment).encode("ascii")).hexdigest()
    return payload_segment, checksum


def license_signing_bytes(payload: dict[str, Any]) -> bytes:
    payload_segment = base64url_without_padding(canonical_json_bytes(payload))
    return (LICENSE_PREFIX + "." + payload_segment).encode("ascii")


def validate_binding(prefix: str, payload: dict[str, Any]) -> None:
    expected = {
        REQUEST_PREFIX: ("request", 2, REQUEST_SCHEMA),
        LICENSE_PREFIX: ("license", 2, LICENSE_SCHEMA),
    }.get(prefix)
    if expected is None:
        raise DesignError("unknown prefix")
    actual = (payload.get("container_type"), payload.get("container_version"), payload.get("schema"))
    if actual != expected:
        raise DesignError("prefix/container/schema mismatch")


def _read_source(path: Path) -> tuple[str, ast.Module]:
    require(path.is_file(), f"required source file missing: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text, filename=str(path))


def check_smoke_source_safety() -> None:
    """Freeze this smoke's no-production-import and no-key-resource boundary."""

    source_text = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(Path(__file__)))
    allowed_imports = {
        "__future__",
        "ast",
        "base64",
        "hashlib",
        "hmac",
        "json",
        "os",
        "re",
        "sys",
        "unicodedata",
        "pathlib",
        "typing",
        "uuid",
    }
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= allowed_imports, "design smoke gained a production or third-party import")

    expected_sources = {
        "REQUEST_PATH",
        "LICENSE_SCHEMA_PATH",
        "LICENSE_MANAGER_PATH",
        "HWID_PATH",
        "ADMIN_CORE_PATH",
        "LEGACY_GENERATOR_PATH",
    }
    source_arguments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_read_source":
            require(len(node.args) == 1 and isinstance(node.args[0], ast.Name), "unbounded source read added")
            source_arguments.append(node.args[0].id)
    require(set(source_arguments) == expected_sources, "design smoke source allowlist changed")
    require(len(source_arguments) == len(expected_sources), "design smoke reads a source more than once")

    forbidden_dynamic_names = {"__import__", "compile", "eval", "exec", "getattr", "open"}
    forbidden_methods = {
        "open",
        "read_bytes",
        "write_text",
        "write_bytes",
        "home",
        "glob",
        "rglob",
        "load_pem_public_key",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            require(
                node.func.id not in forbidden_dynamic_names,
                f"design smoke gained forbidden dynamic/file call: {node.func.id}",
            )
        elif isinstance(node.func, ast.Attribute):
            require(
                node.func.attr not in forbidden_methods,
                f"design smoke gained forbidden file/key method: {node.func.attr}",
            )

    parents = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    read_text_receivers: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "read_text":
            continue
        parent = parents.get(id(node))
        require(
            isinstance(parent, ast.Call) and parent.func is node,
            "design smoke may not alias a text reader",
        )
        read_text_receivers.append(ast.unparse(node.value))
    require(
        sorted(read_text_receivers) == ["DESIGN_PATH", "Path(__file__)", "path"],
        "design smoke text-read allowlist changed",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            require(
                node.id not in forbidden_dynamic_names,
                f"design smoke references forbidden dynamic/file primitive: {node.id}",
            )

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith("_PATH") and value is not None:
                expression = ast.unparse(value).lower()
                require("crypto" not in expression and ".pem" not in expression, "key-bearing path added to smoke")

    admin_review = _function(tree, "simulate_admin_issuance_review")
    require(
        tuple(argument.arg for argument in admin_review.args.args)
        == ("request_kind", "request_payload"),
        "admin review positional inputs changed",
    )
    require(
        tuple(argument.arg for argument in admin_review.args.kwonlyargs)
        == (
            "mode",
            "externally_authorized",
            "replay_state",
            "timestamp_acceptable",
            "issuer",
        ),
        "admin review gained an untrusted callback or local resolver input",
    )
    allowed_admin_calls = {
        "DesignError",
        "isinstance",
        "issuer",
        "require_supported_identity_algorithm",
        "select_synthetic_issuance_mode",
        "validate_request_payload",
    }
    allowed_admin_methods = {"get", "strip", "upper"}
    forbidden_host_roots = {"getpass", "os", "platform", "socket", "subprocess", "winreg"}
    for node in ast.walk(admin_review):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            require(node.func.id in allowed_admin_calls, f"admin review gained forbidden call: {node.func.id}")
        elif isinstance(node.func, ast.Attribute):
            root: ast.expr = node.func.value
            while isinstance(root, ast.Attribute):
                root = root.value
            require(
                not isinstance(root, ast.Name) or root.id not in forbidden_host_roots,
                "admin review gained a host-identity call",
            )
            require(node.func.attr in allowed_admin_methods, f"admin review gained forbidden method: {node.func.attr}")
        else:
            raise AssertionError("admin review gained indirect callable dispatch")


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"assignment missing: {name}")


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
    raise AssertionError(f"function missing: {name}")


def _returned_dict_keys(function: ast.FunctionDef) -> tuple[str, ...]:
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = []
            for key in node.value.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    break
                keys.append(key.value)
            else:
                return tuple(keys)
    raise AssertionError(f"literal returned dict missing: {function.name}")


def _call_lines(function: ast.FunctionDef, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        called = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""
        if called == name:
            lines.append(node.lineno)
    return sorted(lines)


def _assert_v1_canonical_function(tree: ast.Module, name: str) -> None:
    function = _function(tree, name)
    dump_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr == "dumps"
    ]
    require(len(dump_calls) == 1, f"{name} json.dumps call changed")
    dump_call = dump_calls[0]
    keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in dump_call.keywords}
    require(
        keywords == {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")},
        f"{name} legacy canonical keywords changed",
    )
    encoded = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "encode"
        and node.func.value is dump_call
    ]
    require(len(encoded) == 1 and ast.literal_eval(encoded[0].args[0]) == "utf-8", f"{name} UTF-8 changed")


def check_frozen_production_contracts() -> None:
    request_text, request_tree = _read_source(REQUEST_PATH)
    schema_text, schema_tree = _read_source(LICENSE_SCHEMA_PATH)
    manager_text, manager_tree = _read_source(LICENSE_MANAGER_PATH)
    hwid_text, hwid_tree = _read_source(HWID_PATH)
    admin_text, admin_tree = _read_source(ADMIN_CORE_PATH)
    generator_text, generator_tree = _read_source(LEGACY_GENERATOR_PATH)

    require(_literal_assignment(request_tree, "REQUEST_PREFIX") == "LFREQ1", "LFREQ1 prefix changed")
    require(_literal_assignment(request_tree, "REQUEST_SCHEMA") == "lfreq-1", "lfreq-1 schema changed")
    require(_literal_assignment(request_tree, "CHECKSUM_LENGTH") == 12, "LFREQ1 checksum length changed")
    require(_literal_assignment(request_tree, "PRODUCT_ID") == "launchflow", "request product changed")
    require(
        _returned_dict_keys(_function(request_tree, "build_request_payload")) == V1_REQUEST_FIELDS,
        "current request factory fields changed",
    )
    required_values = []
    for node in ast.walk(_function(request_tree, "_validate_current_payload")):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "required" for target in node.targets):
            required_values.append(ast.literal_eval(node.value))
    require(required_values == [V1_REQUEST_FIELDS], "current request required fields changed")
    _assert_v1_canonical_function(request_tree, "_canonical_payload_bytes")
    require('.rstrip("=")' in request_text, "LFREQ1 no-padding emitter changed")
    require('"=" * (-len(text) % 4)' in request_text, "LFREQ1 decode-padding behavior changed")
    require('hashlib.sha256(data).hexdigest()[:CHECKSUM_LENGTH]' in request_text, "LFREQ1 checksum input changed")
    require('normalized_token.split(".")' in request_text and 'len(parts) != 3' in request_text, "LFREQ1 framing changed")
    require('return _parse_legacy_token(normalized_token)' in request_text, "legacy request fallback changed")
    encode_function = _function(request_tree, "encode_request_token")
    raw_assignments = [
        node
        for node in ast.walk(encode_function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "raw" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_canonical_payload_bytes"
    ]
    require(
        len(raw_assignments) == 1
        and len(raw_assignments[0].value.args) == 1
        and isinstance(raw_assignments[0].value.args[0], ast.Name)
        and raw_assignments[0].value.args[0].id == "normalized",
        "LFREQ1 raw bytes no longer come from the normalized canonical payload",
    )
    payload_encode_calls = [
        node
        for node in ast.walk(encode_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_base64url_encode"
    ]
    require(
        len(payload_encode_calls) == 1
        and len(payload_encode_calls[0].args) == 1
        and isinstance(payload_encode_calls[0].args[0], ast.Name)
        and payload_encode_calls[0].args[0].id == "raw",
        "LFREQ1 payload segment no longer encodes the same canonical raw bytes",
    )
    checksum_calls = [
        node
        for node in ast.walk(encode_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_checksum"
    ]
    require(
        len(checksum_calls) == 1
        and len(checksum_calls[0].args) == 1
        and isinstance(checksum_calls[0].args[0], ast.Name)
        and checksum_calls[0].args[0].id == "raw",
        "LFREQ1 encoder no longer checksums canonical raw bytes",
    )

    require(_literal_assignment(schema_tree, "LICENSE_SCHEMA") == "lflic-1", "lflic-1 schema changed")
    require(tuple(_literal_assignment(schema_tree, "NEW_LICENSE_FIELDS")) == V1_LICENSE_FIELDS, "lflic-1 fields changed")
    require(_literal_assignment(schema_tree, "PRODUCT_ID") == "launchflow", "license product changed")
    require(
        _returned_dict_keys(_function(admin_tree, "build_license_payload")) == V1_UNSIGNED_LICENSE_FIELDS,
        "admin lflic-1 unsigned payload fields changed",
    )
    _assert_v1_canonical_function(generator_tree, "canonical_json_bytes")
    require('if k != "signature"' in manager_text, "current all-fields-except-signature payload changed")
    require("padding.PKCS1v15()" in generator_text and "hashes.SHA256()" in generator_text, "legacy signer algorithm changed")
    require("base64.b64encode(signature)" in generator_text, "legacy signature encoding changed")
    sign_function = _function(generator_tree, "sign_payload")
    message_assignments = [
        node
        for node in ast.walk(sign_function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "message" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "canonical_json_bytes"
    ]
    require(
        len(message_assignments) == 1
        and len(message_assignments[0].value.args) == 1
        and isinstance(message_assignments[0].value.args[0], ast.Name)
        and message_assignments[0].value.args[0].id == "payload",
        "legacy signer input no longer uses the whole unsigned canonical payload",
    )

    validate_method = _function(manager_tree, "validate_license_data")
    shape_lines = _call_lines(validate_method, "validate_new_license_shape")
    verify_lines = _call_lines(validate_method, "verify_signature")
    identity_lines = _call_lines(validate_method, "get_machine_id")
    expiry_lines = _call_lines(validate_method, "is_expired")
    version_lines = _call_lines(validate_method, "app_version_allowed")
    require(
        len(shape_lines) == len(verify_lines) == len(identity_lines) == len(expiry_lines) == len(version_lines) == 1,
        "LicenseManager validation call counts changed",
    )
    require(
        shape_lines[0] < verify_lines[0] < identity_lines[0] < expiry_lines[0] < version_lines[0],
        "LicenseManager shape/signature/identity/validity order changed",
    )
    payload_assignments = [
        node
        for node in ast.walk(validate_method)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets)
        and isinstance(node.value, ast.DictComp)
    ]
    verify_calls = [
        node
        for node in ast.walk(validate_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "verify_signature"
    ]
    require(len(payload_assignments) == len(verify_calls) == 1, "LicenseManager signature payload binding changed")
    payload_comprehension = payload_assignments[0].value
    require(
        isinstance(payload_comprehension.key, ast.Name)
        and payload_comprehension.key.id == "k"
        and isinstance(payload_comprehension.value, ast.Name)
        and payload_comprehension.value.id == "v",
        "LicenseManager signature payload is no longer the original key/value pair",
    )
    require(len(payload_comprehension.generators) == 1, "LicenseManager signature payload comprehension changed")
    generator = payload_comprehension.generators[0]
    require(
        isinstance(generator.target, ast.Tuple)
        and [ast.unparse(item) for item in generator.target.elts] == ["k", "v"]
        and isinstance(generator.iter, ast.Call)
        and isinstance(generator.iter.func, ast.Attribute)
        and isinstance(generator.iter.func.value, ast.Name)
        and generator.iter.func.value.id == "license_data"
        and generator.iter.func.attr == "items"
        and len(generator.ifs) == 1
        and isinstance(generator.ifs[0], ast.Compare)
        and isinstance(generator.ifs[0].left, ast.Name)
        and generator.ifs[0].left.id == "k"
        and len(generator.ifs[0].ops) == 1
        and isinstance(generator.ifs[0].ops[0], ast.NotEq)
        and len(generator.ifs[0].comparators) == 1
        and isinstance(generator.ifs[0].comparators[0], ast.Constant)
        and generator.ifs[0].comparators[0].value == "signature",
        "LicenseManager signature payload filter is not exactly all fields except signature",
    )
    verify_call = verify_calls[0]
    require(
        len(verify_call.args) == 3
        and isinstance(verify_call.args[0], ast.Attribute)
        and isinstance(verify_call.args[0].value, ast.Name)
        and verify_call.args[0].value.id == "self"
        and verify_call.args[0].attr == "public_key_path"
        and isinstance(verify_call.args[1], ast.Name)
        and verify_call.args[1].id == "payload"
        and isinstance(verify_call.args[2], ast.Name)
        and verify_call.args[2].id == "signature",
        "LicenseManager verify call no longer consumes the all-fields-except-signature payload",
    )
    invalid_signature_lines = [
        node.lineno
        for node in ast.walk(validate_method)
        if isinstance(node, ast.Constant) and node.value == "invalid_signature"
    ]
    require(
        len(invalid_signature_lines) == 1 and verify_lines[0] < invalid_signature_lines[0] < identity_lines[0],
        "invalid signature no longer returns before identity",
    )
    legacy_lists = []
    for node in ast.walk(validate_method):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "required_fields" for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            if value:
                legacy_lists.append(tuple(value))
    require(legacy_lists == [V1_LEGACY_LICENSE_FIELDS], "unversioned legacy license fields changed")
    require('schema not in (None, "", "lflic-1")' in manager_text, "legacy/schema dispatch changed")

    expected_hwid_signatures = {
        "_read_windows_machine_guid": ((), (), (), "str"),
        "_read_machine_sid_fallback": ((), (), (), "str"),
        "_read_volume_serial": ((), (), (), "str"),
        "get_machine_fingerprint_parts": ((), (), (), "Dict[str, str]"),
        "get_machine_id": ((), (), (), "str"),
        "format_machine_id": (("machine_id", "group"), ("str", "int"), (4,), "str"),
    }
    for name, (arguments, annotations, defaults, return_annotation) in expected_hwid_signatures.items():
        function = _function(hwid_tree, name)
        require(tuple(argument.arg for argument in function.args.args) == arguments, f"HWID signature changed: {name}")
        require(
            tuple(ast.unparse(argument.annotation) if argument.annotation is not None else "" for argument in function.args.args)
            == annotations,
            f"HWID parameter annotations changed: {name}",
        )
        require(tuple(ast.literal_eval(default) for default in function.args.defaults) == defaults, f"HWID defaults changed: {name}")
        require(
            not function.args.posonlyargs
            and function.args.vararg is None
            and not function.args.kwonlyargs
            and function.args.kwarg is None,
            f"HWID variadic/keyword-only signature changed: {name}",
        )
        require(function.returns is not None and ast.unparse(function.returns) == return_annotation, f"HWID return changed: {name}")
    machine_id_function = _function(hwid_tree, "get_machine_id")
    require(_call_lines(machine_id_function, "get_machine_fingerprint_parts") == [machine_id_function.body[1].lineno], "HWID collection count changed")
    require(len(_call_lines(machine_id_function, "build_legacy_v1_machine_id")) == 1, "legacy-v1 builder call changed")
    require("HardwareIdentityParts" in hwid_text and "build_legacy_v1_machine_id" in hwid_text, "HWID facade route changed")
    require("LICENSE_SCHEMA" in admin_text and "machine_id" in admin_text, "admin current payload route changed")
    require("NEW_LICENSE_FIELDS" in schema_text, "license schema constant missing")

    synthetic_raw = (
        "11111111-2222-3333-4444-555555555555||ABCD-1234||"
        "Windows|11|10.0.26100|TEST-HOST|TestUser"
    )
    digest = hashlib.sha256(synthetic_raw.encode("utf-8")).hexdigest().upper()
    require(digest == EXPECTED_LEGACY_V1_DIGEST, "Phase 1k fixed synthetic digest changed")


def check_reference_vectors() -> None:
    require(REQUEST_FIELDS.isdisjoint(REQUEST_AUTHORIZATION_FIELDS), "request gained authorization fields")
    require(
        {"customer", "edition", "entitlements", "issued_at", "expires_at"} <= LICENSE_FIELDS,
        "license lost administrator-authoritative fields",
    )
    require(select_synthetic_issuance_mode("LFREQ2", None) == "inspect-only", "admin no longer defaults to inspect-only")
    require(
        select_synthetic_issuance_mode("legacy-unprefixed", "legacy-lflic-1") == "lflic-1"
        and select_synthetic_issuance_mode("LFREQ1", "legacy-lflic-1") == "lflic-1"
        and select_synthetic_issuance_mode("LFREQ2", "versioned-lflic-2") == "LFLIC2",
        "explicit issuance-mode matrix changed",
    )
    for request_kind, mode in (
        ("LFREQ2", "legacy-lflic-1"),
        ("LFREQ1", "versioned-lflic-2"),
        ("legacy-unprefixed", "versioned-lflic-2"),
    ):
        require_raises(
            lambda request_kind=request_kind, mode=mode: select_synthetic_issuance_mode(request_kind, mode),
            "cross-generation issuance mode was accepted",
        )

    validate_request_payload(REQUEST_VECTOR)
    validate_license_payload(LICENSE_VECTOR)
    require_supported_identity_algorithm(REQUEST_VECTOR["identity_algorithm"])
    require_supported_identity_algorithm(LICENSE_VECTOR["identity_algorithm"])
    evaluate_synthetic_license_policy(LICENSE_VECTOR)
    validate_binding(REQUEST_PREFIX, REQUEST_VECTOR)
    validate_binding(LICENSE_PREFIX, LICENSE_VECTOR)

    request_bytes = canonical_json_bytes(REQUEST_VECTOR)
    license_bytes = canonical_json_bytes(LICENSE_VECTOR)
    require(request_bytes == REQUEST_CANONICAL_TEXT.encode("utf-8"), "request canonical bytes changed")
    require(license_bytes == LICENSE_CANONICAL_TEXT.encode("utf-8"), "license canonical bytes changed")
    require(hashlib.sha256(request_bytes).hexdigest() == EXPECTED_REQUEST_PAYLOAD_SHA256, "request vector digest changed")
    require(hashlib.sha256(license_bytes).hexdigest() == EXPECTED_LICENSE_PAYLOAD_SHA256, "license vector digest changed")

    request_segment, checksum = request_checksum(REQUEST_VECTOR)
    require(checksum == EXPECTED_REQUEST_CHECKSUM, "request prefix-bound checksum changed")
    require(strict_base64url_decode(request_segment) == request_bytes, "request Base64URL round trip changed")
    signing_bytes = license_signing_bytes(LICENSE_VECTOR)
    require(hashlib.sha256(signing_bytes).hexdigest() == EXPECTED_LICENSE_SIGNING_SHA256, "license signing bytes changed")
    license_segment = signing_bytes.split(b".", 1)[1].decode("ascii")
    require(strict_base64url_decode(license_segment) == license_bytes, "license Base64URL round trip changed")

    reverse_request = dict(reversed(list(REQUEST_VECTOR.items())))
    reverse_license = dict(reversed(list(LICENSE_VECTOR.items())))
    require(canonical_json_bytes(reverse_request) == request_bytes, "request input order became semantic")
    require(canonical_json_bytes(reverse_license) == license_bytes, "license input order became semantic")
    require("测试用户".encode("utf-8") in license_bytes and b"\\u" not in license_bytes, "Unicode fixture escaped")
    require(LICENSE_VECTOR["max_app_version"] is None, "empty optional field fixture changed")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", PLACEHOLDER_SIGNATURE) is None, "placeholder became valid Base64URL")

    mutations: dict[str, Any] = {
        "container_type": "request",
        "container_version": 3,
        "schema": "lflic-3",
        "signing_algorithm": "rsa-pss-sha256",
        "key_id": "spki-sha256:" + "1" * 64,
        "license_id": "00000000-0000-4000-8000-000000000003",
        "request_id": "00000000-0000-4000-8000-000000000004",
        "product": "launchflow-other",
        "identity_algorithm": "future-v9",
        "identity_value": "B" * 64,
        "customer": "Synthetic Customer",
        "edition": "pro",
        "entitlements": ["launch"],
        "issued_at": 1767225601,
        "expires_at": 1798761601,
        "min_app_version": "0.1.1",
        "max_app_version": "1.0.0",
    }
    require(set(mutations) == LICENSE_FIELDS, "signed-field mutation coverage is incomplete")
    baseline_signing = license_signing_bytes(LICENSE_VECTOR)
    for field, value in mutations.items():
        changed = dict(LICENSE_VECTOR)
        changed[field] = value
        require(license_signing_bytes(changed) != baseline_signing, f"signed field did not affect bytes: {field}")

    unknown_license = dict(LICENSE_VECTOR)
    unknown_license["candidate_ids"] = ["A" * 64]
    require_raises(lambda: validate_license_payload(unknown_license), "unknown license field was accepted")
    unknown_request = dict(REQUEST_VECTOR)
    unknown_request["candidate_ids"] = ["A" * 64]
    require_raises(lambda: validate_request_payload(unknown_request), "unknown request field was accepted")
    require_raises(
        lambda: strict_json_object(b'{"schema":"lflic-2","schema":"lflic-1"}', require_canonical=False),
        "duplicate JSON key was accepted",
    )
    mismatch = dict(REQUEST_VECTOR)
    mismatch["schema"] = "lfreq-1"
    require_raises(lambda: validate_binding(REQUEST_PREFIX, mismatch), "prefix/schema mismatch was accepted")
    license_mismatch = dict(LICENSE_VECTOR)
    license_mismatch["schema"] = "lflic-1"
    require_raises(lambda: validate_binding(LICENSE_PREFIX, license_mismatch), "license prefix/schema mismatch was accepted")
    unsupported = dict(LICENSE_VECTOR)
    unsupported["identity_algorithm"] = "future-unregistered-v9"
    validate_license_payload(unsupported)
    resolver_calls: list[str] = []

    def synthetic_resolver() -> str:
        resolver_calls.append("called")
        return "A" * 64

    require_raises(
        lambda: simulate_post_signature_identity_dispatch(
            unsupported,
            signature_valid=True,
            resolver=synthetic_resolver,
        ),
        "unsupported signed identity algorithm was accepted",
    )
    require(not resolver_calls, "unsupported signed algorithm acquired identity")
    require_raises(
        lambda: simulate_post_signature_identity_dispatch(
            LICENSE_VECTOR,
            signature_valid=False,
            resolver=synthetic_resolver,
        ),
        "invalid signature reached identity dispatch",
    )
    require(not resolver_calls, "invalid signature acquired identity")

    forged_request = dict(REQUEST_VECTOR)
    forged_request["identity_value"] = "B" * 64
    forged_segment, forged_checksum = request_checksum(forged_request)
    require(forged_segment != request_segment, "synthetic request mutation did not change payload")
    require(
        forged_checksum == hashlib.sha256((REQUEST_PREFIX + "." + forged_segment).encode("ascii")).hexdigest(),
        "request checksum stopped being publicly recomputable",
    )
    require(select_synthetic_issuance_mode("LFREQ2", None) == "inspect-only", "forgeable request selected issuance")

    issuer_calls: list[tuple[str, tuple[str, str]]] = []

    def synthetic_issuer(output: str, identity_pair: tuple[str, str]) -> str:
        issuer_calls.append((output, identity_pair))
        return output

    inspect_result = simulate_admin_issuance_review(
        "LFREQ2",
        forged_request,
        mode=None,
        externally_authorized=True,
        replay_state="new",
        timestamp_acceptable=True,
        issuer=synthetic_issuer,
    )
    require(inspect_result == "inspect-only" and not issuer_calls, "inspect-only review issued a license")
    require(
        "resolver" not in simulate_admin_issuance_review.__code__.co_varnames,
        "admin review gained a local identity resolver",
    )

    def require_admin_rejection(
        payload: dict[str, Any],
        message: str,
        *,
        externally_authorized: bool = True,
        replay_state: str | None = "new",
        timestamp_acceptable: bool = True,
    ) -> None:
        before = len(issuer_calls)
        require_raises(
            lambda: simulate_admin_issuance_review(
                "LFREQ2",
                payload,
                mode="versioned-lflic-2",
                externally_authorized=externally_authorized,
                replay_state=replay_state,
                timestamp_acceptable=timestamp_acceptable,
                issuer=synthetic_issuer,
            ),
            message,
        )
        require(len(issuer_calls) == before, f"{message}: issuer was called")

    require_admin_rejection(forged_request, "forged request without authorization issued", externally_authorized=False)
    require_admin_rejection(REQUEST_VECTOR, "processed request replay issued", replay_state="processed")
    require_admin_rejection(REQUEST_VECTOR, "conflicting request ID issued", replay_state="conflict")
    require_admin_rejection(REQUEST_VECTOR, "missing replay state issued", replay_state=None)
    require_admin_rejection(REQUEST_VECTOR, "unreviewed request timestamp issued", timestamp_acceptable=False)
    unsupported_request_algorithm = dict(REQUEST_VECTOR)
    unsupported_request_algorithm["identity_algorithm"] = "future-unregistered-v9"
    require_admin_rejection(unsupported_request_algorithm, "unsupported request identity algorithm issued")

    issued = simulate_admin_issuance_review(
        "LFREQ2",
        REQUEST_VECTOR,
        mode="versioned-lflic-2",
        externally_authorized=True,
        replay_state="new",
        timestamp_acceptable=True,
        issuer=synthetic_issuer,
    )
    require(issued == "LFLIC2", "explicit authorized versioned issuance selected wrong output")
    require(
        issuer_calls[-1]
        == ("LFLIC2", (REQUEST_VECTOR["identity_algorithm"], REQUEST_VECTOR["identity_value"])),
        "admin did not copy the exact requested identity pair",
    )
    for legacy_kind in ("LFREQ1", "legacy-unprefixed"):
        legacy_output = simulate_admin_issuance_review(
            legacy_kind,
            {"machine_id": "a" * 64},
            mode="legacy-lflic-1",
            externally_authorized=True,
            replay_state="new",
            timestamp_acceptable=True,
            issuer=synthetic_issuer,
        )
        require(legacy_output == "lflic-1", "legacy request selected wrong explicit output")
        require(
            issuer_calls[-1] == ("lflic-1", ("legacy-v1", "A" * 64)),
            "legacy request did not copy normalized machine_id",
        )

    valid_trace: list[str] = []
    valid_identity_calls: list[str] = []
    valid_key_lookups: list[tuple[str, str]] = []

    def valid_resolver() -> str:
        valid_identity_calls.append("called")
        return "A" * 64

    valid_wire = synthetic_license_wire(LICENSE_VECTOR)
    exposed = simulate_lflic2_validation_order(
        valid_wire,
        signature_valid=True,
        now=1780000000,
        app_version="0.1.0-beta.2",
        resolver_registry={"legacy-v1": valid_resolver},
        key_lookups=valid_key_lookups,
        trace=valid_trace,
    )
    require(valid_identity_calls == ["called"], "eligible LFLIC2 did not acquire identity exactly once")
    require(
        valid_key_lookups == [(SIGNING_ALGORITHM, LICENSE_VECTOR["key_id"])],
        "eligible LFLIC2 did not perform one exact trusted-key lookup",
    )
    require(exposed == ("launch", "workflow-export"), "eligible entitlements were not exposed")
    require(
        valid_trace
        == [
            "framing",
            "encoded_limits",
            "base64url_decode",
            "json_duplicate_reject",
            "canonical_equality",
            "field_binding",
            "trusted_key_lookup",
            "signature_length_check",
            "signature_check",
            "signed_semantics",
            "product_policy",
            "validity",
            "app_version",
            "edition_entitlement_policy",
            "identity_algorithm_policy",
            "identity_registry_lookup",
            "identity_acquire",
            "identity_compare",
            "entitlements_exposed",
        ],
        "LFLIC2 validation trace changed",
    )

    def require_pre_identity_rejection(
        payload: dict[str, Any] | None,
        message: str,
        *,
        wire: str | None = None,
        signature_valid: bool = True,
        signature_length: int = 256,
        now: int = 1780000000,
        app_version: str = "0.1.0-beta.2",
        resolver_registry_present: bool = True,
    ) -> None:
        trace: list[str] = []
        calls: list[str] = []
        key_lookups: list[tuple[str, str]] = []

        def forbidden_resolver() -> str:
            calls.append("called")
            return "A" * 64

        candidate_wire = wire
        if candidate_wire is None:
            require(payload is not None, "pre-identity fixture is missing payload and wire")
            candidate_wire = synthetic_license_wire(payload, signature_length=signature_length)
        resolver_registry = {"legacy-v1": forbidden_resolver} if resolver_registry_present else {}
        require_raises(
            lambda: simulate_lflic2_validation_order(
                candidate_wire,
                signature_valid=signature_valid,
                now=now,
                app_version=app_version,
                resolver_registry=resolver_registry,
                key_lookups=key_lookups,
                trace=trace,
            ),
            message,
        )
        require(not calls and "identity_acquire" not in trace, f"{message}: identity was acquired")
        require("entitlements_exposed" not in trace, f"{message}: entitlements were exposed")
        require(len(key_lookups) <= 1, f"{message}: trusted-key lookup retried")

    require_pre_identity_rejection(LICENSE_VECTOR, "invalid signature reached identity", signature_valid=False)
    require_pre_identity_rejection(LICENSE_VECTOR, "signature length mismatch reached identity", signature_length=255)
    require_pre_identity_rejection(LICENSE_VECTOR, "not-yet-effective license reached identity", now=1767225599)
    require_pre_identity_rejection(LICENSE_VECTOR, "expired license reached identity", now=1798761600)
    require_pre_identity_rejection(LICENSE_VECTOR, "incompatible app version reached identity", app_version="0.0.1")
    require_pre_identity_rejection(LICENSE_VECTOR, "invalid current app version reached identity", app_version="not-semver")

    bounded_app_version = dict(LICENSE_VECTOR)
    bounded_app_version["max_app_version"] = "0.1.0-beta.2"
    require_pre_identity_rejection(bounded_app_version, "app version above maximum reached identity", app_version="0.1.0")

    wrong_product = dict(LICENSE_VECTOR)
    wrong_product["product"] = "example-product"
    require_pre_identity_rejection(wrong_product, "wrong product reached identity")
    unsupported_edition = dict(LICENSE_VECTOR)
    unsupported_edition["edition"] = "future-edition"
    require_pre_identity_rejection(unsupported_edition, "unsupported edition reached identity")
    unsupported_entitlement = dict(LICENSE_VECTOR)
    unsupported_entitlement["entitlements"] = ["future-capability"]
    require_pre_identity_rejection(unsupported_entitlement, "unsupported entitlement reached identity")
    unsupported_identity = dict(LICENSE_VECTOR)
    unsupported_identity["identity_algorithm"] = "future-unregistered-v9"
    require_pre_identity_rejection(unsupported_identity, "unsupported identity algorithm reached identity")
    unknown_algorithm = dict(LICENSE_VECTOR)
    unknown_algorithm["signing_algorithm"] = "rsa-pss-sha256"
    require_pre_identity_rejection(unknown_algorithm, "unknown signing algorithm reached identity")
    unknown_key = dict(LICENSE_VECTOR)
    unknown_key["key_id"] = "spki-sha256:" + "1" * 64
    require_pre_identity_rejection(unknown_key, "unknown key reached identity")
    path_like_key = dict(LICENSE_VECTOR)
    path_like_key["key_id"] = "https://example.invalid/verification-key"
    require_pre_identity_rejection(path_like_key, "URL-like key ID reached identity")
    windows_path_key = dict(LICENSE_VECTOR)
    windows_path_key["key_id"] = "C:\\synthetic\\verification-key"
    require_pre_identity_rejection(windows_path_key, "path-like key ID reached identity")
    require_pre_identity_rejection(
        LICENSE_VECTOR,
        "missing identity resolver reached acquisition",
        resolver_registry_present=False,
    )

    valid_signature_segment = valid_wire.rsplit(".", 1)[1]
    duplicate_segment = base64url_without_padding(b'{"schema":"lflic-2","schema":"lflic-1"}')
    noncanonical_segment = base64url_without_padding(json.dumps(LICENSE_VECTOR, ensure_ascii=False).encode("utf-8"))
    malformed_wires = (
        "XLFLIC2" + valid_wire[len(LICENSE_PREFIX) :],
        valid_wire + ".extra",
        valid_wire + "=",
        f"{LICENSE_PREFIX}.{'A' * 10924}.{valid_signature_segment}",
        f"{LICENSE_PREFIX}.{duplicate_segment}.{valid_signature_segment}",
        f"{LICENSE_PREFIX}.{noncanonical_segment}.{valid_signature_segment}",
    )
    for malformed_wire in malformed_wires:
        require_pre_identity_rejection(None, "malformed container reached identity", wire=malformed_wire)

    wrong_schema = dict(LICENSE_VECTOR)
    wrong_schema["schema"] = "lflic-1"
    require_pre_identity_rejection(wrong_schema, "schema mismatch reached identity")

    mismatch_trace: list[str] = []
    mismatch_calls: list[str] = []
    mismatch_key_lookups: list[tuple[str, str]] = []

    def mismatch_resolver() -> str:
        mismatch_calls.append("called")
        return "B" * 64

    require_raises(
        lambda: simulate_lflic2_validation_order(
            valid_wire,
            signature_valid=True,
            now=1780000000,
            app_version="0.1.0-beta.2",
            resolver_registry={"legacy-v1": mismatch_resolver},
            key_lookups=mismatch_key_lookups,
            trace=mismatch_trace,
        ),
        "identity mismatch was accepted",
    )
    require(mismatch_calls == ["called"], "identity mismatch retried or skipped acquisition")
    require(len(mismatch_key_lookups) == 1, "identity mismatch retried trusted-key lookup")
    require("entitlements_exposed" not in mismatch_trace, "identity mismatch exposed entitlements")

    provider_trace: list[str] = []
    provider_calls: list[str] = []
    provider_key_lookups: list[tuple[str, str]] = []

    def failing_provider() -> str:
        provider_calls.append("called")
        raise DesignError("synthetic provider failure")

    require_raises(
        lambda: simulate_lflic2_validation_order(
            valid_wire,
            signature_valid=True,
            now=1780000000,
            app_version="0.1.0-beta.2",
            resolver_registry={"legacy-v1": failing_provider},
            key_lookups=provider_key_lookups,
            trace=provider_trace,
        ),
        "provider failure was accepted",
    )
    require(provider_calls == ["called"], "provider failure retried or skipped acquisition")
    require(len(provider_key_lookups) == 1, "provider failure retried trusted-key lookup")
    require("entitlements_exposed" not in provider_trace, "provider failure exposed entitlements")
    oversized = dict(REQUEST_VECTOR)
    oversized["identity_value"] = "A" * 513
    require_raises(lambda: validate_request_payload(oversized), "oversized identity was accepted")
    oversized_license = dict(LICENSE_VECTOR)
    oversized_license["customer"] = "A" * 129
    require_raises(lambda: validate_license_payload(oversized_license), "oversized license field was accepted")
    too_many_entitlements = dict(LICENSE_VECTOR)
    too_many_entitlements["entitlements"] = [f"item-{index:02d}" for index in range(65)]
    require_raises(lambda: validate_license_payload(too_many_entitlements), "oversized entitlement list was accepted")
    non_nfc = dict(LICENSE_VECTOR)
    non_nfc["customer"] = "Cafe\u0301"
    require_raises(lambda: validate_license_payload(non_nfc), "non-NFC customer was accepted")
    boolean_time = dict(REQUEST_VECTOR)
    boolean_time["created_at"] = True
    require_raises(lambda: validate_request_payload(boolean_time), "Boolean timestamp was accepted")
    require_raises(lambda: strict_json_object(b'{"created_at":1.0}', require_canonical=False), "float was accepted")
    for segment in ("A=", "A+A", "A/A", "A A", "A", "AB"):
        require_raises(lambda value=segment: strict_base64url_decode(value), f"ambiguous Base64URL accepted: {segment!r}")

    validate_size_contract(
        "request",
        wire_length=4096,
        encoded_payload_length=2731,
        decoded_payload_length=2048,
    )
    require_raises(
        lambda: validate_size_contract(
            "request",
            wire_length=4097,
            encoded_payload_length=2731,
            decoded_payload_length=2048,
        ),
        "request wire limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "request",
            wire_length=4096,
            encoded_payload_length=2732,
            decoded_payload_length=2048,
        ),
        "request payload-segment limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "request",
            wire_length=4096,
            encoded_payload_length=2731,
            decoded_payload_length=2049,
        ),
        "request payload limit+1 was accepted",
    )
    validate_size_contract(
        "license",
        wire_length=16384,
        encoded_payload_length=10923,
        decoded_payload_length=8192,
        signature_segment_length=1024,
        decoded_signature_length=256,
        modulus_length=256,
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16385,
            encoded_payload_length=10923,
            decoded_payload_length=8192,
            signature_segment_length=1024,
            decoded_signature_length=256,
            modulus_length=256,
        ),
        "license wire limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16384,
            encoded_payload_length=10924,
            decoded_payload_length=8192,
            signature_segment_length=1024,
            decoded_signature_length=256,
            modulus_length=256,
        ),
        "license payload-segment limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16384,
            encoded_payload_length=10923,
            decoded_payload_length=8193,
            signature_segment_length=1024,
            decoded_signature_length=256,
            modulus_length=256,
        ),
        "license payload limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16384,
            encoded_payload_length=10923,
            decoded_payload_length=8192,
            signature_segment_length=1025,
            decoded_signature_length=256,
            modulus_length=256,
        ),
        "license signature-segment limit+1 was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16384,
            encoded_payload_length=10923,
            decoded_payload_length=8192,
            signature_segment_length=1024,
            decoded_signature_length=255,
            modulus_length=256,
        ),
        "wrong decoded signature length was accepted",
    )
    require_raises(
        lambda: validate_size_contract(
            "license",
            wire_length=16384,
            encoded_payload_length=10923,
            decoded_payload_length=8192,
            signature_segment_length=1024,
            decoded_signature_length=769,
            modulus_length=769,
        ),
        "license decoded-signature absolute limit+1 was accepted",
    )
    unknown_policy = dict(LICENSE_VECTOR)
    unknown_policy["entitlements"] = ["future-capability"]
    require_raises(lambda: evaluate_synthetic_license_policy(unknown_policy), "unknown entitlement was partially accepted")
    unknown_edition = dict(LICENSE_VECTOR)
    unknown_edition["edition"] = "future-edition"
    require_raises(lambda: evaluate_synthetic_license_policy(unknown_edition), "unknown edition was accepted")

    # The complete value exists only in memory, is visibly synthetic, is not
    # printed or persisted, and is not accepted by the current broad legacy
    # Base64URL-JSON behavior.  This freezes the old-admin fail-closed premise
    # without importing or calling the production parser.
    synthetic_candidate = f"{REQUEST_PREFIX}.{request_segment}.{checksum}"
    prefix_decoded = base64.urlsafe_b64decode((REQUEST_PREFIX + "==").encode("ascii"))
    require(prefix_decoded[0] == 0x2C, "LFREQ2 old-decoder first byte changed")
    require(prefix_decoded[0] not in b" \t\r\n{", "LFREQ2 could begin a legacy JSON object")
    try:
        legacy_raw = base64.urlsafe_b64decode(
            (synthetic_candidate + "=" * (-len(synthetic_candidate) % 4)).encode("ascii")
        )
        legacy_value = json.loads(legacy_raw.decode("utf-8"))
        old_legacy_accepted = isinstance(legacy_value, dict) and bool(str(legacy_value.get("machine_id", "")).strip())
    except (ValueError, UnicodeError, json.JSONDecodeError):
        old_legacy_accepted = False
    require(not old_legacy_accepted, "current legacy request behavior could accept the LFREQ2 vector")

    require(strict_json_object(request_bytes) == REQUEST_VECTOR, "strict request canonical parse changed")
    require(strict_json_object(license_bytes) == LICENSE_VECTOR, "strict license canonical parse changed")
    require_raises(
        lambda: strict_json_object(json.dumps(REQUEST_VECTOR, ensure_ascii=False).encode("utf-8")),
        "non-canonical wire JSON was accepted",
    )


def check_design_document() -> None:
    require(DESIGN_PATH.is_file(), "design document missing")
    text = DESIGN_PATH.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())
    required_markers = (
        "Status: Phase 1l design freeze complete; implementation not started.",
        "Container Version",
        "Payload Schema Version",
        "Identity Algorithm Version",
        "LFREQ2.<payload_b64url>.<checksum_hex>",
        "LFLIC2.<payload_b64url>.<signature_b64url>",
        "container_type",
        "container_version",
        "identity_algorithm",
        "identity_value",
        'b"LFLIC2." + P.encode("ascii")',
        'b"LFREQ2." + P.encode("ascii")',
        "unknown fields are rejected",
        "duplicate-key",
        "match-any",
        "fail closed",
        "Request parsing and admin-review order",
        "Request trust boundary",
        "LFREQ2` is unauthenticated",
        "checksum is forgeable",
        "`request_id` is correlation only",
        "`created_at` timestamp is untrusted",
        "Request replay requires administrator-side persistent state",
        "Request fields do not grant entitlement",
        "administrator authorization records",
        "admin defaults to inspect-only",
        "issuance mode is explicit",
        "request prefix does not select issuance mode",
        "versioned-lflic-2",
        "trusted key registry",
        "user-writable configuration",
        "runtime injection",
        "`key_id` is never treated as a file path, URL",
        "environment variable",
        "Windows Registry location",
        "unknown signing algorithm or key ID fails closed before identity collection",
        "signature-before-identity",
        "policy-before-identity",
        "expiry-before-identity",
        "app-version-before-identity",
        "Identity is collected exactly once",
        "entitlements are exposed only after identity success",
        "implementation requirement",
        "not implemented by Phase 1l",
        "protected_files_checked > 0",
        "changed=0",
        "hash_mismatch=0",
        "Exact SemVer contract",
        "Compatibility matrix",
        "Downgrade and parser threat model",
        "Migration policy",
        "Reissue and reactivation policy",
        "Rollback policy",
        "non-production synthetic design vector",
        EXPECTED_REQUEST_PAYLOAD_SHA256,
        EXPECTED_REQUEST_CHECKSUM,
        EXPECTED_LICENSE_PAYLOAD_SHA256,
        EXPECTED_LICENSE_SIGNING_SHA256,
        PLACEHOLDER_SIGNATURE,
        "HWID v2 is not defined",
        "implemented by this design",
        "does not change a production",
        "parser, encoder, signer",
        "unsupported_license_policy",
        "legacy-lflic-1",
        "Build metadata is allowed",
    )
    for marker in required_markers:
        require(marker.lower() in normalized_text.lower(), f"design document marker missing: {marker}")

    compatibility_rows = (
        "old client + old license",
        "old client + `LFLIC2`",
        "new client + old license",
        "new client + `LFLIC2`",
        "old admin + old request",
        "old admin + `LFREQ2`",
        "new admin + old request",
        "new admin + `LFREQ2`",
    )
    for row in compatibility_rows:
        require(row in text, f"compatibility row missing: {row}")

    threat_markers = (
        "Prefix substitution",
        "Schema substitution",
        "Identity field stripping",
        "Identity downgrade",
        "Candidate-ID injection",
        "Unknown-field smuggling",
        "Duplicate JSON keys",
        "Unsigned outer metadata",
        "Signature swapping",
        "Request replay",
        "License replay/clone",
        "Old-admin legacy issuance",
        "New-admin auto downgrade",
        "New-license v1 fallback",
        "Entitlement mutation",
        "Expiry mutation",
        "Product/edition mutation",
        "Oversized-token DoS",
        "Malformed Unicode",
        "Base64URL ambiguity",
        "Padding ambiguity",
    )
    for threat in threat_markers:
        require(threat in text, f"downgrade threat missing: {threat}")
    require(text.count("| old client +") >= 2 and text.count("| new admin +") >= 2, "compatibility matrix incomplete")
    require(text.count("| Prefix substitution |") == 1, "threat matrix structure changed")

    license_order = " ".join(
        text.split("## 11. License validation order", 1)[1].split("## 12. Compatibility matrix", 1)[0].split()
    )
    order_markers = (
        "Verify the RSA signature",
        "validate all signed semantics",
        "Reject an expired",
        "select the unique",
        "Acquire local identity exactly once",
        "Expose entitlements only after identity success",
    )
    positions = [license_order.index(marker) for marker in order_markers]
    require(positions == sorted(positions), "LFLIC2 policy/time/identity order changed")


def main() -> int:
    cwd_before = Path.cwd()
    environment_before = dict(os.environ)
    module_presence_before = {
        name: (name in sys.modules, sys.modules.get(name))
        for name in ("winreg", "socket", "getpass", "subprocess", "cryptography")
    }

    check_smoke_source_safety()
    check_frozen_production_contracts()
    check_reference_vectors()
    check_design_document()

    require(Path.cwd() == cwd_before, "design smoke changed cwd")
    require(dict(os.environ) == environment_before, "design smoke changed environment")
    for name, (was_present, original_module) in module_presence_before.items():
        require((name in sys.modules) == was_present, f"design smoke changed module presence: {name}")
        if was_present:
            require(sys.modules.get(name) is original_module, f"design smoke replaced module: {name}")

    print("versioned container design smoke ok")
    print("legacy_request=LFREQ1,lfreq-1,frozen")
    print("legacy_license=lflic-1,unversioned-legacy,frozen")
    print("recommended_request=LFREQ2,lfreq-2")
    print("recommended_license=LFLIC2,lflic-2")
    print("canonical_vectors=deterministic,non-production-synthetic")
    print("old_tool_new_request=fail-closed")
    print("identity=single-signed-pair,no-match-any")
    print("validation=signature-and-policy-before-one-identity-read")
    print("request_trust=unauthenticated,admin-state-required")
    print("key_registry=exact-pair,no-path,no-fallback")
    print("side_effects=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
