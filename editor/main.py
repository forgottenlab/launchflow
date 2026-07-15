"""
main.py

Launch Flow 程序入口。

该模块负责：
1. 解析当前运行环境下的项目根目录；
2. 初始化 Qt 应用；
3. 在进入主工作台前先校验本地授权状态；
4. 根据授权结果决定进入激活窗口或主窗口。

位置：
- editor/main.py

相关模块：
- licensing.license_manager
- editor.ui.activation_window
- editor.ui.main_window

注意事项：
- project_root 只定位源码或 frozen 只读资源；
- 可变数据统一由 shared.app_paths 写入用户 AppData。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from shared.app_info import APP_NAME
from shared.app_logging import get_app_logger
from shared.app_icon import apply_application_icon, configure_windows_app_id, resolve_app_icon_path
from shared.app_paths import AppPathError, ensure_app_directories
from shared.data_migration import migrate_legacy_data


def get_project_root() -> Path:
    """
    获取当前运行环境下的项目根目录。

    返回值：
    - 开发模式下返回项目源码根目录；
    - 打包模式下返回 exe 所在目录，仅用于识别明确的旧版便携数据。

    设计原因：
    - 开发模式需要直接访问源码目录中的模块与资源；
    - 可变数据始终由 shared.app_paths 定位到用户数据目录；
    - onefile 中的图标、公钥等只读资源通过 sys._MEIPASS 单独解析。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()
if str(PROJECT_ROOT) not in sys.path:
    # 将项目根目录加入 sys.path，
    # 保证源码模式和打包模式都能以统一方式导入内部模块。
    sys.path.insert(0, str(PROJECT_ROOT))

from licensing.license_manager import LicenseManager
from editor.ui.main_window import MainWindow
from editor.ui.activation_window import ActivationWindow


def main() -> None:
    """
    启动应用程序。

    启动流程：
    1. 创建 QApplication；
    2. 校验当前本地授权；
    3. 授权有效则直接进入主窗口；
    4. 授权无效则先进入激活窗口；
    5. 激活成功后再进入主窗口。
    """
    # Windows must receive the stable process identity before QApplication or
    # any top-level window exists, otherwise taskbar grouping can keep the
    # generic Python/Qt identity.
    configure_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = apply_application_icon(app, PROJECT_ROOT)

    try:
        ensure_app_directories()
    except AppPathError as exc:
        QMessageBox.critical(None, "LaunchFlow 无法启动", str(exc))
        return

    logger = get_app_logger()
    if icon.isNull():
        logger.warning("LaunchFlow icon unavailable at startup: %s", resolve_app_icon_path(PROJECT_ROOT))
    migration = migrate_legacy_data(PROJECT_ROOT)
    logger.info(
        "Legacy migration: copied=%s skipped=%s errors=%s",
        len(migration.copied),
        len(migration.skipped),
        len(migration.errors),
    )
    for item in migration.copied:
        logger.info("Legacy migration copied: %s", item)
    for item in migration.skipped:
        logger.info("Legacy migration skipped: %s", item)
    for item in migration.errors:
        logger.warning("Legacy migration error: %s", item)

    license_manager = LicenseManager(PROJECT_ROOT)
    license_result = license_manager.validate_current_license()
    logger.info("License check result: %s", license_result.code)

    if license_result.is_valid:
        window = MainWindow(PROJECT_ROOT)
        window.show()
        sys.exit(app.exec())

    activation_window = ActivationWindow(PROJECT_ROOT)
    activation_window.show()

    result = activation_window.exec()
    if result == ActivationWindow.DialogCode.Accepted and activation_window.activation_success:
        window = MainWindow(PROJECT_ROOT)
        window.show()
        sys.exit(app.exec())

    sys.exit(0)


if __name__ == "__main__":
    main()
