"""Validate local diagnostics preview, redaction, clipboard, and log-directory routing."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"diagnostics-smoke-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "用户 数据")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from editor.ui.main_window import DiagnosticsDialog, MainWindow  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.app_paths import get_license_dir, get_logs_dir  # noqa: E402
from shared.diagnostics import collect_diagnostics, open_logs_directory  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_license_dir().mkdir(parents=True, exist_ok=True)
    (get_license_dir() / "license.lic").write_text("LICENSE-CONTENT-MUST-NOT-APPEAR", encoding="utf-8")

    lines = [f"normal log {index}" for index in range(240)]
    lines.extend(
        [
            f"path={Path.home() / 'Desktop' / 'demo.cmd'}",
            "machine_id=ABCDEF1234567890",
            "request_id=12345678-1234-1234-1234-123456789012",
            "signature=VERY-LONG-SIGNATURE-VALUE",
            "LFREQ1." + "abcdefghijklmnopqrstuvwxyz0123456789" + ".ABCD1234",
            "private_key.pem SECRET-PRIVATE-CONTENT",
        ]
    )
    diagnostic = collect_diagnostics(
        plan_name="诊断方案",
        step_count=3,
        visible_log="\n".join(lines),
        current_error="示例错误",
        max_log_lines=100,
    )

    required = ("版本:", "构建渠道:", "当前时间:", "Windows:", "最近日志", "诊断方案")
    if any(item not in diagnostic for item in required):
        raise AssertionError("diagnostic metadata is incomplete")
    log_section = diagnostic.split("最近日志（最多 100 行）:\n", 1)[1]
    if len(log_section.splitlines()) > 100:
        raise AssertionError("diagnostic log limit was not enforced")
    forbidden = (
        "ABCDEF1234567890",
        "12345678-1234-1234-1234-123456789012",
        "VERY-LONG-SIGNATURE-VALUE",
        "abcdefghijklmnopqrstuvwxyz0123456789",
        "SECRET-PRIVATE-CONTENT",
        "private_key.pem",
        "LICENSE-CONTENT-MUST-NOT-APPEAR",
    )
    if any(value in diagnostic for value in forbidden):
        raise AssertionError("sensitive diagnostic value leaked")
    if "%USERPROFILE%" not in diagnostic:
        raise AssertionError("user profile path was not normalized")

    dialog = DiagnosticsDialog(None, diagnostic, True)
    dialog._copy()
    if QApplication.clipboard().text() != diagnostic:
        raise AssertionError("diagnostic clipboard copy failed")
    if not any("不会自动上传" in label.text() for label in dialog.findChildren(QLabel)):
        raise AssertionError("diagnostic dialog did not instantiate")
    dialog.close()

    opened: list[str] = []
    original_startfile = os.startfile
    os.startfile = lambda path: opened.append(path)
    try:
        returned = open_logs_directory()
    finally:
        os.startfile = original_startfile
    if returned != get_logs_dir() or opened != [str(get_logs_dir())]:
        raise AssertionError("log directory opener did not use shared app_paths")

    window = MainWindow(ROOT)
    try:
        if len(window.log_tool_buttons) != 5 or window.btn_feedback not in window.log_tool_buttons:
            raise AssertionError("feedback is not part of the five-action responsive toolbar")
        if hasattr(window, "btn_log_hide") or hasattr(window, "btn_log_restore"):
            raise AssertionError("diagnostic toolbar still contains duplicate layout controls")
    finally:
        window.close()
        app.processEvents()
        reset_app_logger_for_tests()

    print("diagnostics smoke ok")
    print("metadata=version,channel,time,system,logs")
    print("log_limit=100")
    print("redaction=paths,machine_id,request_id,LFREQ1,signature,private-key-reference")
    print("license_content=not-read")
    print("clipboard=qt-offscreen")
    print("log_directory=shared-app-paths")
    print("feedback_toolbar=five-actions,no-duplicate-layout-controls")
    shutil.rmtree(TEMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
