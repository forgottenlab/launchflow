"""Conservative copy-only migration from known legacy LaunchFlow locations."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from shared.app_paths import (
    ensure_app_directories,
    get_app_data_dir,
    get_config_dir,
    get_data_dir,
    get_license_dir,
    get_logs_dir,
    get_plans_dir,
)


MIGRATION_MARKER = "legacy_data_migration_v1.json"
BLOCKED_PARTS = {"private", "generated_licenses"}


@dataclass
class MigrationResult:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _safe_copy(source: Path, destination: Path, result: MigrationResult) -> None:
    if not source.is_file():
        return
    lowered_parts = {part.lower() for part in source.parts}
    if lowered_parts & BLOCKED_PARTS or source.name.lower() == "private_key.pem":
        result.skipped.append(f"blocked:{source}")
        return
    if destination.exists():
        result.skipped.append(f"exists:{destination}")
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        result.copied.append(f"{source} -> {destination}")
    except OSError as exc:
        result.errors.append(f"{source}: {exc}")


def _copy_files(source_dir: Path, destination_dir: Path, result: MigrationResult, pattern: str = "*") -> None:
    if not source_dir.is_dir():
        return
    for source in sorted(source_dir.glob(pattern)):
        if source.is_file():
            _safe_copy(source, destination_dir / source.name, result)


def _known_legacy_roots(project_root: Path) -> list[Path]:
    roots = [project_root.resolve()]
    cwd = Path.cwd().resolve()
    if cwd != roots[0] and ((cwd / "LaunchFlow.exe").exists() or (cwd / "editor" / "main.py").exists()):
        roots.append(cwd)
    return roots


def _write_migration_log(result: MigrationResult) -> None:
    try:
        path = get_logs_dir() / "migration.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now().isoformat(timespec='seconds')}] ")
            handle.write(
                f"copied={len(result.copied)} skipped={len(result.skipped)} errors={len(result.errors)}\n"
            )
            for label, entries in (("copied", result.copied), ("skipped", result.skipped), ("error", result.errors)):
                for entry in entries:
                    handle.write(f"  {label}: {entry}\n")
    except OSError:
        pass


def migrate_legacy_data(
    project_root: Path,
    *,
    legacy_roots: Iterable[Path] | None = None,
    write_marker: bool = True,
) -> MigrationResult:
    """Copy known legacy user files into AppData without deleting or overwriting."""
    ensure_app_directories()
    marker_path = get_config_dir() / MIGRATION_MARKER
    if write_marker and marker_path.exists():
        result = MigrationResult(skipped=[f"marker:{marker_path}"])
        _write_migration_log(result)
        return result

    result = MigrationResult()
    roots = list(legacy_roots) if legacy_roots is not None else _known_legacy_roots(project_root)
    app_root = get_app_data_dir().resolve()

    for raw_root in roots:
        root = Path(raw_root).resolve()
        if root == app_root or app_root in root.parents:
            continue

        _safe_copy(root / "licenses" / "license.lic", get_license_dir() / "license.lic", result)
        _copy_files(root / "plans", get_plans_dir(), result, "*.json")
        _copy_files(root / "data" / "user_plans", get_plans_dir(), result, "*.json")
        _copy_files(root / "editor" / "data" / "user_plans", get_plans_dir(), result, "*.json")
        _copy_files(root / "logs", get_logs_dir(), result, "*.log")
        _copy_files(root / "config", get_config_dir(), result, "*.json")

        _safe_copy(root / "data" / "settings.json", get_config_dir() / "settings.json", result)
        _safe_copy(root / "editor" / "data" / "settings.json", get_config_dir() / "settings.json", result)
        _safe_copy(root / "data" / "app_templates.json", get_data_dir() / "app_templates.json", result)
        _safe_copy(
            root / "editor" / "data" / "app_templates.json",
            get_data_dir() / "app_templates.json",
            result,
        )

    _write_migration_log(result)
    if write_marker:
        try:
            marker_path.write_text(
                json.dumps(
                    {
                        "attempted_at": datetime.now().isoformat(timespec="seconds"),
                        "copied": len(result.copied),
                        "skipped": len(result.skipped),
                        "errors": len(result.errors),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            result.errors.append(f"marker:{exc}")
    return result
