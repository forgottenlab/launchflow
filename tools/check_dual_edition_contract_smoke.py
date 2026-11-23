"""Phase 0 Dual Edition contract tests.

These tests freeze Basic and Professional acceptance criteria using synthetic
fixtures only. They do not build or run exported EXEs, do not invoke
PyInstaller, do not collect hardware identity, and do not read real licenses,
private keys, or user plans.

Run with the project interpreter:

    python tools/check_dual_edition_contract_smoke.py
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.dual_edition_phase0_contract import (
    ENTRY_POINTS,
    BASIC_DATA_DIR_NAME,
    PROFESSIONAL_DATA_DIR_NAME,
    basic_export_preflight,
    basic_runner_source_violations,
    data_directory_names,
    load_shortcut_resolutions,
    professional_export_authorization_required,
    professional_runner_source_missing,
    require_no_basic_activation,
    validate_basic_entry_point,
    validate_basic_plan_dict,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "dual_edition_phase0"
FAILURES: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_path(category: str, name: str) -> Path:
    return FIXTURE_ROOT / category / name


def resolver_for_tests():
    table = load_shortcut_resolutions(FIXTURE_ROOT / "shortcut_resolutions.json")

    def resolve(path: str):
        return table.get(path)

    return resolve


def check_fixture_completeness() -> None:
    manifest = load_json(FIXTURE_ROOT / "manifest.json")
    require(manifest.get("synthetic") is True, "fixture manifest must declare synthetic=true")
    for category in ("basic_valid", "basic_invalid", "professional"):
        expected = list(manifest[category])
        actual = sorted(path.name for path in (FIXTURE_ROOT / category).glob("*.json"))
        require(actual == sorted(expected), f"{category} fixtures mismatch: expected={expected} actual={actual}")
        for name in expected:
            path = fixture_path(category, name)
            require(path.is_file(), f"missing fixture {category}/{name}")
            payload = load_json(path)
            require(isinstance(payload, dict), f"{category}/{name} is not a JSON object")
            require("plan_name" in payload and "steps" in payload, f"{category}/{name} is not a plan object")
            text = path.read_text(encoding="utf-8").lower()
            require("begin private" not in text, f"{category}/{name} looks like a private key")
            require(("-"*5+"begin") not in text, f"{category}/{name} contains a PEM block")
    require((FIXTURE_ROOT / "shortcut_resolutions.json").is_file(), "missing synthetic LNK oracle")
    require(manifest["counts"]["basic_valid"] == 8, "expected 8 Basic-valid fixtures")
    require(manifest["counts"]["basic_invalid"] == 17, "expected 17 Basic-invalid fixtures")
    require(manifest["counts"]["professional"] == 7, "expected 7 Professional fixtures")


def check_basic_accept_reject() -> None:
    manifest = load_json(FIXTURE_ROOT / "manifest.json")
    resolve = resolver_for_tests()
    for name in manifest["basic_valid"]:
        plan = load_json(fixture_path("basic_valid", name))
        result = validate_basic_plan_dict(plan, shortcut_resolver=resolve)
        require(
            result.accepted,
            f"Basic-valid fixture {name} was rejected: {result.error_messages}",
        )
        for entry_point in ENTRY_POINTS:
            entry_result = validate_basic_entry_point(plan, entry_point, shortcut_resolver=resolve)
            require(
                entry_result.accepted,
                f"Basic-valid fixture {name} rejected at {entry_point}: {entry_result.error_messages}",
            )
        export_result = basic_export_preflight(plan, shortcut_resolver=resolve)
        require(
            export_result.accepted,
            f"Basic-valid fixture {name} failed export preflight: {export_result.error_messages}",
        )
        require_no_basic_activation(False, False, False)

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
        result = validate_basic_plan_dict(plan, shortcut_resolver=resolve)
        require(not result.accepted, f"Basic-invalid fixture {name} was accepted")
        expected = expected_codes[name]
        codes = {issue.code for issue in result.issues}
        require(expected in codes, f"{name} expected code {expected}, got {sorted(codes)}")
        # Disabled or trailing unsupported steps must not bypass rejection.
        for entry_point in ENTRY_POINTS:
            entry_result = validate_basic_entry_point(plan, entry_point, shortcut_resolver=resolve)
            require(
                not entry_result.accepted,
                f"Basic-invalid fixture {name} was accepted at {entry_point}",
            )
        export_result = basic_export_preflight(plan, shortcut_resolver=resolve)
        require(not export_result.accepted, f"Basic-invalid fixture {name} passed export preflight")

    # A present incompatible delay must not be treated as 1s.
    delay_plan = load_json(fixture_path("basic_invalid", "non_one_second_delay.json"))
    require(delay_plan["steps"][0]["delay_after"] == 2.0, "delay fixture no longer has a non-1s value")
    normalized = deepcopy(delay_plan)
    normalized["steps"][0]["delay_after"] = 1.0
    require(
        validate_basic_plan_dict(normalized, shortcut_resolver=resolve).accepted,
        "control case with delay_after=1.0 should be accepted",
    )


def check_professional_compatibility() -> None:
    from shared.models import (
        AppStep,
        CommandStep,
        Plan,
        UrlStep,
        WaitStep,
        plan_from_dict,
    )
    from shared.plan_schema import validate_plan_dict

    manifest = load_json(FIXTURE_ROOT / "manifest.json")
    for name in manifest["professional"]:
        raw = load_json(fixture_path("professional", name))
        schema_errors = validate_plan_dict(raw)
        require(not schema_errors, f"Professional fixture {name} failed current schema: {schema_errors}")
        plan = plan_from_dict(raw)
        require(isinstance(plan, Plan), f"{name} did not parse to Plan")
        require(plan.plan_name == raw["plan_name"], f"{name} plan_name changed during parse")
        require(len(plan.steps) == len(raw["steps"]), f"{name} lost steps during parse")
        # Current schema remains the Professional compatibility baseline.
        require("edition" not in raw, f"{name} introduced an edition field into the plan schema")
        round_trip = plan.to_dict()
        reparsed = plan_from_dict(round_trip)
        require(
            reparsed.to_dict()["plan_name"] == plan.plan_name,
            f"{name} lost plan_name on round-trip",
        )
        require(len(reparsed.steps) == len(plan.steps), f"{name} lost steps on round-trip")
        for original, again in zip(plan.steps, reparsed.steps, strict=True):
            require(type(original) is type(again), f"{name} step type changed on round-trip")
            require(original.name == again.name, f"{name} step name changed on round-trip")
            require(original.delay_after == again.delay_after, f"{name} delay_after changed on round-trip")

    four = plan_from_dict(load_json(fixture_path("professional", "four_step_plan.json")))
    require(isinstance(four.steps[0], AppStep), "four-step plan lost AppStep")
    require(four.steps[0].args == ["--profile", "synth"], "advanced app args were weakened")
    require(four.steps[0].working_dir.endswith("Work"), "advanced working_dir was weakened")
    require(four.steps[0].start_minimized is True, "start_minimized was weakened")
    require(isinstance(four.steps[1], UrlStep) and four.steps[1].browser_path, "custom browser was weakened")
    require(isinstance(four.steps[2], CommandStep) and four.steps[2].shell == "cmd", "command configuration was weakened")
    require(isinstance(four.steps[3], WaitStep) and four.steps[3].seconds == 3.0, "wait behavior was weakened")

    commands = plan_from_dict(load_json(fixture_path("professional", "existing_command_configuration.json")))
    require(commands.steps[0].shell == "cmd" and commands.steps[1].shell == "powershell", "cmd/powershell contract changed")
    require(commands.steps[1].new_window is False, "PowerShell new_window contract was weakened")

    wait_plan = plan_from_dict(load_json(fixture_path("professional", "existing_wait_behavior.json")))
    require(wait_plan.steps[1].seconds == 4.5, "existing Wait seconds changed")
    require(wait_plan.steps[0].delay_after == 0.25, "Professional non-1s delay must remain legal")

    # Professional fixtures must not be rejected by the current structural schema
    # merely because Basic forbids those capabilities.
    for name in ("command.json", "wait.json", "powershell.json", "non_one_second_delay.json"):
        raw = load_json(fixture_path("basic_invalid", name))
        require(not validate_plan_dict(raw), f"current schema unexpectedly rejected {name}")
        require(
            not validate_basic_plan_dict(raw, shortcut_resolver=resolver_for_tests()).accepted,
            f"Basic contract unexpectedly accepted {name}",
        )


def check_export_contracts() -> None:
    from tools import build_single_exe

    resolve = resolver_for_tests()
    source = Path(build_single_exe.__file__).read_text(encoding="utf-8")
    template = build_single_exe.EMBEDDED_TEMPLATE
    require("def build_single_file_exe(" in source, "missing build_single_file_exe")
    require("def _prepare_embedded_plan_and_assets(" in source, "missing asset/plan preparation")
    require("_get_pyinstaller_command" in source, "missing PyInstaller command helper")
    require("--onefile" in source and "--windowed" in source, "PyInstaller flags changed")
    require("output_exe_path.parent.mkdir" in source, "exporter still creates the output directory first")
    mkdir_pos = source.index("output_exe_path.parent.mkdir")
    pyinstaller_pos = source.index("subprocess.run(command, check=True)")
    require(mkdir_pos < pyinstaller_pos, "output mkdir no longer happens before PyInstaller")
    exporter_fn = inspect.getsource(build_single_exe.build_single_file_exe)
    require("LicenseManager" not in source and "get_machine_id" not in source, "exporter unexpectedly depends on licensing or HWID")
    require("LicenseManager" not in exporter_fn and "validate_current_license" not in exporter_fn, "build_single_file_exe unexpectedly checks licenses")
    require("run_command_step" in template and "run_wait_step" in template, "current runner no longer embeds command/wait")
    require("os.startfile(path)" in template, "current runner no longer shell-opens shortcuts")
    missing_professional = professional_runner_source_missing(template)
    require(not missing_professional, f"Professional runner symbols missing from current template: {missing_professional}")
    # Frozen Basic runner contract: the current unrestricted template is NOT compliant.
    basic_violations = basic_runner_source_violations(template)
    require(
        "run_command_step" in basic_violations and "run_wait_step" in basic_violations,
        "current embedded runner unexpectedly already satisfies the Basic capability boundary",
    )
    require(
        "LicenseManager" not in basic_violations and "get_machine_id" not in basic_violations,
        "current embedded runner unexpectedly gained a licensing or identity dependency",
    )

    # Export preflight must not create files or invoke packagers.
    ignored_parts = {".git", "__pycache__", ".tmp", ".gui-smoke-tmp", "dist", "build"}
    def _existing_files() -> dict[Path, int]:
        found: dict[Path, int] = {}
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file() or ignored_parts.intersection(path.parts):
                continue
            found[path] = path.stat().st_mtime_ns
        return found

    before = _existing_files()
    accepted = basic_export_preflight(
        load_json(fixture_path("basic_valid", "mixed_app_url.json")),
        shortcut_resolver=resolve,
    )
    rejected = basic_export_preflight(
        load_json(fixture_path("basic_invalid", "command.json")),
        shortcut_resolver=resolve,
    )
    after = _existing_files()
    require(accepted.accepted and not rejected.accepted, "export preflight accept/reject contract failed")
    require(before == after, "Basic export preflight mutated the workspace")
    require_no_basic_activation(False, False, False)
    try:
        professional_export_authorization_required(False)
        require(False, "Professional export authorization failed open")
    except Exception as exc:
        require("activation" in str(exc).lower(), f"unexpected Professional authorization error: {exc}")
    professional_export_authorization_required(True)

    prepared_plan = load_json(fixture_path("professional", "existing_independent_export_expectations.json"))
    original = deepcopy(prepared_plan)
    embedded, assets = build_single_exe._prepare_embedded_plan_and_assets(prepared_plan)
    require(prepared_plan == original, "preparing an embedded plan mutated the caller plan")
    # Synthetic EXE/script files do not exist, so no assets should be staged from this fixture.
    require(assets == [], "synthetic missing files were unexpectedly staged as assets")
    steps = {step["id"]: step for step in embedded["steps"]}
    require(steps["step-pex006"]["type"] == "command" and "_command_launch" in steps["step-pex006"], "command launch contract was not serialized")
    require(steps["step-pex007"]["_command_launch"]["command_args"], "PowerShell command args were not serialized")
    require(steps["step-pex004"]["_url_open"]["open_mode"] == "shell_open", "default URL open mode changed")
    require(steps["step-pex005"]["_url_open"]["open_mode"] == "process", "explicit browser URL mode changed")
    require(steps["step-pex003"]["_application_launch"]["launch_mode"] == "shell_open", "LNK export mode changed")
    require(steps["step-pex003"]["_application_launch"]["resolved_target"].lower().endswith(".lnk"), "LNK export now rewrites the shortcut target")
    require("_embedded_asset" not in steps["step-pex003"], "LNK was unexpectedly packed as an asset")
    require(steps["step-pex008"]["type"] == "wait" and steps["step-pex008"]["seconds"] == 2.0, "Wait export payload changed")

    # Direct exporter entry must not be a Basic bypass in the frozen contract:
    # an incompatible plan is rejected by preflight even if a caller would
    # otherwise invoke build_single_file_exe directly.
    require(
        not basic_export_preflight(prepared_plan, shortcut_resolver=resolve).accepted,
        "Professional export fixture was accepted by the Basic export preflight",
    )


def check_current_architecture_boundaries() -> None:
    main_source = (PROJECT_ROOT / "editor" / "main.py").read_text(encoding="utf-8")
    window_source = (PROJECT_ROOT / "editor" / "ui" / "main_window.py").read_text(encoding="utf-8")
    runtime_source = (PROJECT_ROOT / "runtime" / "launcher_runtime.py").read_text(encoding="utf-8")
    apps_source = (PROJECT_ROOT / "shared" / "platform" / "applications.py").read_text(encoding="utf-8")
    paths_source = (PROJECT_ROOT / "shared" / "app_paths.py").read_text(encoding="utf-8")
    platform_paths = (PROJECT_ROOT / "shared" / "platform" / "paths.py").read_text(encoding="utf-8")
    migration_source = (PROJECT_ROOT / "shared" / "data_migration.py").read_text(encoding="utf-8")
    plan_service = (PROJECT_ROOT / "editor" / "services" / "plan_service.py").read_text(encoding="utf-8")

    require("LicenseManager" in main_source, "startup license manager import missing")
    require("validate_current_license" in main_source, "startup license validation missing")
    require("MainWindow(PROJECT_ROOT)" in main_source, "licensed MainWindow entry missing")
    require("ActivationWindow" in main_source, "activation window entry missing")
    require("migrate_legacy_data" in main_source, "legacy migration still runs at startup")
    require("LicenseManager" not in window_source, "MainWindow unexpectedly gained a license check")
    require("validate_current_license" not in window_source, "export path unexpectedly re-validates licenses")
    require("def validate_plan_for_execution" in window_source, "GUI preflight helper missing")
    require("if not step.enabled:" in window_source, "GUI preflight still skips disabled steps")
    require("def _on_export_exe" in window_source and "build_single_file_exe" in window_source, "GUI export path changed")
    require("class RuntimeExecutor" in runtime_source, "RuntimeExecutor missing")
    require("def run_command_step" in runtime_source and "def run_wait_step" in runtime_source, "runtime command/wait missing")
    require('launch_mode == "shell_open"' in runtime_source, "runtime shortcut shell-open path missing")
    require('".lnk": "shortcut"' in apps_source, "application backend no longer classifies LNK shortcuts")
    require('APP_DIR_NAME = "LaunchFlow"' in paths_source, "Professional data directory name changed")
    require(BASIC_DATA_DIR_NAME not in paths_source, "Basic data directory unexpectedly already implemented in app_paths")
    require("LOCALAPPDATA" in platform_paths, "Windows LOCALAPPDATA path contract missing")
    require("license.lic" in migration_source, "legacy migration still copies license.lic")
    require("get_plans_dir" in plan_service and "get_license_dir" not in plan_service, "PlanService path boundaries changed unexpectedly")

    # Runtime import is allowed, but executing a plan is not part of Phase 0.
    from runtime.launcher_runtime import RuntimeExecutor

    require(hasattr(RuntimeExecutor, "run_app_step"), "runtime app dispatch missing")
    require(hasattr(RuntimeExecutor, "run_command_step"), "runtime command dispatch missing")
    require(hasattr(RuntimeExecutor, "run_wait_step"), "runtime wait dispatch missing")
    require("run_plan" not in sys.argv, "internal guard: this smoke test must not be asked to execute plans")

    names = data_directory_names()
    require(names["basic"] == "LaunchFlow-Basic", "Basic data dir name drifted")
    require(names["professional"] == "LaunchFlow", "Professional data dir name drifted")


def check_no_production_imports_of_phase0_module() -> None:
    production_roots = [
        PROJECT_ROOT / "editor",
        PROJECT_ROOT / "runtime",
        PROJECT_ROOT / "shared",
        PROJECT_ROOT / "licensing",
        PROJECT_ROOT / "tools" / "build_single_exe.py",
        PROJECT_ROOT / "tools" / "build_editor_release.py",
    ]
    pattern = re.compile(r"dual_edition_phase0_contract")
    offenders = []
    for root in production_roots:
        paths = [root] if root.is_file() else root.rglob("*.py")
        for path in paths:
            if path.name.startswith("check_dual_edition") or path.name.startswith("dual_edition_phase0"):
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    require(not offenders, "Phase 0 contract module was imported by production files: " + ", ".join(offenders))


def check_sensitive_scan() -> None:
    scan_roots = [
        FIXTURE_ROOT,
        PROJECT_ROOT / "tools" / "dual_edition_phase0_contract.py",
        PROJECT_ROOT / "tools" / "check_dual_edition_contract_smoke.py",
        PROJECT_ROOT / "docs" / "dual-edition-phase0-contract.md",
    ]
    # Documentary mentions of restricted filenames are allowed. Actual secret
    # material, PEM blocks, and license payloads are not.
    for root in scan_roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            lowered = content.lower()
            require(("-"*5+"begin ") not in lowered, f"PEM/block material found in {path}")
            require(not re.search(r'"signature"\s*:\s*"[A-Za-z0-9+/=]{40,}"', content), f"signature-like secret found in {path}")


def check_module_is_side_effect_free() -> None:
    module = importlib.import_module("tools.dual_edition_phase0_contract")
    source = inspect.getsource(module)
    tree = ast.parse(source)
    disallowed_calls = {"Popen", "run", "urlopen", "get_machine_id", "validate_current_license"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            require(name not in disallowed_calls, f"contract module calls disallowed function {name}")
    require("subprocess" not in source, "contract module must not import subprocess")
    require("PyInstaller" not in source, "contract module must not reference PyInstaller")


def main() -> int:
    checks = [
        ("fixture_completeness", check_fixture_completeness),
        ("basic_accept_reject", check_basic_accept_reject),
        ("professional_compatibility", check_professional_compatibility),
        ("export_contracts", check_export_contracts),
        ("architecture_boundaries", check_current_architecture_boundaries),
        ("no_production_wiring", check_no_production_imports_of_phase0_module),
        ("sensitive_scan", check_sensitive_scan),
        ("contract_module_side_effects", check_module_is_side_effect_free),
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
        print("dual_edition_phase0_contract=FAIL")
        for item in FAILURES:
            print(f"- {item}")
        return 1
    print("dual_edition_phase0_contract=PASS")
    print(f"entry_points={','.join(ENTRY_POINTS)}")
    print(f"basic_data_dir={BASIC_DATA_DIR_NAME}")
    print(f"professional_data_dir={PROFESSIONAL_DATA_DIR_NAME}")
    print("export_side_effects=none")
    print("pyinstaller_invoked=0")
    print("real_license_or_hwid_access=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
