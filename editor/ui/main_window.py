"""
main_window.py

主工作台窗口模块。

该模块负责：
- 构建 Launch Flow 的主界面；
- 管理方案创建、加载、编辑、删除与保存；
- 承担试运行、导出、日志展示、主题切换等工作台交互；
- 统一组织标题栏、自定义对话框与后台任务线程。

位置：
- editor/ui/main_window.py

相关模块：
- editor.services.plan_service
- shared.models
- shared.plan_schema
- runtime.launcher_runtime
- tools.build_single_exe

注意事项：
- 该模块是编辑器层的核心交互入口，包含较多 UI 与业务协调逻辑；
- 发布版中试运行直接执行当前方案，导出功能默认禁用；
- 部分路径与缓存逻辑依赖 project_root，必须保证入口层正确传入。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from runtime.launcher_runtime import RuntimeExecutor

from PySide6.QtCore import Qt, QThread, Signal, QPoint, QSize, QRectF, QPointF
from PySide6.QtGui import (
    QIcon,
    QKeyEvent,
    QColor,
    QPainter,
    QPainterPath,
    QPixmap,
    QLinearGradient,
    QPolygonF,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shared.models import Plan, AppStep, UrlStep, CommandStep, WaitStep
from shared.plan_schema import validate_plan_dict
from editor.services.plan_service import PlanService
from tools.build_single_exe import build_single_file_exe


class ThemeManager:
    """
    主工作台主题样式管理器。

    该类集中维护深色主题、浅色主题以及对话框样式，
    使窗口和弹窗能够在统一视觉体系下切换，而不需要在界面构建代码中
    分散拼接大量样式字符串。
    """

    COMMON = """
    * {
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
    }

    QLabel[role="brand_title"] {
        font-size: 20px;
        font-weight: 800;
        background: transparent;
        border: none;
    }

    QLabel[role="brand_subtitle"] {
        font-size: 12px;
        background: transparent;
        border: none;
    }

    QLabel[role="section"] {
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.4px;
        background: transparent;
        border: none;
        padding-left: 2px;
        margin-bottom: 2px;
    }

    QLabel[role="status"] {
        font-size: 12px;
        background: transparent;
        border: none;
    }

    QLabel[role="empty_title"] {
        font-size: 16px;
        font-weight: 700;
        background: transparent;
        border: none;
    }

    QLabel[role="empty_subtitle"] {
        font-size: 13px;
        background: transparent;
        border: none;
    }

    QLabel[role="panel_title"] {
        font-size: 14px;
        font-weight: 700;
        background: transparent;
        border: none;
    }

    QLabel[role="panel_hint"] {
        font-size: 12px;
        background: transparent;
        border: none;
    }

    QFrame#WindowRoot {
        border: 1px solid;
    }

    QFrame#TitleBar {
        border-bottom: 1px solid;
    }

    QFrame#Sidebar {
        border-right: 1px solid;
    }

    QFrame#TopBar {
        border-bottom: 1px solid;
    }

    QFrame#LogDrawer {
        border-top: 1px solid;
    }

    QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {
        border: 1px solid;
        border-radius: 8px;
        padding: 7px 10px;
    }

    QListWidget#HistoryList {
        border: none;
        outline: none;
    }

    QListWidget#HistoryList::item {
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 2px;
    }

    QListWidget#FlowList {
        border: none;
        outline: none;
    }

    QListWidget#FlowList::item {
        border: 1px solid;
        border-radius: 10px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }

    QPushButton {
        border: none;
        border-radius: 10px;
        padding: 8px 16px;
        font-weight: 600;
    }

    QPushButton#PrimaryBtn,
    QPushButton#SecondaryBtn,
    QPushButton#DangerBtn {
        min-height: 40px;
        max-height: 40px;
        min-width: 116px;
        padding-left: 14px;
        padding-right: 14px;
    }

    QPushButton#ThemeToggle {
        min-height: 40px;
        padding: 8px 16px;
        border-radius: 10px;
        text-align: left;
        font-weight: 500;
    }

    QPushButton#TopToolBtn {
        min-height: 40px;
        max-height: 40px;
        min-width: 126px;
        max-width: 126px;
        padding: 0px 16px;
        font-weight: 600;
        border-radius: 10px;
        border: none;
        font-size: 13px;
        text-align: center;
        qproperty-iconSize: 18px 18px;
    }

    QGroupBox {
        border: 1px solid;
        border-radius: 10px;
        margin-top: 10px;
        padding-top: 10px;
        font-weight: 700;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }

    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }

    QScrollBar::handle:vertical {
        border-radius: 4px;
        min-height: 32px;
    }

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        height: 0px;
        background: transparent;
    }

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {
        background: transparent;
    }

    QScrollBar:horizontal {
        border: none;
        background: transparent;
        height: 8px;
        margin: 0px;
    }

    QScrollBar::handle:horizontal {
        border-radius: 4px;
        min-width: 32px;
    }

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        width: 0px;
        background: transparent;
    }

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    """

    DARK = COMMON + """
    QWidget {
        background: #0F172A;
        color: #F8FAFC;
    }

    QFrame#WindowRoot {
        background: #0F172A;
        border-color: #243145;
    }

    QFrame#TitleBar {
        background: #0F172A;
        border-color: #243145;
    }

    QFrame#Sidebar {
        background: #1E293B;
        border-color: #334155;
    }

    QFrame#TopBar {
        background: #0F172A;
        border-color: #243145;
    }

    QFrame#LogDrawer {
        background: #0F172A;
        border-color: #243145;
    }

    QLabel[role="brand_title"] { color: #FFFFFF; }
    QLabel[role="brand_subtitle"] { color: #94A3B8; }
    QLabel[role="section"] { color: #7C8BA1; }
    QLabel[role="status"] { color: #94A3B8; }
    QLabel[role="empty_title"] { color: #F8FAFC; }
    QLabel[role="empty_subtitle"] { color: #94A3B8; }
    QLabel[role="panel_title"] { color: #F8FAFC; }
    QLabel[role="panel_hint"] { color: #94A3B8; }

    QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {
        background: #0B1220;
        border-color: #334155;
        color: #F8FAFC;
    }

    QListWidget#HistoryList {
        background: transparent;
        color: #E2E8F0;
    }

    QListWidget#HistoryList::item:hover {
        background: #334155;
    }

    QListWidget#HistoryList::item:selected {
        background: #3B82F6;
        color: white;
    }

    QListWidget#FlowList {
        background: transparent;
        color: #F8FAFC;
    }

    QListWidget#FlowList::item {
        background: #172033;
        border-color: #334155;
        color: #F8FAFC;
    }

    QListWidget#FlowList::item:selected {
        background: #1D4ED8;
        border-color: #60A5FA;
        color: white;
    }

    QPushButton#PrimaryBtn {
        background: #3B82F6;
        color: white;
    }

    QPushButton#PrimaryBtn:hover {
        background: #2563EB;
    }

    QPushButton#SecondaryBtn {
        background: #334155;
        color: #F8FAFC;
    }

    QPushButton#SecondaryBtn:hover {
        background: #475569;
    }

    QPushButton#DangerBtn {
        background: #991B1B;
        color: #FECACA;
    }

    QPushButton#DangerBtn:hover {
        background: #B91C1C;
    }

    QPushButton#ThemeToggle {
        background: transparent;
        border: 1px solid #475569;
        color: #E2E8F0;
    }

    QPushButton#ThemeToggle:hover {
        background: rgba(255,255,255,0.06);
    }

    QPushButton#TopToolBtn {
        background: #334155;
        color: #F8FAFC;
    }

    QPushButton#TopToolBtn:hover {
        background: #475569;
    }

    QPushButton#TopToolBtn[role="primary"] {
        background: #3B82F6;
        color: white;
    }

    QPushButton#TopToolBtn[role="primary"]:hover {
        background: #2563EB;
    }

    QGroupBox {
        border-color: #334155;
    }

    QGroupBox::title {
        color: #CBD5E1;
    }

    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {
        background: rgba(148, 163, 184, 0.35);
    }

    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {
        background: rgba(148, 163, 184, 0.55);
    }
    """

    LIGHT = COMMON + """
    QWidget {
        background: #F8FAFC;
        color: #111827;
    }

    QFrame#WindowRoot {
        background: #FFFFFF;
        border-color: #E5E7EB;
    }

    QFrame#TitleBar {
        background: #FFFFFF;
        border-color: #E5E7EB;
    }

    QFrame#Sidebar {
        background: #F8FAFC;
        border-color: #E5E7EB;
    }

    QFrame#TopBar {
        background: #FFFFFF;
        border-color: #E5E7EB;
    }

    QFrame#LogDrawer {
        background: #FFFFFF;
        border-color: #E5E7EB;
    }

    QLabel[role="brand_title"] { color: #111827; }
    QLabel[role="brand_subtitle"] { color: #6B7280; }
    QLabel[role="section"] { color: #94A3B8; }
    QLabel[role="status"] { color: #6B7280; }
    QLabel[role="empty_title"] { color: #111827; }
    QLabel[role="empty_subtitle"] { color: #6B7280; }
    QLabel[role="panel_title"] { color: #111827; }
    QLabel[role="panel_hint"] { color: #6B7280; }

    QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {
        background: #F8FAFC;
        border-color: #D1D5DB;
        color: #111827;
    }

    QListWidget#HistoryList {
        background: transparent;
        color: #111827;
    }

    QListWidget#HistoryList::item:hover {
        background: #F3F4F6;
    }

    QListWidget#HistoryList::item:selected {
        background: #DBEAFE;
        color: #1E40AF;
    }

    QListWidget#FlowList {
        background: transparent;
        color: #111827;
    }

    QListWidget#FlowList::item {
        background: #F8FAFC;
        border-color: #E5E7EB;
        color: #111827;
    }

    QListWidget#FlowList::item:selected {
        background: #DBEAFE;
        border-color: #60A5FA;
        color: #1E40AF;
    }

    QPushButton#PrimaryBtn {
        background: #3B82F6;
        color: white;
    }

    QPushButton#PrimaryBtn:hover {
        background: #2563EB;
    }

    QPushButton#SecondaryBtn {
        background: #F3F4F6;
        color: #374151;
    }

    QPushButton#SecondaryBtn:hover {
        background: #E5E7EB;
    }

    QPushButton#DangerBtn {
        background: #FEE2E2;
        color: #DC2626;
    }

    QPushButton#DangerBtn:hover {
        background: #FECACA;
    }

    QPushButton#ThemeToggle {
        background: transparent;
        border: 1px solid #D1D5DB;
        color: #374151;
    }

    QPushButton#ThemeToggle:hover {
        background: rgba(0,0,0,0.05);
    }

    QPushButton#TopToolBtn {
        background: #F3F4F6;
        color: #374151;
        border: 1px solid #E5E7EB;
    }

    QPushButton#TopToolBtn:hover {
        background: #E5E7EB;
    }

    QPushButton#TopToolBtn[role="primary"] {
        background: #3B82F6;
        color: white;
        border: none;
    }

    QPushButton#TopToolBtn[role="primary"]:hover {
        background: #2563EB;
    }

    QGroupBox {
        border-color: #E5E7EB;
    }

    QGroupBox::title {
        color: #374151;
    }

    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal {
        background: rgba(107, 114, 128, 0.30);
    }

    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {
        background: rgba(107, 114, 128, 0.50);
    }
    """

    DIALOG_COMMON = """
    QDialog {
        border-radius: 14px;
    }

    QLabel#DialogTitle {
        font-size: 18px;
        font-weight: 700;
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
    }

    QLabel#DialogText {
        font-size: 13px;
        line-height: 1.6;
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
    }

    QPushButton#DialogPrimaryBtn {
        border-radius: 8px;
        padding: 8px 18px;
        min-width: 86px;
        font-weight: 600;
    }

    QPushButton#DialogGhostBtn {
        border-radius: 8px;
        padding: 8px 18px;
        min-width: 86px;
        font-weight: 600;
    }
    """

    DIALOG_DARK = DIALOG_COMMON + """
    QDialog {
        background: #1F2937;
        color: #F3F4F6;
        border: 1px solid #374151;
    }
    QLabel#DialogTitle { color: #F9FAFB; }
    QLabel#DialogText { color: #D1D5DB; }
    QPushButton#DialogPrimaryBtn {
        background: #3B82F6;
        color: white;
        border: none;
    }
    QPushButton#DialogPrimaryBtn:hover {
        background: #2563EB;
    }
    QPushButton#DialogGhostBtn {
        background: #374151;
        color: #E5E7EB;
        border: none;
    }
    QPushButton#DialogGhostBtn:hover {
        background: #4B5563;
    }
    """

    DIALOG_LIGHT = DIALOG_COMMON + """
    QDialog {
        background: #FFFFFF;
        color: #111827;
        border: 1px solid #E5E7EB;
    }
    QLabel#DialogTitle { color: #111827; }
    QLabel#DialogText { color: #4B5563; }
    QPushButton#DialogPrimaryBtn {
        background: #3B82F6;
        color: white;
        border: none;
    }
    QPushButton#DialogPrimaryBtn:hover {
        background: #2563EB;
    }
    QPushButton#DialogGhostBtn {
        background: #F3F4F6;
        color: #374151;
        border: none;
    }
    QPushButton#DialogGhostBtn:hover {
        background: #E5E7EB;
    }
    """


class WindowControlButton(QPushButton):
    """
    自绘窗口控制按钮。

    用于无边框窗口标题栏中的最小化、最大化、关闭按钮，
    以便在不同主题下保持统一的交互样式与尺寸。
    """

    def __init__(self, kind: str, parent=None):
        """
        初始化窗口控制按钮。

        参数：
        - kind: 按钮类型，可选值为 min / max / close。
        """
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(44, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setObjectName("CloseTitleBtn" if kind == "close" else "TitleBtn")

    def paintEvent(self, event) -> None:
        """
        根据按钮类型与当前 hover 状态自绘图标。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        if self.underMouse():
            if self.kind == "close":
                painter.fillRect(rect, QColor("#DC2626"))
            else:
                hover_color = (
                    QColor(255, 255, 255, 20)
                    if self.palette().window().color().lightness() < 128
                    else QColor(0, 0, 0, 18)
                )
                painter.fillRect(rect, hover_color)

        if self.kind == "close" and self.underMouse():
            color = QColor("#FFFFFF")
        else:
            color = (
                QColor("#E2E8F0")
                if self.palette().window().color().lightness() < 128
                else QColor("#374151")
            )

        pen = QPen(color, 1.6)
        painter.setPen(pen)

        cx = rect.center().x()
        cy = rect.center().y()

        if self.kind == "min":
            painter.drawLine(cx - 7, cy + 1, cx + 7, cy + 1)
        elif self.kind == "max":
            painter.drawRect(QRectF(cx - 6.5, cy - 6.5, 13, 13))
        elif self.kind == "close":
            painter.drawLine(cx - 6, cy - 6, cx + 6, cy + 6)
            painter.drawLine(cx + 6, cy - 6, cx - 6, cy + 6)

        painter.end()


class FancyDialog(QDialog):
    """
    自定义轻量弹窗。

    用于替代默认消息框，以保持与主工作台一致的视觉风格。
    """

    def __init__(
        self,
        parent: QWidget,
        title: str,
        text: str,
        primary_text: str = "确定",
        secondary_text: Optional[str] = None,
        is_dark: bool = True,
    ) -> None:
        """
        初始化弹窗。

        参数：
        - parent: 父窗口；
        - title: 弹窗标题；
        - text: 弹窗正文；
        - primary_text: 主按钮文本；
        - secondary_text: 次按钮文本，可为空；
        - is_dark: 是否使用深色主题样式。
        """
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(ThemeManager.DIALOG_DARK if is_dark else ThemeManager.DIALOG_LIGHT)

        self.result_value = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_label.setWordWrap(True)
        title_label.setStyleSheet("background: transparent; border: none;")

        text_label = QLabel(text)
        text_label.setObjectName("DialogText")
        text_label.setWordWrap(True)
        text_label.setStyleSheet("background: transparent; border: none;")

        root.addWidget(title_label)
        root.addWidget(text_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 8, 0, 0)
        btn_row.setSpacing(10)
        btn_row.addStretch()

        if secondary_text:
            btn_cancel = QPushButton(secondary_text)
            btn_cancel.setObjectName("DialogGhostBtn")
            btn_cancel.clicked.connect(self.reject)
            btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton(primary_text)
        btn_ok.setObjectName("DialogPrimaryBtn")
        btn_ok.clicked.connect(self._accept_with_value)
        btn_row.addWidget(btn_ok)

        root.addLayout(btn_row)

    def _accept_with_value(self) -> None:
        """
        在确认按钮点击后记录结果并关闭弹窗。
        """
        self.result_value = True
        self.accept()


class BuildWorker(QThread):
    """
    后台导出线程。

    用于将当前方案封装为独立 exe，避免在主线程中执行耗时打包操作。
    """

    progress = Signal(str)
    success = Signal(str)
    failed = Signal(str)

    def __init__(self, plan: Plan, output_exe_path: Path) -> None:
        """
        初始化导出线程。

        参数：
        - plan: 当前待导出的方案对象；
        - output_exe_path: 目标 exe 输出路径。
        """
        super().__init__()
        self.plan = plan
        self.output_exe_path = output_exe_path

    def run(self) -> None:
        """
        执行后台打包流程。
        """
        try:
            self.progress.emit("开始编译方案到缓存...")
            build_single_file_exe(self.plan.to_dict(), self.output_exe_path)
            self.success.emit(str(self.output_exe_path))
        except Exception as e:
            self.failed.emit(f"打包失败: {str(e)}")


class TrialRunWorker(QThread):
    """
    方案试运行线程。

    负责在后台真实执行当前方案中的步骤，
    并将运行日志实时回传到主界面。
    """

    progress = Signal(str)
    success = Signal()
    failed = Signal(str)

    def __init__(self, plan: Plan) -> None:
        """
        初始化试运行线程。

        参数：
        - plan: 当前待执行的方案对象。
        """
        super().__init__()
        self.plan = plan

    def run(self) -> None:
        """
        执行后台试运行流程。
        """
        try:
            executor = RuntimeExecutor(log_callback=self.progress.emit)
            executor.run_plan(self.plan)
            self.success.emit()
        except Exception as e:
            self.failed.emit(str(e))


class CustomTitleBar(QFrame):
    """
    主窗口自定义标题栏。

    负责：
    - 展示应用图标与标题；
    - 提供最小化、最大化、关闭按钮；
    - 支持无边框窗口拖动与双击最大化。
    """

    def __init__(self, parent_window: "MainWindow") -> None:
        """
        初始化标题栏。

        参数：
        - parent_window: 所属主窗口实例。
        """
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.drag_pos: Optional[QPoint] = None

        self.setObjectName("TitleBar")
        self.setFixedHeight(42)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("Launch Flow 工作台")
        self.title_label.setStyleSheet(
            "font-weight: 600; font-size: 13px; background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.btn_min = WindowControlButton("min", self)
        self.btn_max = WindowControlButton("max", self)
        self.btn_close = WindowControlButton("close", self)

        self.btn_min.clicked.connect(parent_window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_maximize)
        self.btn_close.clicked.connect(parent_window.close)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def set_icon(self, icon: QIcon) -> None:
        """
        设置标题栏图标。
        """
        self.icon_label.setPixmap(icon.pixmap(16, 16))

    def _toggle_maximize(self) -> None:
        """
        切换窗口最大化状态。
        """
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def mousePressEvent(self, event) -> None:
        """
        记录窗口拖动起点。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        """
        在非最大化状态下拖动窗口。
        """
        if self.drag_pos and event.buttons() & Qt.MouseButton.LeftButton and not self.parent_window.isMaximized():
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseDoubleClickEvent(self, event) -> None:
        """
        双击标题栏时切换最大化状态。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()


class MainWindow(QMainWindow):
    """
    Launch Flow 主工作台窗口。

    该窗口负责组织方案编辑、步骤管理、试运行、导出、日志展示与主题切换，
    是整个编辑器侧的核心交互界面。
    """

    def __init__(self, project_root: Path) -> None:
        """
        初始化主工作台窗口。

        参数：
        - project_root: 项目根目录或发布版 exe 所在目录。
        """
        super().__init__()
        self.project_root = project_root
        self.plan_service = PlanService(project_root)

        self.current_plan = Plan(plan_name="未命名方案")
        self.current_plan_path: Optional[Path] = None
        self.templates = self.plan_service.load_templates()

        self.is_dark_theme = True
        self.build_worker: Optional[BuildWorker] = None
        self.trial_run_worker: Optional[TrialRunWorker] = None
        self.progress_dialog: Optional[QProgressDialog] = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1280, 800)

        self.app_icon = self._create_app_icon()
        self.setWindowIcon(self.app_icon)

        self._build_ui()
        self._apply_theme()
        self._load_history_plans()
        self._refresh_flow_list()
        self._set_editor_no_steps()
        self._log("工作台已启动。")

    def _build_ui(self) -> None:
        """
        构建主工作台界面。

        界面主要由以下部分组成：
        - 自定义标题栏；
        - 左侧方案管理栏；
        - 右侧工作区；
        - 顶部工具栏；
        - 步骤流与属性编辑区；
        - 底部日志抽屉与状态栏。
        """
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        outer = QVBoxLayout(main_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.window_root = QFrame()
        self.window_root.setObjectName("WindowRoot")
        outer.addWidget(self.window_root)

        root_layout = QVBoxLayout(self.window_root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        self.title_bar.set_icon(self.app_icon)
        root_layout.addWidget(self.title_bar)

        content_host = QWidget()
        content_layout = QHBoxLayout(content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        root_layout.addWidget(content_host, 1)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(245)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(12)

        icon_preview = QLabel()
        icon_preview.setPixmap(self.app_icon.pixmap(48, 48))
        icon_preview.setFixedSize(48, 48)
        icon_preview.setStyleSheet("background: transparent; border: none;")

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        brand_title = self._make_label("Launch Flow", "brand_title")
        brand_subtitle = self._make_label("快捷封装工作台", "brand_subtitle")

        text_col.addStretch()
        text_col.addWidget(brand_title)
        text_col.addWidget(brand_subtitle)
        text_col.addStretch()

        brand_row.addWidget(icon_preview, 0, Qt.AlignmentFlag.AlignVCenter)
        brand_row.addLayout(text_col, 1)

        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(18)

        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("ThemeToggle")
        self.btn_theme_toggle.setMinimumWidth(180)
        self.btn_theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_theme_btn_text()
        self.btn_theme_toggle.clicked.connect(self._toggle_theme)
        sidebar_layout.addWidget(self.btn_theme_toggle)

        sidebar_layout.addSpacing(20)
        sidebar_layout.addWidget(self._make_label("方案管理", "section"))
        sidebar_layout.addSpacing(8)

        self.btn_new_plan = QPushButton("📄 新建方案")
        self.btn_new_plan.setObjectName("SecondaryBtn")
        self.btn_new_plan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_plan.clicked.connect(self._on_new_plan)
        sidebar_layout.addWidget(self.btn_new_plan)

        sidebar_layout.addSpacing(16)
        sidebar_layout.addWidget(self._make_label("本地历史方案 (双击载入)", "section"))
        sidebar_layout.addSpacing(8)

        self.history_list = QListWidget()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_list.itemDoubleClicked.connect(self._load_history_plan_item)
        sidebar_layout.addWidget(self.history_list, 1)

        content_layout.addWidget(sidebar)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(12, 12, 12, 0)
        right_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setHandleWidth(2)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(56)

        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 0, 16, 0)
        top_bar_layout.setSpacing(10)

        top_bar_layout.addWidget(QLabel("方案名称:"))

        self.plan_name_edit = QLineEdit()
        self.plan_name_edit.setPlaceholderText("请输入方案名称...")
        self.plan_name_edit.setFixedWidth(230)
        self.plan_name_edit.textChanged.connect(self._on_plan_name_changed)
        top_bar_layout.addWidget(self.plan_name_edit)

        top_bar_layout.addStretch()

        self.btn_save = QPushButton("保存方案")
        self.btn_save.setObjectName("TopToolBtn")
        self.btn_save.setIcon(self._create_small_icon("save"))
        self.btn_save.setIconSize(QSize(18, 18))
        self.btn_save.clicked.connect(self._on_save_plan)

        self.btn_trial_run = QPushButton("试运行")
        self.btn_trial_run.setObjectName("TopToolBtn")
        self.btn_trial_run.setIcon(self._create_small_icon("run"))
        self.btn_trial_run.setIconSize(QSize(18, 18))
        self.btn_trial_run.clicked.connect(self._on_trial_run)

        self.btn_export_exe = QPushButton("导出 EXE")
        self.btn_export_exe.setObjectName("TopToolBtn")
        self.btn_export_exe.setProperty("role", "primary")
        self.btn_export_exe.setIcon(self._create_small_icon("export"))
        self.btn_export_exe.setIconSize(QSize(18, 18))
        self.btn_export_exe.clicked.connect(self._on_export_exe)

        for btn in [self.btn_save, self.btn_trial_run, self.btn_export_exe]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            top_bar_layout.addWidget(btn)

        workspace_layout.addWidget(top_bar)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setHandleWidth(1)

        flow_panel = QWidget()
        flow_layout = QVBoxLayout(flow_panel)
        flow_layout.setContentsMargins(16, 16, 16, 16)

        flow_layout.addWidget(self._make_label("启动流排布 (DELETE 键删除)", "section"))

        self.flow_list = QListWidget()
        self.flow_list.setObjectName("FlowList")
        self.flow_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.flow_list.itemSelectionChanged.connect(self._on_flow_selection_changed)
        flow_layout.addWidget(self.flow_list)

        action_bar = QHBoxLayout()

        self.btn_add_app = QPushButton("+ 应用")
        self.btn_add_url = QPushButton("+ 网页")
        self.btn_add_cmd = QPushButton("+ 命令")
        self.btn_add_wait = QPushButton("+ 等待")

        for btn in [self.btn_add_app, self.btn_add_url, self.btn_add_cmd, self.btn_add_wait]:
            btn.setObjectName("SecondaryBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_bar.addWidget(btn, 1)

        self.btn_add_app.clicked.connect(self._on_add_app_step)
        self.btn_add_url.clicked.connect(lambda: self._on_add_template_step("url"))
        self.btn_add_cmd.clicked.connect(lambda: self._on_add_template_step("command"))
        self.btn_add_wait.clicked.connect(lambda: self._on_add_template_step("wait"))

        flow_layout.addLayout(action_bar)

        inspector_panel = QWidget()
        inspector_layout = QVBoxLayout(inspector_panel)
        inspector_layout.setContentsMargins(16, 16, 16, 16)

        inspector_layout.addWidget(self._make_label("步骤参数配置", "section"))

        self.editor_stack = QStackedWidget()
        self._build_property_editors()
        inspector_layout.addWidget(self.editor_stack)
        inspector_layout.addStretch()

        self.btn_apply = QPushButton("保存此步骤修改")
        self.btn_apply.setObjectName("PrimaryBtn")
        self.btn_apply.clicked.connect(self._apply_step_changes)
        inspector_layout.addWidget(self.btn_apply)

        self.btn_delete_step = QPushButton("🗑️ 删除步骤")
        self.btn_delete_step.setObjectName("DangerBtn")
        self.btn_delete_step.clicked.connect(self._on_delete_step)
        inspector_layout.addWidget(self.btn_delete_step)

        content_splitter.addWidget(flow_panel)
        content_splitter.addWidget(inspector_panel)
        content_splitter.setSizes([700, 360])

        workspace_layout.addWidget(content_splitter)
        self.main_splitter.addWidget(workspace)

        self.log_drawer = QFrame()
        self.log_drawer.setObjectName("LogDrawer")
        drawer_layout = QVBoxLayout(self.log_drawer)
        drawer_layout.setContentsMargins(12, 10, 12, 12)

        drawer_layout.addWidget(self._make_label("🛠️ 运行与输出日志", "panel_title"))
        drawer_layout.addWidget(self._make_label("试运行、导出、缓存复用等输出都会显示在这里。", "panel_hint"))

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        drawer_layout.addWidget(self.log_text)

        self.main_splitter.addWidget(self.log_drawer)
        self.main_splitter.setSizes([800, 0])

        right_layout.addWidget(self.main_splitter)

        status_bar_layout = QHBoxLayout()
        status_bar_layout.setContentsMargins(12, 6, 12, 12)

        self.status_label = QLabel("状态：准备就绪")
        self.status_label.setProperty("role", "status")
        status_bar_layout.addWidget(self.status_label)
        status_bar_layout.addStretch()

        self.btn_open_log = QPushButton("📟 调阅控制台")
        self.btn_open_log.setObjectName("SecondaryBtn")
        self.btn_open_log.setMinimumWidth(124)
        self.btn_open_log.setFixedHeight(36)
        self.btn_open_log.clicked.connect(self._toggle_log_drawer)
        status_bar_layout.addWidget(self.btn_open_log)

        right_layout.addLayout(status_bar_layout)
        content_layout.addWidget(right_container, 1)

    def _build_property_editors(self) -> None:
        """
        构建右侧属性编辑区的各类页面。

        编辑页包括：
        - 应用步骤页；
        - 网页步骤页；
        - 命令步骤页；
        - 等待步骤页；
        - 无步骤占位页；
        - 未选中步骤占位页；
        - 多选占位页。
        """
        self.page_app = QWidget()
        app_form = QFormLayout(self.page_app)
        self.app_name_in = QLineEdit()
        self.app_path_in = QLineEdit()
        self.app_args_in = QTextEdit()
        self.app_delay_in = QDoubleSpinBox()
        self.app_delay_in.setRange(0, 9999)
        self.app_delay_in.setDecimals(1)
        app_form.addRow("步骤名称", self.app_name_in)
        app_form.addRow("程序路径", self.app_path_in)
        app_form.addRow("启动参数", self.app_args_in)
        app_form.addRow("后续延迟(秒)", self.app_delay_in)
        self.editor_stack.addWidget(self.page_app)

        self.page_url = QWidget()
        url_form = QFormLayout(self.page_url)
        self.url_name_in = QLineEdit()
        self.url_in = QLineEdit()
        self.url_delay_in = QDoubleSpinBox()
        self.url_delay_in.setRange(0, 9999)
        self.url_delay_in.setDecimals(1)
        url_form.addRow("步骤名称", self.url_name_in)
        url_form.addRow("网址 URL", self.url_in)
        url_form.addRow("后续延迟(秒)", self.url_delay_in)
        self.editor_stack.addWidget(self.page_url)

        self.page_cmd = QWidget()
        cmd_form = QFormLayout(self.page_cmd)
        self.cmd_name_in = QLineEdit()
        self.cmd_in = QTextEdit()
        self.cmd_shell_in = QComboBox()
        self.cmd_shell_in.addItems(["cmd", "powershell"])
        self.cmd_delay_in = QDoubleSpinBox()
        self.cmd_delay_in.setRange(0, 9999)
        self.cmd_delay_in.setDecimals(1)
        cmd_form.addRow("步骤名称", self.cmd_name_in)
        cmd_form.addRow("执行命令", self.cmd_in)
        cmd_form.addRow("Shell 类型", self.cmd_shell_in)
        cmd_form.addRow("后续延迟(秒)", self.cmd_delay_in)
        self.editor_stack.addWidget(self.page_cmd)

        self.page_wait = QWidget()
        wait_form = QFormLayout(self.page_wait)
        self.wait_name_in = QLineEdit()
        self.wait_seconds_in = QDoubleSpinBox()
        self.wait_seconds_in.setRange(0, 9999)
        self.wait_seconds_in.setDecimals(1)
        wait_form.addRow("步骤名称", self.wait_name_in)
        wait_form.addRow("等待时间(秒)", self.wait_seconds_in)
        self.editor_stack.addWidget(self.page_wait)

        self.page_no_steps = QWidget()
        no_steps_layout = QVBoxLayout(self.page_no_steps)
        no_steps_layout.setContentsMargins(20, 20, 20, 20)
        no_steps_layout.addStretch()

        title1 = self._make_label("当前方案还没有步骤", "empty_title")
        sub1 = self._make_label("请先在左侧点击“+ 应用 / + 网页 / + 命令 / + 等待”来添加步骤。", "empty_subtitle")
        title1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub1.setWordWrap(True)

        no_steps_layout.addWidget(title1)
        no_steps_layout.addWidget(sub1)
        no_steps_layout.addStretch()
        self.editor_stack.addWidget(self.page_no_steps)

        self.page_none = QWidget()
        none_layout = QVBoxLayout(self.page_none)
        none_layout.setContentsMargins(20, 20, 20, 20)
        none_layout.addStretch()

        title2 = self._make_label("尚未选择步骤", "empty_title")
        sub2 = self._make_label("当前方案已有步骤，请先在左侧点击一个步骤，再编辑其属性。", "empty_subtitle")
        title2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub2.setWordWrap(True)

        none_layout.addWidget(title2)
        none_layout.addWidget(sub2)
        none_layout.addStretch()
        self.editor_stack.addWidget(self.page_none)

        self.page_multi = QWidget()
        multi_layout = QVBoxLayout(self.page_multi)
        multi_layout.setContentsMargins(20, 20, 20, 20)
        multi_layout.addStretch()

        title3 = self._make_label("已选择多个步骤", "empty_title")
        sub3 = self._make_label("请单选某个步骤以编辑其属性。", "empty_subtitle")
        title3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub3.setAlignment(Qt.AlignmentFlag.AlignCenter)

        multi_layout.addWidget(title3)
        multi_layout.addWidget(sub3)
        multi_layout.addStretch()
        self.editor_stack.addWidget(self.page_multi)

    # ---------------- icon ----------------
    def _draw_app_icon_pixmap(self, size: int) -> QPixmap:
        """
        根据指定尺寸动态绘制应用图标位图。

        参数：
        - size: 目标图标尺寸。

        返回值：
        - 对应尺寸的 QPixmap。
        """
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        scale = size / 128.0

        def s(v: float) -> float:
            return v * scale

        # 深色模式下小图标容易不清晰，
        # 这里通过更亮的外描边与渐变底提升任务栏与标题栏中的辨识度。
        outer = QPainterPath()
        outer.addRoundedRect(s(10), s(10), s(108), s(108), s(26), s(26))

        outer_grad = QLinearGradient(s(10), s(10), s(118), s(118))
        outer_grad.setColorAt(0.0, QColor(96, 165, 250, 235))
        outer_grad.setColorAt(1.0, QColor(37, 99, 235, 245))
        p.fillPath(outer, outer_grad)

        p.setPen(QPen(QColor(255, 255, 255, 150), max(1.2, s(2))))
        p.drawPath(outer)

        panel = QPainterPath()
        panel.addRoundedRect(s(24), s(24), s(80), s(80), s(18), s(18))
        p.fillPath(panel, QColor("#F8FAFC"))

        p.setPen(QPen(QColor("#D6E4FF"), max(1.0, s(1.6))))
        p.drawPath(panel)

        p.fillRect(int(s(34)), int(s(34)), int(s(60)), int(s(10)), QColor("#DBEAFE"))

        block_size = int(max(6, s(12)))
        positions = [
            (36, 52), (56, 52), (76, 52),
            (36, 70), (56, 70), (76, 70),
        ]
        colors = ["#60A5FA", "#93C5FD", "#BFDBFE", "#A78BFA", "#C4B5FD", "#DDD6FE"]

        for (x, y), c in zip(positions, colors):
            p.fillRect(int(s(x)), int(s(y)), block_size, block_size, QColor(c))

        p.setBrush(QColor("#10B981"))
        p.setPen(Qt.PenStyle.NoPen)
        arrow = QPolygonF([
            QPointF(s(56), s(92)),
            QPointF(s(56), s(104)),
            QPointF(s(70), s(98)),
        ])
        p.drawPolygon(arrow)

        if size <= 32:
            # 小尺寸场景下额外加一个高光点，
            # 避免任务栏与标题栏中的图标细节丢失过多。
            p.setBrush(QColor(255, 255, 255, 220))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(s(84), s(26), s(8), s(8)))

        p.end()
        return pix

    def _create_app_icon(self) -> QIcon:
        """
        生成多尺寸应用图标。

        返回值：
        - QIcon 对象，内部包含多组尺寸位图，
          以适配任务栏、标题栏与桌面快捷方式等不同场景。
        """
        icon = QIcon()

        for size in [16, 20, 24, 32, 40, 48, 64, 128, 256]:
            icon.addPixmap(self._draw_app_icon_pixmap(size))

        return icon

    def _create_small_icon(self, kind: str) -> QIcon:
        """
        生成顶部工具按钮使用的小图标。

        参数：
        - kind: 图标类型，可选值为 save / run / export。

        返回值：
        - 对应类型的 QIcon 对象。

        说明：
        - 这里采用代码动态绘制而不是依赖外部图标文件，
          便于发布版直接打包，同时保证不同主题下的视觉一致性。
        """
        size = 18
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if kind == "save":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#A78BFA"))
            p.drawRoundedRect(2, 2, 14, 14, 3, 3)
            p.setBrush(QColor("#EDE9FE"))
            p.drawRect(5, 4, 8, 4)
            p.setBrush(QColor("#7C3AED"))
            p.drawRect(6, 10, 6, 4)

        elif kind == "run":
            grad = QLinearGradient(1, 1, 17, 17)
            grad.setColorAt(0.0, QColor("#4ADE80"))
            grad.setColorAt(1.0, QColor("#059669"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(1, 1, 16, 16)

            p.setBrush(QColor("#F0FDF4"))
            tri = QPolygonF([QPoint(7, 5), QPoint(7, 13), QPoint(13, 9)])
            p.drawPolygon(tri)

        elif kind == "export":
            p.translate(9, 9)
            p.rotate(-28)
            p.translate(-9, -9)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F43F5E"))
            p.drawRoundedRect(6, 3, 6, 11, 3, 3)

            p.setBrush(QColor("#60A5FA"))
            p.drawEllipse(7, 5, 4, 4)

            p.setBrush(QColor("#FBBF24"))
            p.drawPolygon(QPolygonF([QPoint(8, 14), QPoint(10, 14), QPoint(9, 17)]))

            p.setBrush(QColor("#A78BFA"))
            p.drawPolygon(QPolygonF([QPoint(5, 10), QPoint(6, 8), QPoint(6, 12)]))
            p.drawPolygon(QPolygonF([QPoint(13, 10), QPoint(12, 8), QPoint(12, 12)]))

        p.end()
        return QIcon(pix)

    # ---------------- utils ----------------
    def _make_label(self, text: str, role: str) -> QLabel:
        """
        创建带 role 属性的标签组件。

        参数：
        - text: 标签文本；
        - role: 用于匹配 QSS 的语义角色名。

        返回值：
        - 已设置 role 属性的 QLabel。
        """
        lab = QLabel(text)
        lab.setProperty("role", role)
        return lab

    def _apply_theme(self) -> None:
        """
        应用当前主题样式到整个主窗口。

        说明：
        - 所有界面配色统一由 ThemeManager 管理；
        - 主题切换时直接整体替换样式表，避免局部控件状态不一致。
        """
        self.setStyleSheet(ThemeManager.DARK if self.is_dark_theme else ThemeManager.LIGHT)

    def _toggle_theme(self) -> None:
        """
        切换深浅主题。

        流程：
        1. 翻转当前主题标记；
        2. 更新侧边栏主题按钮文案；
        3. 重新应用样式表。
        """
        self.is_dark_theme = not self.is_dark_theme
        self._update_theme_btn_text()
        self._apply_theme()

    def _update_theme_btn_text(self) -> None:
        """
        根据当前主题状态更新切换按钮文本。
        """
        if self.is_dark_theme:
            self.btn_theme_toggle.setText("☀️ 开启纯净模式")
        else:
            self.btn_theme_toggle.setText("🌙 切换深色视界")

    def _info(self, title: str, text: str) -> None:
        """
        显示信息提示弹窗。

        参数：
        - title: 弹窗标题；
        - text: 弹窗内容。
        """
        dlg = FancyDialog(self, title, text, primary_text="知道了", is_dark=self.is_dark_theme)
        dlg.exec()

    def _error(self, title: str, text: str) -> None:
        """
        显示错误提示弹窗。

        参数：
        - title: 弹窗标题；
        - text: 弹窗内容。
        """
        dlg = FancyDialog(self, title, text, primary_text="关闭", is_dark=self.is_dark_theme)
        dlg.exec()

    def _confirm(self, title: str, text: str, ok_text: str = "确定") -> bool:
        """
        显示确认弹窗并返回用户选择结果。

        参数：
        - title: 弹窗标题；
        - text: 弹窗内容；
        - ok_text: 确认按钮文本。

        返回值：
        - True 表示用户确认；
        - False 表示用户取消。
        """
        dlg = FancyDialog(
            self,
            title,
            text,
            primary_text=ok_text,
            secondary_text="取消",
            is_dark=self.is_dark_theme,
        )
        dlg.exec()
        return dlg.result_value

    def _log(self, text: str) -> None:
        """
        向日志抽屉追加一条日志，同时更新底部状态文字。

        参数：
        - text: 待写入的日志文本。

        说明：
        - 日志和状态栏共用同一份短文本，有助于让用户同时看到“详细过程”和“当前状态”。
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{now}] {text}")
        self.status_label.setText(f"状态：{text}")

    def _create_progress_dialog(self, title: str, text: str) -> None:
        """
        创建并显示无取消按钮的进度对话框。

        参数：
        - title: 弹窗标题；
        - text: 弹窗正文。

        说明：
        - 导出与打包属于较长耗时操作；
        - 这里使用忙碌型进度框，主要目的是给用户明确反馈“当前仍在执行中”。
        """
        self.progress_dialog = QProgressDialog(text, "", 0, 0, self)
        self.progress_dialog.setWindowTitle(title)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.show()

    def _toggle_log_drawer(self) -> None:
        """
        展开或收起底部日志抽屉。

        说明：
        - 通过读取 splitter 当前尺寸判断抽屉是否关闭；
        - 展开时为日志区预留固定高度，收起时将其高度归零。
        """
        sizes = self.main_splitter.sizes()
        if sizes[1] <= 10:
            total = sizes[0] + sizes[1]
            self.main_splitter.setSizes([max(total - 200, 100), 200])
            self.btn_open_log.setText("🔽 隐藏控制台")
        else:
            total = sizes[0] + sizes[1]
            self.main_splitter.setSizes([total, 0])
            self.btn_open_log.setText("📟 调阅控制台")

    def _set_editor_no_steps(self) -> None:
        """
        将右侧编辑区切换到“当前方案没有步骤”状态。

        说明：
        - 在无步骤状态下隐藏保存与删除按钮，
          避免用户对不存在的步骤执行无意义操作。
        """
        self.editor_stack.setCurrentWidget(self.page_no_steps)

        self.btn_apply.hide()
        self.btn_delete_step.hide()

        self.btn_apply.setEnabled(False)
        self.btn_delete_step.setEnabled(False)
        self.btn_delete_step.setText("🗑️ 删除步骤")

    def _set_editor_no_selection(self) -> None:
        """
        将右侧编辑区切换到“未选中任何步骤”状态。

        说明：
        - 当前方案已有步骤，但用户尚未单选目标步骤；
        - 此时同样不应暴露保存与删除当前步骤的操作。
        """
        self.editor_stack.setCurrentWidget(self.page_none)

        self.btn_apply.hide()
        self.btn_delete_step.hide()

        self.btn_apply.setEnabled(False)
        self.btn_delete_step.setEnabled(False)
        self.btn_delete_step.setText("🗑️ 删除步骤")

    def _set_editor_multi_selection(self, count: int) -> None:
        """
        将右侧编辑区切换到“多选步骤”状态。

        参数：
        - count: 当前选中的步骤数量。

        说明：
        - 多选状态下不允许编辑单个步骤属性；
        - 但允许执行批量删除，因此仅保留删除按钮。
        """
        self.editor_stack.setCurrentWidget(self.page_multi)

        self.btn_apply.hide()
        self.btn_delete_step.show()

        self.btn_apply.setEnabled(False)
        self.btn_delete_step.setEnabled(True)
        self.btn_delete_step.setText(f"🗑️ 批量删除 ({count}) 项")

    # ---------------- cache ----------------
    def _get_cache_root(self) -> Path:
        """
        获取试运行与导出相关的缓存目录。

        返回值：
        - `.visual_launcher_cache` 目录路径。

        说明：
        - 缓存统一放在项目根目录下，便于清理与调试；
        - 使用隐藏目录名称，避免干扰普通用户的主文件视图。
        """
        cache_root = self.project_root / ".visual_launcher_cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        return cache_root

    def _plan_signature(self) -> str:
        """
        基于当前方案内容生成签名摘要。

        返回值：
        - 当前方案 JSON 内容对应的 MD5 字符串。

        说明：
        - 这里的签名仅用于本地缓存命名与变更检测，不用于安全校验。
        """
        payload = json.dumps(self.current_plan.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _get_cached_exe_path(self, plan_name: str) -> Path:
        """
        获取当前方案对应的缓存 exe 路径。

        参数：
        - plan_name: 方案名称。

        返回值：
        - 带有方案名与内容签名的缓存 exe 路径。
        """
        safe_name = plan_name.strip() or "unnamed_plan"
        sig = self._plan_signature()
        return self._get_cache_root() / f"{safe_name}_{sig}.exe"

    def _clear_cached_exes_for_plan(self, plan_name: str) -> None:
        """
        清理指定方案名下的所有缓存 exe。

        参数：
        - plan_name: 方案名称。

        说明：
        - 当方案内容发生变化时，旧缓存不再可信；
        - 因此按方案名前缀批量清理可以避免复用失效产物。
        """
        cache_root = self._get_cache_root()
        prefix = f"{(plan_name.strip() or 'unnamed_plan')}_"
        for file in cache_root.glob(f"{prefix}*.exe"):
            try:
                file.unlink()
            except Exception:
                pass

    def _mark_plan_changed(self) -> None:
        """
        标记当前方案已发生变更。

        说明：
        - 当前实现通过清理该方案历史缓存 exe 的方式，
          防止用户继续复用过期的导出结果。
        """
        self._clear_cached_exes_for_plan(self.current_plan.plan_name)

    # ---------------- keyboard ----------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """
        处理主窗口键盘事件。

        当前支持：
        - 当步骤列表拥有焦点时，按 Delete 键删除选中步骤。
        """
        if event.key() == Qt.Key.Key_Delete and self.flow_list.hasFocus():
            self._on_delete_step()
            return
        super().keyPressEvent(event)

    # ---------------- plan ----------------
    def _on_plan_name_changed(self, text: str) -> None:
        """
        在方案名称输入变化时同步更新当前方案对象。

        参数：
        - text: 输入框中的最新文本。
        """
        self.current_plan.plan_name = text
        self._mark_plan_changed()

    def _on_new_plan(self) -> None:
        """
        新建空白方案并重置编辑状态。
        """
        self.current_plan = Plan(plan_name="未命名方案")
        self.current_plan_path = None
        self.plan_name_edit.setText(self.current_plan.plan_name)
        self._refresh_flow_list()
        self.flow_list.clearSelection()
        self._set_editor_no_steps()
        self._log("已新建空白方案。")

    def _on_save_plan(self) -> None:
        """
        保存当前方案到本地方案目录。

        保存流程：
        1. 校验方案名是否为空；
        2. 基于方案名生成目标 JSON 文件路径；
        3. 执行结构校验；
        4. 保存成功后刷新历史方案列表。
        """
        name = self.current_plan.plan_name.strip()
        if not name:
            self._error("无法保存", "方案名称不能为空。")
            return

        plans_dir = self.plan_service.get_plans_dir()
        file_path = plans_dir / f"{name}.json"

        try:
            errors = validate_plan_dict(self.current_plan.to_dict())
            if errors:
                self._error("方案校验失败", "\n".join(errors))
                return

            self.plan_service.save_plan(self.current_plan, file_path)
            self.current_plan_path = file_path
            self._load_history_plans()
            self._log(f"方案已保存至: {file_path}")
            self._info("保存成功", "方案已成功保存。")
        except Exception as e:
            self._error("保存失败", str(e))

    def _load_history_plans(self) -> None:
        """
        重新加载左侧历史方案列表。
        """
        self.history_list.clear()
        plans_dir = self.plan_service.get_plans_dir()
        for f in sorted(plans_dir.glob("*.json")):
            item = QListWidgetItem(f"📄 {f.stem}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self.history_list.addItem(item)

    def _load_history_plan_item(self, item: QListWidgetItem) -> None:
        """
        根据历史方案列表项载入对应方案。

        参数：
        - item: 被双击的列表项。
        """
        file_path = item.data(Qt.ItemDataRole.UserRole)
        try:
            from shared.utils import read_json
            from shared.models import plan_from_dict

            data = read_json(file_path)
            self.current_plan = plan_from_dict(data)
            self.current_plan_path = file_path
            self.plan_name_edit.setText(self.current_plan.plan_name)
            self._refresh_flow_list()
            self.flow_list.clearSelection()

            if not self.current_plan.steps:
                self._set_editor_no_steps()
            else:
                self._set_editor_no_selection()

            self._log(f"成功载入方案: {file_path.name}")
        except Exception as e:
            self._error("载入失败", f"载入方案失败：{str(e)}")

    # ---------------- add step ----------------
    def _on_add_app_step(self) -> None:
        """
        通过文件选择框添加一个应用步骤。

        说明：
        - 当前支持 exe / bat / lnk 三类常见启动入口；
        - 选择成功后会立即将步骤加入当前方案并刷新界面。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择应用程序",
            "",
            "Applications (*.exe *.bat *.lnk)"
        )
        if not file_path:
            return

        new_step = self.plan_service.create_app_step(Path(file_path).stem, file_path)
        self.current_plan.steps.append(new_step)
        self._refresh_flow_list()
        self._mark_plan_changed()
        self._set_editor_no_selection()

    def _on_add_template_step(self, step_type: str) -> None:
        """
        根据模板类型添加一个非应用步骤。

        参数：
        - step_type: 模板类型，可选值为 url / command / wait。
        """
        template = next((t for t in self.templates if t.get("type") == step_type), None)
        if not template:
            template = {"type": step_type, "name": f"新{step_type}"}

        new_step = self.plan_service.create_step_from_template(template)
        self.current_plan.steps.append(new_step)
        self._refresh_flow_list()
        self._mark_plan_changed()
        self._set_editor_no_selection()

    # ---------------- flow ----------------
    def _refresh_flow_list(self) -> None:
        """
        根据当前方案重新渲染左侧步骤列表。
        """
        self.flow_list.clear()

        for step in self.current_plan.steps:
            icon = (
                "📱" if step.type == "app"
                else "🌐" if step.type == "url"
                else "⌨️" if step.type == "command"
                else "⏳"
            )
            self.flow_list.addItem(QListWidgetItem(f"{icon}  {step.name}"))

        self._log(f"刷新流布局，当前步骤数：{len(self.current_plan.steps)}")

    def _on_flow_selection_changed(self) -> None:
        """
        处理步骤列表的选中状态变化。

        逻辑分支：
        - 当前方案无步骤：显示“无步骤”占位页；
        - 未选中任何项：显示“未选中”占位页；
        - 单选：进入具体步骤属性编辑页；
        - 多选：进入批量删除状态。
        """
        if not self.current_plan.steps:
            self._set_editor_no_steps()
            return

        selected_items = self.flow_list.selectedItems()
        count = len(selected_items)

        if count == 0:
            self._set_editor_no_selection()
        elif count == 1:
            self.btn_apply.setEnabled(True)
            self.btn_delete_step.setEnabled(True)
            self.btn_delete_step.setText("🗑️ 删除此步骤")
            idx = self.flow_list.row(selected_items[0])
            self._on_step_selected(idx)
        else:
            self._set_editor_multi_selection(count)

    def _on_step_selected(self, index: int) -> None:
        """
        根据索引加载单个步骤到右侧编辑器。

        参数：
        - index: 当前步骤在方案列表中的索引。
        """
        if index < 0 or index >= len(self.current_plan.steps):
            if not self.current_plan.steps:
                self._set_editor_no_steps()
            else:
                self._set_editor_no_selection()
            return

        self.btn_apply.show()
        self.btn_delete_step.show()

        self.btn_apply.setEnabled(True)
        self.btn_delete_step.setEnabled(True)
        self.btn_delete_step.setText("🗑️ 删除此步骤")

        step = self.current_plan.steps[index]

        if isinstance(step, AppStep):
            self.editor_stack.setCurrentWidget(self.page_app)
            self.app_name_in.setText(step.name)
            self.app_path_in.setText(step.path)
            self.app_args_in.setText(" ".join(step.args))
            self.app_delay_in.setValue(step.delay_after)

        elif isinstance(step, UrlStep):
            self.editor_stack.setCurrentWidget(self.page_url)
            self.url_name_in.setText(step.name)
            self.url_in.setText(step.url)
            self.url_delay_in.setValue(step.delay_after)

        elif isinstance(step, CommandStep):
            self.editor_stack.setCurrentWidget(self.page_cmd)
            self.cmd_name_in.setText(step.name)
            self.cmd_in.setText(step.command)
            self.cmd_shell_in.setCurrentText(step.shell)
            self.cmd_delay_in.setValue(step.delay_after)

        elif isinstance(step, WaitStep):
            self.editor_stack.setCurrentWidget(self.page_wait)
            self.wait_name_in.setText(step.name)
            self.wait_seconds_in.setValue(step.seconds)

    def _apply_step_changes(self) -> None:
        """
        将右侧编辑器中的改动写回当前选中步骤。
        """
        idx = self.flow_list.currentRow()
        if idx < 0 or idx >= len(self.current_plan.steps):
            return

        step = self.current_plan.steps[idx]

        if isinstance(step, AppStep):
            step.name = self.app_name_in.text().strip()
            step.path = self.app_path_in.text().strip()
            step.args = self.app_args_in.toPlainText().split()
            step.delay_after = self.app_delay_in.value()

        elif isinstance(step, UrlStep):
            step.name = self.url_name_in.text().strip()
            step.url = self.url_in.text().strip()
            step.delay_after = self.url_delay_in.value()

        elif isinstance(step, CommandStep):
            step.name = self.cmd_name_in.text().strip()
            step.command = self.cmd_in.toPlainText().strip()
            step.shell = self.cmd_shell_in.currentText()
            step.delay_after = self.cmd_delay_in.value()

        elif isinstance(step, WaitStep):
            step.name = self.wait_name_in.text().strip()
            step.seconds = self.wait_seconds_in.value()

        self._refresh_flow_list()
        self.flow_list.setCurrentRow(idx)
        self._log(f"已更新步骤: {step.name}")
        self._mark_plan_changed()

    def _on_delete_step(self) -> None:
        """
        删除当前选中的一个或多个步骤。
        """
        selected_items = self.flow_list.selectedItems()
        if not selected_items:
            return

        if not self._confirm("确认删除", f"确定删除已选中的 {len(selected_items)} 个步骤吗？", "删除"):
            return

        rows = sorted([self.flow_list.row(item) for item in selected_items], reverse=True)
        for row in rows:
            if 0 <= row < len(self.current_plan.steps):
                del self.current_plan.steps[row]

        self._refresh_flow_list()
        self.flow_list.clearSelection()
        self._mark_plan_changed()

        if not self.current_plan.steps:
            self._set_editor_no_steps()
        else:
            self._set_editor_no_selection()

    # ---------------- run / export ----------------
    def _on_trial_run(self) -> None:
        """
        直接试运行当前方案。

        说明：
        - 试运行会真实执行应用、网址和命令步骤；
        - 为避免用户误触，这里先弹确认框；
        - 运行日志会自动展开到底部日志抽屉。
        """
        if not self.current_plan.steps:
            self._error("无法试运行", "当前没有任何步骤。")
            return

        if not self._confirm(
                "确认试运行",
                "试运行会真实打开应用、网址和命令窗口。\n确定继续吗？",
                "开始试运行",
        ):
            return

        sizes = self.main_splitter.sizes()
        if sizes[1] <= 10:
            total = sizes[0] + sizes[1]
            self.main_splitter.setSizes([max(total - 250, 100), 250])
            self.btn_open_log.setText("🔽 隐藏控制台")

        self.btn_trial_run.setEnabled(False)
        self._log("开始直接试运行当前方案...")

        self.trial_run_worker = TrialRunWorker(self.current_plan)
        self.trial_run_worker.progress.connect(self._log)
        self.trial_run_worker.success.connect(self._on_trial_run_success)
        self.trial_run_worker.failed.connect(self._on_trial_run_failed)
        self.trial_run_worker.start()

    def _on_trial_run_success(self) -> None:
        """
        试运行成功后的收尾处理。
        """
        self.btn_trial_run.setEnabled(True)
        self._log("试运行完成。")

    def _on_trial_run_failed(self, error_msg: str) -> None:
        """
        试运行失败后的错误提示处理。

        参数：
        - error_msg: 后台线程返回的错误文本。
        """
        self.btn_trial_run.setEnabled(True)
        self._log(f"试运行失败: {error_msg}")
        self._error("试运行失败", error_msg)

    def _on_export_exe(self) -> None:
        """
        将当前方案导出为独立 exe。

        说明：
        - 发布版编辑器默认不内置打包环境；
        - 只有开发版环境才允许执行完整导出。
        """
        if not self.current_plan.steps:
            self._error("无法导出", "当前没有任何步骤。")
            return

        if getattr(sys, "frozen", False):
            self._error(
                "当前版本不支持导出",
                "发布版编辑器不内置打包环境。\n\n请使用开发版运行项目后再导出 EXE。"
            )
            return

        target_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "导出单文件 EXE",
            f"{self.current_plan.plan_name}.exe",
            "Executable Files (*.exe)"
        )
        if not target_path_str:
            return

        target_path = Path(target_path_str)

        self._create_progress_dialog("正在导出", "正在封装独立 EXE，请稍候...")

        self.build_worker = BuildWorker(self.current_plan, target_path)
        self.build_worker.progress.connect(self._log)
        self.build_worker.success.connect(self._on_full_export_success)
        self.build_worker.failed.connect(self._on_full_export_failed)
        self.build_worker.start()

    def _on_full_export_success(self, path: str) -> None:
        """
        导出成功后的界面反馈处理。

        参数：
        - path: 导出的 exe 路径。
        """
        if self.progress_dialog:
            self.progress_dialog.close()
        self._log(f"导出成功！路径: {path}")
        self._info("导出成功", "方案已封装并导出成功。")

    def _on_full_export_failed(self, err: str) -> None:
        """
        导出失败后的界面反馈处理。

        参数：
        - err: 错误信息文本。
        """
        if self.progress_dialog:
            self.progress_dialog.close()
        self._log(f"导出失败: {err}")
        self._error("导出失败", err)