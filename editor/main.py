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
- 发布版中 project_root 指向 exe 所在目录，
  这样 data / licenses / logs 都会按便携模式跟随程序目录保存。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from shared.app_info import APP_NAME


def get_project_root() -> Path:
    """
    获取当前运行环境下的项目根目录。

    返回值：
    - 开发模式下返回项目源码根目录；
    - 打包模式下返回 exe 所在目录。

    设计原因：
    - 开发模式需要直接访问源码目录中的模块与资源；
    - 发布模式需要让配置、日志、授权文件与 exe 保持同目录便携存放。
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
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    license_manager = LicenseManager(PROJECT_ROOT)
    license_result = license_manager.validate_current_license()

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