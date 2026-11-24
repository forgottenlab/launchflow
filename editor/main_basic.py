"""
main_basic.py

LaunchFlow Basic 程序入口。

该模块负责：
1. 在任何数据目录或迁移工作之前设置进程级 Basic 版本上下文；
2. 初始化 Qt 应用，并使用与 Professional 分开的 Windows 进程标识；
3. 使用 LaunchFlow-Basic 数据目录直接进入工作台。

Basic 入口不校验许可证，不采集硬件身份，也不对 Professional
数据目录运行遗留迁移。

位置：
- editor/main_basic.py

启动方式：
- 源码：python -m editor.main_basic
- 打包目标：LaunchFlow-Basic.exe
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from editor.launch import (
    BASIC_APP_DISPLAY_NAME,
    BASIC_EDITOR_APP_ID,
    BASIC_EDITOR_ENTRY,
    apply_launch_edition_for_entry,
    ensure_project_root_on_path,
    get_project_root,
)
from shared.app_icon import apply_application_icon, configure_windows_app_id, resolve_app_icon_path
from shared.app_logging import get_app_logger
from shared.app_paths import AppPathError, ensure_app_directories


PROJECT_ROOT = ensure_project_root_on_path(get_project_root())

from editor.ui.main_window import MainWindow


def main() -> None:
    """Start the Basic editor without license checks or Professional data access."""

    apply_launch_edition_for_entry(BASIC_EDITOR_ENTRY)
    configure_windows_app_id(BASIC_EDITOR_APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(BASIC_APP_DISPLAY_NAME)
    icon = apply_application_icon(app, PROJECT_ROOT)

    try:
        ensure_app_directories()
    except AppPathError as exc:
        QMessageBox.critical(None, "LaunchFlow Basic 无法启动", str(exc))
        return

    logger = get_app_logger()
    if icon.isNull():
        logger.warning(
            "LaunchFlow Basic icon unavailable at startup: %s",
            resolve_app_icon_path(PROJECT_ROOT),
        )

    window = MainWindow(PROJECT_ROOT)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
