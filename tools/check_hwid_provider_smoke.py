"""Verify the legacy-v1 identity provider using synthetic sources only."""

from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError, fields
import hashlib
import inspect
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CWD_BEFORE_IMPORT = Path.cwd()
ENVIRONMENT_BEFORE_IMPORT = dict(os.environ)
WINREG_BEFORE_IMPORT = sys.modules.pop("winreg", None)

import licensing.hwid as hwid  # noqa: E402
import shared.platform.identity as identity  # noqa: E402
from shared.platform.base import PlatformInfo  # noqa: E402
from shared.platform.detection import detect_platform  # noqa: E402
from shared.platform.identity import (  # noqa: E402
    HardwareIdentityParts,
    HardwareIdentityProvider,
    LegacyPosixHardwareIdentityProvider,
    WindowsHardwareIdentityProvider,
    build_legacy_v1_machine_id,
    get_hardware_identity_provider,
    hash_legacy_v1_serialized,
    read_legacy_machine_fallback,
    read_windows_machine_guid,
    read_windows_volume_stdout,
    serialize_legacy_v1,
)


IDENTITY_PATH = ROOT / "shared" / "platform" / "identity.py"
HWID_PATH = ROOT / "licensing" / "hwid.py"
SYNTHETIC_GUID = "11111111-2222-3333-4444-555555555555"
SYNTHETIC_VOLUME = "ABCD-1234"
SYNTHETIC_FALLBACK = "Windows|11|10.0.26100|TEST-HOST|TestUser"
SYNTHETIC_RAW = (
    "11111111-2222-3333-4444-555555555555||ABCD-1234||"
    "Windows|11|10.0.26100|TEST-HOST|TestUser"
)
SYNTHETIC_HWID = "92FD6B08959D22BC7EB9FEC57E6471C701CB7BDE158D48128D6BC403666DAC4D"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def platform_fixture(system: str) -> PlatformInfo:
    source_system = {
        "windows": "Windows",
        "linux": "Linux",
        "macos": "Darwin",
        "unknown": "MysteryOS",
    }[system]
    return detect_platform(
        system=source_system,
        machine="AMD64",
        os_name="fixture",
        sys_platform="fixture",
    )


def synthetic_parts(**overrides: str) -> HardwareIdentityParts:
    values = {
        "machine_guid": SYNTHETIC_GUID,
        "volume_serial": SYNTHETIC_VOLUME,
        "fallback": SYNTHETIC_FALLBACK,
        "python": "3.13.9",
        "platform": "Windows-11-SYNTHETIC",
    }
    values.update(overrides)
    return HardwareIdentityParts(**values)


def check_static_module_boundary() -> None:
    source = IDENTITY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(IDENTITY_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    allowed_imports = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "getpass",
        "hashlib",
        "os",
        "platform",
        "shared.platform.base",
        "shared.platform.detection",
        "socket",
        "sys",
        "typing",
        "winreg",
    }
    unexpected_imports = imported - allowed_imports
    require(not unexpected_imports, f"identity module crossed stdlib boundary: {unexpected_imports}")
    require("runtime.command_runner" not in source, "identity module imports runtime command runner")
    require("os.system" not in source and "subprocess" not in source, "identity module has executor fallback")
    require("/etc/machine-id" not in source and "IOPlatformUUID" not in source, "native v2 source leaked in")
    require("identity_version" not in source and "hwid_version" not in source, "identity version leaked in")
    require("winreg" not in sys.modules, "identity import eagerly loaded winreg")


def check_parts_contract() -> None:
    part_fields = fields(HardwareIdentityParts)
    require(
        tuple(field.name for field in part_fields)
        == ("machine_guid", "volume_serial", "fallback", "python", "platform"),
        "parts field names/order changed",
    )
    require(all(field.type == "str" for field in part_fields), "parts fields are not all strings")

    parts = synthetic_parts()
    try:
        parts.machine_guid = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("HardwareIdentityParts is not frozen")

    legacy = parts.to_legacy_dict()
    require(type(legacy) is dict, "legacy conversion is not an ordinary dict")
    require(
        tuple(legacy)
        == ("machine_guid", "volume_serial", "fallback", "python", "platform"),
        "legacy dict keys/order changed",
    )
    require(tuple(legacy.values()) == tuple(getattr(parts, key) for key in legacy), "legacy values changed")
    require(not ({"identity_version", "status", "errors"} & set(legacy)), "new parts fields leaked in")


def check_provider_selection_and_construction() -> None:
    calls: list[str] = []

    def source(name: str, value: str):
        return lambda: calls.append(name) or value

    def executor(command: str, shell: str):
        calls.append("executor")
        return SimpleNamespace(stdout=SYNTHETIC_VOLUME)

    windows = get_hardware_identity_provider(
        platform_info=platform_fixture("windows"),
        command_executor=executor,
        machine_guid_reader=source("machine_guid", SYNTHETIC_GUID),
        volume_reader=source("volume", SYNTHETIC_VOLUME),
        fallback_reader=source("fallback", SYNTHETIC_FALLBACK),
        python_version_reader=source("python", "3.13.9"),
        platform_metadata_reader=source("platform", "Windows-SYNTHETIC"),
    )
    require(isinstance(windows, WindowsHardwareIdentityProvider), "Windows factory selection changed")
    require(isinstance(windows, HardwareIdentityProvider), "Windows provider does not satisfy Protocol")
    require(calls == [], "Windows factory or construction collected sources")

    try:
        get_hardware_identity_provider(platform_info=platform_fixture("windows"))
    except ValueError as exc:
        require("command_executor" in str(exc), "missing executor error is not explicit")
    else:
        raise AssertionError("Windows factory accepted a missing executor")

    for label in ("linux", "macos", "unknown"):
        legacy_calls: list[str] = []

        def forbidden_executor(command: str, shell: str):
            legacy_calls.append("executor")
            raise AssertionError("Legacy provider invoked Windows executor")

        provider = get_hardware_identity_provider(
            platform_info=platform_fixture(label),
            command_executor=forbidden_executor,
            fallback_reader=lambda: SYNTHETIC_FALLBACK,
            python_version_reader=lambda: "3.13.9",
            platform_metadata_reader=lambda: label,
        )
        require(isinstance(provider, LegacyPosixHardwareIdentityProvider), f"{label} selected Windows provider")
        require(isinstance(provider, HardwareIdentityProvider), f"{label} provider does not satisfy Protocol")
        require(not hasattr(provider, "command_executor"), f"{label} provider stored Windows executor")
        require(legacy_calls == [], f"{label} factory collected or executed")
        parts = provider.collect_parts()
        require(parts.machine_guid == "" and parts.volume_serial == "", f"{label} Windows fields changed")
        require(legacy_calls == [], f"{label} called Windows executor")


def check_windows_collection_order() -> None:
    calls: list[str] = []

    def source(name: str, value: object):
        return lambda: calls.append(name) or value

    def fallback() -> str:
        return read_legacy_machine_fallback(
            system_reader=source("fallback.system", "Windows"),
            release_reader=source("fallback.release", "11"),
            version_reader=source("fallback.version", "10.0.26100"),
            hostname_reader=source("fallback.hostname", "TEST-HOST"),
            username_reader=source("fallback.username", "TestUser"),
        )

    provider = get_hardware_identity_provider(
        platform_info=platform_fixture("windows"),
        command_executor=lambda command, shell: (_ for _ in ()).throw(
            AssertionError("custom volume reader was bypassed")
        ),
        machine_guid_reader=source("machine_guid", SYNTHETIC_GUID),
        volume_reader=source("volume", SYNTHETIC_VOLUME),
        fallback_reader=fallback,
        python_version_reader=source("python", "3.13.9"),
        platform_metadata_reader=source("platform", "Windows-SYNTHETIC"),
    )
    parts = provider.collect_parts()
    require(
        calls
        == [
            "machine_guid",
            "volume",
            "fallback.system",
            "fallback.release",
            "fallback.version",
            "fallback.hostname",
            "fallback.username",
            "python",
            "platform",
        ],
        f"Windows source order changed: {calls}",
    )
    require(parts.to_legacy_dict() == synthetic_parts(platform="Windows-SYNTHETIC").to_legacy_dict(), "Windows parts changed")


def check_windows_default_provider_integration() -> None:
    registry = fake_winreg(value=f"  {SYNTHETIC_GUID}  ")
    executor_calls: list[tuple[str, str]] = []

    def execute(command: str, shell: str):
        executor_calls.append((command, shell))
        return StdoutOnlyResult(f"  {SYNTHETIC_VOLUME}  \r\n")

    with (
        patch.dict(sys.modules, {"winreg": registry}),
        patch.object(identity.platform, "system", return_value="Windows"),
        patch.object(identity.platform, "release", return_value="11"),
        patch.object(identity.platform, "version", return_value="10.0.26100"),
        patch.object(identity.socket, "gethostname", return_value="TEST-HOST"),
        patch.object(identity.getpass, "getuser", return_value="TestUser"),
        patch.object(identity.platform, "platform", return_value="Windows-SYNTHETIC"),
        patch.object(identity.sys, "version", "3.13.9 SYNTHETIC"),
    ):
        provider = get_hardware_identity_provider(
            platform_info=platform_fixture("windows"),
            command_executor=execute,
        )
        require(executor_calls == [] and registry.calls == [], "default provider construction collected sources")
        actual = provider.collect_parts()

    require(actual.to_legacy_dict() == synthetic_parts(platform="Windows-SYNTHETIC").to_legacy_dict(), "default Windows provider wiring changed")
    require(executor_calls == [(r"vol C:", "cmd")], "default provider executor injection changed")
    require(registry.calls[0][0] == "OpenKey" and registry.calls[2][0] == "QueryValueEx", "default provider registry wiring changed")


class FakeRegistryKey:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def __enter__(self):
        self.calls.append(("enter", self))
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.calls.append(("exit", exc_type))
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
        if error is not None:
            raise error
        return value, 1

    module.OpenKey = open_key
    module.QueryValueEx = query_value
    return module


def check_machine_guid_reader() -> None:
    registry = fake_winreg(value=f"  {SYNTHETIC_GUID}  ")
    with patch.dict(sys.modules, {"winreg": registry}):
        require(read_windows_machine_guid(os_name="nt") == SYNTHETIC_GUID, "MachineGuid strip changed")
    require(registry.calls[0][0] == "OpenKey", "registry access order changed")
    root, path = registry.calls[0][1]
    require(root is registry.HKEY_LOCAL_MACHINE, "registry hive changed")
    require(path == r"SOFTWARE\Microsoft\Cryptography", "registry path changed")
    require(registry.calls[2][1][1] == "MachineGuid", "registry value name changed")

    unicode_value = "  11111111-2222-3333-4444-中文测试设备  "
    with patch.dict(sys.modules, {"winreg": fake_winreg(value=unicode_value)}):
        require(read_windows_machine_guid(os_name="nt") == unicode_value.strip(), "MachineGuid Unicode changed")

    for error in (
        FileNotFoundError("synthetic"),
        PermissionError("synthetic"),
        OSError("synthetic"),
        RuntimeError("synthetic"),
    ):
        with patch.dict(sys.modules, {"winreg": fake_winreg(error=error)}):
            require(read_windows_machine_guid(os_name="nt") == "", f"registry {type(error).__name__} changed")

    attempts: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "winreg":
            attempts.append(name)
            raise AssertionError("non-Windows reader imported winreg")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", guarded_import):
        require(read_windows_machine_guid(os_name="posix") == "", "non-Windows MachineGuid changed")
    require(attempts == [], "non-Windows reader accessed winreg")


class StdoutOnlyResult:
    def __init__(self, stdout: str | None) -> None:
        self._stdout = stdout

    @property
    def stdout(self) -> str | None:
        return self._stdout

    @property
    def returncode(self):
        raise AssertionError("volume reader accessed returncode")

    @property
    def stderr(self):
        raise AssertionError("volume reader accessed stderr")


def check_volume_reader() -> None:
    cases = (
        ("  ordinary output  ", "ordinary output"),
        (" line one\r\nline two \r\n", "line one\r\nline two"),
        (" 驱动器 C 中的卷是 测试卷 \r\n 卷的序列号是 ABCD-1234 \r\n", "驱动器 C 中的卷是 测试卷 \r\n 卷的序列号是 ABCD-1234"),
        ("  Unicode-Ω-测试  \n", "Unicode-Ω-测试"),
        ("", ""),
        (None, ""),
    )
    for stdout, expected in cases:
        calls: list[tuple[str, str]] = []

        def execute(command: str, shell: str):
            calls.append((command, shell))
            return StdoutOnlyResult(stdout)

        actual = read_windows_volume_stdout(execute, os_name="nt")
        require(actual == expected, f"volume stdout changed for {stdout!r}")
        require(calls == [(r"vol C:", "cmd")], "volume command/shell changed")

    for error in (FileNotFoundError("synthetic"), PermissionError("synthetic"), OSError("synthetic"), RuntimeError("synthetic")):
        def fail(command: str, shell: str, *, current_error=error):
            raise current_error

        require(read_windows_volume_stdout(fail, os_name="nt") == "", f"volume {type(error).__name__} changed")

    non_windows_calls: list[tuple[str, str]] = []

    def forbidden(command: str, shell: str):
        non_windows_calls.append((command, shell))
        raise AssertionError("non-Windows volume executed")

    require(read_windows_volume_stdout(forbidden, os_name="posix") == "", "non-Windows volume changed")
    require(non_windows_calls == [], "non-Windows volume called executor")


def check_fallback_reader() -> None:
    calls: list[str] = []

    def source(name: str, value: object):
        return lambda: calls.append(name) or value

    actual = read_legacy_machine_fallback(
        system_reader=source("system", " Win Dows "),
        release_reader=source("release", 0),
        version_reader=source("version", "版本 Ω"),
        hostname_reader=source("hostname", None),
        username_reader=source("username", " Test|User "),
    )
    require(calls == ["system", "release", "version", "hostname", "username"], "fallback source order changed")
    require(actual == " Win Dows |版本 Ω| Test|User ", "fallback filtering/str/whitespace changed")

    marker = RuntimeError("synthetic fallback failure")

    def fail():
        raise marker

    try:
        read_legacy_machine_fallback(
            system_reader=lambda: "Windows",
            release_reader=fail,
            version_reader=lambda: "unused",
            hostname_reader=lambda: "unused",
            username_reader=lambda: "unused",
        )
    except RuntimeError as exc:
        require(exc is marker, "fallback exception identity changed")
    else:
        raise AssertionError("fallback exception was swallowed")


def check_legacy_v1_pure_functions() -> None:
    parts = synthetic_parts()
    before = parts.to_legacy_dict()
    serialized = serialize_legacy_v1(parts)
    require(serialized == SYNTHETIC_RAW, "legacy-v1 serialization changed")
    require(serialized.encode("utf-8") == SYNTHETIC_RAW.encode("utf-8"), "legacy-v1 UTF-8 changed")
    require(hash_legacy_v1_serialized(serialized) == SYNTHETIC_HWID, "legacy-v1 hash changed")
    require(build_legacy_v1_machine_id(parts) == SYNTHETIC_HWID, "legacy-v1 builder changed")
    require(len(SYNTHETIC_HWID) == 64 and SYNTHETIC_HWID == SYNTHETIC_HWID.upper(), "digest shape changed")
    require(not SYNTHETIC_HWID.startswith("legacy-v1"), "digest gained a version prefix")
    require(parts.to_legacy_dict() == before, "pure functions mutated parts")

    metadata_changed = synthetic_parts(python="99.0", platform="Changed-Platform")
    require(build_legacy_v1_machine_id(metadata_changed) == SYNTHETIC_HWID, "metadata entered legacy hash")
    require(build_legacy_v1_machine_id({}) == hashlib.sha256("||||".encode("utf-8")).hexdigest().upper(), "missing-key behavior changed")


def check_legacy_provider_equivalence() -> None:
    fixtures = {
        "linux": (
            "Linux",
            "6.8.0",
            "#1 SMP TEST",
            "88C6137B8F89084E65EA078CF480A2AC086283BA3B7A86EFCDE1728704CCAB25",
        ),
        "macos": (
            "Darwin",
            "24.0.0",
            "Darwin Kernel Version TEST",
            "342F9C1D38D8A23E971C3FECA0165BDD056C4ADFFB522EEE6B2A07A48D5CA38F",
        ),
        "unknown": (
            "MysteryOS",
            "1",
            "Fixture Version",
            "15A0CDBDB1C39F560AF8222AC4CD2E5456BA608FB9EA9B7EC9E019BC892C67FE",
        ),
    }
    ids: dict[str, str] = {}
    for label, (system, release, version, expected_id) in fixtures.items():
        fallback = read_legacy_machine_fallback(
            system_reader=lambda value=system: value,
            release_reader=lambda value=release: value,
            version_reader=lambda value=version: value,
            hostname_reader=lambda: "TEST-HOST",
            username_reader=lambda: "TestUser",
        )
        provider = get_hardware_identity_provider(
            platform_info=platform_fixture(label),
            fallback_reader=lambda value=fallback: value,
            python_version_reader=lambda: "3.13.9",
            platform_metadata_reader=lambda value=label: value,
        )
        parts = provider.collect_parts()
        require(parts.machine_guid == "" and parts.volume_serial == "", f"{label} Windows values changed")
        ids[label] = build_legacy_v1_machine_id(parts)
        require(ids[label] == expected_id, f"{label} fixed legacy digest changed")
    require(len(set(ids.values())) == 3, "legacy fixture algorithms collapsed")


def check_injected_reader_exception_boundary() -> None:
    marker = RuntimeError("synthetic injected reader failure")

    def fail() -> str:
        raise marker

    provider = get_hardware_identity_provider(
        platform_info=platform_fixture("windows"),
        command_executor=lambda command, shell: StdoutOnlyResult(SYNTHETIC_VOLUME),
        machine_guid_reader=fail,
        volume_reader=lambda: SYNTHETIC_VOLUME,
        fallback_reader=lambda: SYNTHETIC_FALLBACK,
        python_version_reader=lambda: "3.13.9",
        platform_metadata_reader=lambda: "Windows-SYNTHETIC",
    )
    try:
        provider.collect_parts()
    except RuntimeError as exc:
        require(exc is marker, "provider changed injected-reader exception")
    else:
        raise AssertionError("provider swallowed injected-reader exception")


def check_facade_compatibility_and_counts() -> None:
    expected_signatures = {
        "_read_windows_machine_guid": "() -> 'str'",
        "_read_machine_sid_fallback": "() -> 'str'",
        "_read_volume_serial": "() -> 'str'",
        "get_machine_fingerprint_parts": "() -> 'Dict[str, str]'",
        "get_machine_id": "() -> 'str'",
        "format_machine_id": "(machine_id: 'str', group: 'int' = 4) -> 'str'",
    }
    for name, expected in expected_signatures.items():
        require(str(inspect.signature(getattr(hwid, name))) == expected, f"facade signature changed: {name}")

    counts = {name: 0 for name in ("factory", "machine_guid", "volume", "fallback", "python", "platform")}
    original_factory = hwid.get_hardware_identity_provider

    def source(name: str, value: str):
        def read() -> str:
            counts[name] += 1
            return value

        return read

    def factory_spy(**kwargs):
        counts["factory"] += 1
        original_python = kwargs["python_version_reader"]

        def python_reader() -> str:
            counts["python"] += 1
            return original_python()

        kwargs["python_version_reader"] = python_reader
        return original_factory(**kwargs)

    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.object(hwid, "get_hardware_identity_provider", factory_spy),
        patch.object(hwid, "_read_windows_machine_guid", source("machine_guid", SYNTHETIC_GUID)),
        patch.object(hwid, "_read_volume_serial", source("volume", SYNTHETIC_VOLUME)),
        patch.object(hwid, "_read_machine_sid_fallback", source("fallback", SYNTHETIC_FALLBACK)),
        patch.object(hwid.platform, "platform", source("platform", "Windows-SYNTHETIC")),
    ):
        first = hwid.get_machine_fingerprint_parts()
        second = hwid.get_machine_fingerprint_parts()

    require(type(first) is dict and tuple(first) == ("machine_guid", "volume_serial", "fallback", "python", "platform"), "facade dict changed")
    require(first == second, "deterministic synthetic facade parts changed")
    require(all(value == 2 for value in counts.values()), f"facade did not recollect each reader once: {counts}")

    id_calls = 0

    def collect_once():
        nonlocal id_calls
        id_calls += 1
        return synthetic_parts().to_legacy_dict()

    with patch.object(hwid, "get_machine_fingerprint_parts", collect_once):
        first_id = hwid.get_machine_id()
        second_id = hwid.get_machine_id()
    require(first_id == SYNTHETIC_HWID and second_id == SYNTHETIC_HWID, "facade ID changed")
    require(id_calls == 2, "get_machine_id did not collect exactly once per call")
    require(hwid.format_machine_id("ab-cd 12_34", 3) == "ABC-D12-34", "format facade changed")

    integrated_counts = {
        name: 0
        for name in ("factory", "machine_guid", "volume", "fallback", "python", "platform")
    }

    def integrated_source(name: str, value: str):
        def read() -> str:
            integrated_counts[name] += 1
            return value

        return read

    def integrated_factory(**kwargs):
        integrated_counts["factory"] += 1
        original_python = kwargs["python_version_reader"]

        def python_reader() -> str:
            integrated_counts["python"] += 1
            return original_python()

        kwargs["python_version_reader"] = python_reader
        return original_factory(**kwargs)

    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.object(hwid, "get_hardware_identity_provider", integrated_factory),
        patch.object(hwid, "_read_windows_machine_guid", integrated_source("machine_guid", SYNTHETIC_GUID)),
        patch.object(hwid, "_read_volume_serial", integrated_source("volume", SYNTHETIC_VOLUME)),
        patch.object(hwid, "_read_machine_sid_fallback", integrated_source("fallback", SYNTHETIC_FALLBACK)),
        patch.object(hwid.platform, "platform", integrated_source("platform", "Windows-SYNTHETIC")),
    ):
        require(hwid.get_machine_id() == SYNTHETIC_HWID, "integrated first ID changed")
        require(hwid.get_machine_id() == SYNTHETIC_HWID, "integrated second ID changed")
    require(
        all(value == 2 for value in integrated_counts.values()),
        f"two ID calls did not reacquire every reader exactly twice: {integrated_counts}",
    )

    helper_calls: list[str] = []

    def helper(name: str, value: str):
        return lambda: helper_calls.append(name) or value

    with (
        patch.object(hwid, "os", SimpleNamespace(name="nt")),
        patch.object(hwid, "_read_windows_machine_guid", helper("machine_guid", SYNTHETIC_GUID)),
        patch.object(hwid, "_read_volume_serial", helper("volume", SYNTHETIC_VOLUME)),
        patch.object(hwid, "_read_machine_sid_fallback", helper("fallback", SYNTHETIC_FALLBACK)),
        patch.object(hwid.platform, "platform", helper("platform", "Windows-SYNTHETIC")),
    ):
        require(hwid.get_machine_id() == SYNTHETIC_HWID, "private helper seam no longer controls ID")
    require(helper_calls == ["machine_guid", "volume", "fallback", "platform"], "private helper order/count changed")


def check_source_and_fake_frozen_imports() -> None:
    script = r'''
import builtins
import getpass
import os
import socket
import subprocess
import sys

mode = sys.argv[1]
if mode == "frozen":
    sys.frozen = True
    sys._MEIPASS = r"X:\SYNTHETIC\MEIPASS"

def forbidden(*args, **kwargs):
    raise AssertionError("identity import performed a guarded side effect")

socket.gethostname = forbidden
getpass.getuser = forbidden
socket.socket = forbidden
os.system = forbidden
subprocess.Popen = forbidden
sys.modules.pop("winreg", None)
original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "winreg":
        raise AssertionError("identity import accessed winreg")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
cwd = os.getcwd()
environment = dict(os.environ)
from shared.platform.base import PlatformInfo
from shared.platform.identity import HardwareIdentityParts, build_legacy_v1_machine_id, get_hardware_identity_provider
import licensing.hwid

provider = get_hardware_identity_provider(
    platform_info=PlatformInfo("windows", "x86_64", "nt", "win32"),
    command_executor=forbidden,
)
parts = HardwareIdentityParts("SYNTHETIC", "SYNTHETIC", "SYNTHETIC", "3.13.9", "SYNTHETIC")
assert build_legacy_v1_machine_id(parts)
assert provider.platform_info.system == "windows"
assert "winreg" not in sys.modules
assert os.getcwd() == cwd
assert dict(os.environ) == environment
print("import-ok:" + mode)
'''
    for mode in ("source", "frozen"):
        completed = subprocess.run(
            [sys.executable, "-c", script, mode],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        require(completed.returncode == 0, f"{mode} import probe failed: {completed.stderr}")
        require(completed.stdout.strip() == f"import-ok:{mode}", f"{mode} import probe output changed")


def check_side_effects() -> None:
    require(Path.cwd() == CWD_BEFORE_IMPORT, "HWID provider smoke changed cwd")
    require(os.environ == ENVIRONMENT_BEFORE_IMPORT, "HWID provider smoke changed environment")


def main() -> int:
    try:
        check_static_module_boundary()
        check_parts_contract()
        check_provider_selection_and_construction()
        check_windows_collection_order()
        check_windows_default_provider_integration()
        check_machine_guid_reader()
        check_volume_reader()
        check_fallback_reader()
        check_legacy_v1_pure_functions()
        check_legacy_provider_equivalence()
        check_injected_reader_exception_boundary()
        check_facade_compatibility_and_counts()
        check_source_and_fake_frozen_imports()
        check_side_effects()
    finally:
        if WINREG_BEFORE_IMPORT is not None:
            sys.modules["winreg"] = WINREG_BEFORE_IMPORT
        else:
            sys.modules.pop("winreg", None)

    print("hwid provider smoke ok")
    print("provider=windows,legacy-posix,per-call,no-cache")
    print("parts=machine_guid,volume_serial,fallback,python,platform;frozen=true")
    print("collection=machine-guid,volume,fallback-five-sources,python,platform;once-each")
    print("command_executor=injected,stdout-only,vol-c-cmd,no-runtime-import")
    print("windows_fixture_sha256=" + SYNTHETIC_HWID)
    print("facade=signatures-and-private-helper-monkeypatch-preserved")
    print("imports=source-and-fake-frozen,collection-side-effects-none")
    print("native_identity=linux:none,macos:none,unknown:none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
