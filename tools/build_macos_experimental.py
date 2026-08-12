"""Build an unsigned, non-production LaunchFlow app on macOS arm64 only."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_IDENTIFIER = "io.github.forgottenlab.launchflow"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validated_output(path: str, label: str, runner_temp: Path) -> Path:
    candidate = Path(path)
    _require(candidate.is_absolute(), f"{label} must be an explicit absolute path")
    resolved = candidate.resolve()
    _require(not _inside(resolved, ROOT.resolve()), f"{label} must stay outside the repository")
    _require(_inside(resolved, runner_temp), f"{label} must stay inside $RUNNER_TEMP")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _sanitized_bundle_path(app: Path, dist_path: Path) -> str:
    return "$RUNNER_TEMP/launchflow-dist/" + app.relative_to(dist_path).as_posix()


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sanitize_output(text: str, runner_temp: Path) -> str:
    result = text
    replacements = (
        (str(ROOT.resolve()), "$GITHUB_WORKSPACE"),
        (str(runner_temp), "$RUNNER_TEMP"),
        (os.environ.get("RUNNER_TOOL_CACHE", ""), "$RUNNER_TOOL_CACHE"),
        (os.environ.get("HOME", ""), "$HOME"),
    )
    for source, replacement in replacements:
        if source:
            result = result.replace(source, replacement)
    result = re.sub(r"/Users/[^/\s]+", "$HOME", result)
    if len(result) > 500_000:
        result = "[earlier build output truncated]\n" + result[-500_000:]
    return result


def _safe_error_message(error: BaseException) -> str:
    result = f"{type(error).__name__}: {error}"
    for variable in ("GITHUB_WORKSPACE", "RUNNER_TEMP", "RUNNER_TOOL_CACHE", "HOME"):
        source = os.environ.get(variable, "")
        if source:
            result = result.replace(source, "$" + variable)
    return re.sub(r"/Users/[^/\s]+", "$HOME", result)[:2_000]


def _file_description(path: Path) -> str:
    completed = subprocess.run(
        ["file", "-b", str(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _require(completed.returncode == 0, "file architecture inspection failed")
    return completed.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-path", required=True)
    parser.add_argument("--dist-path", required=True)
    parser.add_argument("--spec-path", required=True)
    parser.add_argument("--result-json", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    host_system = platform.system()
    host_arch = platform.machine().lower()
    if host_system != "Darwin" or host_arch != "arm64":
        print("build_status=REFUSED")
        print("reason=experimental builder requires Darwin arm64")
        return 2

    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    _require(runner_temp_value, "RUNNER_TEMP is required for the experimental builder")
    runner_temp = Path(runner_temp_value).expanduser().resolve()
    _require(runner_temp.is_absolute(), "RUNNER_TEMP must be absolute")

    work_path = _validated_output(args.work_path, "work path", runner_temp)
    dist_path = _validated_output(args.dist_path, "dist path", runner_temp)
    spec_path = _validated_output(args.spec_path, "spec path", runner_temp)
    report_path = Path(args.result_json)
    _require(report_path.is_absolute(), "result JSON must be an explicit absolute path")
    report_path = report_path.resolve()
    _require(_inside(report_path, runner_temp), "result JSON must stay inside $RUNNER_TEMP")
    _require(not _inside(report_path, ROOT.resolve()), "result JSON must stay outside the repository")

    entry_point = ROOT / "editor" / "main.py"
    _require(entry_point.is_file(), "editor entry point is missing")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "LaunchFlow",
        "--osx-bundle-identifier",
        BUNDLE_IDENTIFIER,
        "--target-architecture",
        "arm64",
        "--workpath",
        str(work_path),
        "--distpath",
        str(dist_path),
        "--specpath",
        str(spec_path),
        "--log-level",
        "WARN",
        str(entry_point),
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    build_log = report_path.parent / "build-log.txt"
    build_log.parent.mkdir(parents=True, exist_ok=True)
    build_log.write_text(_sanitize_output(completed.stdout, runner_temp), encoding="utf-8")
    app_bundle = dist_path / "LaunchFlow.app"
    executable = app_bundle / "Contents" / "MacOS" / "LaunchFlow"
    success = completed.returncode == 0 and app_bundle.is_dir() and executable.is_file()
    architecture = _file_description(executable) if success else "unavailable"
    success = bool(success and "arm64" in architecture.lower())
    payload: dict[str, object] = {
        "success": success,
        "host_system": host_system,
        "host_arch": host_arch,
        "python_version": platform.python_version(),
        "pyinstaller_version": version("PyInstaller"),
        "app_bundle_path": _sanitized_bundle_path(app_bundle, dist_path),
        "build_log": "$RUNNER_TEMP/launchflow-evidence/build-log.txt",
        "bundle_identifier": BUNDLE_IDENTIFIER,
        "executable_architecture": architecture,
        "signed": False,
        "notarized": False,
        "production": False,
    }
    _write_report(report_path, payload)
    print("build_status=" + ("PASS" if success else "FAIL"))
    print("app_bundle=$RUNNER_TEMP/launchflow-dist/LaunchFlow.app")
    print("signed=false")
    print("notarized=false")
    print("production=false")
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("build_status=REFUSED")
        print("reason=" + _safe_error_message(exc))
        raise SystemExit(2) from None
