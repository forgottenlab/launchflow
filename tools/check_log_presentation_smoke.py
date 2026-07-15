"""Validate semantic rich log rendering, plain text, scrolling, bounds, and disk isolation."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"log-presentation-smoke-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from editor.ui.log_console import LogConsole, LogKind, log_formats  # noqa: E402
from editor.ui.main_window import MainWindow  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.app_paths import get_logs_dir  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    for is_dark in (True, False):
        formats = log_formats(is_dark)
        require(set(formats) == set(LogKind), "one or more log categories are missing")
        colors = {fmt.foreground().color().name() for fmt in formats.values()}
        require(len(colors) == len(LogKind), "log categories do not have distinct theme colors")

    console = LogConsole(max_blocks=25)
    console.resize(500, 180)
    console.show()
    kinds = [LogKind.SYSTEM, LogKind.EXECUTION, LogKind.OUTPUT, LogKind.SUCCESS, LogKind.WARNING, LogKind.ERROR]
    for kind in kinds:
        console.append_entry("12:00:00", f"[{kind.name}] plain <text>", kind)
    app.processEvents()
    require("plain <text>" in console.toPlainText(), "rich UI log lost plain text")
    require("&lt;text&gt;" in console.toHtml(), "log text was not safely represented in rich document")
    dark_html = console.toHtml()
    console.set_theme(False)
    light_html = console.toHtml()
    require(dark_html != light_html and "plain &lt;text&gt;" in light_html, "existing log entries were not recolored safely")

    for index in range(80):
        console.append_entry("12:00:01", f"line {index}", LogKind.OUTPUT)
    app.processEvents()
    require(console.document().blockCount() <= 25, "maximum visible log blocks were not enforced")
    console.verticalScrollBar().setValue(0)
    before_scroll = console.verticalScrollBar().value()
    console.append_entry("12:00:02", "new while reviewing old output", LogKind.OUTPUT)
    app.processEvents()
    require(console.verticalScrollBar().value() == before_scroll, "new output stole the user's scroll position")
    require(console.has_unseen_output, "unseen-output state was not exposed")

    window = MainWindow(ROOT)
    window.show()
    app.processEvents()
    try:
        for kind in kinds:
            window._log(f"[{kind.name}] window plain text", kind)
        app.processEvents()
        plain = window.log_text.toPlainText()
        require(all(kind.name in plain for kind in kinds), "MainWindow log categories were not appended")
        require(len(window.log_tool_buttons) == 5, "log presentation exposed duplicate tools")
        window._copy_visible_log()
        require(QApplication.clipboard().text() == plain, "copy-all did not produce plain text")
        require(plain in window._build_diagnostic_text(), "diagnostics did not receive the visible plain-text log")

        for handler in window.disk_logger.handlers:
            handler.flush()
        disk_log = get_logs_dir() / "launchflow.log"
        disk_before = disk_log.read_text(encoding="utf-8", errors="replace")
        require("window plain text" in disk_before, "plain disk log did not receive UI entries")
        window._clear_visible_log()
        require(window.log_text.toPlainText() == "", "clear did not clear the UI log")
        require(disk_log.is_file() and disk_log.read_text(encoding="utf-8", errors="replace") == disk_before, "UI clear changed disk log content")
    finally:
        window.close()
        console.close()
        app.processEvents()

    reset_app_logger_for_tests()
    shutil.rmtree(TEMP, ignore_errors=True)
    print("log presentation smoke ok")
    print("categories=system,execution,output,success,warning,error,separator")
    print("themes=dark,light-distinct-formats")
    print("plain_text=clipboard,diagnostics,disk")
    print("scroll=user-position-preserved,new-output-indicator")
    print("maximum_blocks=25")
    print("clear=ui-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
