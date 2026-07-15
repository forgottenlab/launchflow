"""Verify conservative copy-only migration into isolated LaunchFlow data."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.app_paths import APP_DATA_ENV, ensure_app_directories
from shared.data_migration import MIGRATION_MARKER, migrate_legacy_data


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-migration-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    legacy_root = temp_root / "旧版 便携目录"
    app_root = temp_root / "测试 AppData 空格"
    temp_root.mkdir(parents=True)
    old_override = os.environ.get(APP_DATA_ENV)

    legacy_files = {
        "licenses/license.lic": '{"kind":"example-only"}',
        "plans/direct.json": '{"plan_name":"direct","steps":[]}',
        "data/user_plans/new.json": '{"plan_name":"new","steps":[]}',
        "data/user_plans/existing.json": '{"plan_name":"legacy-existing","steps":[]}',
        "logs/old.log": "legacy log",
        "config/preferences.json": '{"theme":"light"}',
        "config/secret.txt": "must not migrate",
        "data/settings.json": '{"theme":"dark"}',
        "data/app_templates.json": "[]",
        "private/private_key.pem": "example-private-key",
        "generated_licenses/formal.lic": "must not migrate",
    }
    for relative, content in legacy_files.items():
        _write(legacy_root / relative, content)

    try:
        os.environ[APP_DATA_ENV] = str(app_root)
        paths = ensure_app_directories()
        existing_target = paths["plans"] / "existing.json"
        _write(existing_target, '{"plan_name":"keep-target","steps":[]}')

        result = migrate_legacy_data(PROJECT_ROOT, legacy_roots=[legacy_root])
        if result.errors:
            raise AssertionError(f"migration reported errors: {result.errors}")
        expected = [
            paths["licenses"] / "license.lic",
            paths["plans"] / "direct.json",
            paths["plans"] / "new.json",
            paths["logs"] / "old.log",
            paths["config"] / "preferences.json",
            paths["config"] / "settings.json",
            paths["data"] / "app_templates.json",
        ]
        missing = [path for path in expected if not path.is_file()]
        if missing:
            raise AssertionError(f"expected migrated files missing: {missing}")
        if json.loads(existing_target.read_text(encoding="utf-8"))["plan_name"] != "keep-target":
            raise AssertionError("existing destination was overwritten")
        if not any(item.startswith("exists:") and item.endswith("existing.json") for item in result.skipped):
            raise AssertionError("existing destination skip was not reported")

        forbidden_names = {"private_key.pem", "formal.lic", "secret.txt"}
        forbidden_hits = [path for path in app_root.rglob("*") if path.is_file() and path.name in forbidden_names]
        if forbidden_hits:
            raise AssertionError(f"forbidden legacy files migrated: {forbidden_hits}")
        for relative in legacy_files:
            if not (legacy_root / relative).is_file():
                raise AssertionError(f"legacy source was deleted or moved: {relative}")

        marker = paths["config"] / MIGRATION_MARKER
        migration_log = paths["logs"] / "migration.log"
        if not marker.is_file() or not migration_log.is_file():
            raise AssertionError("migration marker or log missing")
        second = migrate_legacy_data(PROJECT_ROOT, legacy_roots=[legacy_root])
        if second.copied or len(second.skipped) != 1 or not second.skipped[0].startswith("marker:"):
            raise AssertionError(f"second migration was not marker-skipped: {second}")
    finally:
        if old_override is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_override
        shutil.rmtree(temp_root, ignore_errors=True)

    print("data migration smoke ok")
    print(f"copied={len(result.copied)}")
    print(f"skipped={len(result.skipped)}")
    print(f"errors={len(result.errors)}")
    print("existing_destination=preserved")
    print("legacy_sources=preserved")
    print("private_generated_and_non_json_config=excluded")
    print("second_run=marker-skipped")


if __name__ == "__main__":
    main()
