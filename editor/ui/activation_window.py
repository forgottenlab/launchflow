"""
activation_window.py

离线激活窗口模块。

该模块负责在程序启动阶段展示机器码与申请码，
并提供授权文件导入、授权状态校验以及进入主工作台的入口。

适用场景：
- 当前设备尚未激活；
- 本地授权无效或已过期；
- 用户需要重新导入 license 文件。

相关模块：
- licensing.activation_service
- licensing.license_manager
- editor.main

说明：
- 当前主流程以“复制申请码 -> 作者签发 .lic -> 用户导入授权文件”为核心；
- 机器码保留展示，用于人工核对和排障，但不作为主交互按钮暴露。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QRectF, QPointF
from PySide6.QtGui import (
    QGuiApplication,
    QColor,
    QPainter,
    QPainterPath,
    QPixmap,
    QLinearGradient,
    QPolygonF,
    QPen,
    QIcon,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from licensing.activation_service import ActivationService
from licensing.license_manager import LicenseManager, LicenseCheckResult
from shared.app_icon import apply_window_icon, load_app_icon


class WindowControlButton(QPushButton):
    """
    自绘窗口控制按钮。

    当前用于激活窗口标题栏中的最小化与关闭按钮，
    以便与主工作台保持一致的视觉风格。
    """

    def __init__(self, kind: str, parent=None):
        """
        初始化按钮。

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
        绘制窗口控制按钮图标与 hover 状态。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        if self.underMouse():
            if self.kind == "close":
                painter.fillRect(rect, QColor("#DC2626"))
            else:
                painter.fillRect(rect, QColor(255, 255, 255, 20))

        color = QColor("#FFFFFF") if self.kind == "close" and self.underMouse() else QColor("#E2E8F0")
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


class ActivationTitleBar(QFrame):
    """
    激活窗口自定义标题栏。

    负责：
    - 展示统一图标与标题；
    - 提供最小化与关闭按钮；
    - 支持拖动无边框窗口。
    """

    def __init__(self, parent_window: "ActivationWindow") -> None:
        """
        初始化标题栏。

        参数：
        - parent_window: 所属激活窗口实例。
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
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("Launch Flow 激活")
        self.title_label.setStyleSheet(
            "font-weight: 600; font-size: 13px; color: #FFFFFF; background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.btn_min = WindowControlButton("min", self)
        self.btn_close = WindowControlButton("close", self)

        self.btn_min.clicked.connect(parent_window.showMinimized)
        self.btn_close.clicked.connect(parent_window.close)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_close)

    def set_icon(self, icon: QIcon) -> None:
        """
        设置标题栏图标。
        """
        self.icon_label.setPixmap(icon.pixmap(16, 16))

    def mousePressEvent(self, event) -> None:
        """
        记录拖动起点，用于支持无边框窗口拖动。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        """
        根据鼠标移动位置拖动窗口。
        """
        if self.drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)


class ActivationWindow(QDialog):
    """
    离线激活窗口。

    该窗口是发布版程序的授权入口，主要负责：
    - 展示机器码与申请码；
    - 接收用户导入或拖入的授权文件；
    - 实时刷新授权状态；
    - 在授权有效后允许进入主工作台。
    """

    def __init__(self, project_root: Path, parent: Optional[QWidget] = None) -> None:
        """
        初始化激活窗口。

        参数：
        - project_root: 项目根目录或发布版 exe 所在目录；
        - parent: 可选父窗口。
        """
        super().__init__(parent)
        self.project_root = project_root
        self.activation_service = ActivationService(project_root)
        self.license_manager = LicenseManager(project_root)
        self.activation_success = False
        self.drag_pos: Optional[QPoint] = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumSize(760, 560)
        self.setModal(True)
        self.setAcceptDrops(True)

        self.app_icon = apply_window_icon(self, project_root)

        self._build_ui()
        self._load_request_info()
        self._refresh_license_status()

    def dragEnterEvent(self, event) -> None:
        """
        处理拖拽进入事件。

        仅接受 .lic 与 .json 类型文件，
        避免误拖其他无关文件触发激活流程。
        """
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if urls:
                file_path = urls[0].toLocalFile()
                if file_path.lower().endswith((".lic", ".json")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        """
        处理拖拽释放事件，并尝试导入授权文件。
        """
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        urls = mime.urls()
        if not urls:
            event.ignore()
            return

        file_path = urls[0].toLocalFile()
        if not file_path:
            event.ignore()
            return

        self._import_license_from_path(Path(file_path))
        event.acceptProposedAction()

    def _import_license_from_path(self, file_path: Path) -> None:
        """
        从指定路径导入授权文件并立即校验。

        参数：
        - file_path: 授权文件路径。

        说明：
        - 导入成功不代表授权一定有效；
        - 仍需继续通过签名、机器码与过期时间校验。
        """
        try:
            self.activation_service.import_license_file(file_path)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"授权文件导入失败：\n{e}")
            return

        result = self.license_manager.validate_current_license()
        if result.is_valid:
            self.activation_success = True
            self._refresh_license_status()
            QMessageBox.information(self, "激活成功", "授权文件校验通过，现在可以进入工作台。")
        else:
            QMessageBox.critical(self, "激活失败", f"授权校验未通过：\n{result.message}")
            self._refresh_license_status()

    def _create_app_icon(self) -> QIcon:
        """Return the same packaged ICO used by QApplication and the editor window."""
        return load_app_icon(self.project_root)

    def _build_ui(self) -> None:
        """
        构建激活窗口界面。

        界面结构分为：
        - 标题栏；
        - 授权状态卡片；
        - 机器码 / 申请码展示区域；
        - 授权文件导入区域；
        - 底部操作按钮区域。
        """
        self.setStyleSheet("""
        QDialog {
            background: #0F172A;
            color: #F8FAFC;
        }

        QFrame#WindowRoot {
            background: #0F172A;
            border: 1px solid #243145;
        }

        QFrame#TitleBar {
            background: #0F172A;
            border: none;
            border-bottom: 1px solid #243145;
        }

        QFrame#Card {
            background: #172033;
            border: 1px solid #334155;
            border-radius: 14px;
        }

        QLabel[role="title"] {
            font-size: 26px;
            font-weight: 800;
            color: #FFFFFF;
            background: transparent;
        }

        QLabel[role="subtitle"] {
            font-size: 13px;
            color: #94A3B8;
            background: transparent;
        }

        QLabel[role="section"] {
            font-size: 13px;
            font-weight: 700;
            color: #E2E8F0;
            background: transparent;
        }

        QLabel[role="status_ok"] {
            font-size: 13px;
            font-weight: 700;
            color: #22C55E;
            background: transparent;
        }

        QLabel[role="status_bad"] {
            font-size: 13px;
            font-weight: 700;
            color: #F87171;
            background: transparent;
        }

        QTextEdit {
            background: #0B1220;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 10px;
            color: #F8FAFC;
            font-size: 13px;
        }

        QPushButton {
            min-height: 42px;
            border-radius: 10px;
            padding: 0 16px;
            font-weight: 700;
            font-size: 13px;
            border: none;
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

        QPushButton#GhostBtn {
            background: transparent;
            color: #CBD5E1;
            border: 1px solid #475569;
        }

        QPushButton#GhostBtn:hover {
            background: rgba(255,255,255,0.05);
        }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.window_root = QFrame()
        self.window_root.setObjectName("WindowRoot")
        outer.addWidget(self.window_root)

        root = QVBoxLayout(self.window_root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = ActivationTitleBar(self)
        self.title_bar.set_icon(self.app_icon)
        root.addWidget(self.title_bar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.setSpacing(18)
        root.addWidget(content, 1)

        title = QLabel("Launch Flow 离线激活")
        title.setProperty("role", "title")
        subtitle = QLabel("当前版本需要授权后才能进入工作台。请复制申请码发送给作者，获取专属 license 文件后导入。")
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)

        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)

        status_card = QFrame()
        status_card.setObjectName("Card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(10)

        status_title = QLabel("授权状态")
        status_title.setProperty("role", "section")

        self.status_label = QLabel("正在检查授权...")
        self.status_label.setProperty("role", "status_bad")
        self.status_detail_label = QLabel("")
        self.status_detail_label.setProperty("role", "subtitle")
        self.status_detail_label.setWordWrap(True)

        status_layout.addWidget(status_title)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.status_detail_label)

        content_layout.addWidget(status_card)

        info_card = QFrame()
        info_card.setObjectName("Card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setSpacing(14)

        machine_title = QLabel("当前机器码")
        machine_title.setProperty("role", "section")
        self.machine_id_edit = QTextEdit()
        self.machine_id_edit.setReadOnly(True)
        self.machine_id_edit.setFixedHeight(72)

        request_title = QLabel("申请码")
        request_title.setProperty("role", "section")
        self.request_code_edit = QTextEdit()
        self.request_code_edit.setReadOnly(True)
        self.request_code_edit.setFixedHeight(120)

        info_layout.addWidget(machine_title)
        info_layout.addWidget(self.machine_id_edit)
        info_layout.addWidget(request_title)
        info_layout.addWidget(self.request_code_edit)

        request_btn_row = QHBoxLayout()
        request_btn_row.setSpacing(10)

        self.btn_copy_request_code = QPushButton("复制申请码")
        self.btn_copy_request_code.setObjectName("PrimaryBtn")
        self.btn_copy_request_code.clicked.connect(self._copy_request_code)

        request_btn_row.addWidget(self.btn_copy_request_code)
        request_btn_row.addStretch()

        info_layout.addLayout(request_btn_row)
        content_layout.addWidget(info_card)

        import_card = QFrame()
        import_card.setObjectName("Card")
        import_layout = QVBoxLayout(import_card)
        import_layout.setContentsMargins(18, 18, 18, 18)
        import_layout.setSpacing(12)

        import_title = QLabel("导入授权文件")
        import_title.setProperty("role", "section")

        import_hint = QLabel("请拖拽或选择作者发给你的 .lic 授权文件。导入成功后即可进入软件。")
        import_hint.setProperty("role", "subtitle")
        import_hint.setWordWrap(True)

        import_layout.addWidget(import_title)
        import_layout.addWidget(import_hint)

        import_btn_row = QHBoxLayout()
        import_btn_row.setSpacing(10)

        self.btn_import_license = QPushButton("导入 license 文件")
        self.btn_import_license.setObjectName("PrimaryBtn")
        self.btn_import_license.clicked.connect(self._import_license_file)

        self.btn_recheck = QPushButton("重新检查授权")
        self.btn_recheck.setObjectName("SecondaryBtn")
        self.btn_recheck.clicked.connect(self._refresh_license_status)

        import_btn_row.addWidget(self.btn_import_license)
        import_btn_row.addWidget(self.btn_recheck)
        import_btn_row.addStretch()

        import_layout.addLayout(import_btn_row)
        content_layout.addWidget(import_card)

        content_layout.addStretch()

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        self.btn_enter = QPushButton("进入工作台")
        self.btn_enter.setObjectName("PrimaryBtn")
        self.btn_enter.setEnabled(False)
        self.btn_enter.clicked.connect(self._enter_main_window)

        self.btn_close = QPushButton("退出")
        self.btn_close.setObjectName("GhostBtn")
        self.btn_close.clicked.connect(self.reject)

        bottom_row.addStretch()
        bottom_row.addWidget(self.btn_close)
        bottom_row.addWidget(self.btn_enter)

        content_layout.addLayout(bottom_row)

    def _load_request_info(self) -> None:
        """
        将当前机器码与申请码加载到界面中。
        """
        machine_id = self.activation_service.get_display_machine_id()
        request_code = self.activation_service.generate_request_code()

        self.machine_id_edit.setPlainText(machine_id)
        self.request_code_edit.setPlainText(request_code)

    def _refresh_license_status(self) -> None:
        """
        刷新界面中的授权状态显示。

        根据校验结果动态更新：
        - 状态文字；
        - 状态详情；
        - “进入工作台”按钮是否可用。
        """
        result = self.license_manager.validate_current_license()

        if result.is_valid:
            self.status_label.setProperty("role", "status_ok")
            self.status_label.setText("授权有效，可进入工作台")
            self.btn_enter.setEnabled(True)

            license_data = result.license_data or {}
            tester_name = str(license_data.get("customer") or license_data.get("tester_name", "未知用户"))
            license_id = str(license_data.get("license_id", "未知编号"))
            expire_at = str(license_data.get("expires_at") or license_data.get("expire_at", "未知时间"))
            self.status_detail_label.setText(
                f"测试用户：{tester_name}\n授权编号：{license_id}\n到期时间：{expire_at}"
            )
        else:
            self.status_label.setProperty("role", "status_bad")
            self.status_label.setText("当前尚未激活或授权无效")
            self.btn_enter.setEnabled(False)
            self.status_detail_label.setText(result.message)

        # 这里显式刷新动态属性样式，
        # 否则切换授权状态后，QSS 中依赖 role 的配色不会立即生效。
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _copy_request_code(self) -> None:
        """
        将申请码复制到系统剪贴板。
        """
        text = self.request_code_edit.toPlainText().strip()
        if text:
            QGuiApplication.clipboard().setText(text)
            QMessageBox.information(self, "复制成功", "申请码已复制到剪贴板。")

    def _import_license_file(self) -> None:
        """
        通过文件选择框导入授权文件。
        """
        file_path_str, _ = QFileDialog.getOpenFileName(
            self,
            "选择授权文件",
            "",
            "License Files (*.lic *.json)"
        )
        if not file_path_str:
            return

        self._import_license_from_path(Path(file_path_str))

    def _enter_main_window(self) -> None:
        """
        在进入主工作台前再次校验当前授权。

        设计原因：
        - 防止界面状态过期；
        - 避免在授权失效或被替换后仍错误进入主窗口。
        """
        result: LicenseCheckResult = self.license_manager.validate_current_license()
        if not result.is_valid:
            QMessageBox.critical(self, "无法进入", f"当前授权无效：\n{result.message}")
            self._refresh_license_status()
            return

        self.activation_success = True
        self.accept()
