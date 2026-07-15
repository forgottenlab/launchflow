"""Validate the five-button log toolbar and its height-responsive modes."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"log-toolbar-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SCREENSHOT_DIR = ROOT.parent / "test" / "v0.1.0-beta.1_2026-07-12_234445" / "screenshots"

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor.ui.main_window import MainWindow  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def visible_buttons(window: MainWindow) -> list[object]:
    return [button for button in window.log_tool_buttons if button.isVisible()]


def save_screenshot(window: MainWindow, name: str) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / name
    require(window.grab().save(str(path), "PNG") and path.stat().st_size > 0, f"failed screenshot: {path}")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    window.resize(1180, 760)
    window.show()
    app.processEvents()
    try:
        require(len(window.log_tool_buttons) == 5, "right toolbar must contain exactly five buttons")
        require(not hasattr(window, "btn_log_hide"), "duplicate right-side hide button still exists")
        require(not hasattr(window, "btn_log_restore"), "restore-default button still exists")

        one_height, full_height = window._log_toolbar_height_requirements()
        require(full_height > one_height > 0, "toolbar height requirements are invalid")

        window.set_log_layout_state("normal")
        app.processEvents()
        require(window.update_log_toolbar_visibility(full_height) == "full", "full-height mode not selected")
        require(window.log_toolbar.isVisible() and len(visible_buttons(window)) == 5, "full mode does not show five buttons")
        save_screenshot(window, "dark-log-normal.png")

        require(window.update_log_toolbar_visibility(full_height - 1) == "expand", "partial-height mode not selected")
        require(window.log_toolbar.isVisible(), "expand-only toolbar is hidden")
        require(visible_buttons(window) == [window.btn_log_expand], "partial height must show only expand")

        require(window.update_log_toolbar_visibility(one_height - 1) == "hidden", "tiny-height mode not selected")
        require(not window.log_toolbar.isVisible() and not visible_buttons(window), "tiny height left a partial button")

        window.set_log_layout_state("collapsed")
        app.processEvents()
        require(window.update_log_toolbar_visibility(full_height) == "hidden", "collapsed mode exposed toolbar")
        require(not window.log_toolbar.isVisible() and not visible_buttons(window), "collapsed mode left tools visible")
        require(not window.log_text.isVisible() and not window.log_hint.isVisible(), "collapsed mode left log body visible")
        require(window.btn_open_log.text() == "显示日志", "collapsed header action text is incorrect")
        require(window.btn_open_log.isVisible(), "collapsed layout lost the recovery action")
        save_screenshot(window, "dark-log-collapsed.png")

        window.set_log_layout_state("normal")
        app.processEvents()
        window.update_log_toolbar_visibility(full_height)
        require(window.btn_open_log.text() == "隐藏日志", "normal header action text is incorrect")
        require(window.btn_log_expand.accessibleName() == "放大日志区域", "normal expand semantics are incorrect")

        window.log_text.setMinimumHeight(0)
        total = sum(window.main_splitter.sizes())
        window.main_splitter.setSizes([max(320, total - 110), 110])
        app.processEvents()
        window.update_log_toolbar_visibility(full_height - 1)
        require(window.btn_open_log.text() == "恢复高度", "small-height recovery entry is unclear")
        require(window.btn_open_log.isVisible(), "small-height recovery entry disappeared")
        save_screenshot(window, "dark-log-small-height.png")
        window.is_dark_theme = False
        window._apply_theme()
        app.processEvents()
        window.update_log_toolbar_visibility(full_height - 1)
        save_screenshot(window, "light-log-small-height.png")
        window.is_dark_theme = True
        window._apply_theme()
        window.btn_open_log.click()
        app.processEvents()
        require(window.log_layout_state == "normal", "small-height header action did not restore normal layout")
        window.log_text.setMinimumHeight(148)

        window.set_log_layout_state("expanded")
        app.processEvents()
        window.update_log_toolbar_visibility(full_height)
        require(window.btn_open_log.text() == "隐藏日志", "expanded header action text is incorrect")
        require(window.btn_log_expand.accessibleName() == "恢复正常大小", "expanded restore semantics are incorrect")

        geometries = [button.geometry() for button in visible_buttons(window)]
        require(all(window.log_toolbar.rect().contains(rect) for rect in geometries), "a toolbar button is only partially visible")
        require(
            all(not left.intersects(right) for index, left in enumerate(geometries) for right in geometries[index + 1 :]),
            "toolbar buttons overlap",
        )

        require(not hasattr(window, "status_bar"), "legacy bottom status bar still exists")
        require(window.status_label.parent() is window.log_header, "status is not in the main log control row")
        require(window.btn_open_log.parent() is window.log_header, "visibility action is not in the main log control row")
        require(window.btn_open_log.height() <= 30 and window.btn_open_log.width() < 124, "header action is oversized")
        require("QFrame#LogToolbar, QFrame#LogHeader { background: transparent; border: none; }" in window.styleSheet(), "toolbar still has a nested outer frame")
        long_status = "状态：" + "很长的状态内容" * 80
        window.status_label.setText(long_status)
        app.processEvents()
        require(window.status_label.toolTip() == long_status, "full status is not available through tooltip")
        require(window.status_label.full_text == long_status, "status label lost full text")

        print("log toolbar responsive smoke ok")
        print("toolbar_buttons=5")
        print("modes=full,expand-only,hidden")
        print("collapsed=body-hidden,toolbar-hidden,header-show-log")
        print("normal,expanded=header-hide-log,semantic-expand-action")
        print("tiny-height=header-restore-entry")
        print(f"log_header_height={window.log_header.height()}")
        print(f"screenshots={SCREENSHOT_DIR}")
        return 0
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
