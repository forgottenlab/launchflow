"""
Smoke-test LaunchFlow's editor UI without requiring a real license.

The script creates a QApplication, isolates all mutable data behind
LAUNCHFLOW_DATA_DIR, instantiates MainWindow against a temporary project root,
and verifies the spinbox/combobox interaction contract in both themes. It also
captures deterministic offscreen screenshots for review. Instantiating the
workbench component directly is the explicit mock-authorized GUI test path; it
does not import, generate, or persist any license.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QDoubleSpinBox, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox

from editor.ui.main_window import DiagnosticsDialog, MainWindow, ReorderableStepList, TrialRunWorker
from shared.app_logging import reset_app_logger_for_tests
from shared.app_paths import APP_DATA_ENV
from shared.models import CommandStep, Plan


SCREENSHOT_DIR = PROJECT_ROOT.parent / "test" / "beta_2026-07-10" / "screenshots"


def _save_screenshot(window: MainWindow, name: str) -> Path:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / name
    if not window.grab().save(str(path), "PNG"):
        raise AssertionError(f"failed to save screenshot: {path}")
    if not path.is_file() or path.stat().st_size == 0:
        raise AssertionError(f"empty screenshot: {path}")
    return path


def _check_spinbox_contract(window: MainWindow, spinbox: QDoubleSpinBox, name: str) -> None:
    if spinbox.minimum() != 0:
        raise AssertionError(f"{name}: unexpected minimum {spinbox.minimum()}")
    if spinbox.maximum() < 9999:
        raise AssertionError(f"{name}: maximum too small {spinbox.maximum()}")
    if spinbox.decimals() != 1:
        raise AssertionError(f"{name}: unexpected decimals {spinbox.decimals()}")
    if spinbox.singleStep() <= 0:
        raise AssertionError(f"{name}: singleStep must be positive")
    if spinbox.minimumWidth() < 150 or spinbox.height() < 36:
        raise AssertionError(f"{name}: spinbox too small for reliable clicking")

    stylesheet = window.styleSheet()
    required = [
        "QDoubleSpinBox::up-button",
        "QDoubleSpinBox::down-button",
        "subcontrol-position: top right",
        "subcontrol-position: bottom right",
    ]
    missing = [item for item in required if item not in stylesheet]
    if missing:
        raise AssertionError(f"{name}: missing QSS snippets {missing}")


def _click_spinbox_arrows(spinbox: QDoubleSpinBox) -> None:
    spinbox.setValue(1.0)
    spinbox.setFocus()
    QApplication.processEvents()

    up_pos = QPoint(spinbox.width() - 13, 8)
    down_pos = QPoint(spinbox.width() - 13, spinbox.height() - 8)

    before = spinbox.value()
    QTest.mouseClick(spinbox, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, up_pos)
    QApplication.processEvents()
    after_up = spinbox.value()
    if after_up <= before:
        raise AssertionError(f"up click did not increase value: before={before}, after={after_up}")

    QTest.mouseClick(spinbox, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, down_pos)
    QApplication.processEvents()
    after_down = spinbox.value()
    if after_down >= after_up:
        raise AssertionError(f"down click did not decrease value: before={after_up}, after={after_down}")


def _color_distance(left: QColor, right: QColor) -> int:
    return sum(abs(a - b) for a, b in zip(left.getRgb()[:3], right.getRgb()[:3]))


def _assert_spinbox_arrow_visible(spinbox: QDoubleSpinBox, name: str) -> None:
    option = QStyleOptionSpinBox()
    spinbox.initStyleOption(option)
    rect = spinbox.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        option,
        QStyle.SubControl.SC_SpinBoxUp,
        spinbox,
    )
    image = spinbox.grab().toImage()
    center = rect.center()
    arrow = image.pixelColor(center)
    background = image.pixelColor(QPoint(max(rect.left() + 2, center.x() - 8), center.y()))
    if _color_distance(arrow, background) < 45:
        raise AssertionError(
            f"{name}: rendered up arrow lacks contrast; rect={rect}, "
            f"arrow={arrow.getRgb()}, background={background.getRgb()}"
        )


def _assert_combo_contract(combo: QComboBox, theme_name: str) -> None:
    original = combo.currentText()
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    arrow_rect = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox,
        option,
        QStyle.SubControl.SC_ComboBoxArrow,
        combo,
    )
    image = combo.grab().toImage()
    center = arrow_rect.center()
    arrow = image.pixelColor(center)
    background = image.pixelColor(QPoint(max(arrow_rect.left() + 2, center.x() - 8), center.y()))
    if _color_distance(arrow, background) < 45:
        raise AssertionError(f"{theme_name}: rendered combo arrow lacks contrast")

    click_positions = [QPoint(12, combo.height() // 2), QPoint(combo.width() - 10, combo.height() // 2), QPoint(combo.width() - 32, combo.height() // 2)]
    for position in click_positions:
        combo.hidePopup()
        QTest.mouseClick(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position)
        QApplication.processEvents()
        if not combo.view().isVisible():
            raise AssertionError(f"{theme_name}: combo did not open at {position}")
        combo.hidePopup()
    if combo.currentText() != original:
        raise AssertionError(f"{theme_name}: combo current value changed during smoke")


def _check_trial_worker_lifecycle(window: MainWindow) -> None:
    """Prove the real worker remains owned until QThread.finished is delivered."""
    python_path = str(Path(sys.executable))
    plan = Plan(
        plan_name="thread lifecycle smoke",
        steps=[
            CommandStep(
                name="delayed command",
                command=f'"{python_path}" -c "import time;time.sleep(1);print(\'worker-finished\')"',
                shell="cmd",
                delay_after=0.0,
            )
        ],
    )
    worker = TrialRunWorker(plan)
    window.trial_run_worker = worker
    window.btn_trial_run.setEnabled(False)
    progress: list[str] = []
    failures: list[str] = []
    success_state: list[tuple[bool, bool]] = []
    timed_out = [False]
    loop = QEventLoop()

    worker.progress.connect(progress.append)
    worker.success.connect(
        lambda: success_state.append((window.btn_trial_run.isEnabled(), window.trial_run_worker is worker))
    )
    worker.success.connect(window._on_trial_run_success)
    worker.failed.connect(failures.append)
    worker.finished.connect(window._on_trial_run_finished)
    worker.finished.connect(loop.quit)

    def on_timeout() -> None:
        timed_out[0] = True
        loop.quit()

    QTimer.singleShot(8000, on_timeout)
    worker.start()
    loop.exec()
    QApplication.processEvents()

    if timed_out[0]:
        worker.wait(3000)
        raise AssertionError("TrialRunWorker did not finish after communicate/log delivery")
    if failures or not success_state:
        raise AssertionError(f"TrialRunWorker failed: {failures}")
    if success_state != [(False, True)]:
        raise AssertionError(f"worker ownership changed before QThread.finished: {success_state}")
    if window.trial_run_worker is not None or not window.btn_trial_run.isEnabled():
        raise AssertionError("finished handler did not release worker and re-enable trial run")
    if not any("worker-finished" in line for line in progress):
        raise AssertionError("worker stdout was not logged before completion")


def _check_add_step_and_shortcut_contract(window: MainWindow) -> None:
    """Cover immediate inspection plus visible editor shortcuts."""
    window.current_plan = Plan(plan_name="interaction smoke")
    window._refresh_flow_list()
    window._set_editor_no_steps()

    QTest.mouseClick(window.btn_add_cmd, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    if len(window.current_plan.steps) != 1 or not isinstance(window.current_plan.steps[0], CommandStep):
        raise AssertionError("+ command did not append exactly one CommandStep")
    if window.flow_list.currentRow() != 0 or len(window.flow_list.selectedItems()) != 1:
        raise AssertionError("new command step was not selected immediately")
    if window.editor_stack.currentWidget() is not window.page_cmd:
        raise AssertionError("new command step did not open the command inspector")
    if window.cmd_name_in.text() != "新命令" or window.cmd_in.toPlainText() != "":
        raise AssertionError("new command defaults are not ready for direct editing")
    if window.cmd_shell_in.currentText() != "cmd" or window.cmd_delay_in.value() != 1.0:
        raise AssertionError("new command shell/delay defaults changed unexpectedly")
    if not window.cmd_name_in.hasFocus():
        raise AssertionError("new command name field was not focused for editing")

    expected_shortcuts = {
        window.action_save: "Ctrl+S",
        window.action_save_as: "Ctrl+Shift+S",
        window.action_trial_run: "Ctrl+R",
        window.action_export_exe: "Ctrl+E",
        window.action_delete_step: "Del",
    }
    for action, expected in expected_shortcuts.items():
        actual = action.shortcut().toString()
        if actual != expected:
            raise AssertionError(f"unexpected shortcut for {action.text()!r}: {actual!r}")

    if not isinstance(window.flow_list, ReorderableStepList):
        raise AssertionError("step list is missing the reorderable drag adapter")
    if window.flow_list.dragDropMode() != QAbstractItemView.DragDropMode.InternalMove:
        raise AssertionError("step list does not use InternalMove")
    if window.flow_list.showDropIndicator() or not window.flow_list.hasAutoScroll():
        raise AssertionError("custom step drag indicator/autoscroll contract is missing")
    if not window.btn_feedback.toolTip() or "不会自动上传" not in window.btn_feedback.toolTip():
        raise AssertionError("feedback button/tooltip is missing")
    diagnostic_dialog = window._create_diagnostics_dialog()
    if not isinstance(diagnostic_dialog, DiagnosticsDialog) or not diagnostic_dialog.preview.toPlainText():
        raise AssertionError("diagnostics dialog could not be instantiated")
    diagnostic_dialog.close()

    confirmations: list[bool] = []

    def confirm_delete(*args, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        confirmations.append(True)
        return True

    window._confirm = confirm_delete  # type: ignore[method-assign]
    window.flow_list.setFocus()
    QTest.keyClick(window.flow_list, Qt.Key.Key_Delete)
    QApplication.processEvents()
    if window.current_plan.steps or window.flow_list.count() != 0:
        raise AssertionError("Delete shortcut did not call the shared step deletion handler")
    if len(confirmations) != 1:
        raise AssertionError(f"Delete shortcut invoked deletion {len(confirmations)} times")


def _check_log_layout_contract(window: MainWindow) -> None:
    buttons = (
        window.btn_log_expand,
        window.btn_clear_log,
        window.btn_copy_log,
        window.btn_open_logs_dir,
        window.btn_feedback,
    )
    if window.log_toolbar.width() != 32 or window.log_toolbar.x() <= window.log_main.x():
        raise AssertionError("log tools are not in the fixed right-side toolbar")
    for button in buttons:
        if button.width() < 32 or not button.toolTip() or not button.accessibleName():
            raise AssertionError(f"log tool contract missing: {button.objectName()}")
    if window.findChild(type(window.log_toolbar), "LogToolbar") is not window.log_toolbar:
        raise AssertionError("log toolbar object is not discoverable")
    if window.status_label.parent() is not window.log_header or window.btn_open_log.parent() is not window.log_header:
        raise AssertionError("status and visibility action are not integrated into the log header")
    if hasattr(window, "status_bar"):
        raise AssertionError("legacy bottom status bar still exists")
    if window.main_splitter.widget(0).minimumHeight() < 300:
        raise AssertionError("upper editor minimum height is too small")
    if window.log_drawer.minimumHeight() < 40 or window.log_text.minimumHeight() < 140:
        raise AssertionError("log minimum height contract is missing")

    window.set_log_layout_state("normal")
    QApplication.processEvents()
    if not window.log_toolbar.isVisible() or sum(button.isVisible() for button in buttons) != 5:
        raise AssertionError("normal log layout should expose exactly five tools at full height")
    normal_height = window.main_splitter.sizes()[1]
    visible_lines = window.log_text.height() // max(1, window.log_text.fontMetrics().lineSpacing())
    if normal_height < 190 or visible_lines < 8:
        raise AssertionError(f"normal log layout is too short: drawer={normal_height}, lines={visible_lines}")

    window.set_log_layout_state("expanded")
    QApplication.processEvents()
    expanded_height = window.main_splitter.sizes()[1]
    if expanded_height <= normal_height or window.log_layout_state != "expanded":
        raise AssertionError("expanded log layout did not grow")

    window.set_log_layout_state("collapsed")
    QApplication.processEvents()
    if window.log_text.isVisible() or window.log_toolbar.isVisible() or window.log_layout_state != "collapsed":
        raise AssertionError("collapsed log layout did not hide the log body")
    if window.btn_open_log.text() != "显示日志":
        raise AssertionError("collapsed log layout did not expose the header show-log action")

    window._restore_default_log_layout()
    QApplication.processEvents()
    restored_height = window.main_splitter.sizes()[1]
    if window.log_layout_state != "normal" or window.btn_open_log.text() != "隐藏日志" or abs(restored_height - normal_height) > 8:
        raise AssertionError("restore-default log layout is unstable")
    if window.btn_open_log.height() > 30 or window.btn_open_log.width() >= 124:
        raise AssertionError("log header action is not compact")


def main() -> None:
    app = QApplication.instance() or QApplication([])

    tmp_dir = Path(tempfile.gettempdir()) / f"launchflow-gui-smoke-{os.getpid()}-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True)
    old_data_dir = os.environ.get(APP_DATA_ENV)
    os.environ[APP_DATA_ENV] = str(tmp_dir / "测试 AppData 空格")
    screenshots: list[Path] = []
    try:
        window = MainWindow(tmp_dir)
        window.resize(1180, 760)
        window.show()
        QApplication.processEvents()

        spinboxes = {
            "app_delay_in": window.app_delay_in,
            "url_delay_in": window.url_delay_in,
            "cmd_delay_in": window.cmd_delay_in,
            "wait_seconds_in": window.wait_seconds_in,
        }

        discovered = window.findChildren(QDoubleSpinBox)
        if len(discovered) < len(spinboxes):
            raise AssertionError(f"expected at least {len(spinboxes)} spinboxes, found {len(discovered)}")

        for name, spinbox in spinboxes.items():
            _check_spinbox_contract(window, spinbox, name)

        _check_add_step_and_shortcut_contract(window)
        _check_log_layout_contract(window)

        for theme_name, is_dark in (("dark", True), ("light", False)):
            window.is_dark_theme = is_dark
            window._apply_theme()
            window.editor_stack.setCurrentWidget(window.page_no_steps)
            QApplication.processEvents()
            screenshots.append(_save_screenshot(window, f"{theme_name}-main-window.png"))
            window.editor_stack.setCurrentWidget(window.page_wait)
            QApplication.processEvents()
            _click_spinbox_arrows(window.wait_seconds_in)
            _assert_spinbox_arrow_visible(window.wait_seconds_in, theme_name)
            window.editor_stack.setCurrentWidget(window.page_cmd)
            QApplication.processEvents()
            _assert_combo_contract(window.cmd_shell_in, theme_name)
            screenshots.append(_save_screenshot(window, f"{theme_name}-spinbox-combobox.png"))

        _check_trial_worker_lifecycle(window)

        if (Path(os.environ[APP_DATA_ENV]) / "licenses" / "license.lic").exists():
            raise AssertionError("GUI smoke unexpectedly created a license file")

        window.close()
        app.processEvents()
    finally:
        reset_app_logger_for_tests()
        if old_data_dir is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_data_dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("editor gui smoke ok")
    print(f"spinbox_count={len(discovered)}")
    print("themes=dark,light")
    print("combo_popup_click_regions=3")
    print("new_step_immediate_inspector=ok")
    print("editor_shortcuts=Ctrl+S,Ctrl+Shift+S,Ctrl+R,Ctrl+E,Delete")
    print("step_drag=internal-move,custom-indicator,autoscroll")
    print("log_layout=five-tool-responsive,normal,expanded,collapsed,compact-status")
    print("feedback_dialog=instantiated,no-auto-upload")
    print("trial_worker_lifecycle=finished-before-release")
    print("authorization_mode=mocked-mainwindow,no-license-file")
    print("screenshot_mode=offscreen-simulated-theme")
    for path in screenshots:
        print(f"screenshot={path}")


if __name__ == "__main__":
    main()
