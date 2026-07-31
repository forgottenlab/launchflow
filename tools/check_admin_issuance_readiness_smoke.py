"""Static and synthetic gate for Phase 1m admin issuance readiness.

This script is deliberately stdlib-only. It does not import production admin,
licensing, identity, runtime, editor, cryptography, or signing modules. It reads
an exact non-key-bearing source/document allowlist, uses visibly synthetic
records, and exercises only a named shared in-memory SQLite database. It does
not load keys, sign, verify, generate artifacts, read host identity, access
AppData, use the network, change cwd/environment, or write files.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
READINESS_PATH = ROOT / "docs" / "admin-issuance-security-readiness.md"
VERSIONED_DESIGN_PATH = ROOT / "docs" / "versioned-request-license-container-design.md"
ARCHITECTURE_PATH = ROOT / "docs" / "architecture.md"
AUDIT_PATH = ROOT / "docs" / "cross-platform-audit.md"
ROADMAP_PATH = ROOT / "docs" / "cross-platform-roadmap.md"
MATRIX_PATH = ROOT / "docs" / "platform-support-matrix.md"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"

ADMIN_CLI_PATH = ROOT / "tools" / "license_admin.py"
ADMIN_CORE_PATH = ROOT / "tools" / "license_admin_core.py"
REQUEST_PATH = ROOT / "licensing" / "request_token.py"
LICENSE_SCHEMA_PATH = ROOT / "licensing" / "license_schema.py"
LICENSE_MANAGER_PATH = ROOT / "licensing" / "license_manager.py"
VERSIONED_SMOKE_PATH = ROOT / "tools" / "check_versioned_container_design_smoke.py"

SOURCE_PATHS = {
    "admin_cli": ADMIN_CLI_PATH,
    "admin_core": ADMIN_CORE_PATH,
    "request": REQUEST_PATH,
    "license_schema": LICENSE_SCHEMA_PATH,
    "license_manager": LICENSE_MANAGER_PATH,
    "versioned_smoke": VERSIONED_SMOKE_PATH,
}
DOCUMENT_PATHS = (
    READINESS_PATH,
    VERSIONED_DESIGN_PATH,
    ARCHITECTURE_PATH,
    AUDIT_PATH,
    ROADMAP_PATH,
    MATRIX_PATH,
    CHANGELOG_PATH,
)

EXPECTED_SOURCE_SHA256 = {
    "admin_cli": "2230b8343e79b24703af4ed40e9b95fcde9b4352c5ed879bfa7f521ebcc1cfda",
    "admin_core": "386e847754acffe791c5631ee4d7fdec15e1676b2fd11ff4924fb8b2ac61bedb",
    "request": "047852bef09580485a92e78aed4b7967d1c393d9181d9d71ac45bce89bcf194a",
    "license_schema": "31a0da9bf7f8c1d7c0fc0511e7b72b041c49bcb49d455985dda4532bd402753d",
    "license_manager": "e0a5b25453e3bace865c42bf75e277e20aac9efbb07bfc1c9e862bfc5b7d6785",
    "versioned_smoke": "e068f1459e33ad065e6f96249862f276a5d555f3134dbfbf66d17a0c4e648aaa",
}

DB_URI = "file:launchflow-phase1m-readiness?mode=memory&cache=shared"
MODES = ("inspect-only", "legacy-lflic-1", "versioned-lflic-2")
MODE_MATRIX = {
    ("legacy-unprefixed", "legacy-lflic-1"): "lflic-1",
    ("LFREQ1", "legacy-lflic-1"): "lflic-1",
    ("LFREQ2", "versioned-lflic-2"): "LFLIC2",
}

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
REQUEST_AUTHORITY_FIELDS = frozenset(
    {
        "customer",
        "customer_id",
        "edition",
        "entitlements",
        "features",
        "validity",
        "validity_policy",
        "issued_at",
        "expires_at",
        "issuance_mode",
        "signing_algorithm",
        "key_id",
        "policy_revision",
    }
)

SYNTHETIC_REQUEST = {
    "container_type": "request",
    "container_version": 2,
    "schema": "lfreq-2",
    "product": "launchflow",
    "app_version": "0.1.0-beta.2",
    "request_id": "10000000-0000-4000-8000-000000000001",
    "created_at": 1767225600,
    "identity_algorithm": "legacy-v1",
    "identity_value": "A" * 64,
}


class ReadinessError(ValueError):
    """Raised when a synthetic readiness contract is violated."""


class SyntheticFailure(RuntimeError):
    """Injected before-commit failure used to prove transaction rollback."""


@dataclass(frozen=True)
class AuthorizationRecord:
    authorization_id: str
    revision: int
    request_schema: str
    request_id: str
    request_payload_digest: str
    customer_id: str
    customer_snapshot: str
    product: str
    edition: str
    entitlements: tuple[str, ...]
    validity_policy: str
    max_validity_seconds: int
    min_app_version: str
    max_app_version: str | None
    allowed_issuance_mode: str
    allowed_identity_algorithm: str
    signing_profile_id: str
    issued_at: int
    expires_at: int
    request_ownership_proof_reference: str
    policy_revision: str
    policy_digest: str
    approval_actor: str
    approval_timestamp: int
    approval_reason: str
    reissue_policy: str
    status: str
    revocation_reference: str | None


@dataclass(frozen=True)
class ProcessedRequestRecord:
    request_schema: str
    request_id: str
    request_payload_digest: str
    authorization_id: str
    authorization_revision: int
    issuance_mode: str
    operation_id: str
    resulting_license_id: str
    processed_timestamp: int
    operator: str
    result_status: str


@dataclass(frozen=True)
class TrustedSigningKeyRecord:
    registry_scope: str
    signing_algorithm: str
    key_id: str
    public_key_fingerprint: str
    private_key_reference_identifier: str
    allowed_issuance_modes: tuple[str, ...]
    allowed_product: str
    active_from: int
    retired_at: int | None
    status: str


@dataclass(frozen=True)
class PolicyRecord:
    policy_id: str
    revision: int
    digest: str
    product: str
    edition: str
    allowed_entitlements: tuple[str, ...]
    max_validity_seconds: int
    perpetual_allowed: bool
    min_app_version_floor: str
    max_app_version_ceiling: str | None
    allowed_identity_algorithms: tuple[str, ...]
    allowed_issuance_modes: tuple[str, ...]
    allowed_signing_profiles: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class IssuanceAuditRecord:
    event_id: str
    authorization_id: str
    authorization_revision: int
    request_schema: str
    request_id: str
    request_payload_digest: str
    operation_id: str
    license_id: str
    issuance_mode: str
    identity_algorithm: str
    masked_identity_value: str
    product: str
    customer_id: str
    edition: str
    entitlements: tuple[str, ...]
    issued_at: int
    expires_at: int
    signing_key_id: str
    policy_revision: str
    operator: str
    timestamp: int
    old_state: str
    new_state: str
    result_status: str
    output_artifact_digest: str | None


AUTHORIZATION_REQUIRED_FIELDS = frozenset(
    {
        "authorization_id",
        "revision",
        "request_schema",
        "request_id",
        "request_payload_digest",
        "customer_id",
        "customer_snapshot",
        "product",
        "edition",
        "entitlements",
        "validity_policy",
        "max_validity_seconds",
        "min_app_version",
        "max_app_version",
        "allowed_issuance_mode",
        "allowed_identity_algorithm",
        "signing_profile_id",
        "issued_at",
        "expires_at",
        "request_ownership_proof_reference",
        "policy_revision",
        "policy_digest",
        "approval_actor",
        "approval_timestamp",
        "approval_reason",
        "reissue_policy",
        "status",
        "revocation_reference",
    }
)
PROCESSED_REQUIRED_FIELDS = frozenset(
    {
        "request_schema",
        "request_id",
        "request_payload_digest",
        "authorization_id",
        "authorization_revision",
        "issuance_mode",
        "operation_id",
        "resulting_license_id",
        "processed_timestamp",
        "operator",
        "result_status",
    }
)
KEY_REQUIRED_FIELDS = frozenset(
    {
        "registry_scope",
        "signing_algorithm",
        "key_id",
        "public_key_fingerprint",
        "private_key_reference_identifier",
        "allowed_issuance_modes",
        "allowed_product",
        "active_from",
        "retired_at",
        "status",
    }
)
AUDIT_FORBIDDEN_FIELDS = frozenset(
    {
        "machine_guid",
        "volume_stdout",
        "hostname",
        "username",
        "machine_id",
        "identity_value",
        "request_token",
        "request_payload",
        "license_body",
        "signature",
        "private_key",
        "private_key_path",
        "private_key_reference_identifier",
        "email_body",
    }
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;

CREATE TABLE schema_meta (
    version INTEGER NOT NULL CHECK (version = 1)
);
INSERT INTO schema_meta(version) VALUES (1);

CREATE TABLE authorization_records (
    authorization_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    request_schema TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_snapshot TEXT NOT NULL,
    product TEXT NOT NULL,
    edition TEXT NOT NULL,
    entitlements_json TEXT NOT NULL,
    validity_policy TEXT NOT NULL,
    max_validity_seconds INTEGER NOT NULL CHECK (max_validity_seconds > 0),
    min_app_version TEXT NOT NULL,
    max_app_version TEXT,
    issuance_mode TEXT NOT NULL,
    identity_algorithm TEXT NOT NULL,
    signing_profile_id TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK (expires_at > issued_at),
    ownership_proof_reference TEXT NOT NULL,
    policy_revision TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    approval_actor TEXT NOT NULL,
    approval_timestamp INTEGER NOT NULL,
    approval_reason TEXT NOT NULL,
    reissue_policy TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'approved','reserved','consumed','rejected','expired',
            'revoked-before-use','superseded','abandoned'
        )
    ),
    reserved_operation_id TEXT,
    revocation_reference TEXT,
    PRIMARY KEY (authorization_id, revision)
);

CREATE TABLE processed_requests (
    request_schema TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    authorization_revision INTEGER NOT NULL,
    issuance_mode TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    resulting_license_id TEXT NOT NULL UNIQUE,
    processed_timestamp INTEGER NOT NULL,
    operator TEXT NOT NULL,
    result_status TEXT NOT NULL CHECK (
        result_status IN ('reserved','completed','quarantined','abandoned')
    ),
    PRIMARY KEY (request_schema, request_id),
    UNIQUE (request_id),
    FOREIGN KEY (authorization_id, authorization_revision)
        REFERENCES authorization_records(authorization_id, revision)
);

CREATE TABLE issuance_operations (
    operation_id TEXT PRIMARY KEY,
    request_schema TEXT NOT NULL,
    request_id TEXT NOT NULL,
    license_id TEXT NOT NULL UNIQUE,
    output_target TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('reserved','signing','signed','persisted','completed','failed','quarantined','abandoned')
    ),
    signer_entered INTEGER NOT NULL DEFAULT 0 CHECK (signer_entered IN (0,1)),
    artifact_digest TEXT,
    FOREIGN KEY (request_schema, request_id)
        REFERENCES processed_requests(request_schema, request_id)
);

CREATE TABLE trusted_signing_keys (
    registry_scope TEXT NOT NULL CHECK (registry_scope = 'admin-issuance'),
    signing_algorithm TEXT NOT NULL,
    key_id TEXT NOT NULL,
    public_key_fingerprint TEXT NOT NULL,
    private_key_reference_identifier TEXT NOT NULL,
    allowed_issuance_modes_json TEXT NOT NULL,
    allowed_product TEXT NOT NULL,
    active_from INTEGER NOT NULL,
    retired_at INTEGER,
    status TEXT NOT NULL CHECK (
        status IN ('draft','active','retired','disabled','compromised')
    ),
    CHECK (key_id = 'spki-sha256:' || public_key_fingerprint),
    PRIMARY KEY (signing_algorithm, key_id)
);

CREATE TABLE policy_registry (
    policy_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    digest TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','active','retired','disabled')),
    PRIMARY KEY (policy_id, revision),
    UNIQUE (digest)
);

CREATE TABLE issuance_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_json TEXT NOT NULL
);

CREATE TABLE license_lifecycle (
    license_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('issued','superseded','revoked-local','expired-recorded')
    ),
    output_target TEXT NOT NULL UNIQUE,
    artifact_digest TEXT,
    FOREIGN KEY (operation_id) REFERENCES issuance_operations(operation_id)
);

CREATE TRIGGER issuance_audit_no_update
BEFORE UPDATE ON issuance_audit
BEGIN
    SELECT RAISE(ABORT, 'issuance audit is append-only');
END;

CREATE TRIGGER issuance_audit_no_delete
BEFORE DELETE ON issuance_audit
BEGIN
    SELECT RAISE(ABORT, 'issuance audit is append-only');
END;

CREATE TRIGGER authorization_definition_immutable
BEFORE UPDATE OF
    authorization_id, revision, request_schema, request_id, request_digest,
    customer_id, customer_snapshot, product, edition, entitlements_json,
    validity_policy, max_validity_seconds, min_app_version, max_app_version,
    issuance_mode, identity_algorithm, signing_profile_id, issued_at,
    expires_at, ownership_proof_reference, policy_revision, policy_digest,
    approval_actor, approval_timestamp, approval_reason, reissue_policy
ON authorization_records
BEGIN
    SELECT RAISE(ABORT, 'authorization definition is immutable; create a new revision');
END;

CREATE TRIGGER issuance_operation_transition_guard
BEFORE UPDATE OF state, signer_entered ON issuance_operations
WHEN NOT (
    (OLD.state = 'reserved' AND NEW.state = 'signing'
        AND OLD.signer_entered = 0 AND NEW.signer_entered = 1)
    OR (OLD.state = 'signing' AND NEW.state = 'signed'
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
    OR (OLD.state = 'signed' AND NEW.state = 'persisted'
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
    OR (OLD.state = 'persisted' AND NEW.state = 'completed'
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
    OR (OLD.state IN ('signing','signed','persisted') AND NEW.state = 'quarantined'
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
    OR (OLD.state = 'reserved' AND NEW.state = 'failed'
        AND OLD.signer_entered = 0 AND NEW.signer_entered = 0)
    OR (OLD.state = 'failed' AND NEW.state = 'reserved'
        AND OLD.signer_entered = 0 AND NEW.signer_entered = 0)
    OR (OLD.state = 'failed' AND NEW.state = 'abandoned'
        AND OLD.signer_entered = 0 AND NEW.signer_entered = 0)
    OR (OLD.state = 'quarantined' AND NEW.state IN ('signed','persisted','completed')
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
    OR (OLD.state = 'quarantined' AND NEW.state = 'abandoned'
        AND OLD.signer_entered = 1 AND NEW.signer_entered = 1)
)
BEGIN
    SELECT RAISE(ABORT, 'invalid issuance operation transition');
END;

CREATE TRIGGER issuance_output_target_immutable
BEFORE UPDATE OF output_target ON issuance_operations
BEGIN
    SELECT RAISE(ABORT, 'canonical output target is immutable');
END;

CREATE TRIGGER license_lifecycle_transition_guard
BEFORE UPDATE OF state ON license_lifecycle
WHEN NOT (
    OLD.state = 'issued'
    AND NEW.state IN ('superseded','revoked-local','expired-recorded')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid license lifecycle transition');
END;

CREATE TRIGGER license_output_target_immutable
BEFORE UPDATE OF output_target ON license_lifecycle
BEGIN
    SELECT RAISE(ABORT, 'canonical output target is immutable');
END;
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_raises(expected: type[BaseException], action: Any, message: str) -> None:
    try:
        action()
    except expected:
        return
    raise AssertionError(message)


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def normalized_source_hash(text: str) -> str:
    # Path.read_text() already performs universal-newline normalization.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mask_identity(value: str) -> str:
    canonical = value.strip()
    if len(canonical) <= 8:
        return "*" * max(len(canonical), 1)
    return f"{canonical[:4]}...{canonical[-4:]}"


def require_lower_hex_digest(value: str, label: str) -> None:
    require(
        len(value) == 64 and all(character in "0123456789abcdef" for character in value),
        f"{label} must be a lowercase SHA-256 hex digest",
    )


def require_opaque_principal(value: str, label: str) -> None:
    require(
        value.startswith("principal:")
        and len(value) > len("principal:")
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789-_:." for character in value),
        f"{label} must be an opaque principal identifier",
    )


def canonical_output_target(license_id: str) -> str:
    require(
        bool(license_id)
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in license_id),
        "license ID is not safe for the canonical output namespace",
    )
    return f"{license_id}.lic"


def synthetic_authorization(
    *,
    suffix: str,
    payload: dict[str, Any] = SYNTHETIC_REQUEST,
    status: str = "approved",
) -> AuthorizationRecord:
    return AuthorizationRecord(
        authorization_id=f"synthetic-authorization-{suffix}",
        revision=1,
        request_schema=str(payload["schema"]),
        request_id=str(payload["request_id"]),
        request_payload_digest=request_digest(payload),
        customer_id="principal:synthetic-customer-001",
        customer_snapshot=(
            '{"display_name":"Synthetic Customer",'
            '"principal_id":"principal:synthetic-customer-001"}'
        ),
        product="launchflow",
        edition="beta",
        entitlements=("launch", "workflow-export"),
        validity_policy="bounded-duration",
        max_validity_seconds=7_776_000,
        min_app_version="0.1.0-beta.2",
        max_app_version=None,
        allowed_issuance_mode="versioned-lflic-2",
        allowed_identity_algorithm="legacy-v1",
        signing_profile_id="rsa-pkcs1v15-sha256|spki-sha256:" + "1" * 64,
        issued_at=1767225800,
        expires_at=1775001800,
        request_ownership_proof_reference="synthetic-proof-reference-001",
        policy_revision="synthetic-launchflow-policy:1",
        policy_digest=hashlib.sha256(b"synthetic-policy-1").hexdigest(),
        approval_actor="principal:synthetic-operator",
        approval_timestamp=1767225700,
        approval_reason="synthetic-readiness-review",
        reissue_policy="new-request-and-authorization",
        status=status,
        revocation_reference=None,
    )


def synthetic_key_record() -> TrustedSigningKeyRecord:
    return TrustedSigningKeyRecord(
        registry_scope="admin-issuance",
        signing_algorithm="rsa-pkcs1v15-sha256",
        key_id="spki-sha256:" + "1" * 64,
        public_key_fingerprint="1" * 64,
        private_key_reference_identifier="synthetic-secret-reference-001",
        allowed_issuance_modes=("versioned-lflic-2",),
        allowed_product="launchflow",
        active_from=1767225500,
        retired_at=None,
        status="active",
    )


def synthetic_policy() -> PolicyRecord:
    return PolicyRecord(
        policy_id="synthetic-launchflow-policy",
        revision=1,
        digest=hashlib.sha256(b"synthetic-policy-1").hexdigest(),
        product="launchflow",
        edition="beta",
        allowed_entitlements=("launch", "workflow-export"),
        max_validity_seconds=7_776_000,
        perpetual_allowed=False,
        min_app_version_floor="0.1.0-beta.2",
        max_app_version_ceiling=None,
        allowed_identity_algorithms=("legacy-v1",),
        allowed_issuance_modes=("versioned-lflic-2",),
        allowed_signing_profiles=(
            "rsa-pkcs1v15-sha256|spki-sha256:" + "1" * 64,
        ),
        status="active",
    )


def select_output_container(request_kind: str, mode: str | None) -> str:
    selected_mode = mode or "inspect-only"
    if selected_mode not in MODES:
        raise ReadinessError("unknown issuance mode")
    if selected_mode == "inspect-only":
        return "inspect-only"
    output = MODE_MATRIX.get((request_kind, selected_mode))
    if output is None:
        raise ReadinessError("request kind and explicit issuance mode are incompatible")
    return output


def select_trusted_key(
    registry: dict[tuple[str, str], TrustedSigningKeyRecord],
    signing_algorithm: str,
    key_id: str,
) -> TrustedSigningKeyRecord:
    record = registry.get((signing_algorithm, key_id))
    if record is None:
        raise ReadinessError("unknown signing algorithm/key pair")
    require_lower_hex_digest(record.public_key_fingerprint, "public key fingerprint")
    if record.registry_scope != "admin-issuance":
        raise ReadinessError("client release trust metadata is not an admin issuance registry")
    if record.key_id != "spki-sha256:" + record.public_key_fingerprint:
        raise ReadinessError("key ID must equal the SPKI-SHA256 fingerprint identifier")
    if record.status != "active" or record.retired_at is not None:
        raise ReadinessError("signing key is not active for issuance")
    return record


def select_policy(
    registry: dict[tuple[str, str], PolicyRecord],
    policy_revision: str,
    policy_digest: str,
) -> PolicyRecord:
    record = registry.get((policy_revision, policy_digest))
    if record is None:
        raise ReadinessError("unknown policy revision/digest pair")
    expected_revision = f"{record.policy_id}:{record.revision}"
    require_lower_hex_digest(record.digest, "policy digest")
    if expected_revision != policy_revision or record.digest != policy_digest or record.status != "active":
        raise ReadinessError("policy registry record is not active or exactly bound")
    return record


def signing_profile_identifier(record: TrustedSigningKeyRecord) -> str:
    return f"{record.signing_algorithm}|{record.key_id}"


def build_issuance_plan(
    request_kind: str,
    payload: dict[str, Any],
    authorization: AuthorizationRecord | None,
    policy_registry: dict[tuple[str, str], PolicyRecord] | None,
    key_registry: dict[tuple[str, str], TrustedSigningKeyRecord] | None,
    *,
    mode: str | None = None,
    signing_algorithm: str | None = None,
    key_id: str | None = None,
    state_available: bool = True,
    timestamp_approved: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    output_container = select_output_container(request_kind, mode)
    if output_container == "inspect-only":
        return {"status": "inspected", "state_writes": 0, "issuer_calls": 0}

    if mode is None:
        raise ReadinessError("issuance requires an explicit mode")
    if not state_available:
        raise ReadinessError("authoritative state unavailable")
    if not timestamp_approved:
        raise ReadinessError("request time review failed")
    if set(payload) != REQUEST_FIELDS or set(payload) & REQUEST_AUTHORITY_FIELDS:
        raise ReadinessError("request field boundary violated")
    if authorization is None or authorization.status != "approved":
        raise ReadinessError("approved authorization required")
    if policy_registry is None:
        raise ReadinessError("active policy registry required")
    if key_registry is None or signing_algorithm is None or key_id is None:
        raise ReadinessError("trusted signing registry and exact selector required")

    policy = select_policy(policy_registry, authorization.policy_revision, authorization.policy_digest)
    key_record = select_trusted_key(key_registry, signing_algorithm, key_id)

    digest = request_digest(payload)
    require_lower_hex_digest(authorization.request_payload_digest, "authorization request digest")
    require_lower_hex_digest(authorization.policy_digest, "authorization policy digest")
    require_opaque_principal(authorization.customer_id, "customer")
    require_opaque_principal(authorization.approval_actor, "approval actor")
    if (
        authorization.request_schema != payload["schema"]
        or authorization.request_id != payload["request_id"]
        or authorization.request_payload_digest != digest
    ):
        raise ReadinessError("authorization request binding mismatch")
    if authorization.allowed_issuance_mode != mode:
        raise ReadinessError("authorization mode mismatch")
    if authorization.allowed_identity_algorithm != payload["identity_algorithm"]:
        raise ReadinessError("authorization identity algorithm mismatch")
    if authorization.product != payload["product"] or policy.product != authorization.product:
        raise ReadinessError("product policy mismatch")
    if policy.edition != authorization.edition:
        raise ReadinessError("edition policy mismatch")
    if authorization.entitlements != tuple(sorted(set(authorization.entitlements))):
        raise ReadinessError("authorization entitlements are not sorted and unique")
    if not set(authorization.entitlements) <= set(policy.allowed_entitlements):
        raise ReadinessError("entitlement escalation")
    if authorization.max_validity_seconds > policy.max_validity_seconds:
        raise ReadinessError("validity exceeds policy")
    if authorization.allowed_identity_algorithm not in policy.allowed_identity_algorithms:
        raise ReadinessError("identity algorithm not allowed by policy")
    if mode not in policy.allowed_issuance_modes:
        raise ReadinessError("issuance mode not allowed by policy")
    if key_record.allowed_product != authorization.product or mode not in key_record.allowed_issuance_modes:
        raise ReadinessError("trusted key metadata policy mismatch")
    if signing_profile_identifier(key_record) not in policy.allowed_signing_profiles:
        raise ReadinessError("signing profile is not allowed by policy")
    if authorization.signing_profile_id != signing_profile_identifier(key_record):
        raise ReadinessError("authorization is not bound to the selected signing profile")
    if key_record.active_from > authorization.approval_timestamp:
        raise ReadinessError("signing key is not active at approval time")
    if authorization.expires_at - authorization.issued_at != authorization.max_validity_seconds:
        raise ReadinessError("authorization validity window is not deterministic")

    return {
        "status": "dry-run" if dry_run else "ready-to-reserve",
        "output_container": output_container,
        "authorization_id": authorization.authorization_id,
        "customer_id": authorization.customer_id,
        "customer_snapshot": authorization.customer_snapshot,
        "product": authorization.product,
        "edition": authorization.edition,
        "entitlements": authorization.entitlements,
        "issued_at": authorization.issued_at,
        "expires_at": authorization.expires_at,
        "min_app_version": authorization.min_app_version,
        "max_app_version": authorization.max_app_version,
        "identity_algorithm": payload["identity_algorithm"],
        "identity_value": payload["identity_value"],
        "key_id": key_record.key_id,
        "state_writes": 0,
        "issuer_calls": 0,
    }


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_URI,
        uri=True,
        isolation_level=None,
        check_same_thread=False,
        timeout=0.05,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    database_files = [row[2] for row in connection.execute("PRAGMA database_list")]
    require(database_files and all(value == "" for value in database_files), "SQLite escaped in-memory storage")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def insert_authorization(connection: sqlite3.Connection, record: AuthorizationRecord) -> None:
    require_lower_hex_digest(record.request_payload_digest, "authorization request digest")
    require_lower_hex_digest(record.policy_digest, "authorization policy digest")
    require_opaque_principal(record.customer_id, "customer")
    require_opaque_principal(record.approval_actor, "approval actor")
    require(
        record.expires_at - record.issued_at == record.max_validity_seconds,
        "authorization validity window must be exact",
    )
    connection.execute(
        """
        INSERT INTO authorization_records (
            authorization_id, revision, request_schema, request_id,
            request_digest, customer_id, customer_snapshot, product, edition, entitlements_json,
            validity_policy, max_validity_seconds, min_app_version,
            max_app_version, issuance_mode, identity_algorithm,
            signing_profile_id, issued_at, expires_at, ownership_proof_reference,
            policy_revision, policy_digest,
            approval_actor, approval_timestamp, approval_reason, reissue_policy, status,
            reserved_operation_id, revocation_reference
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record.authorization_id,
            record.revision,
            record.request_schema,
            record.request_id,
            record.request_payload_digest,
            record.customer_id,
            record.customer_snapshot,
            record.product,
            record.edition,
            json.dumps(record.entitlements, separators=(",", ":")),
            record.validity_policy,
            record.max_validity_seconds,
            record.min_app_version,
            record.max_app_version,
            record.allowed_issuance_mode,
            record.allowed_identity_algorithm,
            record.signing_profile_id,
            record.issued_at,
            record.expires_at,
            record.request_ownership_proof_reference,
            record.policy_revision,
            record.policy_digest,
            record.approval_actor,
            record.approval_timestamp,
            record.approval_reason,
            record.reissue_policy,
            record.status,
            None,
            record.revocation_reference,
        ),
    )


def load_authorization(
    connection: sqlite3.Connection,
    authorization_id: str,
    revision: int,
) -> AuthorizationRecord | None:
    row = connection.execute(
        """
        SELECT authorization_id, revision, request_schema, request_id,
               request_digest, customer_id, customer_snapshot, product, edition, entitlements_json,
               validity_policy, max_validity_seconds, min_app_version,
               max_app_version, issuance_mode, identity_algorithm,
               signing_profile_id, issued_at, expires_at, ownership_proof_reference,
               policy_revision, policy_digest,
               approval_actor, approval_timestamp, approval_reason,
               reissue_policy, status, revocation_reference
        FROM authorization_records
        WHERE authorization_id = ? AND revision = ?
        """,
        (authorization_id, revision),
    ).fetchone()
    if row is None:
        return None
    values = list(row)
    values[9] = tuple(json.loads(values[9]))
    return AuthorizationRecord(*values)


def authorization_definition_matches(stored: AuthorizationRecord, supplied: AuthorizationRecord) -> bool:
    stored_values = asdict(stored)
    supplied_values = asdict(supplied)
    stored_values.pop("status")
    supplied_values.pop("status")
    return stored_values == supplied_values


def insert_trusted_key(connection: sqlite3.Connection, record: TrustedSigningKeyRecord) -> None:
    require(record.registry_scope == "admin-issuance", "admin signing registry scope changed")
    require_lower_hex_digest(record.public_key_fingerprint, "public key fingerprint")
    require(
        bool(record.private_key_reference_identifier)
        and all(
            marker not in record.private_key_reference_identifier
            for marker in ("/", "\\", "://", "%", "${")
        ),
        "private key reference must be opaque metadata, not a dynamic location",
    )
    require(
        record.key_id == "spki-sha256:" + record.public_key_fingerprint,
        "key ID must equal SPKI-SHA256 fingerprint identifier",
    )
    connection.execute(
        """
        INSERT INTO trusted_signing_keys (
            registry_scope, signing_algorithm, key_id, public_key_fingerprint,
            private_key_reference_identifier, allowed_issuance_modes_json,
            allowed_product, active_from, retired_at, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record.registry_scope,
            record.signing_algorithm,
            record.key_id,
            record.public_key_fingerprint,
            record.private_key_reference_identifier,
            json.dumps(record.allowed_issuance_modes, separators=(",", ":")),
            record.allowed_product,
            record.active_from,
            record.retired_at,
            record.status,
        ),
    )


def load_trusted_key(
    connection: sqlite3.Connection,
    signing_algorithm: str,
    key_id: str,
) -> TrustedSigningKeyRecord | None:
    row = connection.execute(
        """
        SELECT registry_scope, signing_algorithm, key_id, public_key_fingerprint,
               private_key_reference_identifier, allowed_issuance_modes_json,
               allowed_product, active_from, retired_at, status
        FROM trusted_signing_keys
        WHERE signing_algorithm = ? AND key_id = ?
        """,
        (signing_algorithm, key_id),
    ).fetchone()
    if row is None:
        return None
    values = list(row)
    values[5] = tuple(json.loads(values[5]))
    return TrustedSigningKeyRecord(*values)


def insert_policy(connection: sqlite3.Connection, record: PolicyRecord) -> None:
    require_lower_hex_digest(record.digest, "policy digest")
    connection.execute(
        """
        INSERT INTO policy_registry(policy_id, revision, digest, policy_json, status)
        VALUES (?,?,?,?,?)
        """,
        (
            record.policy_id,
            record.revision,
            record.digest,
            json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            record.status,
        ),
    )


def load_policy(connection: sqlite3.Connection, policy_id: str, revision: int) -> PolicyRecord | None:
    row = connection.execute(
        "SELECT policy_json FROM policy_registry WHERE policy_id = ? AND revision = ?",
        (policy_id, revision),
    ).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    for name in (
        "allowed_entitlements",
        "allowed_identity_algorithms",
        "allowed_issuance_modes",
        "allowed_signing_profiles",
    ):
        value[name] = tuple(value[name])
    return PolicyRecord(**value)


def load_processed_request(
    connection: sqlite3.Connection,
    request_schema: str,
    request_id: str,
) -> ProcessedRequestRecord | None:
    row = connection.execute(
        """
        SELECT request_schema, request_id, request_digest, authorization_id,
               authorization_revision, issuance_mode, operation_id,
               resulting_license_id, processed_timestamp, operator, result_status
        FROM processed_requests
        WHERE request_schema = ? AND request_id = ?
        """,
        (request_schema, request_id),
    ).fetchone()
    return None if row is None else ProcessedRequestRecord(*row)


def unique_index_columns(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    allowed = {
        "processed_requests",
        "issuance_operations",
        "license_lifecycle",
        "trusted_signing_keys",
        "policy_registry",
    }
    require(table in allowed, "unbounded unique-index inspection")
    result: set[tuple[str, ...]] = set()
    for row in connection.execute(f"PRAGMA index_list({table})"):
        if not row[2]:
            continue
        index_name = str(row[1])
        columns = tuple(str(item[2]) for item in connection.execute(f"PRAGMA index_info({index_name})"))
        result.add(columns)
    return result


def append_audit(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    authorization: AuthorizationRecord,
    payload: dict[str, Any],
    operation_id: str,
    license_id: str,
    result_status: str,
    old_state: str,
    new_state: str,
    output_artifact_digest: str | None = None,
    idempotent: bool = False,
) -> None:
    if output_artifact_digest is not None:
        require_lower_hex_digest(output_artifact_digest, "audit artifact digest")
    if new_state in {"signed", "persisted", "completed"}:
        require(output_artifact_digest is not None, f"{new_state} audit requires an artifact digest")
    if new_state in {"approved", "reserved", "failed", "signing"}:
        require(output_artifact_digest is None, f"{new_state} audit forbids an artifact digest")
    require_opaque_principal(authorization.customer_id, "audit customer")
    require_opaque_principal(authorization.approval_actor, "audit operator")
    _algorithm, separator, signing_key_id = authorization.signing_profile_id.partition("|")
    require(bool(separator) and bool(signing_key_id), "authorization signing profile is malformed")
    record = IssuanceAuditRecord(
        event_id=event_id,
        authorization_id=authorization.authorization_id,
        authorization_revision=authorization.revision,
        request_schema=str(payload["schema"]),
        request_id=str(payload["request_id"]),
        request_payload_digest=request_digest(payload),
        operation_id=operation_id,
        license_id=license_id,
        issuance_mode=authorization.allowed_issuance_mode,
        identity_algorithm=str(payload["identity_algorithm"]),
        masked_identity_value=mask_identity(str(payload["identity_value"])),
        product=authorization.product,
        customer_id=authorization.customer_id,
        edition=authorization.edition,
        entitlements=authorization.entitlements,
        issued_at=authorization.issued_at,
        expires_at=authorization.expires_at,
        signing_key_id=signing_key_id,
        policy_revision=authorization.policy_revision,
        operator=authorization.approval_actor,
        timestamp=1767225800,
        old_state=old_state,
        new_state=new_state,
        result_status=result_status,
        output_artifact_digest=output_artifact_digest,
    )
    statement = (
        "INSERT OR IGNORE INTO issuance_audit(event_id, event_json) VALUES (?,?)"
        if idempotent
        else "INSERT INTO issuance_audit(event_id, event_json) VALUES (?,?)"
    )
    connection.execute(
        statement,
        (event_id, json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
    )


def claim_request(
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    *,
    operation_id: str,
    license_id: str,
    inject_failure: bool = False,
) -> str:
    digest = request_digest(payload)
    last_locked_error: sqlite3.OperationalError | None = None
    for _attempt in range(40):
        connection = connect_database()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stored_authorization = load_authorization(
                connection,
                authorization.authorization_id,
                authorization.revision,
            )
            if stored_authorization is None or not authorization_definition_matches(stored_authorization, authorization):
                raise ReadinessError("supplied authorization does not match authoritative storage")
            existing = connection.execute(
                """
                SELECT request_schema, request_digest, authorization_id,
                       authorization_revision, operation_id, resulting_license_id
                FROM processed_requests WHERE request_id = ?
                """,
                (payload["request_id"],),
            ).fetchone()
            if existing is not None:
                if existing[2:4] != (stored_authorization.authorization_id, stored_authorization.revision):
                    raise ReadinessError("existing request belongs to another authorization")
                result = "duplicate" if existing[:2] == (payload["schema"], digest) else "conflict"
                append_audit(
                    connection,
                    event_id=f"{existing[4]}-replay-{result}",
                    authorization=stored_authorization,
                    payload=payload,
                    operation_id=str(existing[4]),
                    license_id=str(existing[5]),
                    result_status=result,
                    old_state="reserved",
                    new_state="reserved",
                    idempotent=True,
                )
                connection.commit()
                return result

            expected = (
                payload["schema"],
                payload["request_id"],
                digest,
                stored_authorization.allowed_issuance_mode,
                payload["identity_algorithm"],
                "approved",
            )
            actual = (
                stored_authorization.request_schema,
                stored_authorization.request_id,
                stored_authorization.request_payload_digest,
                stored_authorization.allowed_issuance_mode,
                stored_authorization.allowed_identity_algorithm,
                stored_authorization.status,
            )
            if actual != expected:
                raise ReadinessError("authorization missing, unapproved, consumed, or request-bound elsewhere")

            updated = connection.execute(
                """
                UPDATE authorization_records
                SET status = 'reserved', reserved_operation_id = ?
                WHERE authorization_id = ? AND revision = ? AND status = 'approved'
                """,
                (operation_id, stored_authorization.authorization_id, stored_authorization.revision),
            )
            if updated.rowcount != 1:
                raise ReadinessError("authorization reservation lost")

            connection.execute(
                """
                INSERT INTO processed_requests (
                    request_schema, request_id, request_digest,
                    authorization_id, authorization_revision, issuance_mode,
                    operation_id, resulting_license_id, processed_timestamp,
                    operator, result_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["schema"],
                    payload["request_id"],
                    digest,
                    stored_authorization.authorization_id,
                    stored_authorization.revision,
                    stored_authorization.allowed_issuance_mode,
                    operation_id,
                    license_id,
                    1767225800,
                    stored_authorization.approval_actor,
                    "reserved",
                ),
            )
            connection.execute(
                """
                INSERT INTO issuance_operations (
                    operation_id, request_schema, request_id, license_id, output_target,
                    state, signer_entered, artifact_digest
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    operation_id,
                    payload["schema"],
                    payload["request_id"],
                    license_id,
                    canonical_output_target(license_id),
                    "reserved",
                    0,
                    None,
                ),
            )
            append_audit(
                connection,
                event_id=f"{operation_id}-reserved",
                authorization=stored_authorization,
                payload=payload,
                operation_id=operation_id,
                license_id=license_id,
                result_status="reserved",
                old_state="approved",
                new_state="reserved",
            )
            if inject_failure:
                raise SyntheticFailure("synthetic rollback before commit")
            connection.commit()
            return "success"
        except sqlite3.OperationalError as exc:
            if connection.in_transaction:
                connection.rollback()
            if "locked" not in str(exc).lower():
                raise
            last_locked_error = exc
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        time.sleep(0.005)
    raise AssertionError("bounded SQLite claim retry exhausted") from last_locked_error


def load_transition_context(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> tuple[AuthorizationRecord, tuple[Any, ...]]:
    stored = load_authorization(connection, authorization.authorization_id, authorization.revision)
    if stored is None or not authorization_definition_matches(stored, authorization):
        raise ReadinessError("transition authorization does not match authoritative storage")
    row = connection.execute(
        """
        SELECT operation.request_schema, operation.request_id, operation.license_id,
               operation.output_target, operation.state, operation.signer_entered,
               operation.artifact_digest,
               processed.request_digest, processed.authorization_id,
               processed.authorization_revision, processed.result_status
        FROM issuance_operations AS operation
        JOIN processed_requests AS processed
          ON processed.request_schema = operation.request_schema
         AND processed.request_id = operation.request_id
        WHERE operation.operation_id = ?
        """,
        (operation_id,),
    ).fetchone()
    if row is None:
        raise ReadinessError("issuance operation or license lifecycle is missing")
    expected = (
        payload["schema"],
        payload["request_id"],
        request_digest(payload),
        stored.authorization_id,
        stored.revision,
    )
    actual = (row[0], row[1], row[7], row[8], row[9])
    if actual != expected:
        raise ReadinessError("transition request or authorization binding mismatch")
    return stored, row


def mark_pre_sign_failure(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:7] != ("reserved", 0, None) or row[10] != "reserved":
            raise ReadinessError("only a reserved pre-signer operation may become retryable failed")
        updated = connection.execute(
            "UPDATE issuance_operations SET state = 'failed' WHERE operation_id = ?",
            (operation_id,),
        )
        require(updated.rowcount == 1, "pre-sign operation transition was lost")
        require(stored.status == "reserved", "pre-sign failure released authorization claim")
        append_audit(
            connection,
            event_id=f"{operation_id}-pre-sign-failed",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="failed",
            old_state="reserved",
            new_state="failed",
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def retry_same_pre_sign_operation(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:7] != ("failed", 0, None) or row[10] != "reserved":
            raise ReadinessError("pre-sign retry must reuse the same unentered operation")
        if stored.status != "reserved":
            raise ReadinessError("pre-sign retry must retain the original authorization claim")
        connection.execute(
            "UPDATE issuance_operations SET state = 'reserved' WHERE operation_id = ?",
            (operation_id,),
        )
        append_audit(
            connection,
            event_id=f"{operation_id}-retry-reserved",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="reserved",
            old_state="failed",
            new_state="reserved",
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def enter_signing(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:7] != ("reserved", 0, None) or row[10] != "reserved":
            raise ReadinessError("only a reserved operation may enter the signer")
        connection.execute(
            "UPDATE issuance_operations SET state = 'signing', signer_entered = 1 WHERE operation_id = ?",
            (operation_id,),
        )
        append_audit(
            connection,
            event_id=f"{operation_id}-signing",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="signing",
            old_state="reserved",
            new_state="signing",
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def mark_signed(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
    artifact_digest: str,
) -> None:
    require_lower_hex_digest(artifact_digest, "signed artifact digest")
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:7] != ("signing", 1, None) or row[10] != "reserved":
            raise ReadinessError("signed transition requires signer entry")
        connection.execute(
            "UPDATE issuance_operations SET state = 'signed', artifact_digest = ? WHERE operation_id = ?",
            (artifact_digest, operation_id),
        )
        append_audit(
            connection,
            event_id=f"{operation_id}-signed",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="signed",
            old_state="signing",
            new_state="signed",
            output_artifact_digest=artifact_digest,
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def mark_persisted(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:6] != ("signed", 1) or row[6] is None or row[10] != "reserved":
            raise ReadinessError("persisted transition requires a signed license")
        artifact_digest = str(row[6])
        require_lower_hex_digest(artifact_digest, "persisted artifact digest")
        connection.execute(
            "UPDATE issuance_operations SET state = 'persisted' WHERE operation_id = ?",
            (operation_id,),
        )
        append_audit(
            connection,
            event_id=f"{operation_id}-persisted",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="persisted",
            old_state="signed",
            new_state="persisted",
            output_artifact_digest=artifact_digest,
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def mark_completed(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4:6] != ("persisted", 1) or row[6] is None or row[10] != "reserved":
            raise ReadinessError("completion requires a persisted license")
        artifact_digest = str(row[6])
        require_lower_hex_digest(artifact_digest, "completed artifact digest")
        connection.execute(
            "UPDATE issuance_operations SET state = 'completed' WHERE operation_id = ?",
            (operation_id,),
        )
        connection.execute(
            """
            INSERT INTO license_lifecycle (
                license_id, operation_id, state, output_target, artifact_digest
            ) VALUES (?,?,?,?,?)
            """,
            (str(row[2]), operation_id, "issued", str(row[3]), artifact_digest),
        )
        connection.execute(
            "UPDATE processed_requests SET result_status = 'completed' WHERE operation_id = ?",
            (operation_id,),
        )
        consumed = connection.execute(
            """
            UPDATE authorization_records
            SET status = 'consumed'
            WHERE authorization_id = ? AND revision = ?
              AND status = 'reserved' AND reserved_operation_id = ?
            """,
            (stored.authorization_id, stored.revision, operation_id),
        )
        require(consumed.rowcount == 1, "completion did not consume authorization")
        append_audit(
            connection,
            event_id=f"{operation_id}-completed",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="completed",
            old_state="persisted",
            new_state="completed",
            output_artifact_digest=artifact_digest,
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def mark_quarantined(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    authorization: AuthorizationRecord,
    operation_id: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        stored, row = load_transition_context(connection, payload, authorization, operation_id)
        if row[4] not in {"signing", "signed", "persisted"} or row[5] != 1:
            raise ReadinessError("only a signer-entered active operation may be quarantined")
        artifact_digest = None if row[6] is None else str(row[6])
        if row[4] in {"signed", "persisted"}:
            require(artifact_digest is not None, "post-sign quarantine requires artifact digest")
        if artifact_digest is not None:
            require_lower_hex_digest(artifact_digest, "quarantined artifact digest")
        connection.execute(
            "UPDATE issuance_operations SET state = 'quarantined' WHERE operation_id = ?",
            (operation_id,),
        )
        connection.execute(
            "UPDATE processed_requests SET result_status = 'quarantined' WHERE operation_id = ?",
            (operation_id,),
        )
        require(stored.status == "reserved", "quarantine released authorization claim")
        append_audit(
            connection,
            event_id=f"{operation_id}-quarantined",
            authorization=stored,
            payload=payload,
            operation_id=operation_id,
            license_id=str(row[2]),
            result_status="quarantined",
            old_state=str(row[4]),
            new_state="quarantined",
            output_artifact_digest=artifact_digest,
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def table_count(connection: sqlite3.Connection, table: str) -> int:
    allowed = {
        "authorization_records",
        "processed_requests",
        "issuance_operations",
        "license_lifecycle",
        "trusted_signing_keys",
        "policy_registry",
        "issuance_audit",
    }
    require(table in allowed, "unbounded table count")
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _read_source(path: Path) -> tuple[str, ast.Module]:
    require(path.is_file(), f"required source missing: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text, filename=str(path))


def _read_document(path: Path) -> str:
    require(path.is_file(), f"required document missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"expected one function {name}")
    return matches[0]


def _call_lines(function: ast.FunctionDef, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == name:
            lines.append(node.lineno)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
            lines.append(node.lineno)
    return sorted(lines)


def _called_literal_first_args(tree: ast.AST, method_name: str) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            values.add(node.args[0].value)
    return values


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    matches: list[Any] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                matches.append(ast.literal_eval(node.value))
    require(len(matches) == 1, f"expected one literal assignment {name}")
    return matches[0]


def check_smoke_source_safety() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(Path(__file__)))
    allowed_imports = {
        "__future__",
        "ast",
        "dataclasses",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "sqlite3",
        "sys",
        "threading",
        "time",
        "typing",
    }
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= allowed_imports, "readiness smoke gained a production, key, network, or third-party import")

    forbidden_names = {"__import__", "compile", "eval", "exec", "open"}
    forbidden_methods = {
        "open",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "replace",
        "rename",
        "home",
        "glob",
        "rglob",
        "chdir",
        "putenv",
        "load_extension",
        "load_pem_private_key",
        "load_pem_public_key",
        "private_bytes",
        "public_bytes",
        "generate_private_key",
    }
    forbidden_call_names = {
        "sign",
        "sign_payload",
        "verify",
        "verify_signature",
        "verify_signature_with_key",
        "load_private_key",
    }
    connect_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            require(node.func.id not in forbidden_names, f"forbidden dynamic/file call: {node.func.id}")
            require(node.func.id not in forbidden_call_names, f"forbidden signing/key call: {node.func.id}")
        elif isinstance(node.func, ast.Attribute):
            require(node.func.attr not in forbidden_methods, f"forbidden file/key/environment method: {node.func.attr}")
            require(node.func.attr not in forbidden_call_names, f"forbidden signing/key method: {node.func.attr}")
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "sqlite3" and node.func.attr == "connect":
                connect_calls += 1
                require(len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "DB_URI", "SQLite URI is not fixed")
                keyword_values = {item.arg: item.value for item in node.keywords if item.arg}
                require(
                    isinstance(keyword_values.get("uri"), ast.Constant)
                    and keyword_values["uri"].value is True,
                    "SQLite connection must use URI mode",
                )
    require(connect_calls == 1, "readiness smoke SQLite connection boundary changed")

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            require(node.id not in forbidden_names, f"forbidden dynamic/file primitive referenced: {node.id}")

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
        require(isinstance(parent, ast.Call) and parent.func is node, "readiness smoke aliases a text reader")
        read_text_receivers.append(ast.unparse(node.value))
    require(
        sorted(read_text_receivers) == ["Path(__file__)", "path", "path"],
        "readiness smoke text-read allowlist changed",
    )

    schema_lower = SCHEMA_SQL.lower()
    require("attach " + "database" not in schema_lower, "SQLite may attach another database")
    require("vacuum " + "into" not in schema_lower, "SQLite may write a vacuum output")

    for path in (*SOURCE_PATHS.values(), *DOCUMENT_PATHS):
        relative = path.relative_to(ROOT).as_posix().lower()
        require("crypto" not in relative and not relative.endswith(".pem"), "source/document allowlist contains key material")

    build_plan = _function(tree, "build_issuance_plan")
    parameter_names = {
        argument.arg
        for argument in (*build_plan.args.posonlyargs, *build_plan.args.args, *build_plan.args.kwonlyargs)
    }
    require(not parameter_names & {"issuer", "signer", "verifier", "confirmation"}, "readiness plan gained a signer/confirmation input")


def check_current_admin_contracts() -> None:
    loaded: dict[str, tuple[str, ast.Module]] = {}
    for name, path in SOURCE_PATHS.items():
        text, tree = _read_source(path)
        require(normalized_source_hash(text) == EXPECTED_SOURCE_SHA256[name], f"protected source changed: {name}")
        loaded[name] = (text, tree)

    admin_text, admin_tree = loaded["admin_cli"]
    core_text, core_tree = loaded["admin_core"]
    request_text, request_tree = loaded["request"]
    schema_text, schema_tree = loaded["license_schema"]
    manager_text, manager_tree = loaded["license_manager"]
    versioned_smoke_text, _versioned_smoke_tree = loaded["versioned_smoke"]

    require(_literal_assignment(request_tree, "REQUEST_PREFIX") == "LFREQ1", "LFREQ1 prefix changed")
    require(_literal_assignment(request_tree, "REQUEST_SCHEMA") == "lfreq-1", "lfreq-1 schema changed")
    require(_literal_assignment(schema_tree, "LICENSE_SCHEMA") == "lflic-1", "lflic-1 schema changed")
    require("return _parse_legacy_token(normalized_token)" in request_text, "legacy request fallback changed")
    require("--issuance-mode" not in admin_text and "--dry-run" not in admin_text, "production admin unexpectedly implemented Phase 1m")
    admin_commands = _called_literal_first_args(admin_tree, "add_parser")
    require(
        {"inspect", "issue", "issue-dev", "verify", "history"} <= admin_commands,
        "current admin command surface changed",
    )
    admin_main = _function(admin_tree, "main")
    inspect_comparisons = [
        node
        for node in ast.walk(admin_main)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and isinstance(node.left.value, ast.Name)
        and node.left.value.id == "args"
        and node.left.attr == "command"
        and any(
            isinstance(comparator, ast.Constant) and comparator.value == "inspect"
            for comparator in node.comparators
        )
    ]
    require(len(inspect_comparisons) == 1 and len(_call_lines(admin_main, "_print_request")) == 1, "current inspect path changed")

    issue_function = _function(core_tree, "issue_license")
    order = []
    for name in ("request_was_issued", "sign_payload", "validate_new_license_shape", "write_json", "append_history"):
        lines = _call_lines(issue_function, name)
        require(len(lines) == 1, f"current issue call count changed: {name}")
        order.append(lines[0])
    require(order == sorted(order), "current legacy issue chain changed")
    require("force" in {argument.arg for argument in issue_function.args.args + issue_function.args.kwonlyargs}, "legacy force seam changed")
    require("history_file.open(\"a\"" in core_text, "current JSONL append behavior changed")
    require("request_was_issued" in core_text and "sign_payload" in core_text, "current replay/sign symbols changed")

    imports = {
        node.module
        for node in ast.walk(core_tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    require("tools.license_generator" in imports and "licensing.crypto" in imports, "current admin dependency boundary changed")

    validate_method = _function(manager_tree, "validate_license_data")
    verify_lines = _call_lines(validate_method, "verify_signature")
    identity_lines = _call_lines(validate_method, "get_machine_id")
    require(len(verify_lines) == len(identity_lines) == 1 and verify_lines[0] < identity_lines[0], "legacy signature-before-identity changed")
    require("LFREQ2" not in request_text and "LFLIC2" not in schema_text + manager_text, "new container appeared in production")
    require("versioned container design smoke ok" in versioned_smoke_text, "Phase 1l design gate changed")


def check_document_contracts() -> None:
    documents = {path: _read_document(path) for path in DOCUMENT_PATHS}
    readiness = " ".join(documents[READINESS_PATH].split())
    required_markers = (
        "Phase 1m readiness complete; implementation not started",
        "Verified current administrator call chain",
        "Signing currently precedes full shape and output preflight",
        "inspect-only",
        "legacy-lflic-1",
        "versioned-lflic-2",
        "never inferred from request prefix",
        "`AuthorizationRecord` is the sole authority",
        "request_payload_digest",
        "request_ownership_proof_ref",
        "ProcessedRequestRecord",
        "Same ID/schema and same digest",
        "different schema or digest is an audited conflict",
        "Inspect-only and dry-run do not create or consume",
        "BEGIN IMMEDIATE",
        "Exactly one concurrent claimant",
        "`sqlite3` as the single authoritative",
        "JSONL may be a redacted, regenerated audit export",
        "TrustedSigningKeyRecord",
        "private-key reference identifier",
        "exact `(signing_algorithm, key_id)` pair",
        "The registry contains no private-key body",
        "PolicyRegistry",
        "unknown product, edition, entitlement",
        "IssuanceAuditRecord",
        "complete machine/identity value",
        "first four and last four",
        "Atomic issuance state machine",
        "signing",
        "signed",
        "persisted",
        "completed",
        "failed",
        "quarantined",
        "SQLite and the filesystem cannot share one real transaction",
        "never silently re-sign",
        "new request, new approved AuthorizationRecord",
        "Phase 1n",
        "Phase 1o",
        "Phase 1p",
        "Phase 1q",
        "No administrator infrastructure, replay protection, trusted registry, signing",
    )
    for marker in required_markers:
        require(marker.lower() in readiness.lower(), f"readiness document marker missing: {marker}")

    versioned = " ".join(documents[VERSIONED_DESIGN_PATH].split())
    for marker in (
        "LFREQ2` is unauthenticated",
        "The admin defaults to inspect-only",
        "The issuance mode is explicit",
        "Request replay requires administrator-side persistent state",
        "unknown signing algorithm or key ID fails closed before identity collection",
    ):
        require(marker.lower() in versioned.lower(), f"Phase 1l boundary changed: {marker}")

    cross_reference_docs = (
        ARCHITECTURE_PATH,
        AUDIT_PATH,
        ROADMAP_PATH,
        MATRIX_PATH,
        CHANGELOG_PATH,
    )
    for path in cross_reference_docs:
        text = documents[path]
        require("Phase 1m" in text and "admin-issuance-security-readiness.md" in text, f"Phase 1m cross-reference missing: {path.name}")


def check_record_and_policy_contracts() -> None:
    require({field.name for field in fields(AuthorizationRecord)} == AUTHORIZATION_REQUIRED_FIELDS, "AuthorizationRecord fields changed")
    require({field.name for field in fields(ProcessedRequestRecord)} == PROCESSED_REQUIRED_FIELDS, "ProcessedRequestRecord fields changed")
    require({field.name for field in fields(TrustedSigningKeyRecord)} == KEY_REQUIRED_FIELDS, "TrustedSigningKeyRecord fields changed")
    require(not ({field.name for field in fields(IssuanceAuditRecord)} & AUDIT_FORBIDDEN_FIELDS), "audit record contains forbidden raw material")
    require(not (set(SYNTHETIC_REQUEST) & REQUEST_AUTHORITY_FIELDS), "request fixture gained authorization fields")
    require(set(SYNTHETIC_REQUEST) == REQUEST_FIELDS, "synthetic request fields changed")

    authorization = synthetic_authorization(suffix="plan")
    key_record = synthetic_key_record()
    policy = synthetic_policy()
    key_registry = {(key_record.signing_algorithm, key_record.key_id): key_record}
    policy_registry = {(authorization.policy_revision, authorization.policy_digest): policy}
    require(key_record.registry_scope == "admin-issuance", "admin key metadata scope changed")
    require(
        key_record.key_id == "spki-sha256:" + key_record.public_key_fingerprint,
        "key ID and SPKI-SHA256 fingerprint diverged",
    )
    require_opaque_principal(authorization.customer_id, "customer")
    require_opaque_principal(authorization.approval_actor, "approval actor")
    require(
        authorization.expires_at - authorization.issued_at == authorization.max_validity_seconds,
        "approved validity window is not deterministic",
    )
    require(
        canonical_output_target("synthetic-license-plan") == "synthetic-license-plan.lic",
        "canonical output target contract changed",
    )
    require_raises(
        AssertionError,
        lambda: canonical_output_target("../synthetic-license-plan"),
        "unsafe output target identifier was accepted",
    )
    require(select_trusted_key(key_registry, key_record.signing_algorithm, key_record.key_id) is key_record, "exact key lookup failed")
    require_raises(
        ReadinessError,
        lambda: select_trusted_key(key_registry, "unknown-algorithm", key_record.key_id),
        "unknown algorithm did not fail closed",
    )
    require_raises(
        ReadinessError,
        lambda: select_trusted_key(key_registry, key_record.signing_algorithm, "unknown-key"),
        "unknown key did not fail closed",
    )
    reference = key_record.private_key_reference_identifier
    require(all(marker not in reference for marker in ("/", "\\", "://", "%", "${")), "synthetic key reference resembles a dynamic location")

    inspect = build_issuance_plan("LFREQ2", SYNTHETIC_REQUEST, None, None, None)
    require(inspect == {"status": "inspected", "state_writes": 0, "issuer_calls": 0}, "default mode is not inspect-only")
    require(select_output_container("LFREQ2", None) == "inspect-only", "request prefix selected issuance mode")
    require(select_output_container("LFREQ1", "legacy-lflic-1") == "lflic-1", "explicit legacy matrix changed")
    require(select_output_container("LFREQ2", "versioned-lflic-2") == "LFLIC2", "explicit versioned matrix changed")
    require_raises(ReadinessError, lambda: select_output_container("LFREQ2", "legacy-lflic-1"), "cross-generation downgrade accepted")
    require_raises(ReadinessError, lambda: select_output_container("LFREQ1", "versioned-lflic-2"), "cross-generation upgrade accepted")
    require_raises(ReadinessError, lambda: select_output_container("LFREQ2", "unknown-mode"), "unknown mode accepted")

    plan = build_issuance_plan(
        "LFREQ2",
        SYNTHETIC_REQUEST,
        authorization,
        policy_registry,
        key_registry,
        mode="versioned-lflic-2",
        signing_algorithm=key_record.signing_algorithm,
        key_id=key_record.key_id,
        dry_run=True,
    )
    require(plan["status"] == "dry-run" and plan["state_writes"] == plan["issuer_calls"] == 0, "dry-run gained side effects")
    require(plan["customer_id"] == authorization.customer_id, "customer did not come from authorization")
    require(plan["customer_snapshot"] == authorization.customer_snapshot, "customer snapshot was not exact")
    require(plan["edition"] == authorization.edition, "edition did not come from authorization")
    require(plan["entitlements"] == authorization.entitlements, "entitlements did not come from authorization")
    require(
        (plan["issued_at"], plan["expires_at"]) == (authorization.issued_at, authorization.expires_at),
        "issued/expires values were recomputed outside authorization",
    )
    require(plan["identity_value"] == SYNTHETIC_REQUEST["identity_value"], "identity proposal was recomputed")
    require_raises(
        ReadinessError,
        lambda: build_issuance_plan(
            "LFREQ2",
            SYNTHETIC_REQUEST,
            authorization,
            policy_registry,
            key_registry,
            mode="versioned-lflic-2",
            signing_algorithm=key_record.signing_algorithm,
            key_id=key_record.key_id,
            state_available=False,
        ),
        "unavailable state did not fail closed",
    )
    require_raises(
        ReadinessError,
        lambda: build_issuance_plan(
            "LFREQ2",
            SYNTHETIC_REQUEST,
            authorization,
            policy_registry,
            key_registry,
            mode="versioned-lflic-2",
            signing_algorithm=key_record.signing_algorithm,
            key_id=key_record.key_id,
            timestamp_approved=False,
        ),
        "unreviewed timestamp did not fail closed",
    )

    bad_entitlements = AuthorizationRecord(
        **{**asdict(authorization), "entitlements": ("launch", "unknown-entitlement")}
    )
    require_raises(
        ReadinessError,
        lambda: build_issuance_plan(
            "LFREQ2",
            SYNTHETIC_REQUEST,
            bad_entitlements,
            policy_registry,
            key_registry,
            mode="versioned-lflic-2",
            signing_algorithm=key_record.signing_algorithm,
            key_id=key_record.key_id,
        ),
        "entitlement escalation accepted",
    )
    masked = mask_identity(str(SYNTHETIC_REQUEST["identity_value"]))
    require(masked != SYNTHETIC_REQUEST["identity_value"] and masked == "AAAA...AAAA", "identity mask contract changed")


def check_sqlite_transaction_contracts() -> None:
    anchor = connect_database()
    initialize_database(anchor)
    try:
        require(anchor.execute("SELECT version FROM schema_meta").fetchone() == (1,), "SQLite schema is not migration version 1")
        tables = {
            row[0]
            for row in anchor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        require(
            {
                "authorization_records",
                "processed_requests",
                "issuance_operations",
                "trusted_signing_keys",
                "policy_registry",
                "issuance_audit",
                "license_lifecycle",
            }
            <= tables,
            "SQLite readiness schema is incomplete",
        )

        expected_unique_indexes = {
            "processed_requests": {
                ("request_schema", "request_id"),
                ("request_id",),
                ("operation_id",),
                ("resulting_license_id",),
            },
            "issuance_operations": {
                ("operation_id",),
                ("license_id",),
                ("output_target",),
            },
            "license_lifecycle": {
                ("license_id",),
                ("operation_id",),
                ("output_target",),
            },
            "trusted_signing_keys": {("signing_algorithm", "key_id")},
            "policy_registry": {("policy_id", "revision"), ("digest",)},
        }
        for table, expected in expected_unique_indexes.items():
            actual = unique_index_columns(anchor, table)
            require(expected <= actual, f"SQLite unique constraints changed: {table}")

        key_record = synthetic_key_record()
        policy_record = synthetic_policy()
        insert_trusted_key(anchor, key_record)
        insert_policy(anchor, policy_record)
        require(
            load_trusted_key(anchor, key_record.signing_algorithm, key_record.key_id) == key_record,
            "trusted signing metadata round trip changed",
        )
        require(
            load_policy(anchor, policy_record.policy_id, policy_record.revision) == policy_record,
            "policy registry round trip changed",
        )
        require_raises(
            sqlite3.IntegrityError,
            lambda: insert_trusted_key(anchor, key_record),
            "duplicate trusted algorithm/key pair was accepted",
        )
        duplicate_digest_policy = PolicyRecord(
            **{**asdict(policy_record), "policy_id": "synthetic-policy-duplicate-digest"}
        )
        require_raises(
            sqlite3.IntegrityError,
            lambda: insert_policy(anchor, duplicate_digest_policy),
            "duplicate policy digest was accepted",
        )

        rollback_request = dict(SYNTHETIC_REQUEST)
        rollback_request["request_id"] = "20000000-0000-4000-8000-000000000001"
        rollback_auth = synthetic_authorization(suffix="rollback", payload=rollback_request)
        insert_authorization(anchor, rollback_auth)
        require(
            load_authorization(anchor, rollback_auth.authorization_id, rollback_auth.revision)
            == rollback_auth,
            "AuthorizationRecord database round trip changed",
        )
        require_raises(
            SyntheticFailure,
            lambda: claim_request(
                rollback_request,
                rollback_auth,
                operation_id="synthetic-operation-rollback",
                license_id="synthetic-license-rollback",
                inject_failure=True,
            ),
            "injected transaction failure did not propagate",
        )
        require(
            anchor.execute(
                "SELECT status, reserved_operation_id FROM authorization_records WHERE authorization_id = ?",
                (rollback_auth.authorization_id,),
            ).fetchone()
            == ("approved", None),
            "failed transaction consumed authorization",
        )
        require(
            anchor.execute("SELECT COUNT(*) FROM processed_requests WHERE request_id = ?", (rollback_request["request_id"],)).fetchone()[0]
            == 0,
            "failed transaction left processed request",
        )
        require(
            claim_request(
                rollback_request,
                rollback_auth,
                operation_id="synthetic-operation-rollback-retry",
                license_id="synthetic-license-rollback-retry",
            )
            == "success",
            "rollback did not permit one later reservation",
        )
        processed = load_processed_request(
            anchor,
            str(rollback_request["schema"]),
            str(rollback_request["request_id"]),
        )
        require(
            processed
            == ProcessedRequestRecord(
                request_schema=str(rollback_request["schema"]),
                request_id=str(rollback_request["request_id"]),
                request_payload_digest=request_digest(rollback_request),
                authorization_id=rollback_auth.authorization_id,
                authorization_revision=rollback_auth.revision,
                issuance_mode=rollback_auth.allowed_issuance_mode,
                operation_id="synthetic-operation-rollback-retry",
                resulting_license_id="synthetic-license-rollback-retry",
                processed_timestamp=1767225800,
                operator=rollback_auth.approval_actor,
                result_status="reserved",
            ),
            "ProcessedRequestRecord database round trip changed",
        )
        require_raises(
            sqlite3.IntegrityError,
            lambda: anchor.execute(
                """
                INSERT INTO processed_requests (
                    request_schema, request_id, request_digest,
                    authorization_id, authorization_revision, issuance_mode,
                    operation_id, resulting_license_id, processed_timestamp,
                    operator, result_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "synthetic-other-schema",
                    rollback_request["request_id"],
                    request_digest(rollback_request),
                    rollback_auth.authorization_id,
                    rollback_auth.revision,
                    rollback_auth.allowed_issuance_mode,
                    "synthetic-operation-global-request-id-collision",
                    "synthetic-license-global-request-id-collision",
                    1767225800,
                    rollback_auth.approval_actor,
                    "reserved",
                ),
            ),
            "global request_id uniqueness was not enforced by SQLite",
        )
        require(
            claim_request(
                rollback_request,
                rollback_auth,
                operation_id="synthetic-operation-duplicate",
                license_id="synthetic-license-duplicate",
            )
            == "duplicate",
            "same request/digest was not classified as duplicate",
        )
        conflict_request = dict(rollback_request)
        conflict_request["identity_value"] = "B" * 64
        require(
            claim_request(
                conflict_request,
                rollback_auth,
                operation_id="synthetic-operation-conflict",
                license_id="synthetic-license-conflict",
            )
            == "conflict",
            "same request ID with different digest was not quarantined as conflict",
        )

        new_id_same_payload = dict(rollback_request)
        new_id_same_payload["request_id"] = "20000000-0000-4000-8000-000000000002"
        require_raises(
            ReadinessError,
            lambda: claim_request(
                new_id_same_payload,
                rollback_auth,
                operation_id="synthetic-operation-no-authorization",
                license_id="synthetic-license-no-authorization",
            ),
            "same payload under a new request ID inherited authorization",
        )

        before_inspect = tuple(table_count(anchor, name) for name in ("processed_requests", "issuance_operations", "issuance_audit"))
        inspect = build_issuance_plan("LFREQ2", SYNTHETIC_REQUEST, None, None, None)
        require(inspect["state_writes"] == inspect["issuer_calls"] == 0, "inspect-only gained state or issuer side effect")
        after_inspect = tuple(table_count(anchor, name) for name in ("processed_requests", "issuance_operations", "issuance_audit"))
        require(after_inspect == before_inspect, "inspect-only consumed request state")

        concurrent_request = dict(SYNTHETIC_REQUEST)
        concurrent_request["request_id"] = "30000000-0000-4000-8000-000000000001"
        concurrent_auth = synthetic_authorization(suffix="concurrent", payload=concurrent_request)
        insert_authorization(anchor, concurrent_auth)
        barrier = threading.Barrier(2)
        result_lock = threading.Lock()
        results: list[str] = []
        errors: list[str] = []

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=5)
                result = claim_request(
                    concurrent_request,
                    concurrent_auth,
                    operation_id=f"synthetic-operation-concurrent-{index}",
                    license_id=f"synthetic-license-concurrent-{index}",
                )
                with result_lock:
                    results.append(result)
            except BaseException as exc:
                with result_lock:
                    errors.append(type(exc).__name__)

        threads = [threading.Thread(target=worker, args=(index,), daemon=False) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        require(not any(thread.is_alive() for thread in threads), "concurrency worker did not terminate")
        require(not errors, f"concurrency worker failed: {errors}")
        require(sorted(results) == ["duplicate", "success"], "concurrent duplicate did not yield one winner")
        require(
            anchor.execute("SELECT COUNT(*) FROM processed_requests WHERE request_id = ?", (concurrent_request["request_id"],)).fetchone()[0]
            == 1,
            "concurrent claim created more than one processed request",
        )
        require(
            anchor.execute(
                "SELECT status FROM authorization_records WHERE authorization_id = ?",
                (concurrent_auth.authorization_id,),
            ).fetchone()
            == ("reserved",),
            "concurrent claim did not reserve authorization exactly once",
        )

        failure_request = dict(SYNTHETIC_REQUEST)
        failure_request["request_id"] = "40000000-0000-4000-8000-000000000001"
        failure_auth = synthetic_authorization(suffix="pre-sign-failure", payload=failure_request)
        insert_authorization(anchor, failure_auth)
        require(
            claim_request(
                failure_request,
                failure_auth,
                operation_id="synthetic-operation-pre-sign-failure",
                license_id="synthetic-license-pre-sign-failure",
            )
            == "success",
            "pre-sign failure fixture reservation failed",
        )
        mark_pre_sign_failure(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
        )
        require(
            anchor.execute(
                "SELECT state, signer_entered FROM issuance_operations WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ).fetchone()
            == ("failed", 0),
            "pre-sign failure state changed",
        )
        require(
            anchor.execute(
                "SELECT status, reserved_operation_id FROM authorization_records WHERE authorization_id = ?",
                (failure_auth.authorization_id,),
            ).fetchone()
            == ("reserved", "synthetic-operation-pre-sign-failure"),
            "pre-sign failure released the authorization claim",
        )
        require(
            load_processed_request(anchor, str(failure_request["schema"]), str(failure_request["request_id"]))
            .result_status
            == "reserved",
            "pre-sign failure changed the ProcessedRequest state",
        )
        retry_same_pre_sign_operation(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
        )
        require(
            anchor.execute(
                "SELECT state FROM issuance_operations WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ).fetchone()
            == ("reserved",),
            "same-operation pre-sign retry changed",
        )
        require(
            anchor.execute(
                "SELECT status, reserved_operation_id FROM authorization_records WHERE authorization_id = ?",
                (failure_auth.authorization_id,),
            ).fetchone()
            == ("reserved", "synthetic-operation-pre-sign-failure"),
            "same-operation retry replaced the original authorization claim",
        )

        enter_signing(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
        )
        require_raises(
            ReadinessError,
            lambda: mark_pre_sign_failure(
                anchor,
                failure_request,
                failure_auth,
                "synthetic-operation-pre-sign-failure",
            ),
            "signer-entered operation was allowed to use pre-sign retry",
        )
        artifact_digest = hashlib.sha256(b"synthetic-artifact-bytes").hexdigest()
        mark_signed(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
            artifact_digest,
        )
        mark_persisted(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
        )
        mark_completed(
            anchor,
            failure_request,
            failure_auth,
            "synthetic-operation-pre-sign-failure",
        )
        require(
            anchor.execute(
                "SELECT state, signer_entered, artifact_digest FROM issuance_operations WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ).fetchone()
            == ("completed", 1, artifact_digest),
            "full issuance operation transition chain changed",
        )
        require(
            anchor.execute(
                "SELECT status FROM authorization_records WHERE authorization_id = ?",
                (failure_auth.authorization_id,),
            ).fetchone()
            == ("consumed",),
            "completion did not consume the authorization",
        )
        require(
            load_processed_request(anchor, str(failure_request["schema"]), str(failure_request["request_id"]))
            .result_status
            == "completed",
            "completion did not complete the ProcessedRequest",
        )
        require(
            anchor.execute(
                "SELECT state, output_target, artifact_digest FROM license_lifecycle WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ).fetchone()
            == (
                "issued",
                canonical_output_target("synthetic-license-pre-sign-failure"),
                artifact_digest,
            ),
            "completed license lifecycle changed",
        )
        require_raises(
            sqlite3.DatabaseError,
            lambda: anchor.execute(
                "UPDATE issuance_operations SET output_target = output_target WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ),
            "claimed issuance output target was mutable",
        )
        if anchor.in_transaction:
            anchor.rollback()
        require_raises(
            sqlite3.DatabaseError,
            lambda: anchor.execute(
                "UPDATE license_lifecycle SET output_target = output_target WHERE operation_id = ?",
                ("synthetic-operation-pre-sign-failure",),
            ),
            "persisted license output target was mutable",
        )
        if anchor.in_transaction:
            anchor.rollback()

        quarantine_request = dict(SYNTHETIC_REQUEST)
        quarantine_request["request_id"] = "50000000-0000-4000-8000-000000000001"
        quarantine_auth = synthetic_authorization(suffix="quarantine", payload=quarantine_request)
        insert_authorization(anchor, quarantine_auth)
        require(
            claim_request(
                quarantine_request,
                quarantine_auth,
                operation_id="synthetic-operation-quarantine",
                license_id="synthetic-license-quarantine",
            )
            == "success",
            "quarantine fixture reservation failed",
        )
        enter_signing(
            anchor,
            quarantine_request,
            quarantine_auth,
            "synthetic-operation-quarantine",
        )
        mark_quarantined(
            anchor,
            quarantine_request,
            quarantine_auth,
            "synthetic-operation-quarantine",
        )
        require(
            anchor.execute(
                "SELECT state, signer_entered FROM issuance_operations WHERE operation_id = ?",
                ("synthetic-operation-quarantine",),
            ).fetchone()
            == ("quarantined", 1),
            "signer-entered failure did not quarantine the operation",
        )
        require(
            anchor.execute(
                "SELECT status, reserved_operation_id FROM authorization_records WHERE authorization_id = ?",
                (quarantine_auth.authorization_id,),
            ).fetchone()
            == ("reserved", "synthetic-operation-quarantine"),
            "quarantine released the authorization claim",
        )
        require(
            load_processed_request(
                anchor,
                str(quarantine_request["schema"]),
                str(quarantine_request["request_id"]),
            ).result_status
            == "quarantined",
            "quarantine did not mark the ProcessedRequest",
        )
        require_raises(
            ReadinessError,
            lambda: retry_same_pre_sign_operation(
                anchor,
                quarantine_request,
                quarantine_auth,
                "synthetic-operation-quarantine",
            ),
            "quarantined signer-entered operation was allowed to retry signing",
        )

        serialized_audit = "\n".join(
            row[0] for row in anchor.execute("SELECT event_json FROM issuance_audit ORDER BY sequence")
        )
        require(
            str(SYNTHETIC_REQUEST["identity_value"]) not in serialized_audit,
            "audit stored a complete synthetic identity value",
        )

        first_audit = anchor.execute("SELECT sequence FROM issuance_audit ORDER BY sequence LIMIT 1").fetchone()[0]
        require_raises(
            sqlite3.DatabaseError,
            lambda: anchor.execute("UPDATE issuance_audit SET event_json = event_json WHERE sequence = ?", (first_audit,)),
            "audit update was not rejected",
        )
        if anchor.in_transaction:
            anchor.rollback()
        require_raises(
            sqlite3.DatabaseError,
            lambda: anchor.execute("DELETE FROM issuance_audit WHERE sequence = ?", (first_audit,)),
            "audit delete was not rejected",
        )
        if anchor.in_transaction:
            anchor.rollback()
    finally:
        anchor.close()


def main() -> int:
    cwd_before = Path.cwd()
    environment_before = dict(os.environ)
    sensitive_modules = (
        "cryptography",
        "licensing.crypto",
        "subprocess",
        "socket",
        "winreg",
        "getpass",
        "tempfile",
    )
    module_presence_before = {
        name: (name in sys.modules, sys.modules.get(name))
        for name in sensitive_modules
    }

    check_smoke_source_safety()
    check_current_admin_contracts()
    check_document_contracts()
    check_record_and_policy_contracts()
    check_sqlite_transaction_contracts()

    require(Path.cwd() == cwd_before, "readiness smoke changed cwd")
    require(dict(os.environ) == environment_before, "readiness smoke changed environment")
    for name, (was_present, original_module) in module_presence_before.items():
        require((name in sys.modules) == was_present, f"readiness smoke changed module presence: {name}")
        if was_present:
            require(sys.modules.get(name) is original_module, f"readiness smoke replaced module: {name}")

    print("admin issuance readiness smoke ok")
    print("status=readiness-only,implementation-not-started")
    print("current_admin=legacy-v1,jsonl,non-atomic")
    print("default_mode=inspect-only")
    print("issuance_modes=explicit,legacy-lflic-1,versioned-lflic-2")
    print("authorization=administrator-record-only")
    print("replay=sqlite-transaction,one-concurrent-winner")
    print("constraints=request-id,operation-id,license-id,output-target")
    print("state_machine=pre-sign-retry,post-sign-quarantine,complete")
    print("output=canonical-claim,no-clobber")
    print("key_registry=metadata-only,exact-pair,no-secret")
    print("policy=versioned,round-trip,fail-closed")
    print("audit=masked,append-only")
    print("signing=not-invoked")
    print("side_effects=shared-memory-sqlite-only")
    print(f"protected_files_checked={len(EXPECTED_SOURCE_SHA256)}")
    print("changed=0")
    print("hash_mismatch=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
