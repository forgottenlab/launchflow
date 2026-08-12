"""Inspect an experimental macOS arm64 app bundle without loading its code or keys."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import subprocess
from pathlib import Path


EXPECTED_BUNDLE_ID = "io.github.forgottenlab.launchflow"
SENSITIVE_SUFFIXES = {
    ".key",
    ".lic",
    ".lflic",
    ".lreq",
    ".mobileprovision",
    ".p12",
    ".pem",
    ".pfx",
}
SENSITIVE_NAME_PARTS = (
    "private_key",
    "private-key",
    "request_code",
    "request-code",
)


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


def file_description(path: Path) -> str:
    completed = subprocess.run(
        ["file", "-b", str(path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    require(completed.returncode == 0, "file inspection failed")
    return completed.stdout.strip()


def signature_status(app: Path) -> tuple[bool, bool, str]:
    completed = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(app)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    detail = completed.stdout + "\n" + completed.stderr
    distribution_signed = "Authority=" in detail or "TeamIdentifier=" in detail and "TeamIdentifier=not set" not in detail
    ad_hoc = completed.returncode == 0 and "Signature=adhoc" in detail
    require(not distribution_signed, "unexpected distribution signing identity found")
    status = "ad-hoc-only" if ad_hoc else "unsigned"
    return distribution_signed, ad_hoc, status


def candidate_macho_files(frameworks: Path) -> list[Path]:
    candidates: list[Path] = []
    if not frameworks.is_dir():
        return candidates
    for path in frameworks.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        framework_executables = {
            part[: -len(".framework")]
            for part in path.parts
            if part.endswith(".framework")
        }
        if path.suffix.lower() in {".dylib", ".so"} or path.name in framework_executables:
            candidates.append(path)
    return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require(platform.system() == "Darwin", "bundle probe requires Darwin")
    require(platform.machine().lower() == "arm64", "bundle probe requires arm64")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    require(runner_temp_value, "RUNNER_TEMP is required")
    runner_temp = Path(runner_temp_value).resolve()

    app = Path(args.app)
    report = Path(args.report)
    require(app.is_absolute() and report.is_absolute(), "app and report paths must be absolute")
    app = app.resolve()
    report = report.resolve()
    require(inside(app, runner_temp), "app bundle must stay inside $RUNNER_TEMP")
    require(inside(report, runner_temp), "report must stay inside $RUNNER_TEMP")
    require(app.name == "LaunchFlow.app" and app.is_dir(), "LaunchFlow.app is missing")

    contents = app / "Contents"
    executable = contents / "MacOS" / "LaunchFlow"
    plist_path = contents / "Info.plist"
    resources = contents / "Resources"
    frameworks = contents / "Frameworks"
    require(executable.is_file(), "Contents/MacOS/LaunchFlow is missing")
    require(plist_path.is_file(), "Contents/Info.plist is missing")
    require(resources.is_dir(), "Contents/Resources is missing")
    require(frameworks.is_dir(), "Contents/Frameworks is missing")

    with plist_path.open("rb") as stream:
        plist = plistlib.load(stream)
    expected_fields = {
        "CFBundleIdentifier": EXPECTED_BUNDLE_ID,
        "CFBundleName": "LaunchFlow",
        "CFBundleExecutable": "LaunchFlow",
        "CFBundlePackageType": "APPL",
    }
    for field, expected in expected_fields.items():
        require(plist.get(field) == expected, f"unexpected {field}")

    executable_architecture = file_description(executable)
    require("mach-o" in executable_architecture.lower(), "main executable is not Mach-O")
    require("arm64" in executable_architecture.lower(), "main executable is not arm64")

    inspected_macho = 0
    architecture_failures: list[str] = []
    for candidate in candidate_macho_files(frameworks):
        description = file_description(candidate)
        if "mach-o" not in description.lower():
            continue
        inspected_macho += 1
        if "arm64" not in description.lower():
            architecture_failures.append(candidate.relative_to(app).as_posix())
    require(not architecture_failures, "a bundled Mach-O dependency lacks arm64 architecture")

    cocoa_plugins = [
        path.relative_to(app).as_posix()
        for path in app.rglob("libqcocoa.dylib")
        if "plugins/platforms" in path.as_posix()
    ]
    require(cocoa_plugins, "Qt cocoa platform plugin is missing")

    sensitive_names: list[str] = []
    windows_executables: list[str] = []
    for path in app.rglob("*"):
        relative = path.relative_to(app).as_posix()
        lowered_name = path.name.lower()
        if path.is_file() and path.suffix.lower() == ".exe":
            windows_executables.append(relative)
        if path.is_file() and (
            path.suffix.lower() in SENSITIVE_SUFFIXES
            or any(marker in lowered_name for marker in SENSITIVE_NAME_PARTS)
        ):
            sensitive_names.append(relative)
    require(not windows_executables, "Windows .exe found in macOS bundle")
    require(not sensitive_names, "sensitive key/request/license filename found in bundle")
    distribution_signed, ad_hoc_signed, signature_probe = signature_status(app)

    payload: dict[str, object] = {
        "status": "PASS",
        "production": False,
        "bundle_path": "$RUNNER_TEMP/launchflow-dist/LaunchFlow.app",
        "bundle_identifier": plist["CFBundleIdentifier"],
        "bundle_name": plist["CFBundleName"],
        "bundle_executable": plist["CFBundleExecutable"],
        "bundle_package_type": plist["CFBundlePackageType"],
        "minimum_system_version": plist.get("LSMinimumSystemVersion"),
        "executable_architecture": executable_architecture,
        "macho_dependencies_inspected": inspected_macho,
        "macho_architecture_failures": architecture_failures,
        "qt_cocoa_plugin": cocoa_plugins[0],
        "windows_executables": 0,
        "sensitive_filenames": 0,
        "signed": distribution_signed,
        "ad_hoc_signed": ad_hoc_signed,
        "notarized": False,
        "signature_probe": signature_probe,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("bundle_probe=PASS")
    print("bundle=$RUNNER_TEMP/launchflow-dist/LaunchFlow.app")
    print(f"macho_dependencies_inspected={inspected_macho}")
    print("sensitive_filenames=0")
    print("signed=false")
    print("notarized=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("bundle_probe=FAIL")
        print("reason=" + safe_error_message(exc))
        raise SystemExit(1) from None
