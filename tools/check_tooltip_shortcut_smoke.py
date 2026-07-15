"""Verify tooltip text stays aligned with QAction shortcuts."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"tooltip-smoke-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from editor.ui.main_window import MainWindow, SHORTCUTS  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    try:
        bindings = [
            (window.btn_save, window.action_save, "save"),
            (window.btn_save_as, window.action_save_as, "save_as"),
            (window.btn_trial_run, window.action_trial_run, "trial_run"),
            (window.btn_export_exe, window.action_export_exe, "export"),
            (window.btn_delete_step, window.action_delete_step, "delete"),
        ]
        for button, action, key in bindings:
            actual = action.shortcut()
            if actual != type(actual)(SHORTCUTS[key]) or SHORTCUTS[key] not in button.toolTip():
                raise AssertionError(f"tooltip/shortcut mismatch: {key}, {actual.toString()!r}, {button.toolTip()!r}")
        if "后台命令" not in window.btn_add_cmd.toolTip() or "日志" not in window.btn_add_cmd.toolTip():
            raise AssertionError("Command tooltip does not explain background logging")
        if "不会弹出外部终端" not in window.cmd_shell_in.toolTip():
            raise AssertionError("Shell tooltip does not explain hidden-terminal behavior")
        if SHORTCUTS["move_up"] not in window.flow_list.toolTip() or SHORTCUTS["move_down"] not in window.flow_list.toolTip():
            raise AssertionError("step reorder shortcuts missing from tooltip")
        if window.action_move_step_up.shortcut().toString() != SHORTCUTS["move_up"]:
            raise AssertionError("move-up QAction mismatch")
        if window.action_move_step_down.shortcut().toString() != SHORTCUTS["move_down"]:
            raise AssertionError("move-down QAction mismatch")
        if len(window.log_tool_buttons) != 5 or any(not button.toolTip() for button in window.log_tool_buttons):
            raise AssertionError("five-button log toolbar tooltip contract is incomplete")
        if "放大" not in window.btn_log_expand.toolTip() or window.btn_open_log.text() != "隐藏日志":
            raise AssertionError("log expand/visibility tooltips and labels are inconsistent")
        print("tooltip shortcut smoke ok")
        print("toolbar_shortcuts=shared-action-source")
        print("command_hidden_terminal_tooltip=ok")
        print("step_reorder_tooltip=Alt+Up,Alt+Down")
        print("log_toolbar_tooltips=five-actions,no-duplicate-hide")
        return 0
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
