"""Verify Phase 2 launch entries, Basic data isolation, and the restricted runner.

This smoke is side-effect free with respect to real AppData, licenses, HWID,
and PyInstaller. It uses isolated temporary directories and source inspection.

Usage:
    python tools/check_dual_edition_phase2_smoke.py
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor.launch import (
    BASIC_APP_DIR_NAME,
    BASIC_EDITOR_APP_ID,
    BASIC_EDITOR_ENTRY,
    CURRENT_PRODUCT_ENTRY,
    apply_basic_launch_edition,
    apply_current_product_launch_edition,
    apply_launch_edition_for_entry,
    edition_for_launch_entry,
)
from shared.app_paths import (
    APP_DATA_ENV,
    APP_DIR_NAME,
    APP_SUBDIRECTORIES,
    AppPathError,
    ensure_app_directories,
    get_active_app_dir_name,
    get_app_data_dir,
)
from shared.data_migration import migrate_legacy_data
from shared.edition_policy import (
    BASIC_EDITION,
    EditionContext,
    get_edition_context,
    is_basic_edition_active,
    set_process_edition_context,
)
from tools import build_single_exe
from tools.basic_embedded_runner import BASIC_EMBEDDED_TEMPLATE
from tools.build_editor_release import (
    build_basic_editor_command,
    build_editor_command,
)
from tools.dual_edition_phase0_contract import (
    BASIC_DATA_DIR_NAME,
    basic_runner_source_violations,
    data_directory_names,
    professional_runner_source_missing,
)


FROZEN_PROFESSIONAL_TEMPLATE_SHA256 = (
    "3ba5e0ea8727b8b88644d072cf746602f8d25a93861a1d29e17e165d0c047e35"
)

BASIC_COMPATIBLE_PLAN = {
    "plan_name": "basic-phase2",
    "version": "1.0",
    "steps": [
        {
            "id": "app-1",
            "type": "app",
            "name": "本地应用",
            "enabled": True,
            "delay_after": 1.0,
            "path": r"C:\Windows\System32\notepad.exe",
            "args": [],
            "working_dir": "",
            "start_minimized": False,
        },
        {
            "id": "url-1",
            "type": "url",
            "name": "网页",
            "enabled": True,
            "delay_after": 1.0,
            "url": "https://example.com",
            "browser_path": "",
        },
    ],
}

COMMAND_PLAN = {
    "plan_name": "professional-command",
    "version": "1.0",
    "steps": [
        {
            "id": "cmd-1",
            "type": "command",
            "name": "命令",
            "enabled": True,
            "delay_after": 1.0,
            "command": "echo hello",
            "shell": "cmd",
            "working_dir": "",
            "new_window": False,
        }
    ],
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def check_launch_entries() -> None:
    require(edition_for_launch_entry(CURRENT_PRODUCT_ENTRY) is None, "current entry must stay unset/Professional")
    require(edition_for_launch_entry("editor/main.py") is None, "editor/main.py must stay Professional")
    require(edition_for_launch_entry(BASIC_EDITOR_ENTRY) == BASIC_EDITION, "basic entry must map to basic")
    require(edition_for_launch_entry("editor/main_basic.py") == BASIC_EDITION, "main_basic path must map to basic")

    previous = set_process_edition_context(EditionContext(edition=BASIC_EDITION))
    try:
        context = apply_current_product_launch_edition()
        require(context.edition is None, "current product entry must reset to the unset Professional path")
        require(not is_basic_edition_active(), "current product entry must not leave Basic active")
        require(get_active_app_dir_name() == APP_DIR_NAME, "Professional path must keep LaunchFlow")

        basic = apply_launch_edition_for_entry(BASIC_EDITOR_ENTRY)
        require(basic.edition == BASIC_EDITION, "Basic entry did not set process context")
        require(is_basic_edition_active(), "Basic entry must activate Basic context")
        require(get_active_app_dir_name() == BASIC_APP_DIR_NAME, "Basic entry must select LaunchFlow-Basic")

        current = apply_launch_edition_for_entry(CURRENT_PRODUCT_ENTRY)
        require(current.edition is None, "re-applying the current entry must leave Basic")
        require(not is_basic_edition_active(), "Professional relaunch must not stay on Basic")
    finally:
        set_process_edition_context(previous)

    main_source = (PROJECT_ROOT / "editor" / "main.py").read_text(encoding="utf-8")
    basic_source = (PROJECT_ROOT / "editor" / "main_basic.py").read_text(encoding="utf-8")
    require("apply_launch_edition_for_entry(CURRENT_PRODUCT_ENTRY)" in main_source, "Professional entry is not wired")
    require("apply_launch_edition_for_entry(BASIC_EDITOR_ENTRY)" in basic_source, "Basic entry is not wired")
    require("LicenseManager" in main_source and "migrate_legacy_data" in main_source, "Professional startup contract changed")
    require("ActivationWindow" in main_source, "Professional activation path changed")
    require("LicenseManager" not in basic_source, "Basic entry imported LicenseManager")
    require("ActivationWindow" not in basic_source, "Basic entry opened an activation window")
    require("migrate_legacy_data" not in basic_source, "Basic entry still calls legacy migration")
    require("validate_current_license" not in basic_source, "Basic entry probes licenses")
    require("get_machine_id" not in basic_source, "Basic entry probes hardware identity")
    require("configure_windows_app_id(BASIC_EDITOR_APP_ID)" in basic_source, "Basic entry is missing a distinct Windows identity")
    launch_source = (PROJECT_ROOT / "editor" / "launch.py").read_text(encoding="utf-8")
    require(BASIC_EDITOR_APP_ID in launch_source, "Basic Windows identity constant is missing")

    main_tree = ast.parse(main_source)
    main_fn = next(node for node in main_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    basic_tree = ast.parse(basic_source)
    basic_fn = next(node for node in basic_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")

    def _named_call_lines(function: ast.FunctionDef, name: str) -> list[int]:
        lines = []
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
                lines.append(node.lineno)
        return lines

    require(_named_call_lines(main_fn, "configure_windows_app_id")[0] < _named_call_lines(main_fn, "QApplication")[0], "Professional App ID order changed")
    require(_named_call_lines(basic_fn, "configure_windows_app_id")[0] < _named_call_lines(basic_fn, "QApplication")[0], "Basic App ID order changed")
    apply_line = min(
        node.lineno
        for node in ast.walk(basic_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_launch_edition_for_entry"
    )
    ensure_line = min(
        node.lineno
        for node in ast.walk(basic_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ensure_app_directories"
    )
    require(apply_line < ensure_line, "Basic edition context must be set before data directories")


def check_data_directory_isolation() -> None:
    names = data_directory_names()
    require(names["basic"] == BASIC_DATA_DIR_NAME == BASIC_APP_DIR_NAME == "LaunchFlow-Basic", "Basic data dir name drifted")
    require(names["professional"] == APP_DIR_NAME == "LaunchFlow", "Professional data dir name drifted")
    require(names["basic_dev"] == "LaunchFlow-Basic-Dev", "Basic dev dir name drifted")

    temp_root = Path(tempfile.gettempdir()) / f"launchflow-phase2-paths-{os.getpid()}-{uuid.uuid4().hex}"
    local_app_data = temp_root / "Local AppData"
    professional_root = local_app_data / "LaunchFlow"
    professional_dev = local_app_data / "LaunchFlow-Dev"
    basic_root = local_app_data / "LaunchFlow-Basic"
    isolated = temp_root / "isolated-basic"
    professional_root.mkdir(parents=True)
    _write(professional_root / "licenses" / "license.lic", '{"kind":"must-not-read"}')
    _write(professional_root / "plans" / "pro.json", '{"plan_name":"pro","steps":[]}')
    professional_stamp = (professional_root / "licenses" / "license.lic").read_bytes()
    old_override = os.environ.get(APP_DATA_ENV)
    old_local = os.environ.get("LOCALAPPDATA")
    previous = set_process_edition_context(EditionContext())
    try:
        os.environ["LOCALAPPDATA"] = str(local_app_data)
        os.environ.pop(APP_DATA_ENV, None)

        apply_current_product_launch_edition()
        require(get_app_data_dir() == professional_root, "Professional default data root changed")
        require(not basic_root.exists(), "Professional path created LaunchFlow-Basic")

        apply_basic_launch_edition()
        require(get_app_data_dir() == basic_root, "Basic default data root is wrong")
        require(not basic_root.exists(), "path calculation created LaunchFlow-Basic")
        created = ensure_app_directories()
        require(created["root"] == basic_root, "Basic ensure_app_directories used the wrong root")
        require(all((basic_root / name).is_dir() for name in APP_SUBDIRECTORIES), "Basic subdirectories missing")
        require(
            (professional_root / "licenses" / "license.lic").read_bytes() == professional_stamp,
            "Basic directory creation touched Professional license data",
        )
        require(
            list((professional_root / "plans").iterdir())[0].name == "pro.json",
            "Basic directory creation touched Professional plans",
        )

        os.environ[APP_DATA_ENV] = str(professional_root)
        try:
            get_app_data_dir()
        except AppPathError as exc:
            require("Professional data directory" in str(exc), f"unexpected fail-closed message: {exc}")
        else:
            raise AssertionError("Basic accepted a Professional data-directory override")

        os.environ[APP_DATA_ENV] = str(professional_dev)
        try:
            get_app_data_dir()
        except AppPathError:
            pass
        else:
            raise AssertionError("Basic accepted a LaunchFlow-Dev override")

        os.environ[APP_DATA_ENV] = str(isolated)
        require(get_app_data_dir() == isolated, "Basic rejected a non-Professional test override")

        os.environ.pop(APP_DATA_ENV, None)
        migration = migrate_legacy_data(PROJECT_ROOT, legacy_roots=[professional_root])
        require(migration.copied == [], f"Basic migration copied files: {migration.copied}")
        require(
            migration.skipped == ["basic-edition:legacy-migration-disabled"],
            f"Basic migration was not skipped closed: {migration}",
        )
        require(
            (professional_root / "licenses" / "license.lic").read_bytes() == professional_stamp,
            "Basic migration read or rewrote a Professional license",
        )
        require(not (basic_root / "licenses" / "license.lic").exists(), "Basic migration imported a Professional license")
        require(not (isolated / "licenses" / "license.lic").exists(), "Basic migration wrote into the test override")
    finally:
        set_process_edition_context(previous)
        if old_override is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_override
        if old_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_local
        shutil.rmtree(temp_root, ignore_errors=True)


def check_professional_template_unchanged() -> None:
    digest = hashlib.sha256(build_single_exe.EMBEDDED_TEMPLATE.encode("utf-8")).hexdigest()
    require(digest == FROZEN_PROFESSIONAL_TEMPLATE_SHA256, f"EMBEDDED_TEMPLATE changed: {digest}")
    require(not professional_runner_source_missing(build_single_exe.EMBEDDED_TEMPLATE), "Professional runner symbols missing")
    require("run_command_step" in build_single_exe.EMBEDDED_TEMPLATE, "Professional template lost Command")
    require("os.startfile(path)" in build_single_exe.EMBEDDED_TEMPLATE, "Professional template lost shortcut shell_open")
    require(
        "Path(local_app_data) / \"LaunchFlow\"" in build_single_exe.EMBEDDED_TEMPLATE
        or 'Path(local_app_data) / "LaunchFlow"' in build_single_exe.EMBEDDED_TEMPLATE,
        "Professional runner log path changed",
    )


def check_basic_runner_restrictions() -> None:
    template = BASIC_EMBEDDED_TEMPLATE
    require(template is build_single_exe.BASIC_EMBEDDED_TEMPLATE, "exporter is not using the dedicated Basic template")
    violations = basic_runner_source_violations(template)
    require(violations == [], f"Basic runner still contains forbidden capabilities: {violations}")
    require("run_command_step" not in template and "run_wait_step" not in template, "Basic runner embeds Command/Wait handlers")
    require("os.startfile(path)" not in template, "Basic runner still shell-opens shortcuts")
    require("os.startfile(url)" in template, "Basic runner lost default-browser URL opening")
    require("LaunchFlow-Basic" in template, "Basic runner logs are not isolated")
    require('Path(local_app_data) / "LaunchFlow"' not in template, "Basic runner still hard-codes the Professional data dir")
    require("powershell_script" not in template, "Basic runner still mentions script-app handling")


def check_export_selection_and_assets() -> None:
    previous = set_process_edition_context(EditionContext())
    temp_dir = Path(tempfile.mkdtemp(prefix="launchflow-phase2-export-"))
    try:
        apply_current_product_launch_edition()
        template, plan, assets = build_single_exe._select_embedded_export_material(COMMAND_PLAN)
        require(template is build_single_exe.EMBEDDED_TEMPLATE, "Professional export did not keep EMBEDDED_TEMPLATE")
        require(any(step.get("type") == "command" and "_command_launch" in step for step in plan["steps"]), "Professional export stopped serializing Command")

        pyinstaller_lookups = {"count": 0}

        def fake_pyinstaller_command() -> list[str]:
            pyinstaller_lookups["count"] += 1
            raise RuntimeError("pyinstaller-probed")

        output = temp_dir / "pro" / "plan.exe"
        with patch.object(build_single_exe, "_get_pyinstaller_command", side_effect=fake_pyinstaller_command):
            try:
                build_single_exe.build_single_file_exe(COMMAND_PLAN, output)
            except RuntimeError as exc:
                require("pyinstaller-probed" in str(exc), f"unexpected professional export error: {exc}")
            else:
                raise AssertionError("Professional export did not reach PyInstaller lookup")
        require(pyinstaller_lookups["count"] == 1, "Professional export lookup count changed")

        apply_basic_launch_edition()
        basic_template, basic_plan, basic_assets = build_single_exe._select_embedded_export_material(BASIC_COMPATIBLE_PLAN)
        require(basic_template is BASIC_EMBEDDED_TEMPLATE, "Basic export did not use the restricted template")
        require(basic_runner_source_violations(basic_template) == [], "selected Basic template is not restricted")
        rendered = basic_template.replace("__PLAN_DATA__", repr(basic_plan))
        require(basic_runner_source_violations(rendered) == [], "rendered Basic debug script leaked Professional handlers")
        require(all(step.get("type") in {"app", "url"} for step in basic_plan["steps"]), "Basic export retained unsupported steps")
        require(all(step.get("type") != "command" for step in basic_plan["steps"]), "Basic export retained Command")
        for step in basic_plan["steps"]:
            if step.get("type") == "app":
                require(step["_application_launch"]["launch_mode"] == "process", "Basic app launch was not process-only")
            if step.get("type") == "url":
                require(step["_url_open"]["open_mode"] == "shell_open", "Basic URL launch changed")

        script_suffixes = {".bat", ".cmd", ".com", ".ps1"}
        script_plan = {
            "plan_name": "script-app",
            "version": "1.0",
            "steps": [
                {
                    "id": "app-script",
                    "type": "app",
                    "name": "脚本",
                    "enabled": True,
                    "delay_after": 1.0,
                    "path": str(temp_dir / "tool.bat"),
                    "args": [],
                    "working_dir": "",
                    "start_minimized": False,
                }
            ],
        }
        _write(temp_dir / "tool.bat", "echo should-not-pack")
        exe_source = temp_dir / "tool.exe"
        exe_source.write_bytes(b"MZ-fake-exe")
        exe_plan = {
            "plan_name": "exe-app",
            "version": "1.0",
            "steps": [
                {
                    "id": "app-exe",
                    "type": "app",
                    "name": "本地 EXE",
                    "enabled": True,
                    "delay_after": 1.0,
                    "path": str(exe_source),
                    "args": [],
                    "working_dir": "",
                    "start_minimized": False,
                }
            ],
        }

        rejected_script = False
        try:
            build_single_exe._prepare_basic_embedded_plan_and_assets(script_plan)
        except ValueError:
            rejected_script = True
        require(rejected_script, "Basic export packed or accepted a script application")

        _, packed_assets = build_single_exe._prepare_basic_embedded_plan_and_assets(exe_plan)
        require(packed_assets and packed_assets[0][0] == exe_source.resolve(), "Basic export did not pack the local EXE")
        require(all(Path(source).suffix.lower() not in script_suffixes for source, _name in packed_assets), "Basic export packed a script")

        from shared.edition_policy import BasicPolicyViolation

        basic_output = temp_dir / "basic-nested" / "plan.exe"
        pyinstaller_lookups["count"] = 0
        with patch.object(build_single_exe, "_get_pyinstaller_command", side_effect=fake_pyinstaller_command):
            rejected = False
            try:
                build_single_exe.build_single_file_exe(COMMAND_PLAN, basic_output)
            except BasicPolicyViolation:
                rejected = True
            require(rejected, "Basic export must still reject Command plans before packaging")
            require(pyinstaller_lookups["count"] == 0, "Basic export looked up PyInstaller after rejecting Command")
            require(not basic_output.parent.exists(), "Basic Command rejection created the output directory")
            require(not list(temp_dir.glob("*_embedded_debug.py")), "Basic Command rejection wrote a debug script")
    finally:
        set_process_edition_context(previous)
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_packaging_entries() -> None:
    professional = build_editor_command(PROJECT_ROOT)
    require(str(PROJECT_ROOT / "editor" / "main.py") in professional, "Professional packager entry changed")
    require("LaunchFlow" in professional, "Professional exe name changed")
    basic = build_basic_editor_command(PROJECT_ROOT)
    require(str(PROJECT_ROOT / "editor" / "main_basic.py") in basic, "Basic packager is not using main_basic.py")
    require("LaunchFlow-Basic" in basic, "Basic packager exe name is wrong")
    require(inspect.signature(build_editor_command).parameters["exe_name"].default == "LaunchFlow", "default editor exe name changed")

    script = (PROJECT_ROOT / "tools" / "run_editor_basic_dev.ps1").read_text(encoding="utf-8")
    require("LaunchFlow-Basic-Dev" in script, "Basic dev script is not isolated")
    require("editor.main_basic" in script, "Basic dev script is not using the Basic entry")
    require("LaunchFlow-Dev`" not in script and 'Join-Path $localAppData "LaunchFlow-Dev"' not in script, "Basic dev script references Professional dev data")
    professional_script = (PROJECT_ROOT / "tools" / "run_editor_dev.ps1").read_text(encoding="utf-8")
    require("editor.main" in professional_script and "editor.main_basic" not in professional_script, "Professional dev script was retargeted")


def main() -> int:
    previous = get_edition_context()
    try:
        check_launch_entries()
        check_data_directory_isolation()
        check_professional_template_unchanged()
        check_basic_runner_restrictions()
        check_export_selection_and_assets()
        check_packaging_entries()
    finally:
        set_process_edition_context(previous)

    print("dual edition phase 2 smoke ok")
    print("launch_entries=editor.main:unset-professional,editor.main_basic:basic")
    print("data_dirs=LaunchFlow,LaunchFlow-Basic,LaunchFlow-Basic-Dev")
    print("professional_template=unchanged")
    print("basic_runner=restricted,no-command-wait,no-script,no-lnk-shell-open")
    print("packaging=LaunchFlow.exe,LaunchFlow-Basic.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
