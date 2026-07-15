"""Behavior smoke for drag/keyboard step reordering and downstream plan order."""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"step-reorder-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SCREENSHOT_DIR = ROOT.parent / "test" / "v0.1.0-beta.1_2026-07-12_234445" / "screenshots"

from PySide6.QtCore import Qt, QRect  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QAbstractItemView, QFileDialog  # noqa: E402

import editor.ui.main_window as main_window_module  # noqa: E402
from editor.ui.main_window import MainWindow, ReorderableStepList, calculate_drop_target  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.models import CommandStep, Plan  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_plan(name: str = "reorder") -> Plan:
    return Plan(
        plan_name=name,
        steps=[
            CommandStep(name="A", command="echo A", delay_after=0),
            CommandStep(name="B", command="echo B", delay_after=0),
            CommandStep(name="C", command="echo C", delay_after=0),
        ],
    )


def install(window: MainWindow, plan: Plan, selected: int = 0) -> None:
    window.current_plan = plan
    window.current_editor_index = None
    window.current_step_dirty = False
    window.plan_dirty = False
    window._loading_plan = True
    window.plan_name_edit.setText(plan.plan_name)
    window._loading_plan = False
    window._refresh_flow_list()
    window.flow_list.setCurrentRow(selected)
    QApplication.processEvents()


def names(window: MainWindow) -> list[str]:
    return [step.name for step in window.current_plan.steps]


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    window.show()
    QApplication.processEvents()
    window._info = lambda *_args: None
    window._error = lambda title, message: (_ for _ in ()).throw(AssertionError(f"{title}: {message}"))
    try:
        require(isinstance(window.flow_list, ReorderableStepList), "step list must expose the drag contract")
        require(
            window.flow_list.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove,
            "step list must use Qt InternalMove",
        )
        require(not window.flow_list.showDropIndicator(), "native thin drop indicator should be replaced")
        require(window.flow_list.hasAutoScroll(), "drag autoscroll missing")

        rects = [QRect(0, 20, 220, 40), QRect(0, 60, 220, 40), QRect(0, 100, 220, 40)]
        require(calculate_drop_target(5, rects, 180) == 0, "top extended zone did not return index 0")
        require(calculate_drop_target(30, rects, 180) == 0, "first-item upper half did not return index 0")
        require(calculate_drop_target(50, rects, 180) == 1, "first-item lower half did not return index 1")
        require(calculate_drop_target(139, rects, 180) == 3, "last-item bottom region did not return len(steps)")
        require(calculate_drop_target(175, rects, 180) == 3, "bottom extended zone did not return len(steps)")

        require(0.82 <= window.flow_list.DRAG_PREVIEW_OPACITY <= 0.88, "drag preview opacity is outside UX contract")
        require(0.85 <= window.flow_list.DRAG_PREVIEW_WIDTH_SCALE <= 0.92, "drag preview width is not compact")
        require(0.90 <= window.flow_list.DRAG_PREVIEW_HEIGHT_SCALE <= 0.94, "drag preview height is outside UX contract")
        require(window.flow_list.INSERTION_INDICATOR_WIDTH >= 4, "insertion indicator is too thin")
        require(window.flow_list.INSERTION_INDICATOR_HAS_ARROW, "insertion indicator lacks the left arrow contract")

        plan = make_plan()
        original_objects = {step.id: step for step in plan.steps}
        install(window, plan, 2)
        moved_id = plan.steps[2].id
        require(window.reorder_steps(2, 0) == 0, "C -> 0 failed")
        require(names(window) == ["C", "A", "B"], "unexpected backward reorder")
        require(all(original_objects[step.id] is step for step in window.current_plan.steps), "steps were recreated")
        require(window.current_plan.steps[0].id == moved_id, "step id changed")
        require(window.flow_list.currentItem().data(256) == moved_id, "selection was not restored by step id")
        require(window.current_editor_index == 0 and window.plan_dirty, "editor/dirty state not restored")

        item_rect = window.flow_list.visualItemRect(window.flow_list.item(0))
        preview = window.flow_list.build_drag_preview(window.flow_list.item(0))
        require(not preview.isNull(), "drag preview pixmap is missing")
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        require(preview.save(str(SCREENSHOT_DIR / "drag-preview-refined.png"), "PNG"), "drag preview screenshot failed")
        require(preview.width() < item_rect.width() and preview.height() < item_rect.height(), "drag preview is not scaled")
        preview_image = preview.toImage()
        alpha_values = [preview_image.pixelColor(x, preview.height() // 2).alpha() for x in range(preview.width())]
        require(any(0 < alpha < 255 for alpha in alpha_values), "drag preview pixels are not translucent")
        perimeter = (
            [(x, 0) for x in range(preview.width())]
            + [(x, preview.height() - 1) for x in range(preview.width())]
            + [(0, y) for y in range(1, preview.height() - 1)]
            + [(preview.width() - 1, y) for y in range(1, preview.height() - 1)]
        )
        accent = window.flow_list._indicator_color()
        accent_pixels = sum(
            preview_image.pixelColor(x, y).alpha() > 0
            and sum(
                abs(left - right)
                for left, right in zip(preview_image.pixelColor(x, y).getRgb()[:3], accent.getRgb()[:3])
            ) < 60
            for x, y in perimeter
        )
        require(accent_pixels < len(perimeter) // 3, "drag preview still has a dominant second outer frame")

        source_item = window.flow_list.item(2)
        original_foreground = source_item.foreground()
        window.flow_list._dragging_step_id = source_item.data(Qt.ItemDataRole.UserRole)
        window.flow_list._drag_active = True
        window.flow_list._drop_target_index = 0
        require(window.flow_list.drop_target_label == "松开放置到第 1 位", "target position label is incorrect")
        label_rect = window.flow_list._indicator_label_rect(window.flow_list._insertion_y(0))
        require(label_rect.left() >= window.flow_list.viewport().width() * 0.5, "target hint can cover left-side step names")
        dark_palette = window.flow_list.palette()
        dark_palette.setColor(QPalette.ColorRole.Base, QColor("#0F172A"))
        window.flow_list.setPalette(dark_palette)
        dark_color = window.flow_list._indicator_color().name()
        light_palette = window.flow_list.palette()
        light_palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        window.flow_list.setPalette(light_palette)
        light_color = window.flow_list._indicator_color().name()
        require(dark_color != light_color, "drag indicator does not adapt to dark/light palettes")
        window.flow_list.clear_drag_visual_state()
        require(source_item.foreground() == original_foreground, "source item foreground stayed muted after drag cleanup")
        require(not window.flow_list._drag_active and window.flow_list._dragging_step_id is None, "drag state did not clear")

        install(window, make_plan(), 0)
        require(window.reorder_steps(0, 2) == 2 and names(window) == ["B", "C", "A"], "A -> 2 failed")

        before = names(window)
        for source, target in ((-1, 0), (0, 9), (1, 1)):
            window.reorder_steps(source, target)
        require(names(window) == before, "invalid/no-op reorder changed the model")

        install(window, make_plan("draft-reorder"), 1)
        edited_id = window.current_plan.steps[1].id
        window.cmd_in.setPlainText('echo "B latest %PATH%"\n&& echo 中文')
        require(window.reorder_steps(1, 0) == 0, "dirty step reorder failed")
        require(window.current_plan.steps[0].id == edited_id, "dirty selected id changed")
        require("B latest" in window.current_plan.steps[0].command, "dirty draft was lost before reorder")

        window._on_save_plan()
        saved = json.loads((window.plan_service.get_plans_dir() / "draft-reorder.json").read_text(encoding="utf-8"))
        require([step["name"] for step in saved["steps"]] == names(window), "JSON order differs from model")

        trial = window._prepare_plan_for_execution("试运行")
        require(trial.success and [step.name for step in trial.snapshot.steps] == names(window), "trial order differs")

        captured: dict[str, object] = {}

        class FakeSignal:
            def connect(self, _slot) -> None:
                pass

        class FakeBuildWorker:
            def __init__(self, plan_arg, output_path) -> None:
                captured["plan"] = plan_arg
                captured["path"] = output_path
                self.progress = FakeSignal()
                self.success = FakeSignal()
                self.failed = FakeSignal()

            def start(self) -> None:
                captured["started"] = True

        old_worker = main_window_module.BuildWorker
        old_dialog = QFileDialog.getSaveFileName
        main_window_module.BuildWorker = FakeBuildWorker
        QFileDialog.getSaveFileName = lambda *_args, **_kwargs: (str(TEMP / "ordered.exe"), "")
        try:
            window._on_export_exe()
        finally:
            main_window_module.BuildWorker = old_worker
            QFileDialog.getSaveFileName = old_dialog
        exported = captured["plan"]
        require(captured.get("started") is True, "export worker did not start")
        require([step.name for step in exported.steps] == names(window), "export worker received stale order")

        install(window, make_plan(), 1)
        window.cmd_in.setFocus()
        QTest.keyClick(window.cmd_in, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
        QApplication.processEvents()
        require(names(window) == ["A", "B", "C"], "move shortcut fired while an editor input had focus")

        calls: list[tuple[int, int]] = []
        original_reorder = window.reorder_steps
        window.reorder_steps = lambda source, target: (calls.append((source, target)), original_reorder(source, target))[1]
        window.flow_list.setFocus()
        QTest.keyClick(window.flow_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
        QApplication.processEvents()
        require(calls == [(1, 0)] and names(window) == ["B", "A", "C"], "keyboard path did not reuse reorder_steps")

        print("step reorder smoke ok")
        print("model_reorder=backward,forward,invalid")
        print("step_identity=preserved")
        print("dirty_draft=committed-before-move")
        print("save_trial_export_order=consistent")
        print("selection_restore=step-id")
        print("drop_index=top-zone,upper-half,lower-half,bottom-zone")
        print("drag_visual=translucent,scaled,full-width-indicator,left-arrow,target-label,dark-light")
        print("drag_contract=internal-move,custom-indicator,autoscroll,start-distance")
        print("keyboard_fallback=shared-reorder-entry")
        return 0
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
