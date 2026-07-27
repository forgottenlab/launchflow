"""Freeze LaunchFlow's existing HWID contract using synthetic data only."""

from __future__ import annotations

import builtins
import hashlib
import importlib
import inspect
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CWD_BEFORE_IMPORT = Path.cwd()
ENVIRONMENT_BEFORE_IMPORT = dict(os.environ)
WINREG_BEFORE_IMPORT = sys.modules.pop("winreg", None)
import licensing.hwid as hwid  # noqa: E402

SYNTHETIC_GUID = "11111111-2222-3333-4444-555555555555"
SYNTHETIC_VOLUME = "ABCD-1234"
SYNTHETIC_HOST = "TEST-HOST"
SYNTHETIC_USER = "TestUser"
SYNTHETIC_FALLBACK = "Windows|11|10.0.26100|TEST-HOST|TestUser"
SYNTHETIC_RAW = (
    "11111111-2222-3333-4444-555555555555||ABCD-1234||"
    "Windows|11|10.0.26100|TEST-HOST|TestUser"
)
SYNTHETIC_HWID = "92FD6B08959D22BC7EB9FEC57E6471C701CB7BDE158D48128D6BC403666DAC4D"

NON_WINDOWS_FIXTURES = {
    "linux": (
        "Linux",
        "6.8.0",
        "#1 SMP TEST",
        "Linux-6.8.0-x86_64",
        "88C6137B8F89084E65EA078CF480A2AC086283BA3B7A86EFCDE1728704CCAB25",
    ),
    "macos": (
        "Darwin",
        "24.0.0",
        "Darwin Kernel Version TEST",
        "macOS-15.0-arm64",
        "342F9C1D38D8A23E971C3FECA0165BDD056C4ADFFB522EEE6B2A07A48D5CA38F",
    ),
    "unknown": (
        "MysteryOS",
        "1",
        "Fixture Version",
        "MysteryOS-1-unknown",
        "15A0CDBDB1C39F560AF8222AC4CD2E5456BA608FB9EA9B7EC9E019BC892C67FE",
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_import_and_public_api() -> None:
    require(Path.cwd() == CWD_BEFORE_IMPORT, "HWID import changed cwd")
    require(dict(os.environ) == ENVIRONMENT_BEFORE_IMPORT, "HWID import changed environment")
    require("winreg" not in sys.modules, "HWID import eagerly imported winreg")
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


class FakeRegistryKey:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def __enter__(self):
        self.calls.append(("key.enter", None))
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.calls.append(("key.exit", exc_type))
        return False


def fake_winreg(*, value: object = SYNTHETIC_GUID, error: BaseException | None = None):
    module = ModuleType("winreg")
    module.HKEY_LOCAL_MACHINE = object()
    module.calls = []

    def open_key(root, path):
        module.calls.append(("OpenKey", (root, path)))
        if error is not None:
            raise error
        return FakeRegistryKey(module.calls)

    def query_value(key, name):
        module.calls.append(("QueryValueEx", (key, name)))
        return value, 1

    module.OpenKey = open_key
    module.QueryValueEx = query_value
    return module


def check_machine_guid_contract() -> None:
    registry = fake_winreg(value=f"  {SYNTHETIC_GUID}  ")
    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.dict(sys.modules, {"winreg": registry}),
    ):
        require(hwid._read_windows_machine_guid() == SYNTHETIC_GUID, "MachineGuid strip changed")
    require(registry.calls[0][0] == "OpenKey", "registry open order changed")
    root, path = registry.calls[0][1]
    require(root is registry.HKEY_LOCAL_MACHINE, "registry hive changed")
    require(path == r"SOFTWARE\Microsoft\Cryptography", "registry path changed")
    require(registry.calls[2][0] == "QueryValueEx", "registry query order changed")
    require(registry.calls[2][1][1] == "MachineGuid", "registry value name changed")

    for error in (FileNotFoundError("synthetic"), PermissionError("synthetic"), OSError("synthetic")):
        failing_registry = fake_winreg(error=error)
        with (
            patch.object(hwid, "os", SimpleNamespace(name="nt")),
            patch.dict(sys.modules, {"winreg": failing_registry}),
        ):
            require(hwid._read_windows_machine_guid() == "", f"registry {type(error).__name__} changed")

    whitespace_registry = fake_winreg(value="   ")
    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.dict(sys.modules, {"winreg": whitespace_registry}),
    ):
        require(hwid._read_windows_machine_guid() == "", "blank MachineGuid changed")

    import_attempts: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "winreg":
            import_attempts.append(name)
            raise AssertionError("non-Windows path imported winreg")
        return original_import(name, *args, **kwargs)

    with patch.object(hwid, "os", SimpleNamespace(name="posix")), patch(
        "builtins.__import__", guarded_import
    ):
        require(hwid._read_windows_machine_guid() == "", "non-Windows MachineGuid changed")
    require(not import_attempts, "non-Windows path accessed winreg")


def command_result(stdout, *, returncode: int = 0, stderr: str = ""):
    return SimpleNamespace(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        launch_error="synthetic launch metadata",
    )


def read_volume_with(result=None, *, error: BaseException | None = None) -> tuple[str, list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    def execute(command: str, shell: str):
        calls.append((command, shell))
        if error is not None:
            raise error
        return result

    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.object(hwid, "execute_command", execute),
    ):
        return hwid._read_volume_serial(), calls


def check_volume_contract() -> None:
    value, calls = read_volume_with(command_result(f"  {SYNTHETIC_VOLUME}\r\n"))
    require(value == SYNTHETIC_VOLUME, "volume stdout strip changed")
    require(calls == [("vol C:", "cmd")], "volume command/shell changed")

    cases = (
        (command_result(""), ""),
        (command_result(None), ""),
        (command_result("  MiXeD serial  \n", returncode=7, stderr="ignored"), "MiXeD serial"),
        (
            command_result("  卷 C 中的卷是 TEST\r\n  卷序列号是 abcd-1234  \r\n", returncode=9),
            "卷 C 中的卷是 TEST\r\n  卷序列号是 abcd-1234",
        ),
        (command_result("line one\nline two\n"), "line one\nline two"),
    )
    for result, expected in cases:
        actual, result_calls = read_volume_with(result)
        require(actual == expected, f"volume stdout behavior changed: {expected!r}")
        require(result_calls == [("vol C:", "cmd")], "volume probe count changed")

    for error in (FileNotFoundError("synthetic"), PermissionError("synthetic"), OSError("synthetic")):
        actual, error_calls = read_volume_with(error=error)
        require(actual == "", f"volume {type(error).__name__} behavior changed")
        require(error_calls == [("vol C:", "cmd")], "volume exception call changed")

    def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("non-Windows path launched a command")

    with (
        patch.object(hwid, "os", SimpleNamespace(name="posix")),
        patch.object(hwid, "execute_command", forbidden_execute),
    ):
        require(hwid._read_volume_serial() == "", "non-Windows volume behavior changed")


def fake_platform(
    calls: list[str],
    *,
    system: object,
    release: object,
    version: object,
    platform_text: str,
):
    def source(name: str, value: object):
        def read():
            calls.append(name)
            return value

        return read

    return SimpleNamespace(
        system=source("platform.system", system),
        release=source("platform.release", release),
        version=source("platform.version", version),
        platform=source("platform.platform", platform_text),
    )


def check_fallback_inputs() -> None:
    cases = (
        (("Windows", "11", "10.0", SYNTHETIC_HOST, SYNTHETIC_USER), "Windows|11|10.0|TEST-HOST|TestUser"),
        (("Linux", "", None, "测试 主机", "用户+name"), "Linux|测试 主机|用户+name"),
        (("Darwin", " 15 ", "MiXeD", "", " User Name "), "Darwin| 15 |MiXeD| User Name "),
        (("", "", "", "", ""), ""),
    )
    for values, expected in cases:
        calls: list[str] = []
        system, release, version, host, user = values
        with (
            patch.object(
                hwid,
                "platform",
                fake_platform(
                    calls,
                    system=system,
                    release=release,
                    version=version,
                    platform_text="unused",
                ),
            ),
            patch.object(hwid.socket, "gethostname", lambda: calls.append("socket.gethostname") or host),
            patch.object(hwid.getpass, "getuser", lambda: calls.append("getpass.getuser") or user),
        ):
            actual = hwid._read_machine_sid_fallback()
        require(actual == expected, f"fallback serialization changed: {values!r}")
        require(
            calls == [
                "platform.system",
                "platform.release",
                "platform.version",
                "socket.gethostname",
                "getpass.getuser",
            ],
            "fallback source order changed",
        )

    with (
        patch.object(
            hwid,
            "platform",
            fake_platform([], system="Linux", release="6", version="v", platform_text="unused"),
        ),
        patch.object(hwid.socket, "gethostname", side_effect=OSError("synthetic hostname failure")),
        patch.object(hwid.getpass, "getuser", return_value=SYNTHETIC_USER),
    ):
        try:
            hwid._read_machine_sid_fallback()
        except OSError as exc:
            require("synthetic" in str(exc), "fallback exception changed")
        else:
            raise AssertionError("fallback hostname error was swallowed")


def check_windows_fixture() -> None:
    calls: list[str] = []

    def source(name: str, value: str):
        def read() -> str:
            calls.append(name)
            return value

        return read

    with (
        patch.object(hwid, "_read_windows_machine_guid", source("machine_guid", SYNTHETIC_GUID)),
        patch.object(hwid, "_read_volume_serial", source("volume_serial", SYNTHETIC_VOLUME)),
        patch.object(
            hwid,
            "platform",
            fake_platform(
                calls,
                system="Windows",
                release="11",
                version="10.0.26100",
                platform_text="Windows-11-10.0.26100-SP0",
            ),
        ),
        patch.object(hwid.socket, "gethostname", source("socket.gethostname", SYNTHETIC_HOST)),
        patch.object(hwid.getpass, "getuser", source("getpass.getuser", SYNTHETIC_USER)),
        patch.object(hwid.sys, "version", "3.13.9 fixture"),
    ):
        parts = hwid.get_machine_fingerprint_parts()

    require(
        tuple(parts) == ("machine_guid", "volume_serial", "fallback", "python", "platform"),
        "fingerprint part field order changed",
    )
    require(
        parts
        == {
            "machine_guid": SYNTHETIC_GUID,
            "volume_serial": SYNTHETIC_VOLUME,
            "fallback": SYNTHETIC_FALLBACK,
            "python": "3.13.9",
            "platform": "Windows-11-10.0.26100-SP0",
        },
        "Windows fingerprint parts changed",
    )
    require(
        calls
        == [
            "machine_guid",
            "volume_serial",
            "platform.system",
            "platform.release",
            "platform.version",
            "socket.gethostname",
            "getpass.getuser",
            "platform.platform",
        ],
        "Windows source call order changed",
    )
    require(SYNTHETIC_RAW.encode("utf-8").decode("utf-8") == SYNTHETIC_RAW, "UTF-8 contract changed")
    require(hashlib.sha256(SYNTHETIC_RAW.encode("utf-8")).hexdigest().upper() == SYNTHETIC_HWID, "fixture hash invalid")
    with patch.object(hwid, "get_machine_fingerprint_parts", return_value=parts):
        actual = hwid.get_machine_id()
        repeated = hwid.get_machine_id()
    require(actual == SYNTHETIC_HWID == repeated, "Windows final HWID changed or is non-deterministic")
    require(len(actual) == 64 and actual == actual.upper(), "HWID length/case changed")
    require(all(character in "0123456789ABCDEF" for character in actual), "HWID is not uppercase hex")
    require(hwid.format_machine_id(actual) == "-".join(actual[index:index + 4] for index in range(0, 64, 4)), "display grouping changed")
    require(hwid.format_machine_id("ab-cd 12_34", 3) == "ABC-D12-34", "display normalization changed")


def check_hash_input_boundary() -> None:
    base = {
        "machine_guid": SYNTHETIC_GUID,
        "volume_serial": SYNTHETIC_VOLUME,
        "fallback": SYNTHETIC_FALLBACK,
        "python": "3.13.9",
        "platform": "Windows fixture",
    }

    def calculate(parts: dict[str, str]) -> str:
        with patch.object(hwid, "get_machine_fingerprint_parts", return_value=parts):
            return hwid.get_machine_id()

    baseline = calculate(base)
    changed_hashes = []
    for field in ("machine_guid", "volume_serial", "fallback"):
        changed = dict(base)
        changed[field] += "-CHANGED"
        changed_hashes.append(calculate(changed))
    require(all(value != baseline for value in changed_hashes), "a serialized identity field did not affect HWID")
    require(len(set(changed_hashes)) == 3, "changed identity fields collided in fixture")

    for field in ("python", "platform"):
        changed = dict(base)
        changed[field] += "-CHANGED"
        require(calculate(changed) == baseline, f"non-hashed field unexpectedly affects HWID: {field}")

    empty_hash = hashlib.sha256("||||".encode("utf-8")).hexdigest().upper()
    require(calculate({}) == empty_hash, "missing-key empty serialization changed")


def check_non_windows_contract() -> None:
    for label, (system, release, version, platform_text, expected_hash) in NON_WINDOWS_FIXTURES.items():
        calls: list[str] = []

        def forbidden_execute(*_args, **_kwargs):
            raise AssertionError(f"{label} launched vol command")

        with (
            patch.object(hwid, "os", SimpleNamespace(name="posix" if label != "unknown" else "other")),
            patch.object(hwid, "execute_command", forbidden_execute),
            patch.object(
                hwid,
                "platform",
                fake_platform(
                    calls,
                    system=system,
                    release=release,
                    version=version,
                    platform_text=platform_text,
                ),
            ),
            patch.object(hwid.socket, "gethostname", lambda: calls.append("socket.gethostname") or SYNTHETIC_HOST),
            patch.object(hwid.getpass, "getuser", lambda: calls.append("getpass.getuser") or SYNTHETIC_USER),
            patch.object(hwid.sys, "version", "3.13.9 fixture"),
        ):
            parts = hwid.get_machine_fingerprint_parts()
            with patch.object(hwid, "get_machine_fingerprint_parts", return_value=parts):
                actual = hwid.get_machine_id()
        require(parts["machine_guid"] == "" and parts["volume_serial"] == "", f"{label} Windows sources changed")
        require(actual == expected_hash, f"{label} legacy hash changed")
        require(len(actual) == 64 and actual == actual.upper(), f"{label} output format changed")


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 7, 28, 0, 0, 0, tzinfo=tz or timezone.utc)


def load_binding_modules_without_key_material():
    fake_crypto = ModuleType("licensing.crypto")
    fake_crypto.verify_signature = lambda *_args, **_kwargs: True
    fake_crypto.verify_signature_with_key = lambda *_args, **_kwargs: True
    fake_generator = ModuleType("tools.license_generator")
    fake_generator.sign_payload = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("signing must not occur in HWID contract smoke")
    )
    sys.modules.pop("licensing.license_manager", None)
    sys.modules.pop("tools.license_admin_core", None)
    with patch.dict(
        sys.modules,
        {
            "licensing.crypto": fake_crypto,
            "tools.license_generator": fake_generator,
        },
    ):
        license_manager = importlib.import_module("licensing.license_manager")
        admin_core = importlib.import_module("tools.license_admin_core")
    return license_manager, admin_core


def check_request_and_license_binding() -> None:
    request_token = importlib.import_module("licensing.request_token")
    fixed_request_id = UUID("00000000-1111-2222-3333-444444444444")
    with (
        patch.object(request_token, "uuid4", return_value=fixed_request_id),
        patch.object(request_token, "datetime", FixedDateTime),
        patch.object(request_token, "APP_VERSION", "9.9.9-fixture"),
    ):
        request_payload = request_token.build_request_payload("  " + SYNTHETIC_HWID.lower() + "  ")
    require(
        tuple(request_payload)
        == ("schema", "product", "app_version", "machine_id", "request_id", "created_at"),
        "LFREQ1 payload field order changed",
    )
    require(request_payload["machine_id"] == SYNTHETIC_HWID, "request machine binding normalization changed")
    require(request_payload["schema"] == "lfreq-1", "request schema changed")
    require("signature" not in request_payload and "license" not in request_payload, "request gained secret/license fields")

    license_manager, admin_core = load_binding_modules_without_key_material()
    issued_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    license_payload = admin_core.build_license_payload(
        request_payload,
        customer="Synthetic Test Customer",
        edition="fixture",
        features=["fixture"],
        issued_at=issued_at,
        expires_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
        min_app_version="0.0.0",
        max_app_version=None,
        license_id="SYNTHETIC-LICENSE-ID",
    )
    require(license_payload["schema"] == "lflic-1", "license schema changed")
    require(license_payload["machine_id"] == SYNTHETIC_HWID, "license payload machine binding changed")
    require(license_payload["request_id"] == str(fixed_request_id), "request/license link changed")
    require("signature" not in license_payload, "pure license payload unexpectedly signed")

    manager = object.__new__(license_manager.LicenseManager)
    manager.public_key_path = Path("synthetic-public-key-not-read.pem")
    calls: list[str] = []
    license_manager.verify_signature = lambda *_args, **_kwargs: calls.append("verify_signature") or True
    license_manager.get_machine_id = lambda: calls.append("get_machine_id") or SYNTHETIC_HWID

    current_data = {**license_payload, "machine_id": "  " + SYNTHETIC_HWID.lower() + "  ", "signature": "SYNTHETIC"}
    current_result = manager.validate_license_data(current_data)
    require(current_result.is_valid and current_result.code == "ok", "lflic-1 exact machine binding changed")
    require(calls == ["verify_signature", "get_machine_id"], "license validation order changed")

    calls.clear()
    different = dict(current_data)
    different["machine_id"] = "0" * 64
    mismatch = manager.validate_license_data(different)
    require(not mismatch.is_valid and mismatch.code == "machine_not_match", "machine mismatch behavior changed")
    require(calls == ["verify_signature", "get_machine_id"], "mismatch validation order changed")

    legacy_data = {
        "license_id": "SYNTHETIC-LEGACY",
        "tester_name": "Synthetic Tester",
        "machine_id": SYNTHETIC_HWID,
        "edition": "fixture",
        "expire_at": "2099-12-31 23:59:59",
        "created_at": "2026-07-28 00:00:00",
        "signature": "SYNTHETIC",
    }
    calls.clear()
    legacy_result = manager.validate_license_data(legacy_data)
    require(legacy_result.is_valid and legacy_result.code == "ok", "legacy license machine binding changed")
    require(calls == ["verify_signature", "get_machine_id"], "legacy validation order changed")


def check_no_side_effects() -> None:
    require(Path.cwd() == CWD_BEFORE_IMPORT, "smoke changed cwd")
    require(dict(os.environ) == ENVIRONMENT_BEFORE_IMPORT, "smoke changed environment")
    require(not (ROOT / "tools" / "check_hwid_contract_smoke.lic").exists(), "smoke created a license")


def main() -> int:
    try:
        check_import_and_public_api()
        check_machine_guid_contract()
        check_volume_contract()
        check_fallback_inputs()
        check_windows_fixture()
        check_hash_input_boundary()
        check_non_windows_contract()
        check_request_and_license_binding()
        check_no_side_effects()
    finally:
        if WINREG_BEFORE_IMPORT is not None:
            sys.modules["winreg"] = WINREG_BEFORE_IMPORT
        else:
            sys.modules.pop("winreg", None)

    print("hwid contract smoke ok")
    print("windows_fixture_sha256=" + SYNTHETIC_HWID)
    print("windows_sources=machine-guid,volume-stdout,fallback")
    print("hash_contract=double-pipe,utf-8,sha256,uppercase-64")
    print("ignored_hash_fields=python,platform")
    print("registry=delayed,exact-path-and-value,errors-to-empty")
    print("volume=vol-c-cmd,stdout-strip,returncode-and-stderr-ignored,errors-to-empty")
    print("legacy_non_windows=linux,macos,unknown")
    print("request_license_binding=synthetic,payload-only,no-token,no-signing,no-key-read")
    print("side_effects=registry:none,process:none,host:none,user:none,appdata:none,network:none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
