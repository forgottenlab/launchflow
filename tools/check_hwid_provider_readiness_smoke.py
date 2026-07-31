"""Validate Phase 1j HWID provider-readiness decisions without host identity access."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CWD_BEFORE = Path.cwd()
ENVIRONMENT_BEFORE = dict(os.environ)
WINREG_BEFORE = sys.modules.get("winreg")

HWID_PATH = ROOT / "licensing" / "hwid.py"
LICENSE_MANAGER_PATH = ROOT / "licensing" / "license_manager.py"
REQUEST_TOKEN_PATH = ROOT / "licensing" / "request_token.py"
LICENSE_SCHEMA_PATH = ROOT / "licensing" / "license_schema.py"
READINESS_DOC_PATH = ROOT / "docs" / "hardware-identity-provider-readiness.md"
ADMIN_PATHS = (
    ROOT / "tools" / "license_admin.py",
    ROOT / "tools" / "license_admin_core.py",
    ROOT / "tools" / "license_generator.py",
)
PRODUCTION_IDENTITY_PATHS = tuple((ROOT / "licensing").glob("*.py")) + tuple(
    (ROOT / "shared" / "platform").glob("*.py")
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"expected one function named {name}")
    return matches[0]


def called_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def string_constants(node: ast.AST) -> list[str]:
    return [
        value.value
        for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    ]


def check_public_signatures_and_facade() -> None:
    hwid = importlib.import_module("licensing.hwid")
    expected = {
        "_read_windows_machine_guid": "() -> 'str'",
        "_read_machine_sid_fallback": "() -> 'str'",
        "_read_volume_serial": "() -> 'str'",
        "get_machine_fingerprint_parts": "() -> 'Dict[str, str]'",
        "get_machine_id": "() -> 'str'",
        "format_machine_id": "(machine_id: 'str', group: 'int' = 4) -> 'str'",
    }
    for name, signature in expected.items():
        require(str(inspect.signature(getattr(hwid, name))) == signature, f"signature changed: {name}")

    function = find_function(parse(HWID_PATH), "get_machine_id")
    calls = [called_name(node) for node in ast.walk(function) if isinstance(node, ast.Call)]
    constants = string_constants(function)
    require(calls.count("get_machine_fingerprint_parts") == 1, "get_machine_id facade source changed")
    for required_call in ("join", "get", "encode", "sha256", "hexdigest", "upper"):
        require(required_call in calls, f"get_machine_id lost {required_call}")
    require("||" in constants and "utf-8" in constants, "legacy serialization/encoding changed")

    get_keys = [
        node.args[0].value
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    require(
        get_keys == ["machine_guid", "volume_serial", "fallback"],
        "legacy-v1 hashed field order changed",
    )


def check_license_validation_order() -> None:
    function = find_function(parse(LICENSE_MANAGER_PATH), "validate_license_data")
    calls = [
        (node.lineno, called_name(node))
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    verify_lines = [line for line, name in calls if name == "verify_signature"]
    identity_lines = [line for line, name in calls if name == "get_machine_id"]
    require(len(verify_lines) == 1, "LicenseManager signature verification call changed")
    require(len(identity_lines) == 1, "LicenseManager machine-ID call changed")
    require(verify_lines[0] < identity_lines[0], "machine ID is read before signature verification")

    invalid_signature_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and node.value == "invalid_signature"
    ]
    require(
        invalid_signature_lines
        and verify_lines[0] < min(invalid_signature_lines) < identity_lines[0],
        "invalid-signature exit no longer precedes identity acquisition",
    )


def check_admin_boundary() -> None:
    for path in ADMIN_PATHS:
        tree = parse(path)
        calls = [called_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        imports_hwid = any(
            isinstance(node, ast.ImportFrom) and node.module == "licensing.hwid"
            for node in ast.walk(tree)
        )
        require(not imports_hwid, f"admin tool imports licensing.hwid: {path.name}")
        require("get_machine_id" not in calls, f"admin tool recalculates customer identity: {path.name}")


def is_strip_upper_chain(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "upper"
        and not node.args
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Attribute)
        and node.func.value.func.attr == "strip"
        and not node.func.value.args
        and isinstance(node.func.value.func.value, ast.Name)
        and node.func.value.func.value.id == "machine_id"
    )


def check_request_normalization_and_schema() -> None:
    request_tree = parse(REQUEST_TOKEN_PATH)
    build_payload = find_function(request_tree, "build_request_payload")
    normalization = [
        node
        for node in ast.walk(build_payload)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "normalized_machine_id" for target in node.targets)
    ]
    require(
        len(normalization) == 1 and is_strip_upper_chain(normalization[0].value),
        "request machine_id is no longer normalized with strip().upper()",
    )

    current_sources = REQUEST_TOKEN_PATH.read_text(encoding="utf-8") + "\n" + LICENSE_SCHEMA_PATH.read_text(
        encoding="utf-8"
    )
    for forbidden in ("identity_version", "hwid_version", '"identity"', "'identity'"):
        require(forbidden not in current_sources, f"current schema gained an identity-version field: {forbidden}")

    request_constants = string_constants(request_tree)
    license_constants = string_constants(parse(LICENSE_SCHEMA_PATH))
    require("LFREQ1" in request_constants and "lfreq-1" in request_constants, "request schema changed")
    require("lflic-1" in license_constants, "license schema changed")


def check_no_provider_implementation() -> None:
    for path in PRODUCTION_IDENTITY_PATHS:
        source = path.read_text(encoding="utf-8")
        require("HardwareIdentityProvider" not in source, f"provider implementation appeared in {path}")
        tree = ast.parse(source, filename=str(path))
        provider_classes = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and "IdentityProvider" in node.name
        ]
        require(not provider_classes, f"identity provider class appeared in {path}: {provider_classes}")


def check_readiness_document() -> None:
    text = READINESS_DOC_PATH.read_text(encoding="utf-8")
    folded = text.casefold()
    required = (
        "Decision: Option B",
        "Unversioned multi-ID fallback: Rejected",
        "Legacy-v1 pure-function boundary",
        "ActivationService injection strategy",
        "LicenseManager injection strategy",
        "Admin-tool boundary",
        "Legacy-license interpretation",
        "Migration and reactivation policy",
        "Error-state model",
        "Privacy and logging requirements",
        "Phase 1k",
        "Phase 1l",
        "Phase 1m",
        "legacy-v1 is permanent verification behavior",
        "HardwareIdentityProvider is not implemented",
    )
    for marker in required:
        require(marker.casefold() in folded, f"readiness decision missing: {marker}")


def rerun_phase_1i_fixture() -> None:
    contract = importlib.import_module("tools.check_hwid_contract_smoke")
    require(contract.SYNTHETIC_GUID == "11111111-2222-3333-4444-555555555555", "fixture GUID changed")
    require(contract.SYNTHETIC_VOLUME == "ABCD-1234", "fixture volume changed")
    require(contract.SYNTHETIC_HOST == "TEST-HOST", "fixture hostname changed")
    require(contract.SYNTHETIC_USER == "TestUser", "fixture username changed")
    require(
        contract.SYNTHETIC_HWID == "92FD6B08959D22BC7EB9FEC57E6471C701CB7BDE158D48128D6BC403666DAC4D",
        "legacy-v1 fixture digest changed",
    )
    require(contract.main() == 0, "Phase 1i synthetic contract smoke failed")


def check_no_side_effects() -> None:
    require(Path.cwd() == CWD_BEFORE, "readiness smoke changed cwd")
    require(dict(os.environ) == ENVIRONMENT_BEFORE, "readiness smoke changed environment")
    require(sys.modules.get("winreg") is WINREG_BEFORE, "readiness smoke retained a registry module")
    require(not (ROOT / "tools" / "check_hwid_provider_readiness_smoke.lic").exists(), "smoke wrote a license")


def main() -> int:
    check_public_signatures_and_facade()
    check_license_validation_order()
    check_admin_boundary()
    check_request_normalization_and_schema()
    check_no_provider_implementation()
    check_readiness_document()
    rerun_phase_1i_fixture()
    check_no_side_effects()

    print("hwid provider readiness smoke ok")
    print("facade=unchanged,legacy-v1")
    print("validation_order=schema,signature,identity")
    print("admin_identity=copy-only,no-recalculation")
    print("schema=lfreq-1-and-lflic-1,unversioned")
    print("provider=decision-only,not-implemented")
    print("migration=option-b,versioned,no-match-any-fallback")
    print("phase1i_fixture=synthetic,reused")
    print("side_effects=registry:none,process:none,host:none,user:none,key:none,appdata:none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
