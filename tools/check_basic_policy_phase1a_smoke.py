"""Phase 1a Basic policy core tests.

These tests exercise the unused production module shared.basic_policy against
the Phase 0 synthetic fixtures plus Phase 1a regression cases. They do not
build or run exported EXEs, invoke PyInstaller, collect hardware identity,
read real licenses or private keys, or load real user plans.

Run with the project interpreter:

    python tools/check_basic_policy_phase1a_smoke.py
"""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.basic_policy import (
    BasicPolicyDependencies,
    BasicPolicyResult,
    DriveLocality,
    FilesystemInspector,
    ShortcutResolution,
    validate_basic_plan,
    validate_basic_plan_document,
)
from shared.models import AppStep, Plan, UrlStep, plan_from_dict


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "dual_edition_phase0"
FAILURES: list[str] = []

SYNTHETIC_EXISTING_FILES = (
    r"C:\LaunchFlow-Synthetic\Apps\Editor.exe",
    r"C:\LaunchFlow-Synthetic\Apps\Viewer.exe",
    r"C:\LaunchFlow-Synthetic\Apps\bootstrap.ps1",
    r"C:\LaunchFlow-Synthetic\Shortcuts\Editor.lnk",
    r"C:\LaunchFlow-Synthetic\Shortcuts\Broken.lnk",
    r"C:\LaunchFlow-Synthetic\Shortcuts\EditorWithArgs.lnk",
    r"C:\LaunchFlow-Synthetic\Shortcuts\RunScript.lnk",
    r"C:\LaunchFlow-Synthetic\Shortcuts\NetworkApp.lnk",
    r"C:\LaunchFlow-Synthetic\Browsers\FakeBrowser.exe",
    r"Z:\Apps\example.exe",
    r"Y:\Apps\example.exe",
    r"Q:\Apps\example.exe",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_path(category: str, name: str) -> Path:
    return FIXTURE_ROOT / category / name


def _normalize_windows(path: str) -> str:
    return str(path).replace("/", "\\").strip().lower()


class SyntheticFilesystem:
    """In-memory inspector for Phase 0 / Phase 1a synthetic paths only."""

    def __init__(
        self,
        files: tuple[str, ...] = SYNTHETIC_EXISTING_FILES,
        directories: tuple[str, ...] = (),
        raise_on: str | None = None,
    ) -> None:
        self.files = {_normalize_windows(path) for path in files}
        self.directories = {_normalize_windows(path) for path in directories}
        self.raise_on = raise_on

    def path_exists(self, path: str) -> bool:
        if self.raise_on and _normalize_windows(path) == _normalize_windows(self.raise_on):
            raise RuntimeError("synthetic filesystem probe failed")
        key = _normalize_windows(path)
        return key in self.files or key in self.directories

    def is_directory(self, path: str) -> bool:
        if self.raise_on and _normalize_windows(path) == _normalize_windows(self.raise_on):
            raise RuntimeError("synthetic filesystem probe failed")
        return _normalize_windows(path) in self.directories


class SyntheticDriveClassifier:
    def __init__(
        self,
        *,
        local: str = "CD",
        remote: str = "Z",
        unknown: str = "Y",
        raise_on: str | None = None,
        result: DriveLocality | str | None = None,
    ) -> None:
        self.local = {letter.upper() for letter in local}
        self.remote = {letter.upper() for letter in remote}
        self.unknown = {letter.upper() for letter in unknown}
        self.raise_on = raise_on.upper() if raise_on else None
        self.result = result

    def classify_drive(self, path: str) -> DriveLocality | str:
        text = str(path).replace("/", "\\").strip()
        letter = text[0].upper() if text and text[1:2] == ":" else ""
        if self.raise_on and letter == self.raise_on:
            raise RuntimeError("synthetic drive classification failed")
        if self.result is not None:
            return self.result
        if letter in self.local:
            return DriveLocality.LOCAL
        if letter in self.remote:
            return DriveLocality.REMOTE
        if letter in self.unknown:
            return DriveLocality.UNKNOWN
        return DriveLocality.UNAVAILABLE


class SyntheticShortcutResolver:
    def __init__(self, table: Mapping[str, Mapping[str, Any]], *, error_on: str | None = None) -> None:
        self.table = {str(key): value for key, value in table.items()}
        self.error_on = error_on

    def resolve_shortcut(self, path: str) -> Mapping[str, Any] | None:
        if self.error_on is not None and path == self.error_on:
            raise RuntimeError("synthetic shortcut resolver failed")
        return self.table.get(path)


def load_shortcut_table() -> dict[str, Mapping[str, Any]]:
    payload = load_json(FIXTURE_ROOT / "shortcut_resolutions.json")
    raw = payload.get("paths", payload)
    return {str(key): value for key, value in raw.items()}


def default_dependencies(
    *,
    filesystem: FilesystemInspector | None = None,
    drive_classifier: SyntheticDriveClassifier | None = None,
    shortcut_resolver: Any = None,
) -> BasicPolicyDependencies:
    table = load_shortcut_table()
    return BasicPolicyDependencies(
        filesystem=filesystem if filesystem is not None else SyntheticFilesystem(),
        drive_classifier=(
            drive_classifier if drive_classifier is not None else SyntheticDriveClassifier()
        ),
        shortcut_resolver=(
            shortcut_resolver
            if shortcut_resolver is not None
            else SyntheticShortcutResolver(table)
        ),
    )


def validate(document: Any, deps: BasicPolicyDependencies | None = None) -> BasicPolicyResult:
    return validate_basic_plan_document(document, dependencies=deps or default_dependencies())


def load_manifest() -> dict[str, Any]:
    return load_json(FIXTURE_ROOT / "manifest.json")


def single_app_plan(path: str, **overrides: Any) -> dict[str, Any]:
    step = {
        "id": "step-t001",
        "type": "app",
        "name": "Synthetic Target",
        "enabled": True,
        "delay_after": 1.0,
        "path": path,
        "args": [],
        "working_dir": "",
        "start_minimized": False,
    }
    step.update(overrides)
    return {
        "plan_name": "Phase1a Synthetic Plan",
        "version": "1.0.0",
        "steps": [step],
    }


def check_phase0_fixture_results() -> None:
    manifest = load_manifest()
    require(manifest.get("synthetic") is True, "Phase 0 fixture manifest must remain synthetic")
    require(manifest["counts"]["basic_valid"] == 8, "expected 8 Basic-valid fixtures")
    require(manifest["counts"]["basic_invalid"] == 17, "expected 17 Basic-invalid fixtures")
    require(manifest["counts"]["professional"] == 7, "expected 7 Professional fixtures")

    deps = default_dependencies()
    for name in manifest["basic_valid"]:
        plan = load_json(fixture_path("basic_valid", name))
        result = validate(plan, deps)
        require(result.accepted, f"Basic-valid fixture {name} was rejected: {result.error_messages}")

    expected_codes = {
        "command.json": "basic_unsupported_step_type",
        "cmd.json": "basic_unsupported_step_type",
        "powershell.json": "basic_unsupported_step_type",
        "wait.json": "basic_unsupported_step_type",
        "non_one_second_delay.json": "basic_incompatible_delay",
        "non_empty_arguments.json": "basic_custom_arguments_forbidden",
        "non_empty_working_directory.json": "basic_custom_working_dir_forbidden",
        "custom_browser.json": "basic_custom_browser_forbidden",
        "non_default_start_minimized.json": "basic_custom_start_minimized_forbidden",
        "invalid_lnk.json": "basic_invalid_lnk",
        "lnk_with_arguments.json": "basic_lnk_arguments_forbidden",
        "script_target.json": "basic_script_or_unsupported_target",
        "network_target.json": "basic_network_target_forbidden",
        "unsupported_url_scheme.json": "basic_unsupported_url_scheme",
        "unknown_fields.json": "unknown_plan_fields",
        "disabled_unsupported_steps.json": "basic_unsupported_step_type",
        "unsupported_step_after_valid_steps.json": "basic_unsupported_step_type",
    }
    for name in manifest["basic_invalid"]:
        plan = load_json(fixture_path("basic_invalid", name))
        result = validate(plan, deps)
        require(not result.accepted, f"Basic-invalid fixture {name} was accepted")
        codes = {issue.code for issue in result.issues}
        expected = expected_codes[name]
        require(expected in codes, f"{name} expected code {expected}, got {sorted(codes)}")

    for name in manifest["professional"]:
        plan = load_json(fixture_path("professional", name))
        result = validate(plan, deps)
        require(
            not result.accepted,
            f"Professional fixture {name} was accidentally accepted as Basic: {result.error_messages}",
        )


def check_disabled_and_trailing_unsupported_steps() -> None:
    deps = default_dependencies()
    disabled = load_json(fixture_path("basic_invalid", "disabled_unsupported_steps.json"))
    trailing = load_json(fixture_path("basic_invalid", "unsupported_step_after_valid_steps.json"))
    disabled_result = validate(disabled, deps)
    trailing_result = validate(trailing, deps)
    require(not disabled_result.accepted, "disabled unsupported steps were accepted")
    require(not trailing_result.accepted, "unsupported step after valid steps was accepted")
    require(
        disabled["steps"][1]["enabled"] is False and disabled["steps"][2]["enabled"] is False,
        "disabled unsupported fixture was mutated or no longer disabled",
    )
    require(
        trailing["steps"][0]["type"] == "app" and trailing["steps"][2]["type"] == "wait",
        "trailing unsupported fixture shape changed",
    )
    require(
        any(issue.step_index == 1 for issue in disabled_result.issues),
        "disabled command step was not cited",
    )
    require(
        any(issue.step_index == 2 for issue in trailing_result.issues),
        "trailing wait step was not cited",
    )


def check_unknown_fields_before_deserialization() -> None:
    plan = load_json(fixture_path("basic_invalid", "unknown_fields.json"))
    original = copy.deepcopy(plan)
    imported = {"plan_from_dict_called": False}
    real_plan_from_dict = plan_from_dict

    def wrapped(data):
        imported["plan_from_dict_called"] = True
        return real_plan_from_dict(data)

    import shared.models as models_module
    import shared.basic_policy as policy_module

    original_imported = policy_module.plan_from_dict if hasattr(policy_module, "plan_from_dict") else None
    models_original = models_module.plan_from_dict
    models_module.plan_from_dict = wrapped  # type: ignore[assignment]
    if original_imported is not None:
        policy_module.plan_from_dict = wrapped  # type: ignore[attr-defined]
    try:
        result = validate(plan)
    finally:
        models_module.plan_from_dict = models_original
        if original_imported is not None:
            policy_module.plan_from_dict = original_imported  # type: ignore[attr-defined]

    require(not result.accepted, "unknown raw JSON fields were accepted")
    require(
        any(issue.code == "unknown_plan_fields" for issue in result.issues),
        "unknown root field was not reported before deserialization",
    )
    require(
        any(issue.code == "unknown_step_fields" for issue in result.issues),
        "unknown step field was not reported before deserialization",
    )
    require(plan == original, "unknown-field validation mutated the raw document")
    require("edition" in plan and "edition" in plan["steps"][0], "unknown fields were dropped from the input")
    require(imported["plan_from_dict_called"] is False, "raw validation called plan_from_dict")
    try:
        plan_from_dict(original)
        require(False, "plan_from_dict unexpectedly accepted unknown step fields")
    except TypeError:
        pass


def check_delay_values() -> None:
    deps = default_dependencies()
    accepted = []
    for value in (1, 1.0):
        plan = single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe", delay_after=value)
        result = validate(plan, deps)
        accepted.append(result.accepted)
        require(result.accepted, f"exact one-second value {value!r} was rejected: {result.error_messages}")

    rejected_values = (
        True,
        False,
        0,
        0.0,
        2,
        2.0,
        -1,
        1.0000001,
        0.9999999,
        math.nan,
        math.inf,
        -math.inf,
        "1.0",
        "1",
        None,
    )
    for value in rejected_values:
        plan = single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe", delay_after=value)
        result = validate(plan, deps)
        require(not result.accepted, f"incompatible delay {value!r} was accepted")
        require(
            any(issue.code == "basic_incompatible_delay" for issue in result.issues),
            f"incompatible delay {value!r} did not use basic_incompatible_delay: "
            + str(result.error_messages),
        )

    missing = load_json(fixture_path("basic_valid", "empty_optional_fields.json"))
    require("delay_after" not in missing["steps"][0], "empty optional fixture now has a delay")
    require(validate(missing, deps).accepted, "missing delay_after should default to the allowed 1.0")


def check_unc_and_drive_classification() -> None:
    deps = default_dependencies()
    unc = load_json(fixture_path("basic_invalid", "network_target.json"))
    unc_result = validate(unc, deps)
    require(not unc_result.accepted, "UNC fixture was accepted")
    require(
        any(issue.code == "basic_network_target_forbidden" for issue in unc_result.issues),
        "UNC path was not rejected as a network target",
    )

    slash_unc = single_app_plan("//fileserver.example.test/share/Tools/Editor.exe")
    slash_result = validate(slash_unc, deps)
    require(not slash_result.accepted, "forward-slash UNC path was accepted")
    require(
        any(issue.code == "basic_network_target_forbidden" for issue in slash_result.issues),
        "forward-slash UNC path was not rejected as a network target",
    )

    remote = validate(single_app_plan(r"Z:\Apps\example.exe"), deps)
    require(not remote.accepted, "injected remote drive was accepted")
    require(
        any(issue.code == "basic_mapped_or_remote_drive_forbidden" for issue in remote.issues),
        "mapped/remote drive was not rejected through the injected classifier",
    )

    unknown = validate(single_app_plan(r"Y:\Apps\example.exe"), deps)
    require(not unknown.accepted, "unknown drive classification was accepted")
    require(
        any(issue.code == "basic_drive_locality_unknown" for issue in unknown.issues),
        "unknown drive classification did not fail closed",
    )

    unavailable = validate(
        single_app_plan(r"Q:\Apps\example.exe"),
        default_dependencies(),
    )
    require(not unavailable.accepted, "unavailable drive classification was accepted")
    require(
        any(issue.code == "basic_drive_locality_unknown" for issue in unavailable.issues),
        "unavailable drive classification did not fail closed",
    )

    missing_classifier = validate_basic_plan_document(
        single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe"),
        filesystem=SyntheticFilesystem(),
        drive_classifier=None,
        shortcut_resolver=SyntheticShortcutResolver(load_shortcut_table()),
    )
    require(not missing_classifier.accepted, "missing drive classifier was accepted")
    require(
        any(issue.code == "basic_drive_locality_unknown" for issue in missing_classifier.issues),
        "missing drive classifier did not fail closed",
    )

    raising = validate(
        single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe"),
        default_dependencies(drive_classifier=SyntheticDriveClassifier(raise_on="C")),
    )
    require(not raising.accepted, "raising drive classifier was accepted")
    require(
        any(issue.code == "basic_drive_locality_unknown" for issue in raising.issues),
        "raising drive classifier did not fail closed",
    )

    local = validate(single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe"), deps)
    require(local.accepted, f"local drive classification failed: {local.error_messages}")


def check_lnk_resolver_contracts() -> None:
    table = load_shortcut_table()
    deps = default_dependencies()

    missing = validate_basic_plan_document(
        load_json(fixture_path("basic_valid", "valid_local_exe_lnk.json")),
        filesystem=SyntheticFilesystem(),
        drive_classifier=SyntheticDriveClassifier(),
        shortcut_resolver=None,
    )
    require(not missing.accepted, "missing LNK resolver was accepted")
    require(
        any(issue.code == "basic_lnk_resolver_required" for issue in missing.issues),
        "missing LNK resolver did not fail closed",
    )

    exploding = validate(
        load_json(fixture_path("basic_valid", "valid_local_exe_lnk.json")),
        default_dependencies(
            shortcut_resolver=SyntheticShortcutResolver(
                table,
                error_on=r"C:\LaunchFlow-Synthetic\Shortcuts\Editor.lnk",
            )
        ),
    )
    require(not exploding.accepted, "resolver exception was accepted")
    require(
        any(issue.code == "basic_lnk_resolver_error" for issue in exploding.issues),
        "resolver exception did not fail closed",
    )

    with_args = validate(load_json(fixture_path("basic_invalid", "lnk_with_arguments.json")), deps)
    require(not with_args.accepted, "LNK with arguments was accepted")
    require(
        any(issue.code == "basic_lnk_arguments_forbidden" for issue in with_args.issues),
        "LNK with arguments used the wrong rejection code",
    )

    script = single_app_plan(r"C:\LaunchFlow-Synthetic\Shortcuts\RunScript.lnk")
    script_result = validate(script, deps)
    require(not script_result.accepted, "LNK targeting a script was accepted")
    require(
        any(
            issue.code in {"basic_lnk_unsupported_target_kind", "basic_lnk_non_exe_target"}
            for issue in script_result.issues
        ),
        "LNK script target used the wrong rejection code: " + str(script_result.error_messages),
    )

    network = single_app_plan(r"C:\LaunchFlow-Synthetic\Shortcuts\NetworkApp.lnk")
    network_result = validate(network, deps)
    require(not network_result.accepted, "LNK targeting a network location was accepted")
    require(
        any(issue.code == "basic_lnk_network_target_forbidden" for issue in network_result.issues),
        "LNK network target used the wrong rejection code: " + str(network_result.error_messages),
    )

    valid = validate(load_json(fixture_path("basic_valid", "valid_local_exe_lnk.json")), deps)
    require(valid.accepted, f"valid synthetic local EXE LNK was rejected: {valid.error_messages}")

    object_resolution = validate_basic_plan_document(
        load_json(fixture_path("basic_valid", "valid_local_exe_lnk.json")),
        filesystem=SyntheticFilesystem(),
        drive_classifier=SyntheticDriveClassifier(),
        shortcut_resolver=lambda _path: ShortcutResolution(
            target_path=r"C:\LaunchFlow-Synthetic\Apps\Editor.exe",
            target_kind="executable",
            arguments=(),
            working_directory="",
            status="resolved",
        ),
    )
    require(
        object_resolution.accepted,
        f"valid LNK with ShortcutResolution object was rejected: {object_resolution.error_messages}",
    )


def check_path_syntax_and_existence() -> None:
    deps = default_dependencies()
    cases = {
        r"Apps\Editor.exe": "basic_relative_path_forbidden",
        r".\Editor.exe": "basic_relative_path_forbidden",
        r"C:Editor.exe": "basic_relative_path_forbidden",
        r"\\.\C:\LaunchFlow-Synthetic\Apps\Editor.exe": "basic_device_path_forbidden",
        r"\\?\C:\LaunchFlow-Synthetic\Apps\Editor.exe": "basic_device_path_forbidden",
        r"C:\LaunchFlow-Synthetic\Apps\Missing.exe": "basic_target_missing",
        r"C:\LaunchFlow-Synthetic\Apps\bootstrap.com": "basic_script_or_unsupported_target",
        r"file:///C:/LaunchFlow-Synthetic/Apps/Editor.exe": "basic_network_target_forbidden",
    }
    for path, code in cases.items():
        result = validate(single_app_plan(path), deps)
        require(not result.accepted, f"path {path!r} was accepted")
        require(
            any(issue.code == code for issue in result.issues),
            f"path {path!r} expected {code}, got {sorted(issue.code for issue in result.issues)}",
        )

    missing_fs = validate_basic_plan_document(
        single_app_plan(r"C:\LaunchFlow-Synthetic\Apps\Editor.exe"),
        filesystem=None,
        drive_classifier=SyntheticDriveClassifier(),
        shortcut_resolver=SyntheticShortcutResolver(load_shortcut_table()),
    )
    require(not missing_fs.accepted, "missing filesystem inspector was accepted")
    require(
        any(issue.code == "basic_filesystem_unavailable" for issue in missing_fs.issues),
        "missing filesystem inspector did not fail closed",
    )


def check_input_is_not_mutated() -> None:
    deps = default_dependencies()
    manifest = load_manifest()
    samples = [
        load_json(fixture_path("basic_valid", name)) for name in manifest["basic_valid"]
    ] + [
        load_json(fixture_path("basic_invalid", name)) for name in manifest["basic_invalid"]
    ] + [
        load_json(fixture_path("professional", name)) for name in manifest["professional"]
    ]
    for plan in samples:
        original = copy.deepcopy(plan)
        validate(plan, deps)
        require(plan == original, f"validation mutated {plan.get('plan_name')}")

    model = Plan(
        plan_name="Phase1a Model Plan",
        version="1.0.0",
        steps=[
            AppStep(
                id="step-model1",
                name="Synthetic Editor",
                path=r"C:\LaunchFlow-Synthetic\Apps\Editor.exe",
                args=[],
                working_dir="",
                start_minimized=False,
                delay_after=1.0,
            ),
            UrlStep(
                id="step-model2",
                name="Synthetic HTTPS Site",
                url="https://example.com/launchflow-basic",
                browser_path="",
                delay_after=1.0,
            ),
        ],
    )
    before = copy.deepcopy(model.to_dict())
    result = validate_basic_plan(model, dependencies=deps)
    require(result.accepted, f"valid Plan object was rejected: {result.error_messages}")
    require(model.to_dict() == before, "validate_basic_plan mutated the Plan object")


def check_module_is_side_effect_free_and_unwired() -> None:
    module = importlib.import_module("shared.basic_policy")
    source = inspect.getsource(module)
    tree = ast.parse(source)
    disallowed_calls = {
        "Popen",
        "run",
        "urlopen",
        "startfile",
        "get_machine_id",
        "validate_current_license",
        "build_single_file_exe",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            require(name not in disallowed_calls, f"policy module calls disallowed function {name}")
    require("subprocess" not in source, "policy module must not import subprocess")
    require("PyInstaller" not in source, "policy module must not reference PyInstaller")
    require("ctypes" not in source, "policy module must not use ctypes/COM")
    require("winreg" not in source, "policy module must not use winreg")

    production_roots = [
        PROJECT_ROOT / "editor",
        PROJECT_ROOT / "runtime",
        PROJECT_ROOT / "licensing",
        PROJECT_ROOT / "tools" / "build_single_exe.py",
        PROJECT_ROOT / "tools" / "build_editor_release.py",
    ]
    offenders = []
    for root in production_roots:
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if "shared.basic_policy" in text or "from shared import basic_policy" in text:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    require(not offenders, "Basic policy module was imported by integration code: " + ", ".join(offenders))


def main() -> int:
    checks = [
        ("phase0_fixture_results", check_phase0_fixture_results),
        ("disabled_and_trailing_unsupported", check_disabled_and_trailing_unsupported_steps),
        ("unknown_fields_before_deserialization", check_unknown_fields_before_deserialization),
        ("delay_values", check_delay_values),
        ("unc_and_drive_classification", check_unc_and_drive_classification),
        ("lnk_resolver_contracts", check_lnk_resolver_contracts),
        ("path_syntax_and_existence", check_path_syntax_and_existence),
        ("input_is_not_mutated", check_input_is_not_mutated),
        ("module_side_effects_and_wiring", check_module_is_side_effect_free_and_unwired),
    ]
    for name, func in checks:
        before = len(FAILURES)
        try:
            func()
        except Exception as exc:  # pragma: no cover - unexpected test crash
            FAILURES.append(f"{name} crashed: {type(exc).__name__}: {exc}")
        added = len(FAILURES) - before
        status = "PASS" if added == 0 else "FAIL"
        print(f"{name}={status}")
    if FAILURES:
        print("dual_edition_phase1a_basic_policy=FAIL")
        for item in FAILURES:
            print(f"- {item}")
        return 1
    print("dual_edition_phase1a_basic_policy=PASS")
    print("pyinstaller_invoked=0")
    print("real_license_or_hwid_access=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
