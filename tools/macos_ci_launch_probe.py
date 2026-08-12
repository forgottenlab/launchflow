"""Fail-closed bundle launch probe for the experimental macOS CI artifact."""

from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def safe_error_message(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    for variable in ("GITHUB_WORKSPACE", "RUNNER_TEMP", "RUNNER_TOOL_CACHE", "HOME"):
        source = os.environ.get(variable, "")
        if source:
            text = text.replace(source, "$" + variable)
    return re.sub(r"/Users/[^/\s]+", "$HOME", text)[:2_000]


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def calls_in_function(path: Path, function_name: str, class_name: str | None = None) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    search_root: ast.AST = tree
    if class_name is not None:
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == class_name]
        if not classes:
            raise RuntimeError(f"required class is missing: {path.name}:{class_name}")
        search_root = classes[0]
    for node in ast.walk(search_root):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {
                ast.unparse(call.func)
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
    raise RuntimeError(f"required function is missing: {path.name}:{function_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--stdout-log", required=True)
    parser.add_argument("--stderr-log", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require(platform.system() == "Darwin", "launch probe requires Darwin")
    require(platform.machine().lower() == "arm64", "launch probe requires arm64")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    require(runner_temp_value, "RUNNER_TEMP is required")
    runner_temp = Path(runner_temp_value).resolve()
    workspace_value = os.environ.get("GITHUB_WORKSPACE", "").strip()
    require(workspace_value, "GITHUB_WORKSPACE is required")
    workspace = Path(workspace_value).resolve()

    raw_paths = (
        (Path(args.app), "app"),
        (Path(args.source_root), "source root"),
        (Path(args.data_dir), "data dir"),
        (Path(args.report), "report"),
        (Path(args.stdout_log), "stdout log"),
        (Path(args.stderr_log), "stderr log"),
    )
    for path, label in raw_paths:
        require(path.is_absolute(), f"{label} must be absolute")
    app, source_root, data_dir, report, stdout_log, stderr_log = (
        path.resolve() for path, _label in raw_paths
    )
    for path, label in (
        (app, "app"),
        (data_dir, "data dir"),
        (report, "report"),
        (stdout_log, "stdout log"),
        (stderr_log, "stderr log"),
    ):
        require(inside(path, runner_temp), f"{label} must stay inside $RUNNER_TEMP")
    executable = app / "Contents" / "MacOS" / "LaunchFlow"
    require(executable.is_file(), "bundle executable is missing")
    require(source_root == workspace, "source root must match $GITHUB_WORKSPACE")

    main_calls = calls_in_function(source_root / "editor" / "main.py", "main")
    activation_init_calls = calls_in_function(
        source_root / "editor" / "ui" / "activation_window.py", "__init__", "ActivationWindow"
    )
    request_load_calls = calls_in_function(
        source_root / "editor" / "ui" / "activation_window.py", "_load_request_info", "ActivationWindow"
    )
    activation_on_missing_license = "ActivationWindow" in main_calls and "activation_window.exec" in main_calls
    request_load_on_construction = "self._load_request_info" in activation_init_calls
    identity_or_request_on_load = {
        "self.activation_service.get_display_machine_id",
        "self.activation_service.generate_request_code",
    }.issubset(request_load_calls)
    require(
        activation_on_missing_license and request_load_on_construction and identity_or_request_on_load,
        "startup safety boundary changed; manual review is required before any bundle execution",
    )

    reason = (
        "The current no-license startup constructs ActivationWindow, whose constructor reads "
        "device identity and generates a request code before any identity-free ready marker. "
        "The experimental bundle was deliberately not executed."
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    stdout_log.write_text("[not executed] identity-free bundle startup seam is unavailable\n", encoding="utf-8")
    stderr_log.write_text("[blocked] no process was started; no runtime stderr exists\n", encoding="utf-8")
    payload: dict[str, object] = {
        "status": "BLOCKED",
        "production": False,
        "executed": False,
        "app_bundle_path": "$RUNNER_TEMP/launchflow-dist/LaunchFlow.app",
        "data_dir": "$RUNNER_TEMP/launchflow-bundle-data",
        "reason": reason,
        "identity_read": False,
        "request_generated": False,
        "license_read": False,
        "network_access": False,
        "process_started": False,
        "process_terminated": "not-applicable",
        "residual_processes": "not-applicable",
        "startup_evidence": "unavailable",
    }
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("bundle_launch_probe=BLOCKED")
    print("process_started=false")
    print("identity_read=false")
    print("request_generated=false")
    print("reason=no-approved-identity-free-ready-marker")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("bundle_launch_probe=FAIL")
        print("reason=" + safe_error_message(exc))
        raise SystemExit(1) from None
