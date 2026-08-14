"""Static Windows audit and full Darwin arm64 smoke for Phase 2a1."""

from __future__ import annotations

import argparse
import ast
import builtins
import getpass
import hashlib
import importlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "macos-arm64-ci.yml"
DESIGN_DOC = ROOT / "docs" / "macos-arm64-ci-bootstrap.md"
CI_TOOLS = (
    ROOT / "tools" / "check_macos_arm64_ci_smoke.py",
    ROOT / "tools" / "build_macos_experimental.py",
    ROOT / "tools" / "macos_ci_bundle_probe.py",
    ROOT / "tools" / "macos_ci_launch_probe.py",
    ROOT / "tools" / "macos_ci_report.py",
)
APP_ICON_MODULE = "shared.app_icon"
APP_ICON_NORMALIZED_SHA256 = "9e7de2cac1245e9a7484873386004dc22c07ae94ef1462a7a00400181272f903"
QT_BOOTSTRAP_MODULES = (
    "PySide6.QtGui",
    "PySide6.QtWidgets",
)
SAFE_IMPORT_MODULES = (
    "shared.platform",
    "shared.app_paths",
    "shared.diagnostics",
    "runtime.command_runner",
    "runtime.launcher_runtime",
    "editor.main",
    "editor.ui.main_window",
    "licensing.hwid",
    "licensing.activation_service",
)
EXPECTED_SKIPS = {
    "real-hwid",
    "request-generation",
    "license-signing",
    "private-key",
    "windows-release",
    "exe-export",
}
RUN_ON_MACOS = (
    "check_macos_arm64_ci_smoke.py --full",
    "check_platform_coupling_smoke.py --format json",
    "check_readme_docs_smoke.py",
)
RUN_WITH_INJECTED_FIXTURE = (
    "PlatformInfo Darwin/arm64",
    "Application LaunchSpec",
    "URL LaunchSpec",
    "diagnostics redaction",
    "plan save/load",
    "legacy shortcut policy selection",
)
WINDOWS_ONLY_SKIP = (
    "check_command_capture_smoke.py",
    "check_platform_paths_smoke.py current-host assertion",
    "check_app_icon_smoke.py",
    "check_dev_mode_smoke.py",
)
SENSITIVE_SKIP = (
    "request generation",
    "license signing and verification",
    "private-key tests",
    "real HWID and host identity",
)
BUILD_SKIP = (
    "Windows editor release build",
    "Windows EXE export",
    "Windows Release smoke",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def environment_delta(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Return deterministic environment key changes without exposing values."""

    before_keys = set(before)
    after_keys = set(after)
    return {
        "added_keys": sorted(after_keys - before_keys),
        "removed_keys": sorted(before_keys - after_keys),
        "changed_keys": sorted(key for key in before_keys & after_keys if before[key] != after[key]),
    }


def environment_delta_is_empty(delta: dict[str, list[str]]) -> bool:
    return not any(delta.values())


def environment_delta_key_summary(delta: dict[str, list[str]]) -> str:
    """Serialize only the already-redacted key-name lists."""

    return json.dumps(delta, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def assert_environment_delta_contract() -> None:
    before = {
        "UNCHANGED_SYNTHETIC": "redacted-unchanged",
        "CHANGED_SYNTHETIC": "redacted-before",
        "REMOVED_SYNTHETIC": "redacted-removed",
    }
    after = {
        "UNCHANGED_SYNTHETIC": "redacted-unchanged",
        "CHANGED_SYNTHETIC": "redacted-after",
        "ADDED_SYNTHETIC": "redacted-added",
    }
    delta = environment_delta(before, after)
    require(
        delta
        == {
            "added_keys": ["ADDED_SYNTHETIC"],
            "removed_keys": ["REMOVED_SYNTHETIC"],
            "changed_keys": ["CHANGED_SYNTHETIC"],
        },
        "environment delta key classification changed",
    )
    summary = environment_delta_key_summary(delta)
    for value in set(before.values()) | set(after.values()):
        require(value not in summary, "environment delta summary exposed a value")


RUNNER_CONTEXT_PATTERN = re.compile(r"\$\{\{\s*runner\.")
YAML_KEY_PATTERN = re.compile(r"^(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s|$)")


def runner_context_findings(source: str) -> list[tuple[int, str, str]]:
    """Classify runner expressions by their structural YAML context."""

    stack: list[tuple[int, str]] = []
    findings: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key_match = YAML_KEY_PATTERN.match(stripped)
        if key_match:
            stack.append((indent, key_match.group(1)))
        if not RUNNER_CONTEXT_PATTERN.search(line):
            continue

        keys = [key for _indent, key in stack]
        if "env" in keys:
            env_index = len(keys) - 1 - keys[::-1].index("env")
            parents = keys[:env_index]
            if "jobs" not in parents:
                context = "workflow.env"
            elif "steps" not in parents:
                context = "jobs.env"
            else:
                context = "jobs.steps.env"
        elif "steps" in keys and "with" in keys:
            context = "jobs.steps.with"
        elif "steps" in keys and "run" in keys:
            context = "jobs.steps.run"
        else:
            context = "other"
        findings.append((line_number, context, stripped))
    return findings


def assert_runner_context_classifier() -> None:
    invalid_fixture = """\
env:
  GLOBAL_TEMP: ${{ runner.temp }}/global
jobs:
  sample:
    env:
      JOB_TEMP: ${{ runner.temp }}/job
"""
    valid_fixture = """\
jobs:
  sample:
    steps:
      - name: Step env and run
        env:
          STEP_TEMP: ${{ runner.temp }}/step-env
        run: echo "${{ runner.temp }}/step-run"
      - name: Step input
        uses: actions/upload-artifact@v4
        with:
          path: ${{ runner.temp }}/step-with
"""
    require(
        [context for _line, context, _text in runner_context_findings(invalid_fixture)]
        == ["workflow.env", "jobs.env"],
        "runner-context classifier did not reject workflow/job env",
    )
    require(
        [context for _line, context, _text in runner_context_findings(valid_fixture)]
        == ["jobs.steps.env", "jobs.steps.run", "jobs.steps.with"],
        "runner-context classifier rejected a legal step context",
    )


def safe_error_message(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    for variable in ("GITHUB_WORKSPACE", "RUNNER_TEMP", "RUNNER_TOOL_CACHE", "HOME"):
        source = os.environ.get(variable, "")
        if source:
            text = text.replace(source, "$" + variable)
    return re.sub(r"/Users/[^/\s]+", "$HOME", text)[:2_000]


def read_text(path: Path) -> str:
    require(path.is_file(), f"required file is missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def call_names(tree: ast.AST) -> set[str]:
    return {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }


def assert_static_contract() -> dict[str, int]:
    workflow = read_text(WORKFLOW)
    design = read_text(DESIGN_DOC)
    support_matrix = read_text(ROOT / "docs" / "platform-support-matrix.md")
    smoke_source = read_text(CI_TOOLS[0])
    for path in CI_TOOLS:
        ast.parse(read_text(path), filename=str(path))
    assert_runner_context_classifier()
    assert_environment_delta_contract()

    app_icon_source = read_text(ROOT / "shared" / "app_icon.py")
    require(
        hashlib.sha256(app_icon_source.encode("utf-8")).hexdigest() == APP_ICON_NORMALIZED_SHA256,
        "protected shared.app_icon.py changed",
    )
    app_icon_tree = ast.parse(app_icon_source, filename="shared/app_icon.py")
    allowed_top_level = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef)
    unexpected_top_level = [
        node
        for index, node in enumerate(app_icon_tree.body)
        if not isinstance(node, allowed_top_level)
        and not (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    require(not unexpected_top_level, "shared.app_icon.py gained import-time execution")
    for marker in ("os.environ", "os.putenv", "os.unsetenv", "qputenv", "qunsetenv"):
        require(marker not in app_icon_source, f"shared.app_icon.py mutates environment: {marker}")

    required_attribution = (
        "def " + "environment_delta(",
        "QT_BOOTSTRAP_" + "MODULES",
        "qt_bootstrap_environment_delta = " + "environment_delta(",
        "shared_app_icon_environment_delta = " + "environment_delta(",
        "environment_delta_is_empty(" + "shared_app_icon_environment_delta)",
        "environment_delta_is_empty(" + "module_environment_delta)",
        "def " + "write_import_environment_failure(",
        '"qt_bootstrap_environment_delta"' + ": qt_bootstrap_environment_delta",
        '"shared_app_icon_environment_delta"' + ": shared_app_icon_environment_delta",
        '"launchflow_import_environment_result"' + ': "PASS"',
        '"environment_values_recorded"' + ": False",
    )
    for marker in required_attribution:
        require(marker in smoke_source, f"environment attribution marker missing: {marker}")
    for marker in (
        "print(" + "os.environ",
        "print(dict(" + "os.environ",
        "json.dumps(dict(" + "os.environ",
        'startswith("QT' + '_")',
        "startswith('QT" + "_')",
        'startswith("QML' + '_")',
        "startswith('QML" + "_')",
        '"QT_' + '*"',
        '"QML_' + '*"',
    ):
        require(marker not in smoke_source, f"unsafe environment diagnostic found: {marker}")

    required_workflow = (
        "name: macOS arm64 Experimental CI",
        "workflow_dispatch:",
        "pull_request:",
        "push:",
        "branches:",
        "- main",
        "permissions:\n  contents: read",
        "runs-on: macos-15",
        "timeout-minutes: 30",
        "actions/checkout@v4",
        "actions/setup-python@v5",
        'python-version: "3.13"',
        '"PySide6==6.9.3"',
        '"PyInstaller==6.20.0"',
        '"cryptography==46.0.3"',
        "QT_QPA_PLATFORM: offscreen",
        "name: Configure isolated runner paths",
        'echo "LAUNCHFLOW_DATA_DIR=$RUNNER_TEMP/launchflow-data"',
        'echo "PYTHONPYCACHEPREFIX=$RUNNER_TEMP/launchflow-pycache"',
        'echo "CI_EVIDENCE_DIR=$RUNNER_TEMP/launchflow-evidence"',
        'echo "CI_BUILD_DIR=$RUNNER_TEMP/launchflow-build"',
        'echo "CI_DIST_DIR=$RUNNER_TEMP/launchflow-dist"',
        'echo "CI_SPEC_DIR=$RUNNER_TEMP/launchflow-spec"',
        'echo "CI_ARTIFACT_DIR=$RUNNER_TEMP/launchflow-artifacts"',
        'echo "CI_UPLOAD_DIR=$RUNNER_TEMP/launchflow-upload"',
        '} >> "$GITHUB_ENV"',
        "uname -s",
        "uname -m",
        "sw_vers",
        "system_profiler SPHardwareDataType",
        "platform.machine()",
        "sysconfig.get_platform()",
        'os.environ["GITHUB_SHA"]',
        "check_macos_arm64_ci_smoke.py --static-only",
        "--full",
        "--checker tools/check_platform_coupling_smoke.py",
        "check_readme_docs_smoke.py",
        "build_macos_experimental.py",
        "macos_ci_bundle_probe.py",
        "macos_ci_launch_probe.py",
        "macos_ci_report.py coupling",
        "macos_ci_report.py scan-upload",
        "--output-dir \"$CI_UPLOAD_DIR\"",
        "${{ runner.temp }}/launchflow-upload/upload-scan.json",
        "ditto -c -k --sequesterRsrc --keepParent",
        "LaunchFlow-macos-arm64-experimental-unsigned.zip",
        "actions/upload-artifact@v4",
        "if: always()",
        "retention-days: 7",
        "name: launchflow-macos-arm64-experimental",
        "real-hwid,request-generation,license-signing,private-key,windows-release,exe-export",
    )
    for marker in required_workflow:
        require(marker in workflow, f"workflow marker missing: {marker}")

    configure_index = workflow.index("name: Configure isolated runner paths")
    require(
        workflow.index("uses: actions/checkout@v4") < configure_index,
        "runner path initialization must run after checkout",
    )
    require(
        configure_index < workflow.index("name: Prepare isolated temporary directories"),
        "runner path initialization must run before directory preparation",
    )

    runner_findings = runner_context_findings(workflow)
    workflow_env_findings = [item for item in runner_findings if item[1] == "workflow.env"]
    job_env_findings = [item for item in runner_findings if item[1] == "jobs.env"]
    require(not workflow_env_findings, "workflow-level env references runner context")
    require(not job_env_findings, "job-level env references runner context")
    artifact_step_findings = [
        item
        for item in runner_findings
        if item[1] == "jobs.steps.with" and "launchflow-upload/" in item[2]
    ]
    require(len(artifact_step_findings) == 12, "curated artifact step runner paths changed")

    forbidden_workflow = (
        "${{ secrets.",
        "contents: write",
        "packages: write",
        "id-token: write",
        "actions: write",
        "deployments: write",
        "git add",
        "git commit",
        "git push",
        "git tag",
        "gh release",
        "upload-release-asset",
        "xcrun notarytool",
        "altool",
        "security import",
        "codesign --sign",
        "print" + "env",
        "env" + " |",
    )
    lowered_workflow = workflow.lower()
    for marker in forbidden_workflow:
        require(marker.lower() not in lowered_workflow, f"forbidden workflow behavior: {marker}")
    require("path: ${{ runner.temp }}" not in workflow, "artifact upload includes all of RUNNER_TEMP")
    require("${{ runner.temp }}/launchflow-evidence/" not in workflow.split("uses: actions/upload-artifact@v4", 1)[1], "upload bypasses curated scan output")
    require("${{ github.workspace }}/build" not in lowered_workflow, "workflow writes repository build")
    require("${{ github.workspace }}/dist" not in lowered_workflow, "workflow writes repository dist")

    builder = read_text(ROOT / "tools" / "build_macos_experimental.py")
    required_builder = (
        'host_system != "Darwin"',
        'host_arch != "arm64"',
        '"-m",\n        "PyInstaller"',
        '"--noconfirm"',
        '"--clean"',
        '"--windowed"',
        '"--onedir"',
        '"--target-architecture"',
        "io.github.forgottenlab.launchflow",
        '"signed": False',
        '"notarized": False',
        '"production": False',
    )
    for marker in required_builder:
        require(marker in builder, f"builder marker missing: {marker}")
    require("assets/launchflow.ico" not in builder, "Windows ICO was configured for macOS")
    require("--onefile" not in builder and "dmg" not in builder.lower(), "builder exceeded onedir app scope")

    forbidden_calls = {
        "get_machine_id",
        "get_machine_fingerprint_parts",
        "generate_request_code",
        "generate_request_payload",
        "load_pem_private_key",
        "load_pem_public_key",
        "sign_license",
        "verify_license",
    }
    for path in CI_TOOLS:
        tree = ast.parse(read_text(path), filename=str(path))
        for name in call_names(tree):
            require(name.rsplit(".", 1)[-1] not in forbidden_calls, f"sensitive call in {path.name}: {name}")

    launch_probe = read_text(ROOT / "tools" / "macos_ci_launch_probe.py")
    launch_tree = ast.parse(launch_probe, filename="macos_ci_launch_probe.py")
    launch_imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(launch_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    require("subprocess" not in launch_imports, "launch boundary probe can start a subprocess")
    require('"executed": False' in launch_probe, "launch probe does not freeze the blocked state")
    require('"process_started": False' in launch_probe, "launch probe can claim a process start")

    required_design = (
        "Planned / Experimental preparation",
        "macOS arm64 CI bootstrap prepared",
        "Windows cannot build a native macOS application bundle",
        "unsigned",
        "not notarized",
        "Qt offscreen render evidence",
        "not real macOS manual GUI validation",
        "ephemeral runner",
        "stable hardware identity",
        "manual Mac acceptance",
        "BLOCKED",
        "no identity-free ready marker",
    )
    for marker in required_design:
        require(marker.lower() in design.lower(), f"design boundary missing: {marker}")
    require(
        "| Editor startup | Supported | Planned | Planned |" in support_matrix,
        "macOS editor status no longer remains Planned",
    )
    require("macOS supported" not in design and "macOS Beta" not in design, "unsupported status claim found")
    return {
        "workflow_env": len(workflow_env_findings),
        "job_env": len(job_env_findings),
        "step_with": len(artifact_step_findings),
        "qt_attribution": 1,
        "app_icon_hash": 1,
    }


def snapshot_repository_metadata() -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        stat = path.stat()
        result[path.relative_to(ROOT).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


class SideEffectGuard:
    def __init__(self, temp_root: Path) -> None:
        self.temp_root = temp_root
        self.events: list[str] = []
        self.command_calls = 0
        self.command_enabled = False
        self._originals: dict[str, Any] = {}

    def _blocked(self, label: str):  # type: ignore[no-untyped-def]
        def fail(*_args: object, **_kwargs: object) -> Any:
            self.events.append(label)
            raise AssertionError(f"forbidden side effect: {label}")

        return fail

    def _guarded_open(self, file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        value = os.fspath(file) if isinstance(file, (str, os.PathLike)) else ""
        lowered = value.lower()
        if lowered.endswith((".pem", ".key", ".p12", ".pfx", ".lic", ".lflic")):
            self.events.append("sensitive-file-open")
            raise AssertionError("sensitive file access is forbidden")
        return self._originals["open"](file, *args, **kwargs)

    def _guarded_popen(self, args: object, *positional: object, **kwargs: object):  # type: ignore[no-untyped-def]
        allowed = (
            self.command_enabled
            and isinstance(args, list)
            and len(args) == 3
            and args[0] == "/bin/sh"
            and args[1] == "-c"
            and args[2] == "printf 'launchflow-macos-ci-command'"
            and kwargs.get("shell") is False
            and Path(str(kwargs.get("cwd"))).resolve() == self.temp_root
        )
        if not allowed:
            self.events.append("subprocess")
            raise AssertionError("unexpected subprocess launch")
        self.command_calls += 1
        return self._originals["popen"](args, *positional, **kwargs)

    def __enter__(self) -> "SideEffectGuard":
        from cryptography.hazmat.primitives import serialization

        self._originals = {
            "open": builtins.open,
            "popen": subprocess.Popen,
            "run": subprocess.run,
            "call": subprocess.call,
            "check_call": subprocess.check_call,
            "check_output": subprocess.check_output,
            "os_system": os.system,
            "os_popen": os.popen,
            "gethostname": socket.gethostname,
            "create_connection": socket.create_connection,
            "getuser": getpass.getuser,
            "getlogin": getattr(os, "getlogin", None),
            "webbrowser_open": webbrowser.open,
            "urlopen": urllib.request.urlopen,
            "load_public": serialization.load_pem_public_key,
            "load_private": serialization.load_pem_private_key,
        }
        builtins.open = self._guarded_open  # type: ignore[assignment]
        subprocess.Popen = self._guarded_popen  # type: ignore[assignment]
        subprocess.run = self._blocked("subprocess.run")  # type: ignore[assignment]
        subprocess.call = self._blocked("subprocess.call")  # type: ignore[assignment]
        subprocess.check_call = self._blocked("subprocess.check_call")  # type: ignore[assignment]
        subprocess.check_output = self._blocked("subprocess.check_output")  # type: ignore[assignment]
        os.system = self._blocked("os.system")  # type: ignore[assignment]
        os.popen = self._blocked("os.popen")  # type: ignore[assignment]
        socket.gethostname = self._blocked("socket.gethostname")  # type: ignore[assignment]
        socket.create_connection = self._blocked("socket.create_connection")  # type: ignore[assignment]
        getpass.getuser = self._blocked("getpass.getuser")  # type: ignore[assignment]
        if self._originals["getlogin"] is not None:
            os.getlogin = self._blocked("os.getlogin")  # type: ignore[assignment]
        webbrowser.open = self._blocked("webbrowser.open")  # type: ignore[assignment]
        urllib.request.urlopen = self._blocked("urllib.request.urlopen")  # type: ignore[assignment]
        serialization.load_pem_public_key = self._blocked("public-key-load")  # type: ignore[assignment]
        serialization.load_pem_private_key = self._blocked("private-key-load")  # type: ignore[assignment]
        return self

    def __exit__(self, *_args: object) -> None:
        from cryptography.hazmat.primitives import serialization

        builtins.open = self._originals["open"]  # type: ignore[assignment]
        subprocess.Popen = self._originals["popen"]  # type: ignore[assignment]
        subprocess.run = self._originals["run"]  # type: ignore[assignment]
        subprocess.call = self._originals["call"]  # type: ignore[assignment]
        subprocess.check_call = self._originals["check_call"]  # type: ignore[assignment]
        subprocess.check_output = self._originals["check_output"]  # type: ignore[assignment]
        os.system = self._originals["os_system"]  # type: ignore[assignment]
        os.popen = self._originals["os_popen"]  # type: ignore[assignment]
        socket.gethostname = self._originals["gethostname"]  # type: ignore[assignment]
        socket.create_connection = self._originals["create_connection"]  # type: ignore[assignment]
        getpass.getuser = self._originals["getuser"]  # type: ignore[assignment]
        if self._originals["getlogin"] is not None:
            os.getlogin = self._originals["getlogin"]  # type: ignore[assignment]
        webbrowser.open = self._originals["webbrowser_open"]  # type: ignore[assignment]
        urllib.request.urlopen = self._originals["urlopen"]  # type: ignore[assignment]
        serialization.load_pem_public_key = self._originals["load_public"]  # type: ignore[assignment]
        serialization.load_pem_private_key = self._originals["load_private"]  # type: ignore[assignment]


def assert_inside(path: Path, parent: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} must be absolute")
    resolved = path.resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise AssertionError(f"{label} must stay inside $RUNNER_TEMP") from exc
    return resolved


def write_import_environment_failure(
    report_path: Path,
    qt_delta: dict[str, list[str]],
    app_icon_delta: dict[str, list[str]],
    failed_module: str,
    failed_delta: dict[str, list[str]],
) -> None:
    """Persist key-name-only attribution if an import invariant still fails."""

    payload = {
        "status": "FAIL",
        "production": False,
        "phase": "import-environment-attribution",
        "qt_bootstrap_was_first_import": True,
        "qt_bootstrap_environment_delta": qt_delta,
        "shared_app_icon_imported_after_qt_bootstrap": True,
        "shared_app_icon_environment_delta": app_icon_delta,
        "launchflow_import_environment_result": "FAIL",
        "failed_module": failed_module,
        "failed_module_environment_delta": failed_delta,
        "environment_values_recorded": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def run_full_smoke(evidence_dir: Path, report_path: Path) -> dict[str, object]:
    require(platform.system() == "Darwin", "full smoke requires Darwin")
    require(platform.machine().lower() == "arm64", "full smoke requires arm64")
    require(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "Qt offscreen mode is required")
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "bytecode writes must be disabled")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    require(runner_temp_value, "RUNNER_TEMP is required")
    runner_temp = Path(runner_temp_value).resolve()
    evidence_dir = assert_inside(evidence_dir, runner_temp, "evidence directory")
    report_path = assert_inside(report_path, runner_temp, "report path")
    data_dir = assert_inside(Path(os.environ.get("LAUNCHFLOW_DATA_DIR", "")), runner_temp, "data directory")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    temp_plan_dir = runner_temp / "launchflow-plan-fixtures" / "Unicode 空格"
    temp_plan_dir.mkdir(parents=True, exist_ok=True)

    skip_contract = set(os.environ.get("LAUNCHFLOW_CI_SKIP_CONTRACT", "").split(","))
    require(skip_contract == EXPECTED_SKIPS, "explicit sensitive/Windows skip contract changed")
    before_metadata = snapshot_repository_metadata()
    cwd_before = Path.cwd()
    environment_before = dict(os.environ)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import_results: dict[str, str] = {}
    logs: list[str] = []
    with SideEffectGuard(temp_plan_dir) as guard:
        from cryptography.hazmat.primitives import serialization

        require(serialization.load_pem_public_key.__name__ == "fail", "public-key loader guard missing")
        require(dict(os.environ) == environment_before, "side-effect guard bootstrap changed environment")
        require(
            not any(module_name in sys.modules for module_name in QT_BOOTSTRAP_MODULES),
            "PySide6 Qt bootstrap was not the first import",
        )
        require(APP_ICON_MODULE not in sys.modules, "shared.app_icon imported before Qt bootstrap")

        before_qt = dict(os.environ)
        for module_name in QT_BOOTSTRAP_MODULES:
            importlib.import_module(module_name)
        after_qt = dict(os.environ)
        qt_bootstrap_environment_delta = environment_delta(before_qt, after_qt)
        require(APP_ICON_MODULE not in sys.modules, "Qt bootstrap imported shared.app_icon")

        before_app_icon = dict(os.environ)
        importlib.import_module(APP_ICON_MODULE)
        after_app_icon = dict(os.environ)
        shared_app_icon_environment_delta = environment_delta(before_app_icon, after_app_icon)
        if not environment_delta_is_empty(shared_app_icon_environment_delta):
            write_import_environment_failure(
                report_path,
                qt_bootstrap_environment_delta,
                shared_app_icon_environment_delta,
                APP_ICON_MODULE,
                shared_app_icon_environment_delta,
            )
        require(
            environment_delta_is_empty(shared_app_icon_environment_delta),
            "shared.app_icon changed environment keys: "
            + environment_delta_key_summary(shared_app_icon_environment_delta),
        )
        import_results[APP_ICON_MODULE] = "PASS"
        require(Path.cwd() == cwd_before, "shared.app_icon changed cwd")

        for module_name in SAFE_IMPORT_MODULES:
            before_module = dict(os.environ)
            importlib.import_module(module_name)
            after_module = dict(os.environ)
            module_environment_delta = environment_delta(before_module, after_module)
            if not environment_delta_is_empty(module_environment_delta):
                write_import_environment_failure(
                    report_path,
                    qt_bootstrap_environment_delta,
                    shared_app_icon_environment_delta,
                    module_name,
                    module_environment_delta,
                )
            import_results[module_name] = "PASS"
            require(Path.cwd() == cwd_before, f"import changed cwd: {module_name}")
            require(
                environment_delta_is_empty(module_environment_delta),
                f"import changed environment keys: {module_name}: "
                + environment_delta_key_summary(module_environment_delta),
            )
        environment_after_imports = dict(os.environ)
        require(environment_after_imports == after_qt, "LaunchFlow import environment baseline changed")

        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from editor.services.plan_service import PlanService
        from editor.ui.main_window import MainWindow
        from licensing import activation_service as activation_service_module
        from licensing import hwid as hwid_module
        from runtime.command_runner import execute_command
        from runtime.launcher_runtime import RuntimeExecutor
        from shared.diagnostics import _redact_diagnostic_text
        from shared.models import AppStep, CommandStep, Plan, UrlStep, WaitStep
        from shared.platform.applications import LegacyPosixApplicationLauncher, get_application_launcher
        from shared.platform.detection import detect_platform
        from shared.platform.diagnostics import DiagnosticPathAlias, DiagnosticsPresentation
        from shared.platform.process import LegacyPosixCommandBackend, get_command_backend
        from shared.platform.shortcuts import LegacyShortcutPolicy, get_shortcut_policy
        from shared.platform.urls import LegacyPosixUrlOpener, get_url_opener

        require(QApplication.instance() is None, "import created QApplication")
        original_hwid = hwid_module.get_machine_id
        original_activation_hwid = activation_service_module.get_machine_id
        blocked_identity = guard._blocked("identity-read")
        hwid_module.get_machine_id = blocked_identity  # type: ignore[assignment]
        activation_service_module.get_machine_id = blocked_identity  # type: ignore[assignment]
        try:
            app = QApplication([])
            window = MainWindow(ROOT)
            window.resize(1180, 760)
            window.show()
            app.processEvents()
            screenshot = evidence_dir / "gui-main-window.png"
            require(window.grab().save(str(screenshot), "PNG"), "offscreen screenshot save failed")
            require(screenshot.is_file() and screenshot.stat().st_size > 1_000, "offscreen screenshot is empty")
            running_threads = [
                thread.objectName() or thread.__class__.__name__
                for thread in window.findChildren(QThread)
                if thread.isRunning()
            ]
            require(not running_threads, "background Qt thread is running")
            window.close()
            window.deleteLater()
            app.processEvents()
            require(not any(thread.isRunning() for thread in app.findChildren(QThread)), "Qt thread remained after close")

            plan = Plan(
                plan_name="Synthetic macOS CI 方案",
                steps=[
                    AppStep(id="step-app-ci", name="Synthetic app", path="/Applications/Synthetic.app"),
                    UrlStep(
                        id="step-url-ci",
                        name="Synthetic URL",
                        url="https://example.invalid/launchflow",
                        browser_path="/synthetic/browser",
                    ),
                    CommandStep(
                        id="step-command-ci",
                        name="Synthetic command",
                        command="printf 'launchflow-macos-ci-command'",
                        shell="cmd",
                    ),
                    WaitStep(id="step-wait-ci", name="Synthetic wait", seconds=0.01),
                ],
            )
            service = PlanService(ROOT)
            plan_path = temp_plan_dir / "计划 file.json"
            service.save_plan(plan, plan_path)
            loaded = service.load_plan(plan_path)
            require(loaded.to_dict() == plan.to_dict(), "synthetic plan round trip changed")

            macos = detect_platform(system="Darwin", machine="arm64", os_name="posix", sys_platform="darwin")
            require(macos.system == "macos" and macos.architecture == "arm64", "PlatformInfo mismatch")
            command_backend = get_command_backend(platform_info=macos)
            require(isinstance(command_backend, LegacyPosixCommandBackend), "Windows command backend selected")
            require(command_backend.supported_shells == (), "legacy command backend claimed native support")
            shortcut_policy = get_shortcut_policy(macos)
            require(isinstance(shortcut_policy, LegacyShortcutPolicy), "Windows shortcut policy selected")
            require(shortcut_policy.get_profile().save == "Ctrl+S", "legacy shortcut fixture changed")

            app_launcher = get_application_launcher(
                platform_info=macos,
                path_exists=lambda path: path == "/Applications/Synthetic.app",
                path_is_directory=lambda _path: False,
            )
            require(isinstance(app_launcher, LegacyPosixApplicationLauncher), "Windows app launcher selected")
            app_spec = app_launcher.build_launch_spec("/Applications/Synthetic.app", ("--fixture",), "", False)
            require(app_spec.command_args == ("/Applications/Synthetic.app", "--fixture"), "app fixture spec changed")

            url_opener = get_url_opener(platform_info=macos, path_exists=lambda _path: True)
            require(isinstance(url_opener, LegacyPosixUrlOpener), "Windows URL opener selected")
            url_spec = url_opener.build_open_spec("https://example.invalid/launchflow", "/synthetic/browser")
            require(
                url_spec.command_args == ("/synthetic/browser", "https://example.invalid/launchflow"),
                "URL fixture spec changed",
            )

            guard.command_enabled = True
            command_result = execute_command(
                "printf 'launchflow-macos-ci-command'",
                "cmd",
                str(temp_plan_dir),
            )
            guard.command_enabled = False
            require(command_result.succeeded, "neutral command failed")
            require(command_result.stdout == "launchflow-macos-ci-command", "neutral command output changed")
            RuntimeExecutor(log_callback=logs.append).run_wait_step(WaitStep(seconds=0.01))

            presentation = DiagnosticsPresentation(
                platform_label="macOS experimental fixture",
                path_aliases=(
                    DiagnosticPathAlias("/Users/SYNTHETIC-RUNNER", "$HOME"),
                    DiagnosticPathAlias("/tmp/SYNTHETIC-RUNNER", "$RUNNER_TEMP"),
                ),
            )
            diagnostic = _redact_diagnostic_text(
                "path=/Users/SYNTHETIC-RUNNER/project\nrequest_id=SYNTHETIC-REQUEST",
                presentation,
            )
            require("/Users/SYNTHETIC-RUNNER" not in diagnostic, "synthetic HOME was not redacted")
            require("SYNTHETIC-REQUEST" not in diagnostic, "synthetic request identifier was not redacted")
        finally:
            hwid_module.get_machine_id = original_hwid  # type: ignore[assignment]
            activation_service_module.get_machine_id = original_activation_hwid  # type: ignore[assignment]

        require(guard.command_calls == 1, "unexpected command process count")
        require(not guard.events, "forbidden side effect was attempted: " + ",".join(guard.events))

    after_metadata = snapshot_repository_metadata()
    require(before_metadata == after_metadata, "full smoke wrote into the repository")
    require(Path.cwd() == cwd_before, "full smoke changed cwd")
    require(dict(os.environ) == environment_after_imports, "full smoke changed environment after imports")

    payload: dict[str, object] = {
        "status": "PASS",
        "production": False,
        "host_system": "Darwin",
        "host_arch": "arm64",
        "imports": import_results,
        "qt_bootstrap_was_first_import": True,
        "qt_bootstrap_environment_delta": qt_bootstrap_environment_delta,
        "shared_app_icon_imported_after_qt_bootstrap": True,
        "shared_app_icon_environment_delta": shared_app_icon_environment_delta,
        "launchflow_import_environment_result": "PASS",
        "qapplication_created_by_import": False,
        "main_window_offscreen": "PASS",
        "offscreen_evidence": "$RUNNER_TEMP/launchflow-evidence/gui-main-window.png",
        "qt_threads_remaining": 0,
        "isolated_data_dir": "$RUNNER_TEMP/launchflow-data",
        "plan_unicode_space_roundtrip": "PASS",
        "command_fixed_output": "PASS",
        "wait_short_duration": "PASS",
        "application": "injected LaunchSpec only; no target started",
        "url": "injected LaunchSpec only; no browser opened",
        "diagnostics": "synthetic path fixture redacted",
        "shortcut_policy": "legacy synthetic selection only; native keyboard not claimed",
        "identity_reads": 0,
        "request_generation": 0,
        "license_reads": 0,
        "key_loads": 0,
        "network_access": 0,
        "repository_writes": 0,
        "tests": {
            "run_on_macos": RUN_ON_MACOS,
            "run_with_injected_fixture": RUN_WITH_INJECTED_FIXTURE,
            "windows_only_skip": WINDOWS_ONLY_SKIP,
            "sensitive_skip": SENSITIVE_SKIP,
            "build_skip": BUILD_SKIP,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--static-only", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context_counts = assert_static_contract()
    if args.static_only:
        print("macos_arm64_ci_static_smoke=PASS")
        print("workflow=macos-15,contents-read,no-secrets")
        print(f"workflow_level_env_runner_context_findings={context_counts['workflow_env']}")
        print(f"job_level_env_runner_context_findings={context_counts['job_env']}")
        print("runner_temp_initialization=present")
        print(f"step_with_runner_context_preserved={context_counts['step_with']}")
        print("qt_bootstrap_environment_attribution=present")
        print("shared_app_icon_post_bootstrap_environment=zero-required")
        print("other_launchflow_import_environment=zero-required")
        print("environment_value_output=forbidden")
        print("production_app_icon_hash=matched")
        print("builder=darwin-arm64-only,onedir,unsigned,non-production")
        print("support_status=Planned/Experimental-preparation")
        print("production_imports=none")
        print("sensitive_calls=0")
        return 0

    require(bool(args.evidence_dir and args.report), "full smoke requires evidence and report paths")
    payload = run_full_smoke(Path(args.evidence_dir), Path(args.report))
    print("macos_arm64_ci_full_smoke=" + str(payload["status"]))
    print("imports=10-pass")
    print(
        "qt_bootstrap_environment_delta_keys="
        + environment_delta_key_summary(payload["qt_bootstrap_environment_delta"])  # type: ignore[arg-type]
    )
    print(
        "shared_app_icon_environment_delta_keys="
        + environment_delta_key_summary(payload["shared_app_icon_environment_delta"])  # type: ignore[arg-type]
    )
    print("launchflow_import_environment=" + str(payload["launchflow_import_environment_result"]))
    print("offscreen_main_window=PASS")
    print("identity_reads=0")
    print("key_loads=0")
    print("network_access=0")
    print("repository_writes=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("macos_arm64_ci_smoke=FAIL")
        print("reason=" + safe_error_message(exc))
        raise SystemExit(1) from None
