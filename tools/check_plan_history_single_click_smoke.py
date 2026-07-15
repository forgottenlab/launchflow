"""Behavior smoke for single-click/Enter plan history and dirty-change protection."""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"plan-history-smoke-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

from editor.services.plan_service import PlanService  # noqa: E402
from editor.ui.main_window import MainWindow, PlanSwitchDecision  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.models import CommandStep, Plan  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def plan(name: str) -> Plan:
    return Plan(plan_name=name, steps=[CommandStep(name=f"{name} command", command=f"echo {name}", delay_after=0)])


def find_item(window: MainWindow, stem: str) -> QListWidgetItem:
    for index in range(window.history_list.count()):
        item = window.history_list.item(index)
        if Path(item.data(Qt.ItemDataRole.UserRole)).stem == stem:
            return item
    raise AssertionError(f"history item not found: {stem}")


def click(window: MainWindow, stem: str) -> None:
    window.history_list.itemClicked.emit(find_item(window, stem))
    QApplication.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    service = PlanService(ROOT)
    paths = {name: service.get_plans_dir() / f"{name}.json" for name in ("A", "B", "C")}
    for name, path in paths.items():
        service.save_plan(plan(name), path)
    corrupt_path = service.get_plans_dir() / "broken.json"
    corrupt_path.write_text("{broken", encoding="utf-8")

    window = MainWindow(ROOT)
    window._info = lambda *_args: None
    errors: list[tuple[str, str]] = []
    window._error = lambda title, message: errors.append((title, message))
    window.show()
    QApplication.processEvents()
    try:
        require(window.history_section_label.text() == "本地历史方案（单击载入）", "history title is stale")
        require(all(window.history_list.item(i).toolTip() == "单击载入方案" for i in range(window.history_list.count())), "history tooltip missing")

        loads: list[Path] = []
        original_load = window.plan_service.load_plan

        def counted_load(path: Path) -> Plan:
            loads.append(Path(path))
            return original_load(path)

        window.plan_service.load_plan = counted_load
        click(window, "A")
        require(window.current_plan_path == paths["A"] and len(loads) == 1, "single click did not load once")
        click(window, "A")
        window.history_list.itemDoubleClicked.emit(find_item(window, "A"))
        QApplication.processEvents()
        require(len(loads) == 1, "current-plan click/double-click reloaded the plan")

        window.history_list.setFocus()
        QTest.keyClick(window.history_list, Qt.Key.Key_Down)
        QApplication.processEvents()
        require(window.current_plan_path == paths["A"] and len(loads) == 1, "arrow navigation auto-loaded a plan")
        QTest.keyClick(window.history_list, Qt.Key.Key_Return)
        QApplication.processEvents()
        require(window.current_plan_path == paths["B"] and len(loads) == 2, "Enter did not load selected plan")

        window.cmd_in.setPlainText("echo dirty-cancel")
        window._prompt_unsaved_plan_change = lambda _path: PlanSwitchDecision.CANCEL
        click(window, "C")
        require(window.current_plan_path == paths["B"], "cancel changed the current plan")
        require(window.history_list.currentItem().data(Qt.ItemDataRole.UserRole) == paths["B"], "cancel did not restore history selection")
        require(window.cmd_in.toPlainText() == "echo dirty-cancel", "cancel lost the visible draft")

        window._prompt_unsaved_plan_change = lambda _path: PlanSwitchDecision.SAVE
        click(window, "C")
        require(window.current_plan_path == paths["C"], "save-and-load did not load target")
        saved_b = json.loads(paths["B"].read_text(encoding="utf-8"))
        require(saved_b["steps"][0]["command"] == "echo dirty-cancel", "save-and-load did not commit the editor draft")
        require(not window.current_step_dirty and not window.plan_dirty, "successful load did not clear dirty state")
        require(window.flow_list.currentRow() == 0 and window.current_editor_index == 0, "loaded plan did not select an editable step")

        original_c = paths["C"].read_text(encoding="utf-8")
        window.cmd_in.setPlainText("echo discard-me")
        window._prompt_unsaved_plan_change = lambda _path: PlanSwitchDecision.DISCARD
        click(window, "A")
        require(window.current_plan_path == paths["A"], "discard-and-load did not load target")
        require(paths["C"].read_text(encoding="utf-8") == original_c, "discard unexpectedly saved the dirty plan")

        click(window, "broken")
        require(window.current_plan_path == paths["A"] and errors[-1][0] == "载入失败", "broken JSON was not handled safely")
        missing_item = QListWidgetItem("missing")
        missing_item.setData(Qt.ItemDataRole.UserRole, service.get_plans_dir() / "missing.json")
        window._load_history_plan_item(missing_item)
        require(window.current_plan_path == paths["A"] and "不存在" in errors[-1][1], "missing plan was not reported safely")

        print("plan history single-click smoke ok")
        print("mouse_click=single-load,current-path-no-reload")
        print("keyboard=enter-load,arrows-select-only")
        print("dirty_guard=save,discard,cancel")
        print("invalid_files=missing,broken-json-readable-error")
        print("loaded_state=name,steps,selection,clean")
        return 0
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
