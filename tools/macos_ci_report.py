"""Produce sanitized Phase 2a1 coupling evidence and audit the upload allowlist."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COUPLING_CHECKER = ROOT / "tools" / "check_platform_coupling_smoke.py"
TEXT_EVIDENCE = {
    "build-log.txt",
    "build-result.json",
    "bundle-report.json",
    "dependency-versions.txt",
    "launch-report.json",
    "launch-stderr.log",
    "launch-stdout.log",
    "platform-coupling.json",
    "smoke-report.json",
}
UPLOAD_EVIDENCE = TEXT_EVIDENCE | {"gui-main-window.png"}
SENSITIVE_TEXT = (
    re.compile(r"-----BEGIN (?:RSA )?(?:PUBLIC|PRIVATE) KEY-----", re.IGNORECASE),
    re.compile(r"-----BEGIN ENCRYPTED " r"PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:LFREQ1|LFREQ2|LFLIC2)\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}", re.IGNORECASE),
    re.compile(r"(?i)private[/\\]private_key\.pem|private_key\.pem"),
    re.compile(r"(?i)\b(?:GITHUB_TOKEN|AC_PASSWORD|APPLE_ID|ASC_PROVIDER|APPLE_API_KEY)\s*="),
    re.compile(r"/Users/[^/\s]+"),
)
SENSITIVE_ARCHIVE_SUFFIXES = {
    ".key",
    ".lic",
    ".lflic",
    ".lreq",
    ".mobileprovision",
    ".p12",
    ".pem",
    ".pfx",
}


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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def coupling_report(checker: Path, output: Path) -> int:
    require(checker.resolve() == COUPLING_CHECKER.resolve(), "only the repository coupling checker is allowed")
    completed = subprocess.run(
        [sys.executable, str(checker), "--format", "json"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    require(completed.returncode == 0, "platform coupling checker failed")
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("platform coupling checker returned invalid JSON") from exc
    summary = raw.get("summary")
    require(isinstance(summary, dict), "platform coupling summary is missing")
    for field in ("new", "new_core", "stale_baseline"):
        require(summary.get(field) == 0, f"platform coupling gate failed: {field}")
    classifications = summary.get("classifications")
    require(isinstance(classifications, dict), "platform coupling classifications are missing")
    require(
        classifications.get("unexpected_core_coupling") == 0,
        "platform coupling gate failed: unexpected_core_coupling",
    )
    payload: dict[str, object] = {
        "status": "PASS",
        "new": 0,
        "new_core": 0,
        "unexpected_core_coupling": 0,
        "stale_baseline": 0,
        "finding_details_uploaded": False,
    }
    write_json(output, payload)
    print("platform_coupling=PASS")
    print("new=0")
    print("new_core=0")
    print("unexpected_core_coupling=0")
    print("stale_baseline=0")
    return 0


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def scan_upload(evidence_dir: Path, archive: Path, output_dir: Path) -> int:
    runner_temp_value = os.environ.get("RUNNER_TEMP", "").strip()
    require(runner_temp_value, "RUNNER_TEMP is required")
    runner_temp = Path(runner_temp_value).resolve()
    evidence_dir = evidence_dir.resolve()
    archive = archive.resolve()
    output_dir = output_dir.resolve()
    require(inside(evidence_dir, runner_temp), "evidence directory must stay inside $RUNNER_TEMP")
    require(inside(archive, runner_temp), "archive must stay inside $RUNNER_TEMP")
    require(inside(output_dir, runner_temp), "upload directory must stay inside $RUNNER_TEMP")
    output_dir.mkdir(parents=True, exist_ok=True)
    require(not any(output_dir.iterdir()), "curated upload directory must start empty")

    actual = {path.name for path in evidence_dir.iterdir() if path.is_file()} if evidence_dir.is_dir() else set()
    require(actual <= UPLOAD_EVIDENCE, "evidence directory contains a file outside the upload allowlist")

    findings: list[str] = []
    for name in sorted(TEXT_EVIDENCE & actual):
        path = evidence_dir / name
        require(path.stat().st_size <= 2_000_000, f"text evidence is unexpectedly large: {name}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in SENSITIVE_TEXT):
            findings.append(name)
    png = evidence_dir / "gui-main-window.png"
    if png.is_file():
        require(png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "GUI evidence is not a PNG")

    archive_findings: list[str] = []
    if archive.is_file():
        with zipfile.ZipFile(archive) as bundle_zip:
            names = bundle_zip.namelist()
        require(any(name.endswith("LaunchFlow.app/Contents/Info.plist") for name in names), "app bundle is absent from ZIP")
        for name in names:
            path = Path(name)
            lowered = path.name.lower()
            if path.suffix.lower() in SENSITIVE_ARCHIVE_SUFFIXES or "private_key" in lowered:
                archive_findings.append(name)
    require(not findings, "sensitive text was found in upload evidence")
    require(not archive_findings, "sensitive filename was found in app ZIP")

    for name in sorted(actual):
        shutil.copy2(evidence_dir / name, output_dir / name)
    if archive.is_file():
        shutil.copy2(archive, output_dir / archive.name)
    missing = sorted(UPLOAD_EVIDENCE - actual)
    if not archive.is_file():
        missing.append(archive.name)
    status = "PASS" if not missing else "PARTIAL"
    write_json(
        output_dir / "upload-scan.json",
        {
            "status": status,
            "production": False,
            "available_files": sorted(actual | ({archive.name} if archive.is_file() else set())),
            "missing_files": missing,
            "sensitive_text_findings": 0,
            "sensitive_archive_names": 0,
        },
    )
    print("upload_allowlist_scan=" + status)
    print(f"text_evidence_files={len(TEXT_EVIDENCE & actual)}")
    print("gui_png=" + ("validated" if png.is_file() else "unavailable"))
    print("sensitive_text_findings=0")
    print("sensitive_archive_names=0")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    coupling = subparsers.add_parser("coupling")
    coupling.add_argument("--checker", required=True)
    coupling.add_argument("--output", required=True)
    scan = subparsers.add_parser("scan-upload")
    scan.add_argument("--evidence-dir", required=True)
    scan.add_argument("--archive", required=True)
    scan.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "coupling":
        return coupling_report(Path(args.checker), Path(args.output))
    return scan_upload(Path(args.evidence_dir), Path(args.archive), Path(args.output_dir))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("macos_ci_report=FAIL")
        print("reason=" + safe_error_message(exc))
        raise SystemExit(1) from None
