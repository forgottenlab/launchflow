"""Generate deterministic, real-widget screenshots for the public READMEs.

The script instantiates the production MainWindow, LogConsole, reorder paint
layer, history list, and FancyDialog against an isolated data root. It never
loads a license and never writes to the normal LaunchFlow AppData directory.
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "images"
TEMP_ROOT = ROOT.parent / "test" / f"readme-screenshots-{os.getpid()}-{uuid.uuid4().hex}"

os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP_ROOT / "data")
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from editor.services.plan_service import PlanService  # noqa: E402
from editor.ui.log_console import LogKind  # noqa: E402
from editor.ui.main_window import FancyDialog, MainWindow  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.models import AppStep, CommandStep, Plan, UrlStep, WaitStep  # noqa: E402


SCREENSHOT_NAMES = (
    "launchflow-workbench-dark.png",
    "launchflow-workbench-light.png",
    "launchflow-step-reorder.png",
    "launchflow-log-console.png",
    "launchflow-plan-history.png",
    "launchflow-export-workflow.png",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def configure_chinese_font(app: QApplication) -> str:
    """Select an installed Windows UI font that can render Chinese."""

    families = QFontDatabase.families()
    preferred = (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "DengXian",
        "SimSun",
        "Noto Sans CJK SC",
    )
    ordered = [family for family in preferred if family in families]
    ordered.extend(family for family in families if family not in ordered)
    for family in ordered:
        font = QFont(family, 10)
        if QFontMetrics(font).inFontUcs4(ord("中")):
            app.setFont(font)
            return family
    raise RuntimeError(
        "No installed font can render Chinese. Run this generator on Windows "
        "with Microsoft YaHei UI (or another CJK font) available."
    )


def demo_plan(name: str = "每日工作环境") -> Plan:
    return Plan(
        plan_name=name,
        steps=[
            AppStep(
                name="打开文本编辑器",
                path=r"C:\Windows\System32\notepad.exe",
                delay_after=0.5,
            ),
            UrlStep(
                name="打开项目主页",
                url="https://github.com/forgottenlab/launchflow",
                delay_after=0.5,
            ),
            CommandStep(
                name="检查 Python 环境",
                command="python --version",
                shell="cmd",
                delay_after=0.5,
            ),
            WaitStep(name="等待服务启动", seconds=3.0, delay_after=0.0),
        ],
    )


def seed_history(service: PlanService) -> dict[str, Path]:
    plans = {
        "每日工作环境": demo_plan(),
        "发布前检查": Plan(
            plan_name="发布前检查",
            steps=[
                CommandStep(name="运行基础检查", command="python --version", shell="cmd", delay_after=0.0),
                WaitStep(name="等待检查完成", seconds=2.0, delay_after=0.0),
            ],
        ),
        "文档与反馈": Plan(
            plan_name="文档与反馈",
            steps=[UrlStep(name="打开项目主页", url="https://github.com/forgottenlab/launchflow")],
        ),
    }
    paths: dict[str, Path] = {}
    for name, plan in plans.items():
        path = service.get_plans_dir() / f"{name}.json"
        service.save_plan(plan, path)
        paths[name] = path
    return paths


def install_plan(window: MainWindow, plan: Plan, path: Path, selected_row: int) -> None:
    window.current_plan = plan
    window.current_plan_path = path
    window.current_editor_index = None
    window.current_step_dirty = False
    window.plan_dirty = False
    window._loading_plan = True
    window.plan_name_edit.setText(plan.plan_name)
    window._loading_plan = False
    window._refresh_flow_list()
    window._load_history_plans()
    window.flow_list.setCurrentRow(selected_row)
    window._restore_history_selection()
    QApplication.processEvents()


def populate_logs(window: MainWindow) -> None:
    window.log_text.clear_visible()
    entries = (
        ("09:30:00", "工作台已启动。", LogKind.SYSTEM),
        ("09:30:04", "开始执行方案: 每日工作环境", LogKind.EXECUTION),
        ("09:30:04", "[执行] 步骤 1: 打开文本编辑器 (app)", LogKind.EXECUTION),
        ("09:30:04", "[成功] 已启动应用: 打开文本编辑器", LogKind.SUCCESS),
        ("09:30:05", "[执行] 步骤 3: 检查 Python 环境 (command)", LogKind.EXECUTION),
        ("09:30:05", "[命令] python --version", LogKind.EXECUTION),
        ("09:30:05", "[输出] Python 3.13.9", LogKind.OUTPUT),
        ("09:30:05", "[退出码] 0", LogKind.EXECUTION),
        ("09:30:05", "[成功] 命令执行完成", LogKind.SUCCESS),
        ("09:30:06", "[等待] 3.0 秒", LogKind.WARNING),
    )
    for timestamp, message, kind in entries:
        window.log_text.append_entry(timestamp, message, kind)
    window.status_label.setText("状态：试运行完成，所有步骤已执行。")


def apply_theme(window: MainWindow, dark: bool) -> None:
    window.is_dark_theme = dark
    window._apply_theme()
    QApplication.processEvents()


def save_pixmap(pixmap, name: str, minimum_size: tuple[int, int]) -> Path:  # noqa: ANN001
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    require(not pixmap.isNull(), f"empty pixmap for {name}")
    require(
        pixmap.width() >= minimum_size[0] and pixmap.height() >= minimum_size[1],
        f"unexpected screenshot size for {name}: {pixmap.width()}x{pixmap.height()}",
    )
    require(pixmap.save(str(path), "PNG"), f"failed to save {path}")
    require(path.stat().st_size > 10_000, f"screenshot is suspiciously small: {path}")
    return path


def capture_export_dialog(window: MainWindow) -> Path:
    message = (
        "检测到 1 个本地应用启动文件。\n\n"
        "导出时会自动把该启动文件随包携带，并在启动器运行时优先从包内启动。\n"
        "如果应用依赖外部 DLL、配置文件或数据目录，目标电脑仍需具备对应环境。"
    )
    dialog = FancyDialog(
        window,
        "确认导出",
        message,
        primary_text="继续导出",
        secondary_text="取消",
        is_dark=window.is_dark_theme,
    )
    dialog.setFixedWidth(560)
    dialog.adjustSize()
    dialog.show()
    QApplication.processEvents()

    base = window.grab()
    dialog_pixmap = dialog.grab()
    composed = base.copy()
    painter = QPainter(composed)
    painter.fillRect(composed.rect(), QColor(4, 9, 20, 135))
    position = QPoint(
        (composed.width() - dialog_pixmap.width()) // 2,
        (composed.height() - dialog_pixmap.height()) // 2,
    )
    painter.drawPixmap(position, dialog_pixmap)
    painter.end()
    dialog.close()
    return save_pixmap(composed, "launchflow-export-workflow.png", (1200, 760))


def _generate_with_isolated_data() -> list[Path]:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    font_family = configure_chinese_font(app)

    service = PlanService(ROOT)
    history_paths = seed_history(service)
    plan = demo_plan()
    window = MainWindow(ROOT)
    window.resize(1440, 900)
    window.show()
    QApplication.processEvents()

    generated: list[Path] = []
    try:
        install_plan(window, plan, history_paths["每日工作环境"], 2)
        populate_logs(window)
        window.set_log_layout_state("normal")
        apply_theme(window, True)
        generated.append(save_pixmap(window.grab(), "launchflow-workbench-dark.png", (1200, 760)))

        window.flow_list.setCurrentRow(1)
        apply_theme(window, False)
        generated.append(save_pixmap(window.grab(), "launchflow-workbench-light.png", (1200, 760)))

        window.flow_list.setCurrentRow(2)
        apply_theme(window, True)
        source_item = window.flow_list.item(2)
        window.flow_list._dragging_step_id = source_item.data(Qt.ItemDataRole.UserRole)
        window.flow_list._drag_active = True
        window.flow_list._drop_target_index = 1
        ghost = QLabel(window.flow_list.viewport())
        ghost_pixmap = window.flow_list.build_drag_preview(source_item)
        ghost.setPixmap(ghost_pixmap)
        ghost.resize(ghost_pixmap.size())
        ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        last_rect = window.flow_list.visualItemRect(window.flow_list.item(3))
        ghost.move(max(8, last_rect.left() + 10), max(8, last_rect.top() + 6))
        ghost.show()
        window.flow_list.viewport().update()
        QApplication.processEvents()
        generated.append(save_pixmap(window.grab(), "launchflow-step-reorder.png", (1200, 760)))
        ghost.hide()
        ghost.deleteLater()
        window.flow_list.clear_drag_visual_state()

        populate_logs(window)
        window.set_log_layout_state("expanded")
        QApplication.processEvents()
        generated.append(save_pixmap(window.log_drawer.grab(), "launchflow-log-console.png", (1000, 360)))

        window.set_log_layout_state("normal")
        window.history_list.setCurrentRow(0)
        window.history_list.setFocus()
        QApplication.processEvents()
        generated.append(save_pixmap(window.grab(), "launchflow-plan-history.png", (1200, 760)))

        generated.append(capture_export_dialog(window))
        print(f"font={font_family}")
        for path in generated:
            print(f"screenshot={path.name} size={path.stat().st_size}")
        return generated
    finally:
        window.close()
        QApplication.processEvents()
        reset_app_logger_for_tests()


def generate() -> list[Path]:
    TEMP_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        return _generate_with_isolated_data()
    finally:
        shutil.rmtree(TEMP_ROOT, ignore_errors=True)


if __name__ == "__main__":
    generated_files = generate()
    require(
        {path.name for path in generated_files} == set(SCREENSHOT_NAMES),
        "not all README screenshots were generated",
    )
