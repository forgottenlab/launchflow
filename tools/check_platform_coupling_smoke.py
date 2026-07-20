"""Report platform coupling and reject unregistered core coupling.

The check is intentionally static and stdlib-only.  It scans product code plus
the release/export entry points, compares stable finding fingerprints with a
checked-in baseline, and fails when a new finding appears under a core package.
Existing coupling remains visible without making the current Windows Beta red.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sys
import tokenize
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "tools" / "check_platform_coupling_baseline.json"
CORE_ROOTS = ("editor", "runtime", "shared", "licensing")
TOOL_ENTRY_POINTS = (
    "tools/build_editor_release.py",
    "tools/build_single_exe.py",
    "tools/generate_app_icon.py",
    "tools/run_editor_dev.ps1",
)
REFERENCE_FILES = ("README.md", "README_EN.md", "CHANGELOG.md")
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "generated_licenses",
    "logs",
    "private",
    "temp",
}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    severity: str
    pattern: re.Pattern[str]
    description: str


@dataclass(frozen=True)
class Finding:
    rule_id: str
    category: str
    severity: str
    scope: str
    path: str
    line: int
    evidence: str
    fingerprint: str
    match_type: str = "unclassified"
    baseline: bool = False


RULES = (
    Rule(
        "WIN-API-001",
        "windows-api",
        "P1",
        re.compile(r"\bos\.startfile\b|\bwinreg\b|\bctypes\.windll\b|\bMessageBoxW\b"),
        "Windows-only API",
    ),
    Rule(
        "WIN-PROC-001",
        "process",
        "P1",
        re.compile(r"\bCREATE_NO_WINDOW\b|\bSTARTF_USESHOWWINDOW\b|\bSW_HIDE\b"),
        "Windows subprocess flag",
    ),
    Rule(
        "WIN-SHELL-001",
        "command-shell",
        "P1",
        re.compile(
            r"[\"'](?:cmd(?:\.exe)?|powershell(?:\.exe)?)[\"']|\bvol\s+C:",
            re.IGNORECASE,
        ),
        "Windows command shell or command",
    ),
    Rule(
        "WIN-PATH-001",
        "paths",
        "P1",
        re.compile(r"LOCALAPPDATA|USERPROFILE|AppData[/\\]Local"),
        "Windows user-data path or environment variable",
    ),
    Rule(
        "WIN-ASSET-001",
        "artifacts",
        "P2",
        re.compile(r"\.(?:exe|lnk|ico|bat|cmd|ps1)\b", re.IGNORECASE),
        "Windows artifact or script suffix",
    ),
    Rule(
        "WIN-DESKTOP-001",
        "desktop-integration",
        "P2",
        re.compile(r"AppUserModelID|SetCurrentProcessExplicitAppUserModelID|Segoe UI|Microsoft YaHei UI"),
        "Windows desktop integration or font",
    ),
    Rule(
        "WIN-HWID-001",
        "hardware-identity",
        "P1",
        re.compile(r"MachineGuid|HKEY_LOCAL_MACHINE|volume_serial", re.IGNORECASE),
        "Windows-oriented hardware identity source",
    ),
    Rule(
        "WIN-BRANCH-001",
        "platform-branch",
        "P2",
        re.compile(r"os\.name\s*(?:==|!=)\s*[\"']nt[\"']|sys\.platform\s*(?:==|!=)\s*[\"']win32[\"']"),
        "Explicit Windows platform branch",
    ),
    Rule(
        "UNIX-ASSUME-001",
        "unix-assumption",
        "P2",
        re.compile(r"/bin/sh|\.local/share"),
        "Single Unix fallback used for all non-Windows platforms",
    ),
    Rule(
        "PACK-ONEFILE-001",
        "packaging",
        "P2",
        re.compile(r"--onefile|PyInstaller|_MEIPASS"),
        "PyInstaller onefile packaging contract",
    ),
    Rule(
        "UI-SHORTCUT-001",
        "ui-input",
        "P2",
        re.compile(r"Ctrl\+(?:S|Shift\+S|R|E)"),
        "Literal Ctrl shortcut instead of a platform standard key",
    ),
)

FUTURE_TARGETS = {
    "windows-api": "DesktopIntegration or ApplicationLauncher",
    "process": "CommandBackend",
    "command-shell": "CommandBackend",
    "paths": "PlatformPaths",
    "artifacts": "ApplicationLauncher or PackagingBackend",
    "desktop-integration": "DesktopIntegration",
    "hardware-identity": "HardwareIdentityProvider",
    "platform-branch": "shared/platform/detection.py",
    "unix-assumption": "platform-specific backend selection",
    "packaging": "PackagingBackend",
    "ui-input": "PlatformInfo and Qt StandardKey",
}


def _normalized_evidence(line: str) -> str:
    return " ".join(line.strip().split())[:240]


def _fingerprint(path: str, rule_id: str, evidence: str) -> str:
    payload = f"{path}\0{rule_id}\0{evidence}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _python_lines(path: Path) -> dict[int, str]:
    """Return Python source without comments/docstrings, retaining real lines."""

    source = path.read_text(encoding="utf-8-sig")
    source_lines = source.splitlines()
    excluded_lines: set[int] = set()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"cannot parse {path}: {exc}") from exc
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        end_line = getattr(first, "end_lineno", first.lineno)
        excluded_lines.update(range(first.lineno, end_line + 1))

    comments: dict[int, int] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.start[1]
    except (IndentationError, SyntaxError, tokenize.TokenError) as exc:
        raise RuntimeError(f"cannot tokenize {path}: {exc}") from exc

    kept: dict[int, str] = {}
    for line_number, line in enumerate(source_lines, start=1):
        if line_number in excluded_lines:
            continue
        if line_number in comments:
            line = line[: comments[line_number]]
        if line.strip():
            kept[line_number] = line
    return kept


def _raw_lines(path: Path) -> dict[int, str]:
    return {
        index: line
        for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    }


def _scan_files() -> Iterable[tuple[Path, str]]:
    for root_name in CORE_ROOTS:
        root = ROOT / root_name
        for path in sorted(root.rglob("*.py")):
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            yield path, "core"
    for relative_path in TOOL_ENTRY_POINTS:
        path = ROOT / relative_path
        if path.is_file():
            yield path, "tooling"
    for relative_path in REFERENCE_FILES:
        path = ROOT / relative_path
        if path.is_file():
            yield path, "reference"
    docs_root = ROOT / "docs"
    if docs_root.is_dir():
        for path in sorted(docs_root.rglob("*.md")):
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            yield path, "reference"
    tools_root = ROOT / "tools"
    if tools_root.is_dir():
        for path in sorted(tools_root.glob("*.py")):
            relative_path = path.relative_to(ROOT).as_posix()
            if path.name == Path(__file__).name or relative_path in TOOL_ENTRY_POINTS:
                continue
            if path.name.startswith("check_") or path.name.startswith("validate_"):
                yield path, "reference"


def collect_findings() -> list[Finding]:
    findings: list[Finding] = []
    for path, scope in _scan_files():
        relative_path = path.relative_to(ROOT).as_posix()
        lines = _python_lines(path) if path.suffix.lower() == ".py" else _raw_lines(path)
        for line_number, line in sorted(lines.items()):
            evidence = _normalized_evidence(line)
            if not evidence:
                continue
            for rule in RULES:
                if not rule.pattern.search(line):
                    continue
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        severity=rule.severity,
                        scope=scope,
                        path=relative_path,
                        line=line_number,
                        evidence=evidence,
                        fingerprint=_fingerprint(relative_path, rule.rule_id, evidence),
                    )
                )
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule_id))


def load_baseline(path: Path) -> dict[str, dict[str, object]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read baseline {path}: {exc}") from exc
    if data.get("schema") != 1 or not isinstance(data.get("entries"), list):
        raise RuntimeError(f"unsupported baseline schema: {path}")
    entries: dict[str, dict[str, object]] = {}
    for item in data["entries"]:
        if not isinstance(item, dict) or not str(item.get("fingerprint", "")):
            raise RuntimeError(f"invalid baseline entry: {path}")
        entries[str(item["fingerprint"])] = item
    return entries


def write_baseline(path: Path, findings: list[Finding]) -> None:
    tracked = [finding for finding in findings if finding.scope != "reference"]
    payload = {
        "schema": 1,
        "description": "Known platform-coupling occurrences for the Windows Beta baseline.",
        "entries": [
            {
                "fingerprint": finding.fingerprint,
                "path": finding.path,
                "rule_id": finding.rule_id,
                "area": finding.category,
                "classification": (
                    "allowed_windows_boundary"
                    if finding.scope == "tooling"
                    or finding.path.startswith("shared/platform/")
                    else "platform_adapter_candidate"
                ),
                "reason": next(
                    rule.description for rule in RULES if rule.rule_id == finding.rule_id
                ),
                "future_target": FUTURE_TARGETS[finding.category],
                "allowed_to_remain": True,
            }
            for finding in tracked
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _with_baseline(
    findings: list[Finding], known: dict[str, dict[str, object]]
) -> list[Finding]:
    annotated: list[Finding] = []
    for finding in findings:
        entry = known.get(finding.fingerprint)
        if finding.scope == "reference":
            match_type = "docs_or_test_reference"
        elif entry is not None:
            match_type = str(entry.get("classification", "platform_adapter_candidate"))
        elif finding.scope == "core":
            match_type = "unexpected_core_coupling"
        else:
            match_type = "allowed_windows_boundary"
        annotated.append(
            Finding(
                **{
                    **asdict(finding),
                    "match_type": match_type,
                    "baseline": entry is not None,
                }
            )
        )
    return annotated


def _summary(
    findings: list[Finding], known: dict[str, dict[str, object]]
) -> dict[str, object]:
    tracked = [finding for finding in findings if finding.scope != "reference"]
    current = {finding.fingerprint for finding in tracked}
    new = [finding for finding in tracked if finding.fingerprint not in known]
    new_core = [
        finding for finding in findings if finding.match_type == "unexpected_core_coupling"
    ]
    categories: dict[str, int] = {}
    classifications = {
        "allowed_windows_boundary": 0,
        "platform_adapter_candidate": 0,
        "unexpected_core_coupling": 0,
        "docs_or_test_reference": 0,
    }
    for finding in findings:
        categories[finding.category] = categories.get(finding.category, 0) + 1
        classifications[finding.match_type] += 1
    return {
        "current": len(findings),
        "tracked": len(tracked),
        "baselined": len(tracked) - len(new),
        "new": len(new),
        "new_core": len(new_core),
        "stale_baseline": len(set(known) - current),
        "categories": dict(sorted(categories.items())),
        "classifications": classifications,
    }


def _print_text(findings: list[Finding], summary: dict[str, object]) -> None:
    for finding in findings:
        if finding.baseline:
            status = "baseline"
        elif finding.scope == "reference":
            status = "reference"
        else:
            status = "NEW"
        print(
            f"{status:8} {finding.match_type:28} {finding.severity} {finding.category:20} "
            f"{finding.path}:{finding.line} [{finding.rule_id}] {finding.evidence}"
        )
    print(
        "summary "
        f"current={summary['current']} tracked={summary['tracked']} "
        f"baselined={summary['baselined']} "
        f"new={summary['new']} new_core={summary['new_core']} "
        f"stale_baseline={summary['stale_baseline']}"
    )
    category_text = " ".join(
        f"{name}={count}" for name, count in dict(summary["categories"]).items()
    )
    print(f"categories {category_text}")
    classification_text = " ".join(
        f"{name}={count}"
        for name, count in dict(summary["classifications"]).items()
    )
    print(f"classifications {classification_text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Replace the selected baseline with the current reviewed findings.",
    )
    args = parser.parse_args()

    try:
        findings = collect_findings()
        if args.write_baseline:
            write_baseline(args.baseline, findings)
        known = load_baseline(args.baseline)
    except RuntimeError as exc:
        print(f"platform coupling check error: {exc}", file=sys.stderr)
        return 2

    annotated = _with_baseline(findings, known)
    summary = _summary(annotated, known)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema": 1,
                    "baseline": args.baseline.resolve().as_posix(),
                    "summary": summary,
                    "findings": [asdict(finding) for finding in annotated],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_text(annotated, summary)
    return 1 if int(summary["new_core"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
