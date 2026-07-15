"""Verify LaunchFlow mutable-data paths without touching real AppData."""

from __future__ import annotations

import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor.services.plan_service import PlanService
from licensing.license_manager import LicenseManager
from shared.app_logging import get_app_logger, reset_app_logger_for_tests
from shared.app_paths import (
    APP_DATA_ENV,
    APP_SUBDIRECTORIES,
    AppPathError,
    ensure_app_directories,
    get_app_data_dir,
)
from shared.models import Plan, WaitStep


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-path-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    override = temp_root / "测试 AppData 空格"
    alternate_cwd = temp_root / "任意 cwd 空格"
    temp_root.mkdir(parents=True)
    alternate_cwd.mkdir()

    protected_source_files = [PROJECT_ROOT / "data" / "app_templates.json", PROJECT_ROOT / "data" / "settings.json"]
    before_hashes = {path: _sha256(path) for path in protected_source_files}
    old_override = os.environ.get(APP_DATA_ENV)
    old_cwd = Path.cwd()
    old_executable = sys.executable

    try:
        os.environ[APP_DATA_ENV] = str(override)
        paths = ensure_app_directories()
        if paths["root"] != override:
            raise AssertionError(f"override mismatch: {paths['root']} != {override}")
        for name in APP_SUBDIRECTORIES:
            if paths[name] != override / name or not paths[name].is_dir():
                raise AssertionError(f"missing or misplaced app directory: {name}={paths[name]}")

        os.chdir(alternate_cwd)
        sys.executable = str(temp_root / "桌面模拟" / "LaunchFlow.exe")
        if get_app_data_dir() != override:
            raise AssertionError("data root changed with cwd or sys.executable")

        plan_service = PlanService(PROJECT_ROOT)
        plan = Plan(plan_name="路径隔离 smoke", steps=[WaitStep(name="等待", seconds=0.1)])
        plan_path = plan_service.get_plans_dir() / "路径隔离 smoke.json"
        plan_service.save_plan(plan, plan_path)
        loaded = plan_service.load_plan(plan_path)
        if loaded.plan_name != plan.plan_name:
            raise AssertionError("plan round-trip failed")

        import_source = temp_root / "example-license.lic"
        import_source.write_text(json.dumps({"kind": "example-only", "signature": "REDACTED"}), encoding="utf-8")
        manager = LicenseManager(PROJECT_ROOT)
        manager.import_license_file(import_source)
        reloaded = LicenseManager(PROJECT_ROOT).load_license()
        if reloaded.get("kind") != "example-only":
            raise AssertionError("license import/reload failed")

        logger = get_app_logger()
        logger.info("app path smoke")
        for handler in logger.handlers:
            handler.flush()
        rotating = [handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)]
        if len(rotating) != 1:
            raise AssertionError(f"expected one rotating handler, found {len(rotating)}")
        if rotating[0].maxBytes != 1_000_000 or rotating[0].backupCount != 3:
            raise AssertionError("unexpected log rotation contract")
        if not (override / "logs" / "launchflow.log").is_file():
            raise AssertionError("application log was not written under the override")

        for mutable_path in (
            plan_service.templates_path,
            plan_service.settings_path,
            plan_service.user_plans_dir,
            plan_service.build_cache_dir,
            plan_service.logs_dir,
            manager.license_path,
        ):
            if override not in mutable_path.parents:
                raise AssertionError(f"mutable path escaped override: {mutable_path}")

        os.environ[APP_DATA_ENV] = "relative-data-root"
        try:
            get_app_data_dir()
        except AppPathError:
            pass
        else:
            raise AssertionError("relative LAUNCHFLOW_DATA_DIR was accepted")

        after_hashes = {path: _sha256(path) for path in protected_source_files}
        if before_hashes != after_hashes:
            raise AssertionError("read-only source data changed")
    finally:
        reset_app_logger_for_tests()
        sys.executable = old_executable
        os.chdir(old_cwd)
        if old_override is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_override
        shutil.rmtree(temp_root, ignore_errors=True)

    print("app paths smoke ok")
    print(f"override_root={override}")
    print(f"directories={','.join(APP_SUBDIRECTORIES)}")
    print("cwd_and_executable_independence=ok")
    print("plan_round_trip=ok")
    print("example_license_import_reload=ok")
    print("log_rotation=maxBytes:1000000,backupCount:3")
    print("source_data_hashes=unchanged")


if __name__ == "__main__":
    main()
