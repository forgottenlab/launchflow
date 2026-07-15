"""Behavior smoke for inspector/model synchronization and execution preflight."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_temp_base = ROOT.parent / "test"
_temp_base.mkdir(parents=True, exist_ok=True)
_temp_data = _temp_base / f"launchflow-step-sync-{os.getpid()}-{uuid.uuid4().hex}"
_temp_data.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(_temp_data / "data root 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor.ui.main_window import MainWindow, StepCommitResult  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.models import AppStep, CommandStep, Plan  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def install_plan(window: MainWindow, plan: Plan, selected_index: int = 0) -> None:
    window.current_plan = plan
    window.current_plan_path = None
    window.current_editor_index = None
    window.current_step_dirty = False
    window.plan_dirty = False
    window._loading_plan = True
    window.plan_name_edit.setText(plan.plan_name)
    window._loading_plan = False
    window._refresh_flow_list()
    if plan.steps:
        window.flow_list.setCurrentRow(selected_index)
    QApplication.processEvents()


def check_save_and_shortcut(window: MainWindow) -> None:
    exact_command = '  echo "中文 %PATH%"\n&& echo done  '
    install_plan(
        window,
        Plan(plan_name="sync-save", steps=[CommandStep(name="保存命令", command="old")]),
    )
    window.cmd_in.setPlainText(exact_command)
    require(window.current_step_dirty, "editing command should mark the inspector draft dirty")

    window._on_save_plan()
    saved_path = window.plan_service.get_plans_dir() / "sync-save.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    require(saved["steps"][0]["command"] == exact_command, "save must preserve the exact visible command")
    require(not window.current_step_dirty and not window.plan_dirty, "successful save should clear dirty state")

    shortcut_command = 'echo "shortcut %TEMP%"\n第二行'
    window.cmd_in.setPlainText(shortcut_command)
    window.action_save.trigger()
    QApplication.processEvents()
    shortcut_saved = json.loads(saved_path.read_text(encoding="utf-8"))
    require(
        shortcut_saved["steps"][0]["command"] == shortcut_command,
        "Ctrl+S action must call the same save path and commit the latest draft",
    )


def check_trial_snapshot(window: MainWindow) -> None:
    latest_command = 'echo "snapshot %PATH%"\n&& echo 中文'
    install_plan(
        window,
        Plan(plan_name="snapshot", steps=[CommandStep(name="快照命令", command="old")]),
    )
    window.cmd_in.setPlainText(latest_command)
    prepared = window._prepare_plan_for_execution("试运行")
    require(prepared.success and prepared.snapshot is not None, "valid plan should prepare for trial run")
    require(prepared.snapshot is not window.current_plan, "worker input must be a deep-copied snapshot")
    require(prepared.snapshot.steps[0].command == latest_command, "trial snapshot must contain latest editor text")
    window.cmd_in.setPlainText("changed after snapshot")
    require(prepared.snapshot.steps[0].command == latest_command, "snapshot must not follow later UI mutations")


def check_drag_commit_boundary(window: MainWindow) -> None:
    install_plan(window, Plan(plan_name="drag-draft", steps=[CommandStep(name="拖拽命令", command="old")]))
    window.cmd_in.setPlainText("echo latest-before-drag")
    require(window._prepare_step_drag(), "valid dirty draft should allow drag")
    require(window.current_plan.steps[0].command == "echo latest-before-drag", "drag boundary lost editor draft")

    original_commit = window.commit_current_step_editor
    original_error = window._error
    errors: list[tuple[str, str]] = []
    window._error = lambda title, message: errors.append((title, message))
    window.commit_current_step_editor = lambda: StepCommitResult(
        success=False,
        error="模拟拖拽提交失败",
        step_index=0,
        step_id=window.current_plan.steps[0].id,
    )
    try:
        require(not window._prepare_step_drag(), "invalid dirty draft must block drag start")
        require(errors and errors[-1][0] == "无法调整步骤顺序", "blocked drag must show a clear error")
    finally:
        window.commit_current_step_editor = original_commit
        window._error = original_error


def check_selection_switch_and_loading(window: MainWindow) -> None:
    first_latest = 'echo "first latest"'
    install_plan(
        window,
        Plan(
            plan_name="selection",
            steps=[
                CommandStep(name="第一步", command="old first"),
                CommandStep(name="第二步", command="echo second"),
            ],
        ),
    )
    window.cmd_in.setPlainText(first_latest)
    window.flow_list.setCurrentRow(1)
    QApplication.processEvents()
    require(window.current_plan.steps[0].command == first_latest, "selection switch must commit the old inspector")
    require(window.current_editor_index == 1, "new selection should become the active inspector")

    window.plan_dirty = False
    window._on_step_selected(1)
    require(not window.current_step_dirty, "loading model data into the inspector must not mark it dirty")
    require(not window.plan_dirty, "loading the inspector must not mark the plan dirty")

    original_commit = window.commit_current_step_editor
    errors: list[tuple[str, str]] = []
    window._error = lambda title, message: errors.append((title, message))
    window.commit_current_step_editor = lambda: StepCommitResult(
        success=False,
        error="模拟提交失败",
        step_index=1,
        step_id=window.current_plan.steps[1].id,
    )
    window.flow_list.setCurrentRow(0)
    QApplication.processEvents()
    require(window.flow_list.currentRow() == 1, "failed commit must restore the previous selection")
    require(window.current_editor_index == 1, "failed commit must keep the previous inspector active")
    require(errors and errors[-1][0] == "无法切换步骤", "failed switch must show a clear error")
    window.commit_current_step_editor = original_commit


def check_full_plan_preflight(window: MainWindow) -> None:
    install_plan(
        window,
        Plan(
            plan_name="preflight",
            steps=[
                AppStep(name="Python GUI", path=sys.executable, delay_after=0),
                CommandStep(name="新命令", command="", shell="cmd", delay_after=0),
            ],
        ),
    )
    errors: list[tuple[str, str]] = []
    window._error = lambda title, message: errors.append((title, message))
    window._confirm = lambda *_args: True

    prepared = window._prepare_plan_for_execution("试运行")
    require(not prepared.success, "empty later command must block the whole plan")
    require(prepared.step_index == 1 and prepared.field == "command", "preflight result must identify step and field")
    require("步骤 2“新命令”的执行命令为空" in prepared.error, "preflight message must be user-readable")
    require(window.flow_list.currentRow() == 1, "preflight must select the invalid step")
    require(window.current_editor_index == 1, "preflight must open the invalid step inspector")
    require(window.cmd_in.hasFocus(), "preflight must focus the invalid command field")

    window._on_trial_run()
    QApplication.processEvents()
    require(window.trial_run_worker is None, "invalid plan must not create or start a trial worker")
    require(errors and errors[-1][0] == "无法试运行", "blocked trial run must show an error")


def check_application_output_isolation() -> None:
    marker = _temp_data / "application-finished.txt"
    child_code = (
        "import sys,time; from pathlib import Path; "
        "print('APP_STDOUT_POLLUTION', flush=True); "
        "print('APP_STDERR_POLLUTION', file=sys.stderr, flush=True); "
        "time.sleep(1.2); "
        f"Path({str(marker)!r}).write_text('done', encoding='utf-8')"
    )
    helper_code = (
        "import sys; "
        "from runtime.launcher_runtime import RuntimeExecutor; "
        "from shared.models import AppStep; "
        "RuntimeExecutor(log_callback=lambda _message: None).run_app_step("
        f"AppStep(name='isolated app', path=sys.executable, args=['-c', {child_code!r}], delay_after=0))"
    )

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", helper_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    require(result.returncode == 0, f"application helper failed: {combined}")
    require("APP_STDOUT_POLLUTION" not in combined, "Application stdout must not inherit the editor pipe")
    require("APP_STDERR_POLLUTION" not in combined, "Application stderr must not inherit the editor pipe")
    require(elapsed < 0.9, f"Application launch should return immediately, elapsed={elapsed:.3f}s")

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    require(marker.exists(), "fire-and-forget Application child should continue after the launcher returns")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    window._info = lambda *_args: None
    window.show()
    QApplication.processEvents()

    try:
        check_save_and_shortcut(window)
        check_trial_snapshot(window)
        check_drag_commit_boundary(window)
        check_selection_switch_and_loading(window)
        check_full_plan_preflight(window)
        check_application_output_isolation()
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(_temp_data, ignore_errors=True)

    print("step editor sync smoke ok")
    print("save_auto_commit=exact-command-json")
    print("shortcut_save=shared-slot")
    print("trial_snapshot=deepcopy-latest-draft")
    print("drag_boundary=shared-editor-commit-and-failure-block")
    print("selection_switch=auto-commit")
    print("preflight=full-plan-before-worker")
    print("loading_editor=clean")
    print("failed_commit=switch-blocked")
    print("application_stdio=devnull-fire-and-forget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
