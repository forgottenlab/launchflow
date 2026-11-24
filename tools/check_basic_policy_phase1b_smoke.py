"""Phase 1b Windows adapters and gated Basic ingress tests.

These tests cover the real Windows IShellLink / drive-classification
adapters and the edition-gated plan ingress hooks. They do not invoke
PyInstaller, build EXEs, open the GUI, collect hardware identity, or
read real licenses, private keys, or user AppData plans.

Run with the project interpreter:

    python tools/check_basic_policy_phase1b_smoke.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor.services.plan_service import PlanService
from editor.ui.main_window import validate_plan_for_execution
from runtime.command_runner import CommandResult
from runtime.launcher_runtime import RuntimeExecutor
from shared.basic_policy import DriveLocality, validate_basic_plan_document
from shared.edition_policy import (
    BASIC_EDITION,
    PROFESSIONAL_EDITION,
    BasicPolicyViolation,
    OsFilesystemInspector,
    build_production_basic_policy_dependencies,
    edition_scope,
    enforce_basic_policy_on_ingress,
    is_basic_edition_active,
)
from shared.models import AppStep, CommandStep, Plan, UrlStep, WaitStep
from shared.platform.applications import get_application_launcher
from shared.platform.windows_drives import (
    DRIVE_FIXED,
    DRIVE_NO_ROOT_DIR,
    DRIVE_REMOTE,
    DRIVE_UNKNOWN,
    WindowsDriveClassifier,
)
from shared.platform.windows_shell_links import (
    WindowsShortcutResolver,
    read_windows_shortcut,
    write_windows_shortcut,
)
from tools import build_single_exe


FAILURES: list[str] = []
COMMAND_PLAN_DOCUMENT = {
    "plan_name": "Professional Command Plan",
    "version": "1.0.0",
    "steps": [
        {
            "id": "step-cmd",
            "type": "command",
            "name": "Echo",
            "enabled": True,
            "delay_after": 1.0,
            "command": "echo launchflow-phase1b-must-not-run",
            "shell": "cmd",
            "working_dir": "",
            "new_window": True,
        }
    ],
}


def require(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def _isolated_data_dir():
    temp_root = Path(tempfile.mkdtemp(prefix="launchflow-phase1b-data-"))
    previous = os.environ.get("LAUNCHFLOW_DATA_DIR")
    os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp_root)
    try:
        yield temp_root
    finally:
        if previous is None:
            os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
        else:
            os.environ["LAUNCHFLOW_DATA_DIR"] = previous
        shutil.rmtree(temp_root, ignore_errors=True)


class _DataDir:
    def __enter__(self):
        self._context = _isolated_data_dir()
        return next(self._context)

    def __exit__(self, exc_type, exc, tb):
        try:
            next(self._context)
        except StopIteration:
            pass


def _command_plan() -> Plan:
    return Plan(
        plan_name="Professional Command Plan",
        version="1.0.0",
        steps=[
            CommandStep(
                id="step-cmd",
                name="Echo",
                command="echo launchflow-phase1b-must-not-run",
                shell="cmd",
                delay_after=0.0,
            )
        ],
    )


def _successful_command_result() -> CommandResult:
    return CommandResult(
        command_args=["cmd", "/c", "echo mocked"],
        returncode=0,
        stdout="mocked\n",
        stderr="",
    )


def check_default_edition_is_not_basic() -> None:
    require(
        not is_basic_edition_active(),
        "Basic edition must be inactive by default",
    )
    require(
        enforce_basic_policy_on_ingress(COMMAND_PLAN_DOCUMENT) is None,
        "Professional / unset edition must not enforce Basic policy",
    )


def check_drive_classifier_injection() -> None:
    remote = WindowsDriveClassifier(
        get_volume_path_name=lambda _path: "Z:\\",
        get_drive_type=lambda _root: DRIVE_REMOTE,
    )
    require(
        remote.classify_drive(r"Z:\Apps\example.exe") == DriveLocality.REMOTE,
        "injected GetDriveType REMOTE must classify mapped drives as remote",
    )

    local = WindowsDriveClassifier(
        get_volume_path_name=lambda _path: "C:\\",
        get_drive_type=lambda _root: DRIVE_FIXED,
    )
    require(
        local.classify_drive(r"C:\Apps\example.exe") == DriveLocality.LOCAL,
        "injected GetDriveType FIXED must classify as local",
    )

    unknown = WindowsDriveClassifier(
        get_volume_path_name=lambda _path: "Q:\\",
        get_drive_type=lambda _root: DRIVE_UNKNOWN,
    )
    require(
        unknown.classify_drive(r"Q:\Apps\example.exe") == DriveLocality.UNKNOWN,
        "injected unknown drive type must fail closed as unknown",
    )

    missing = WindowsDriveClassifier(
        get_volume_path_name=lambda _path: "Y:\\",
        get_drive_type=lambda _root: DRIVE_NO_ROOT_DIR,
    )
    require(
        missing.classify_drive(r"Y:\Apps\example.exe") == DriveLocality.UNAVAILABLE,
        "injected NO_ROOT_DIR must fail closed as unavailable",
    )

    def boom(_path: str) -> str | None:
        raise RuntimeError("volume lookup failed")

    failed = WindowsDriveClassifier(
        get_volume_path_name=boom,
        get_drive_type=lambda _root: DRIVE_FIXED,
    )
    require(
        failed.classify_drive(r"C:\Apps\example.exe") == DriveLocality.LOCAL,
        "volume lookup failure should fall back to lexical drive root when type is local",
    )

    failed_type = WindowsDriveClassifier(
        get_volume_path_name=lambda _path: "C:\\",
        get_drive_type=lambda _root: (_ for _ in ()).throw(RuntimeError("drive type failed")),
    )
    require(
        failed_type.classify_drive(r"C:\Apps\example.exe") == DriveLocality.UNAVAILABLE,
        "drive type API failure must fail closed",
    )


def check_real_drive_classifier() -> None:
    classifier = WindowsDriveClassifier()
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    locality = classifier.classify_drive(str(Path(system_root) / "explorer.exe"))
    require(locality == DriveLocality.LOCAL, f"system drive was not classified local: {locality}")

    temp_locality = classifier.classify_drive(tempfile.gettempdir())
    require(
        temp_locality == DriveLocality.LOCAL,
        f"temp directory was not classified local: {temp_locality}",
    )

    unc_locality = classifier.classify_drive(
        r"\\invalid-launchflow-phase1b-host\share\app.exe"
    )
    require(
        unc_locality != DriveLocality.LOCAL,
        f"nonexistent UNC path must not be classified local: {unc_locality}",
    )
    require(
        unc_locality in {DriveLocality.REMOTE, DriveLocality.UNKNOWN, DriveLocality.UNAVAILABLE},
        f"nonexistent UNC path must fail closed or be remote: {unc_locality}",
    )


def check_real_shortcut_resolver() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="launchflow-phase1b-lnk-"))
    startfile_calls: list[str] = []
    popen_calls: list[Any] = []
    try:
        target = temp_dir / "payload.exe"
        target.write_bytes(b"MZ-launchflow-phase1b-not-executed")
        shortcut = temp_dir / "payload.lnk"
        write_windows_shortcut(str(shortcut), str(target))

        with (
            patch("os.startfile", side_effect=lambda path: startfile_calls.append(path)),
            patch("subprocess.Popen", side_effect=lambda *args, **kwargs: popen_calls.append((args, kwargs))),
        ):
            resolution = WindowsShortcutResolver().resolve_shortcut(str(shortcut))

        require(resolution.status == "resolved", f"valid shortcut was not resolved: {resolution}")
        require(
            Path(resolution.target_path).resolve() == target.resolve(),
            f"shortcut target mismatch: {resolution.target_path}",
        )
        require(resolution.target_kind == "executable", f"unexpected target kind: {resolution.target_kind}")
        require(resolution.arguments == (), f"unexpected arguments: {resolution.arguments}")
        require(
            resolution.working_directory == "",
            f"unexpected working directory: {resolution.working_directory}",
        )
        require(not startfile_calls, f"resolver called os.startfile: {startfile_calls}")
        require(not popen_calls, f"resolver started a process: {popen_calls}")

        args_shortcut = temp_dir / "args.lnk"
        write_windows_shortcut(
            str(args_shortcut),
            str(target),
            arguments="--help",
            working_directory=str(temp_dir),
        )
        args_resolution = read_windows_shortcut(str(args_shortcut))
        require(args_resolution.arguments == ("--help",), f"arguments not returned: {args_resolution}")
        require(
            Path(args_resolution.working_directory).resolve() == temp_dir.resolve(),
            f"working directory not returned: {args_resolution.working_directory}",
        )

        script_target = temp_dir / "run.bat"
        script_target.write_text("echo no\n", encoding="utf-8")
        script_shortcut = temp_dir / "script.lnk"
        write_windows_shortcut(str(script_shortcut), str(script_target))
        script_resolution = read_windows_shortcut(str(script_shortcut))
        require(script_resolution.target_kind == "batch", f"script kind mismatch: {script_resolution}")
        require(script_resolution.status == "resolved", "script shortcut should still resolve factually")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_shortcut_resolver_fail_closed() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="launchflow-phase1b-lnk-bad-"))
    try:
        resolver = WindowsShortcutResolver()
        missing = temp_dir / "missing.lnk"
        missing_failed = False
        try:
            resolution = resolver.resolve_shortcut(str(missing))
            missing_failed = resolution.status != "resolved"
        except Exception:
            missing_failed = True
        require(missing_failed, "missing shortcut must fail closed")

        corrupt = temp_dir / "corrupt.lnk"
        corrupt.write_bytes(b"this is not a shortcut")
        corrupt_failed = False
        try:
            resolution = resolver.resolve_shortcut(str(corrupt))
            corrupt_failed = resolution.status != "resolved"
        except Exception:
            corrupt_failed = True
        require(corrupt_failed, "corrupt shortcut must fail closed")

        def boom(_path: str):
            raise RuntimeError("com failed")

        exploding = WindowsShortcutResolver(reader=boom)
        exploded = False
        try:
            exploding.resolve_shortcut(str(corrupt))
        except RuntimeError as exc:
            exploded = "com failed" in str(exc)
        require(exploded, "resolver must propagate injected reader failures")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_production_dependencies_and_policy() -> None:
    deps = build_production_basic_policy_dependencies()
    require(isinstance(deps.filesystem, OsFilesystemInspector), "production filesystem inspector missing")
    require(deps.drive_classifier is not None, "production drive classifier missing")
    require(deps.shortcut_resolver is not None, "production shortcut resolver missing")

    temp_dir = Path(tempfile.mkdtemp(prefix="launchflow-phase1b-policy-"))
    try:
        target = temp_dir / "Editor.exe"
        target.write_bytes(b"MZ-launchflow-phase1b-not-executed")
        shortcut = temp_dir / "Editor.lnk"
        write_windows_shortcut(str(shortcut), str(target))
        document = {
            "plan_name": "Basic Real LNK",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "step-lnk",
                    "type": "app",
                    "name": "Editor",
                    "enabled": True,
                    "delay_after": 1.0,
                    "path": str(shortcut),
                    "args": [],
                    "working_dir": "",
                    "start_minimized": False,
                }
            ],
        }
        result = validate_basic_plan_document(document, dependencies=deps)
        require(result.accepted, f"real local EXE shortcut was rejected: {result.error_messages}")

        mapped = {
            "plan_name": "Mapped Drive",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "step-mapped",
                    "type": "app",
                    "name": "Mapped",
                    "enabled": True,
                    "delay_after": 1.0,
                    "path": r"Z:\Apps\example.exe",
                    "args": [],
                    "working_dir": "",
                    "start_minimized": False,
                }
            ],
        }
        injected = WindowsDriveClassifier(
            get_volume_path_name=lambda _path: "Z:\\",
            get_drive_type=lambda _root: DRIVE_REMOTE,
        )
        from shared.basic_policy import BasicPolicyDependencies

        mapped_deps = BasicPolicyDependencies(
            filesystem=deps.filesystem,
            drive_classifier=injected,
            shortcut_resolver=deps.shortcut_resolver,
        )
        mapped_result = validate_basic_plan_document(mapped, dependencies=mapped_deps)
        require(not mapped_result.accepted, "mapped drive plan must be rejected")
        require(
            any(issue.code == "basic_mapped_or_remote_drive_forbidden" for issue in mapped_result.issues),
            f"mapped drive rejection code missing: {mapped_result.error_messages}",
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_plan_service_gating() -> None:
    with _DataDir():
        service = PlanService(PROJECT_ROOT)
        command_path = service.get_plans_dir() / "command-plan.json"
        service.save_plan(_command_plan(), command_path)

        loaded = service.load_plan(command_path)
        require(loaded.steps[0].type == "command", "Professional load_plan rejected a command plan")

        command_step = service.create_step_from_template(
            {"type": "command", "name": "查看 Python 版本", "default_command": "python --version", "default_shell": "cmd", "delay_after": 1.0}
        )
        require(isinstance(command_step, CommandStep), "Professional templates must still create command steps")

        wait_step = service.create_step_from_template(
            {"type": "wait", "name": "等待", "default_seconds": 1.0}
        )
        require(isinstance(wait_step, WaitStep), "Professional templates must still create wait steps")

        with edition_scope(BASIC_EDITION):
            rejected = False
            try:
                service.load_plan(command_path)
            except BasicPolicyViolation as exc:
                rejected = not exc.result.accepted
                require(
                    any(issue.code == "basic_unsupported_step_type" for issue in exc.result.issues),
                    f"command plan was rejected for the wrong reason: {exc.result.error_messages}",
                )
            require(rejected, "Basic load_plan must reject command plans")

            template_rejected = False
            try:
                service.create_step_from_template(
                    {"type": "command", "name": "执行命令", "default_command": "python --version", "default_shell": "cmd"}
                )
            except BasicPolicyViolation:
                template_rejected = True
            require(template_rejected, "Basic templates must reject command steps")

        require(not is_basic_edition_active(), "edition_scope leaked Basic context")


def check_executor_gating() -> None:
    executed: list[str] = []

    def fake_execute(command: str, shell: str, working_dir: str) -> CommandResult:
        executed.append(command)
        return _successful_command_result()

    plan = _command_plan()
    executor = RuntimeExecutor(log_callback=lambda _message: None)
    with patch("runtime.launcher_runtime.execute_command", side_effect=fake_execute):
        executor.run_plan(plan)
        require(executed == [plan.steps[0].command], f"Professional executor did not run command step: {executed}")

        executed.clear()
        with edition_scope(BASIC_EDITION):
            rejected = False
            try:
                executor.run_plan(plan)
            except BasicPolicyViolation:
                rejected = True
            require(rejected, "Basic executor must reject command plans before execution")
            require(not executed, "Basic executor executed a rejected command step")


def check_export_gating() -> None:
    pyinstaller_lookups = {"count": 0}
    temp_dir = Path(tempfile.mkdtemp(prefix="launchflow-phase1b-export-"))
    output = temp_dir / "nested" / "plan.exe"

    def fake_pyinstaller_command() -> list[str]:
        pyinstaller_lookups["count"] += 1
        raise RuntimeError("pyinstaller-probed")

    try:
        with patch.object(build_single_exe, "_get_pyinstaller_command", side_effect=fake_pyinstaller_command):
            professional_reached = False
            try:
                build_single_exe.build_single_file_exe(COMMAND_PLAN_DOCUMENT, output)
            except RuntimeError as exc:
                professional_reached = "pyinstaller-probed" in str(exc)
            require(
                professional_reached and pyinstaller_lookups["count"] == 1,
                "Professional export must keep reaching the existing PyInstaller lookup",
            )

            pyinstaller_lookups["count"] = 0
            basic_output = temp_dir / "basic-nested" / "plan.exe"
            with edition_scope(BASIC_EDITION):
                rejected = False
                try:
                    build_single_exe.build_single_file_exe(COMMAND_PLAN_DOCUMENT, basic_output)
                except BasicPolicyViolation:
                    rejected = True
                require(rejected, "Basic export must reject command plans")
                require(
                    pyinstaller_lookups["count"] == 0,
                    "Basic export validation must run before PyInstaller lookup",
                )
                require(
                    not basic_output.parent.exists(),
                    "Basic export validation must run before creating output directories",
                )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_preflight_gating() -> None:
    plan = _command_plan()
    professional = validate_plan_for_execution(plan, "试运行")
    require(professional is None, f"Professional preflight rejected a valid command plan: {professional}")

    with edition_scope(BASIC_EDITION):
        issue = validate_plan_for_execution(plan, "试运行")
        require(issue is not None, "Basic preflight must reject command plans")
        require("Basic" in (issue.message if issue else ""), f"unexpected preflight message: {issue}")

    disabled = Plan(
        plan_name="Disabled Command",
        steps=[
            CommandStep(
                id="step-disabled",
                name="Hidden",
                enabled=False,
                command="echo no",
                shell="cmd",
                delay_after=0.0,
            )
        ],
    )
    require(
        validate_plan_for_execution(disabled, "试运行") is None,
        "Professional preflight must still skip disabled steps",
    )
    with edition_scope(BASIC_EDITION):
        issue = validate_plan_for_execution(disabled, "试运行")
        require(issue is not None, "Basic preflight must validate disabled unsupported steps")


def check_professional_lnk_shell_open_unchanged() -> None:
    launcher = get_application_launcher(
        path_exists=lambda _path: True,
        path_is_directory=lambda _path: False,
    )
    spec = launcher.build_launch_spec(r"C:\LaunchFlow-Synthetic\Editor.lnk", [], "", False)
    require(spec.launch_mode == "shell_open", f"Professional LNK launch_mode changed: {spec.launch_mode}")
    require(spec.target_kind == "shortcut", f"Professional LNK target_kind changed: {spec.target_kind}")
    require(
        spec.resolved_target == r"C:\LaunchFlow-Synthetic\Editor.lnk",
        f"Professional LNK resolved_target changed: {spec.resolved_target}",
    )


def check_gate_inactive_for_professional_label() -> None:
    with edition_scope(PROFESSIONAL_EDITION):
        require(not is_basic_edition_active(), "professional label must not enable Basic validation")
        require(enforce_basic_policy_on_ingress(COMMAND_PLAN_DOCUMENT) is None, "professional label enforced Basic")
    with edition_scope(None):
        require(not is_basic_edition_active(), "unset override must not enable Basic validation")


def main() -> int:
    require(not is_basic_edition_active(), "test process started with Basic edition already active")
    checks = [
        ("default_edition_is_not_basic", check_default_edition_is_not_basic),
        ("drive_classifier_injection", check_drive_classifier_injection),
        ("real_drive_classifier", check_real_drive_classifier),
        ("real_shortcut_resolver", check_real_shortcut_resolver),
        ("shortcut_resolver_fail_closed", check_shortcut_resolver_fail_closed),
        ("production_dependencies_and_policy", check_production_dependencies_and_policy),
        ("plan_service_gating", check_plan_service_gating),
        ("executor_gating", check_executor_gating),
        ("export_gating", check_export_gating),
        ("preflight_gating", check_preflight_gating),
        ("professional_lnk_shell_open_unchanged", check_professional_lnk_shell_open_unchanged),
        ("gate_inactive_for_professional_label", check_gate_inactive_for_professional_label),
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
    if is_basic_edition_active():
        FAILURES.append("Basic edition context leaked after tests")
    if FAILURES:
        print("dual_edition_phase1b_windows_adapters=FAIL")
        for item in FAILURES:
            print(f"- {item}")
        return 1
    print("dual_edition_phase1b_windows_adapters=PASS")
    print("professional_behavior_unchanged=yes")
    print("basic_validation_enforced_only_when_edition_is_basic=yes")
    print("pyinstaller_invoked=0")
    print("real_license_or_hwid_access=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
