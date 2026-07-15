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
- 发布版中试运行直接执行当前方案，导出功能依赖本机可用的 PyInstaller 构建器；
- 部分路径与缓存逻辑依赖 project_root，必须保证入口层正确传入。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from runtime.launcher_runtime import RuntimeExecutor

from PySide6.QtCore import (
    Qt,
    QByteArray,
    QMimeData,
    QThread,
    QTimer,
    Signal,
    QPoint,
    QSize,
    QRect,
    QRectF,
    QPointF,
)
from PySide6.QtGui import (
    QAction,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QColor,
    QPainter,
    QPainterPath,
    QPixmap,
    QLinearGradient,
    QPolygonF,
    QPen,
    QBrush,
    QDrag,
)
from PySide6.QtWidgets import (
    QComboBox,
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QAbstractItemView,
    QAbstractSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shared.models import Plan, AppStep, UrlStep, CommandStep, WaitStep
from shared.plan_schema import validate_plan_dict
from shared.app_logging import get_app_logger
from shared.app_icon import apply_window_icon, load_app_icon
from shared.diagnostics import collect_diagnostics, open_logs_directory
from editor.services.plan_service import PlanService
from editor.ui.log_console import LogConsole, LogKind, infer_log_kind
from tools.build_single_exe import PACKABLE_APP_SUFFIXES, build_single_file_exe


SHORTCUTS = {
    "save": "Ctrl+S",
    "save_as": "Ctrl+Shift+S",
    "trial_run": "Ctrl+R",
    "export": "Ctrl+E",
    "delete": "Delete",
    "move_up": "Alt+Up",
    "move_down": "Alt+Down",
}


def calculate_drop_target(
    mouse_y: int,
    item_rects: list[QRect],
    viewport_height: int,
    edge_zone: int = 20,
) -> int:
    """Return an insertion index from one shared, DPI-independent geometry rule."""

    if not item_rects:
        return 0
    if mouse_y <= edge_zone:
        return 0
    if mouse_y >= max(0, viewport_height - edge_zone):
        return len(item_rects)

    for index, rect in enumerate(item_rects):
        if mouse_y < rect.top() + rect.height() / 2:
            return index
        if mouse_y <= rect.bottom():
            return index + 1
    return len(item_rects)


class PlanSwitchDecision(str, Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


class PlanHistoryList(QListWidget):
    """History list where Enter activates, while arrow keys only move selection."""

    enterPressed = Signal(QListWidgetItem)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.enterPressed.emit(item)
                event.accept()
                return
        super().keyPressEvent(event)


class ElidedLabel(QLabel):
    """Single-line label that keeps the complete status available as a tooltip."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        self._full_text = ""
        super().__init__("", parent)
        self.setText(text)

    @property
    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API name
        self._full_text = text
        self.setToolTip(text)
        self._refresh_elision()

    def _refresh_elision(self) -> None:
        available = max(0, self.contentsRect().width())
        elided = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available,
        )
        super().setText(elided)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._refresh_elision()


class ReorderableStepList(QListWidget):
    """Custom drag feedback that delegates the real model reorder to MainWindow."""

    EDGE_DROP_ZONE = 20
    DRAG_MIME_TYPE = "application/x-launchflow-step-id"
    DRAG_PREVIEW_OPACITY = 0.86
    DRAG_PREVIEW_WIDTH_SCALE = 0.90
    DRAG_PREVIEW_HEIGHT_SCALE = 0.92
    INSERTION_INDICATOR_WIDTH = 4
    INSERTION_INDICATOR_HAS_ARROW = True

    def __init__(
        self,
        prepare_drag: Callable[[], bool],
        reorder: Callable[[int, int], Optional[int]],
        move_selected: Callable[[int], Optional[int]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._prepare_drag = prepare_drag
        self._reorder = reorder
        self._move_selected = move_selected
        self._dragging_step_id: Optional[str] = None
        self._drop_target_index: Optional[int] = None
        self._drag_active = False
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setAutoScroll(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move_selected(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def startDrag(self, supported_actions) -> None:  # type: ignore[no-untyped-def]
        selected = self.selectedItems()
        if len(selected) != 1 or not self._prepare_drag():
            return
        item = selected[0]
        step_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(step_id, str) or not step_id:
            return
        self._dragging_step_id = step_id
        self._drag_active = True
        self.viewport().update()

        drag = QDrag(self)
        mime_data = self.model().mimeData(self.selectedIndexes())
        mime_data.setData(self.DRAG_MIME_TYPE, QByteArray(step_id.encode("utf-8")))
        drag.setMimeData(mime_data)
        preview = self.build_drag_preview(item)
        if not preview.isNull():
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(max(8, preview.width() // 9), preview.height() // 2))

        # Qt InternalMove may delete/recreate the source QListWidgetItem while
        # QDrag.exec() is running. From this point onward only the stable step
        # ID is retained; the Python wrapper must never be touched again.
        selected.clear()
        item = None
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.clear_drag_visual_state()

    def clear_drag_visual_state(self) -> None:
        """Clear drag paint state without dereferencing any list item wrapper."""

        self._drag_active = False
        self._dragging_step_id = None
        self._drop_target_index = None
        self.unsetCursor()
        self.viewport().update()

    def _step_id_from_mime(self, mime_data: QMimeData) -> Optional[str]:
        if not mime_data.hasFormat(self.DRAG_MIME_TYPE):
            return None
        step_id = bytes(mime_data.data(self.DRAG_MIME_TYPE)).decode("utf-8", errors="ignore")
        return step_id or None

    def _row_for_step_id(self, step_id: Optional[str]) -> Optional[int]:
        if not step_id:
            return None
        for index in range(self.count()):
            current = self.item(index)
            if current is not None and current.data(Qt.ItemDataRole.UserRole) == step_id:
                return index
        return None

    def build_drag_preview(self, item: QListWidgetItem) -> QPixmap:
        """Create one compact, translucent card without a second outer frame."""

        rect = self.visualItemRect(item)
        raw = self.viewport().grab(rect)
        if raw.isNull():
            return raw
        target_size = QSize(
            max(1, round(raw.width() * self.DRAG_PREVIEW_WIDTH_SCALE)),
            max(1, round(raw.height() * self.DRAG_PREVIEW_HEIGHT_SCALE)),
        )
        scaled = raw.scaled(
            target_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview = QPixmap(scaled.size())
        preview.fill(Qt.GlobalColor.transparent)
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(preview.rect()), 8, 8)
        painter.setClipPath(clip)
        painter.setOpacity(self.DRAG_PREVIEW_OPACITY)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return preview

    def _item_rects(self) -> list[QRect]:
        return [self.visualItemRect(self.item(index)) for index in range(self.count())]

    def drop_target_at(self, mouse_y: int) -> int:
        return calculate_drop_target(
            mouse_y,
            self._item_rects(),
            self.viewport().height(),
            self.EDGE_DROP_ZONE,
        )

    def final_index_for_drop(self, insertion_index: int) -> Optional[int]:
        source = self._row_for_step_id(self._dragging_step_id)
        if source is None or source < 0 or source >= self.count():
            return None
        final_index = insertion_index - 1 if insertion_index > source else insertion_index
        return max(0, min(final_index, self.count() - 1))

    @property
    def drop_target_label(self) -> str:
        if self._drop_target_index is None:
            return ""
        final_index = self.final_index_for_drop(self._drop_target_index)
        position = (final_index if final_index is not None else self._drop_target_index) + 1
        return f"松开放置到第 {position} 位"

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.source() is self:
            step_id = self._step_id_from_mime(event.mimeData())
            if self._row_for_step_id(step_id) is None:
                event.ignore()
                return
            self._dragging_step_id = step_id
            self._drag_active = True
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.viewport().update()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.source() is not self:
            event.ignore()
            return
        self._drop_target_index = self.drop_target_at(event.position().toPoint().y())
        self._auto_scroll_for_position(event.position().toPoint().y())
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.viewport().update()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.clear_drag_visual_state()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        step_id = self._step_id_from_mime(event.mimeData()) or self._dragging_step_id
        source_index = self._row_for_step_id(step_id)
        insertion_index = self.drop_target_at(event.position().toPoint().y())
        self._dragging_step_id = step_id
        target_index = self.final_index_for_drop(insertion_index)
        if source_index is not None and target_index is not None:
            self._reorder(source_index, target_index)
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.clear_drag_visual_state()
            return
        self.clear_drag_visual_state()
        event.ignore()

    def focusOutEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._drag_active:
            self.clear_drag_visual_state()
        super().focusOutEvent(event)

    def _auto_scroll_for_position(self, mouse_y: int) -> None:
        scrollbar = self.verticalScrollBar()
        amount = max(1, scrollbar.singleStep())
        if mouse_y <= self.EDGE_DROP_ZONE:
            scrollbar.setValue(scrollbar.value() - amount)
        elif mouse_y >= self.viewport().height() - self.EDGE_DROP_ZONE:
            scrollbar.setValue(scrollbar.value() + amount)

    def _insertion_y(self, insertion_index: int) -> int:
        if self.count() == 0:
            return self.viewport().rect().center().y()
        if insertion_index <= 0:
            return self.visualItemRect(self.item(0)).top()
        if insertion_index >= self.count():
            return self.visualItemRect(self.item(self.count() - 1)).bottom() + 1
        return self.visualItemRect(self.item(insertion_index)).top()

    def _indicator_color(self) -> QColor:
        return QColor("#38BDF8" if self.palette().base().color().lightness() < 128 else "#0369A1")

    def _indicator_label_rect(self, insertion_y: int) -> QRectF:
        """Keep the position hint on the right, away from step names on the left."""

        width = 158
        x = max(self.viewport().width() * 0.55, self.viewport().width() - width - 18)
        y = max(2, min(insertion_y - 12, self.viewport().height() - 25))
        return QRectF(x, y, width, 23)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        source_index = self._row_for_step_id(self._dragging_step_id) if self._drag_active else None
        if source_index is not None:
            source_rect = self.visualItemRect(self.item(source_index)).adjusted(3, 3, -3, -3)
            placeholder_pen = QPen(self._indicator_color(), 2, Qt.PenStyle.DashLine)
            placeholder_pen.setColor(QColor(placeholder_pen.color().red(), placeholder_pen.color().green(), placeholder_pen.color().blue(), 175))
            painter.setPen(placeholder_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(source_rect), 7, 7)

        if self._drop_target_index is not None:
            y = self._insertion_y(self._drop_target_index)
            color = self._indicator_color()
            painter.setPen(QPen(color, self.INSERTION_INDICATOR_WIDTH))
            painter.drawLine(12, y, max(12, self.viewport().width() - 12), y)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([
                QPointF(4, y - 7),
                QPointF(4, y + 7),
                QPointF(12, y),
            ]))

            label_rect = self._indicator_label_rect(y)
            painter.setBrush(color)
            painter.drawRoundedRect(label_rect, 5, 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.drop_target_label)
        painter.end()


@dataclass(frozen=True)
class StepCommitResult:
    """Structured result for moving the visible inspector draft into the model."""

    success: bool
    changed: bool = False
    error: str = ""
    step_index: Optional[int] = None
    step_id: Optional[str] = None


@dataclass(frozen=True)
class PlanValidationIssue:
    """A user-facing execution preflight issue tied to one step field."""

    message: str
    step_index: Optional[int] = None
    step_id: Optional[str] = None
    field: str = ""


@dataclass(frozen=True)
class PlanPreparationResult:
    """Committed, validated and immutable-by-convention input for a worker."""

    success: bool
    snapshot: Optional[Plan] = None
    error: str = ""
    step_index: Optional[int] = None
    step_id: Optional[str] = None
    field: str = ""


def validate_plan_for_execution(plan: Plan, action_label: str) -> Optional[PlanValidationIssue]:
    """Return the first enabled-step issue before any external action can start."""

    if not plan.steps:
        return PlanValidationIssue(f"当前没有任何步骤，无法{action_label}。")

    for index, step in enumerate(plan.steps):
        if not step.enabled:
            continue

        number = index + 1
        name = step.name.strip() or f"步骤 {number}"
        prefix = f"步骤 {number}“{name}”"

        if isinstance(step, AppStep):
            if not step.path.strip():
                return PlanValidationIssue(
                    f"{prefix}的应用路径为空，请选择目标文件后再{action_label}。",
                    index,
                    step.id,
                    "path",
                )
        elif isinstance(step, UrlStep):
            if not step.url.strip():
                return PlanValidationIssue(
                    f"{prefix}的网址为空，请输入 URL 后再{action_label}。",
                    index,
                    step.id,
                    "url",
                )
        elif isinstance(step, CommandStep):
            if not step.command.strip():
                return PlanValidationIssue(
                    f"{prefix}的执行命令为空，请输入命令后再{action_label}。",
                    index,
                    step.id,
                    "command",
                )
            if step.shell not in {"cmd", "powershell"}:
                return PlanValidationIssue(
                    f"{prefix}的 Shell 类型无效，请选择 cmd 或 powershell 后再{action_label}。",
                    index,
                    step.id,
                    "shell",
                )
        elif isinstance(step, WaitStep):
            if not isinstance(step.seconds, (int, float)) or not math.isfinite(step.seconds) or step.seconds < 0:
                return PlanValidationIssue(
                    f"{prefix}的等待时间无效，请输入不小于 0 的秒数后再{action_label}。",
                    index,
                    step.id,
                    "seconds",
                )
        else:
            return PlanValidationIssue(
                f"{prefix}的步骤类型无效，无法{action_label}。",
                index,
                getattr(step, "id", None),
                "type",
            )

    return None


@dataclass(frozen=True)
class FieldThemeTokens:
    field_border: str
    field_border_focus: str
    field_background: str
    field_text: str
    field_disabled: str
    subcontrol_background: str
    subcontrol_hover: str
    subcontrol_pressed: str
    separator: str
    arrow_color: str
    popup_background: str


DARK_FIELD_TOKENS = FieldThemeTokens(
    field_border="#475569",
    field_border_focus="#38BDF8",
    field_background="#0B1220",
    field_text="#F8FAFC",
    field_disabled="#0F172A",
    subcontrol_background="#111827",
    subcontrol_hover="#1E293B",
    subcontrol_pressed="#334155",
    separator="#475569",
    arrow_color="#CBD5E1",
    popup_background="#111827",
)

LIGHT_FIELD_TOKENS = FieldThemeTokens(
    field_border="#9CA3AF",
    field_border_focus="#2563EB",
    field_background="#F8FAFC",
    field_text="#111827",
    field_disabled="#F3F4F6",
    subcontrol_background="#F3F4F6",
    subcontrol_hover="#E5E7EB",
    subcontrol_pressed="#D1D5DB",
    separator="#9CA3AF",
    arrow_color="#475569",
    popup_background="#FFFFFF",
)


def _field_control_qss(tokens: FieldThemeTokens) -> str:
    """Build one visible field-border contract for both application themes."""

    return f"""
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox,
    QComboBox, QDoubleSpinBox {{
        background: {tokens.field_background};
        color: {tokens.field_text};
        border: 1px solid {tokens.field_border};
        border-radius: 8px;
    }}

    QLineEdit, QSpinBox, QComboBox, QDoubleSpinBox {{
        min-height: 36px;
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QComboBox:focus, QDoubleSpinBox:focus {{
        border-color: {tokens.field_border_focus};
    }}

    QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled,
    QComboBox:disabled, QDoubleSpinBox:disabled {{
        background: {tokens.field_disabled};
        color: {tokens.field_border};
        border-color: {tokens.field_border};
    }}

    QLineEdit {{
        padding: 0px 10px;
    }}

    QTextEdit, QPlainTextEdit {{
        padding: 7px 10px;
    }}

    QSpinBox {{
        padding: 0px 30px 0px 10px;
    }}

    QComboBox {{
        padding: 0px 34px 0px 10px;
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 30px;
        margin: 0px;
        background: {tokens.subcontrol_background};
        border: none;
        border-left: 1px solid {tokens.separator};
        border-top-right-radius: 7px;
        border-bottom-right-radius: 7px;
    }}

    QComboBox::drop-down:hover {{ background: {tokens.subcontrol_hover}; }}
    QComboBox::drop-down:pressed,
    QComboBox::drop-down:open {{ background: {tokens.subcontrol_pressed}; }}
    QComboBox::drop-down:disabled {{ background: {tokens.field_disabled}; }}
    QComboBox::down-arrow {{ image: none; width: 12px; height: 8px; }}

    QComboBox QAbstractItemView {{
        background: {tokens.popup_background};
        color: {tokens.field_text};
        border: 1px solid {tokens.field_border};
        outline: none;
        padding: 4px;
        selection-color: white;
        selection-background-color: {tokens.field_border_focus};
    }}

    QDoubleSpinBox {{
        padding: 0px 30px 0px 10px;
    }}

    QDoubleSpinBox::up-button,
    QDoubleSpinBox::down-button {{
        subcontrol-origin: padding;
        width: 26px;
        margin: 0px;
        background: {tokens.subcontrol_background};
        border: none;
        border-left: 1px solid {tokens.separator};
    }}

    QDoubleSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 7px;
    }}

    QDoubleSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-top: 1px solid {tokens.separator};
        border-bottom-right-radius: 7px;
    }}

    QDoubleSpinBox::up-button:hover,
    QDoubleSpinBox::down-button:hover {{ background: {tokens.subcontrol_hover}; }}
    QDoubleSpinBox::up-button:pressed,
    QDoubleSpinBox::down-button:pressed {{ background: {tokens.subcontrol_pressed}; }}
    QDoubleSpinBox::up-button:disabled,
    QDoubleSpinBox::down-button:disabled {{ background: {tokens.field_disabled}; }}
    QDoubleSpinBox::up-arrow,
    QDoubleSpinBox::down-arrow {{ image: none; width: 10px; height: 7px; }}
    """


def _widget_arrow_color(widget: QWidget) -> QColor:
    """Return a theme-aware, disabled-safe arrow color."""
    dark_theme = bool(widget.property("darkTheme"))
    tokens = DARK_FIELD_TOKENS if dark_theme else LIGHT_FIELD_TOKENS
    color = QColor(tokens.arrow_color)
    color.setAlpha(235 if widget.isEnabled() else 105)
    return color


class ThemedDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox whose arrows remain visible under Qt style sheets."""

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_widget_arrow_color(self))

        for subcontrol, points_up in (
            (QStyle.SubControl.SC_SpinBoxUp, True),
            (QStyle.SubControl.SC_SpinBoxDown, False),
        ):
            rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox,
                option,
                subcontrol,
                self,
            )
            center = rect.center()
            half_width = max(2.5, min(rect.width(), rect.height()) * 0.2)
            half_height = max(1.8, half_width * 0.65)
            if points_up:
                points = [
                    QPointF(center.x() - half_width, center.y() + half_height / 2),
                    QPointF(center.x() + half_width, center.y() + half_height / 2),
                    QPointF(center.x(), center.y() - half_height),
                ]
            else:
                points = [
                    QPointF(center.x() - half_width, center.y() - half_height / 2),
                    QPointF(center.x() + half_width, center.y() - half_height / 2),
                    QPointF(center.x(), center.y() + half_height),
                ]
            painter.drawPolygon(QPolygonF(points))


class ThemedComboBox(QComboBox):
    """QComboBox with a palette-aware arrow drawn in its real arrow hit area."""

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        center = rect.center()
        half_width = max(3.0, min(rect.width(), rect.height()) * 0.18)
        half_height = max(2.0, half_width * 0.65)
        points = QPolygonF([
            QPointF(center.x() - half_width, center.y() - half_height / 2),
            QPointF(center.x() + half_width, center.y() - half_height / 2),
            QPointF(center.x(), center.y() + half_height),
        ])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_widget_arrow_color(self))
        painter.drawPolygon(points)


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

    QMenuBar#MainMenuBar {
        border-bottom: 1px solid;
        padding: 2px 8px;
    }

    QMenuBar#MainMenuBar::item {
        border-radius: 5px;
        padding: 5px 10px;
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

    QMenuBar#MainMenuBar {
        background: #111827;
        border-color: #243145;
        color: #E2E8F0;
    }

    QMenuBar#MainMenuBar::item:selected,
    QMenuBar#MainMenuBar::item:pressed {
        background: #1E293B;
    }

    QMenu {
        background: #111827;
        border: 1px solid #334155;
        color: #E2E8F0;
    }

    QMenu::item:selected { background: #2563EB; }

    QFrame#Sidebar {
        background: #1E293B;
        border-color: #334155;
    }

    QFrame#TopBar {
        background: #0F172A;
        border-color: #243145;
    }

    QFrame#TopBar QLabel {
        background: transparent;
        border: none;
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
    """ + _field_control_qss(DARK_FIELD_TOKENS)

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

    QMenuBar#MainMenuBar {
        background: #FFFFFF;
        border-color: #E5E7EB;
        color: #1F2937;
    }

    QMenuBar#MainMenuBar::item:selected,
    QMenuBar#MainMenuBar::item:pressed {
        background: #E5E7EB;
    }

    QMenu {
        background: #FFFFFF;
        border: 1px solid #D1D5DB;
        color: #1F2937;
    }

    QMenu::item:selected { background: #DBEAFE; color: #1D4ED8; }

    QFrame#Sidebar {
        background: #F8FAFC;
        border-color: #E5E7EB;
    }

    QFrame#TopBar {
        background: #FFFFFF;
        border-color: #E5E7EB;
    }

    QFrame#TopBar QLabel {
        background: transparent;
        border: none;
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
    """ + _field_control_qss(LIGHT_FIELD_TOKENS)

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


class DiagnosticsDialog(QDialog):
    """Local diagnostic preview; nothing is uploaded or sent automatically."""

    def __init__(self, parent: QWidget, diagnostic_text: str, is_dark: bool) -> None:
        super().__init__(parent)
        self.setObjectName("DiagnosticsDialog")
        self.setWindowTitle("反馈问题 / 诊断信息")
        self.resize(720, 520)
        layout = QVBoxLayout(self)

        warning = QLabel("诊断信息可能包含您输入的命令或文件路径，请在发送前检查。不会自动上传。")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.preview = QTextEdit()
        self.preview.setObjectName("DiagnosticsPreview")
        self.preview.setReadOnly(True)
        self.preview.setPlainText(diagnostic_text)
        layout.addWidget(self.preview, 1)

        self.status = QLabel("")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_copy = QPushButton("复制诊断信息")
        self.btn_copy.setObjectName("DiagnosticsCopyButton")
        self.btn_open_logs = QPushButton("打开日志目录")
        self.btn_open_logs.setObjectName("DiagnosticsOpenLogsButton")
        self.btn_close = QPushButton("关闭")
        buttons.addWidget(self.btn_copy)
        buttons.addWidget(self.btn_open_logs)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self.btn_copy.clicked.connect(self._copy)
        self.btn_open_logs.clicked.connect(self._open_logs)
        self.btn_close.clicked.connect(self.accept)
        self.setStyleSheet(ThemeManager.DARK if is_dark else ThemeManager.LIGHT)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.preview.toPlainText())
        self.status.setText("诊断信息已复制，请在发送前检查内容。")

    def _open_logs(self) -> None:
        try:
            path = open_logs_directory()
            self.status.setText(f"已打开日志目录：{path}")
        except OSError as exc:
            self.status.setText(f"无法打开日志目录：{exc}")


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
        self.disk_logger = get_app_logger()

        self.current_plan = Plan(plan_name="未命名方案")
        self.current_plan_path: Optional[Path] = None
        self.templates = self.plan_service.load_templates()
        self.current_step_dirty = False
        self.plan_dirty = False
        self.loading_editor = False
        self._loading_plan = True
        self._selection_change_in_progress = False
        self.current_editor_index: Optional[int] = None
        self.last_error_status = ""
        self._log_toolbar_mode: Optional[str] = None
        self._log_toolbar_update_pending = False
        self._setting_log_layout = False

        self.is_dark_theme = self.plan_service.load_settings().get("theme", "dark") != "light"
        self.build_worker: Optional[BuildWorker] = None
        self.trial_run_worker: Optional[TrialRunWorker] = None
        self.progress_dialog: Optional[QProgressDialog] = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1280, 800)

        self.app_icon = apply_window_icon(self, project_root, self.disk_logger)

        self._build_ui()
        QTimer.singleShot(0, self._restore_default_log_layout)
        self._configure_tooltips()
        self.plan_name_edit.setText(self.current_plan.plan_name)
        self._connect_step_editor_dirty_signals()
        self._loading_plan = False
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

        self.main_menu_bar = self._build_menu_bar()
        root_layout.addWidget(self.main_menu_bar)

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
        self.history_section_label = self._make_label("本地历史方案（单击载入）", "section")
        sidebar_layout.addWidget(self.history_section_label)
        sidebar_layout.addSpacing(8)

        self.history_list = PlanHistoryList()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_list.itemClicked.connect(self._load_history_plan_item)
        self.history_list.enterPressed.connect(self._load_history_plan_item)
        sidebar_layout.addWidget(self.history_list, 1)

        content_layout.addWidget(sidebar)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(12, 12, 12, 0)
        right_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setHandleWidth(2)
        self.main_splitter.setChildrenCollapsible(False)

        workspace = QWidget()
        workspace.setObjectName("EditorWorkspace")
        workspace.setMinimumHeight(320)
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        self.top_bar.setFixedHeight(60)

        top_bar_layout = QHBoxLayout(self.top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 8)
        top_bar_layout.setSpacing(10)
        top_bar_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.plan_name_label = QLabel("方案名称:")
        self.plan_name_label.setObjectName("TopBarLabel")
        self.plan_name_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        top_bar_layout.addWidget(self.plan_name_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.plan_name_edit = QLineEdit()
        self.plan_name_edit.setPlaceholderText("请输入方案名称...")
        self.plan_name_edit.setFixedWidth(230)
        self.plan_name_edit.setFixedHeight(38)
        self.plan_name_edit.textChanged.connect(self._on_plan_name_changed)
        top_bar_layout.addWidget(self.plan_name_edit, 0, Qt.AlignmentFlag.AlignVCenter)

        top_bar_layout.addStretch()

        self.btn_save = QPushButton("保存方案")
        self.btn_save.setObjectName("TopToolBtn")
        self.btn_save.setIcon(self._create_small_icon("save"))
        self.btn_save.setIconSize(QSize(18, 18))
        self.btn_save.clicked.connect(self._on_save_plan)

        self.btn_save_as = QPushButton("另存为")
        self.btn_save_as.setObjectName("TopToolBtn")
        self.btn_save_as.clicked.connect(self._on_save_plan_as)

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

        for btn in [self.btn_save, self.btn_save_as, self.btn_trial_run, self.btn_export_exe]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            top_bar_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

        workspace_layout.addWidget(self.top_bar)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setHandleWidth(1)

        flow_panel = QWidget()
        flow_layout = QVBoxLayout(flow_panel)
        flow_layout.setContentsMargins(16, 16, 16, 16)

        flow_layout.addWidget(self._make_label("启动流排布 (DELETE 键删除)", "section"))

        self.flow_list = ReorderableStepList(self._prepare_step_drag, self.reorder_steps, self._move_selected_step)
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
        self.log_drawer.setMinimumHeight(44)
        drawer_layout = QHBoxLayout(self.log_drawer)
        drawer_layout.setContentsMargins(10, 7, 7, 8)
        drawer_layout.setSpacing(7)

        self.log_main = QWidget()
        log_main_layout = QVBoxLayout(self.log_main)
        log_main_layout.setContentsMargins(0, 0, 0, 0)
        log_main_layout.setSpacing(3)

        self.log_header = QFrame()
        self.log_header.setObjectName("LogHeader")
        self.log_header.setMinimumHeight(29)
        log_header = QHBoxLayout(self.log_header)
        log_header.setContentsMargins(0, 0, 0, 0)
        log_header.setSpacing(8)
        self.log_title_label = self._make_label("🛠️ 运行与输出日志", "panel_title")
        log_header.addWidget(self.log_title_label)

        self.status_label = ElidedLabel("状态：准备就绪")
        self.status_label.setProperty("role", "status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        log_header.addWidget(self.status_label, 1)

        self.log_unseen_label = QLabel("有新输出")
        self.log_unseen_label.setObjectName("LogUnseenLabel")
        self.log_unseen_label.hide()
        log_header.addWidget(self.log_unseen_label)

        self.btn_open_log = QPushButton("隐藏日志")
        self.btn_open_log.setObjectName("LogHeaderButton")
        self.btn_open_log.setFixedHeight(28)
        self.btn_open_log.setMinimumWidth(86)
        self.btn_open_log.setMaximumWidth(104)
        self.btn_open_log.setIconSize(QSize(14, 14))
        self.btn_open_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_log.clicked.connect(self._toggle_log_drawer)
        log_header.addWidget(self.btn_open_log)
        log_main_layout.addWidget(self.log_header)

        self.log_hint = self._make_label(
            "后台 Command 的标准输出、错误和退出码集中显示在这里。",
            "panel_hint",
        )
        log_main_layout.addWidget(self.log_hint)

        self.log_text = LogConsole(max_blocks=4000)
        self.log_text.setObjectName("LogConsole")
        self.log_text.setMinimumHeight(148)
        self.log_text.unseenOutputChanged.connect(self._on_log_unseen_output_changed)
        log_main_layout.addWidget(self.log_text, 1)
        drawer_layout.addWidget(self.log_main, 1)

        self.log_toolbar = QFrame()
        self.log_toolbar.setObjectName("LogToolbar")
        self.log_toolbar.setFixedWidth(32)
        log_tools_layout = QVBoxLayout(self.log_toolbar)
        log_tools_layout.setContentsMargins(0, 0, 0, 0)
        log_tools_layout.setSpacing(4)

        self.btn_log_expand = QPushButton()
        self.btn_clear_log = QPushButton()
        self.btn_copy_log = QPushButton()
        self.btn_open_logs_dir = QPushButton()
        self.btn_feedback = QPushButton()
        log_button_icons = (
            (self.btn_log_expand, QStyle.StandardPixmap.SP_TitleBarMaxButton),
            (self.btn_clear_log, QStyle.StandardPixmap.SP_TrashIcon),
            (self.btn_copy_log, QStyle.StandardPixmap.SP_FileDialogDetailedView),
            (self.btn_open_logs_dir, QStyle.StandardPixmap.SP_DirOpenIcon),
            (self.btn_feedback, QStyle.StandardPixmap.SP_MessageBoxQuestion),
        )
        for button, icon_kind in log_button_icons:
            button.setObjectName("LogToolButton")
            button.setFixedSize(32, 32)
            button.setIcon(self.style().standardIcon(icon_kind))
            button.setIconSize(QSize(17, 17))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            log_tools_layout.addWidget(button)
        log_tools_layout.addStretch()
        drawer_layout.addWidget(self.log_toolbar)
        self.log_tool_buttons = tuple(button for button, _icon in log_button_icons)

        self.btn_log_expand.clicked.connect(self._toggle_log_expand)
        self.btn_clear_log.clicked.connect(self._clear_visible_log)
        self.btn_copy_log.clicked.connect(self._copy_visible_log)
        self.btn_open_logs_dir.clicked.connect(self._open_logs_directory)
        self.btn_feedback.clicked.connect(self._show_feedback_dialog)

        self.main_splitter.addWidget(self.log_drawer)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.log_layout_state = "normal"
        self.main_splitter.setSizes([470, 250])
        self.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        right_layout.addWidget(self.main_splitter)
        content_layout.addWidget(right_container, 1)

    def _build_menu_bar(self) -> QMenuBar:
        """Build menus whose actions share the toolbar handlers."""
        menu_bar = QMenuBar(self)
        menu_bar.setObjectName("MainMenuBar")

        file_menu = menu_bar.addMenu("文件")
        edit_menu = menu_bar.addMenu("编辑")

        self.action_save = QAction("保存", self)
        self.action_save.setShortcut(QKeySequence(SHORTCUTS["save"]))
        self.action_save.triggered.connect(self._on_save_plan)

        self.action_save_as = QAction("另存为", self)
        self.action_save_as.setShortcut(QKeySequence(SHORTCUTS["save_as"]))
        self.action_save_as.triggered.connect(self._on_save_plan_as)

        self.action_trial_run = QAction("运行", self)
        self.action_trial_run.setShortcut(QKeySequence(SHORTCUTS["trial_run"]))
        self.action_trial_run.triggered.connect(self._on_trial_run)

        self.action_export_exe = QAction("导出 EXE", self)
        self.action_export_exe.setShortcut(QKeySequence(SHORTCUTS["export"]))
        self.action_export_exe.triggered.connect(self._on_export_exe)

        self.action_delete_step = QAction("删除当前选中步骤", self)
        self.action_delete_step.setShortcut(QKeySequence(SHORTCUTS["delete"]))
        self.action_delete_step.triggered.connect(self._on_delete_step)

        self.action_move_step_up = QAction("上移当前步骤", self)
        self.action_move_step_up.setShortcut(QKeySequence(SHORTCUTS["move_up"]))
        self.action_move_step_up.triggered.connect(lambda: self._move_selected_step(-1))

        self.action_move_step_down = QAction("下移当前步骤", self)
        self.action_move_step_down.setShortcut(QKeySequence(SHORTCUTS["move_down"]))
        self.action_move_step_down.triggered.connect(lambda: self._move_selected_step(1))

        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.action_trial_run)
        file_menu.addAction(self.action_export_exe)
        edit_menu.addAction(self.action_move_step_up)
        edit_menu.addAction(self.action_move_step_down)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete_step)
        return menu_bar

    def _configure_seconds_spinbox(self, spinbox: QDoubleSpinBox, *, decimals: int = 1) -> None:
        """
        统一配置秒数/延迟输入框。

        QDoubleSpinBox 的上下箭头是 Qt subcontrol。这里保持固定高度、
        足够右侧内边距和原生 Up/Down 按钮，避免 QSS 泛用输入框 padding
        把视觉按钮和实际可点击区域拉偏。
        """
        spinbox.setRange(0, 9999)
        spinbox.setDecimals(decimals)
        spinbox.setSingleStep(1.0)
        # 40 logical pixels gives Qt an even styled content height so the
        # native Up/Down subcontrols receive identical hitbox dimensions at
        # 100%, 125%, and 150% scale while preserving the compact field row.
        spinbox.setFixedHeight(40)
        spinbox.setMinimumWidth(150)
        spinbox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)

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
        self.app_path_in.setPlaceholderText("选择或粘贴 .exe / .bat / .cmd / .ps1 路径")
        self.app_args_in.setPlaceholderText("可选：按空格分隔启动参数")
        self.app_args_in.setMaximumHeight(82)
        self.app_delay_in = ThemedDoubleSpinBox()
        self._configure_seconds_spinbox(self.app_delay_in)
        app_form.addRow("步骤名称", self.app_name_in)
        app_form.addRow("程序路径", self.app_path_in)
        app_form.addRow("启动参数", self.app_args_in)
        app_form.addRow("后续延迟(秒)", self.app_delay_in)
        self.editor_stack.addWidget(self.page_app)

        self.page_url = QWidget()
        url_form = QFormLayout(self.page_url)
        self.url_name_in = QLineEdit()
        self.url_in = QLineEdit()
        self.url_delay_in = ThemedDoubleSpinBox()
        self._configure_seconds_spinbox(self.url_delay_in)
        url_form.addRow("步骤名称", self.url_name_in)
        url_form.addRow("网址 URL", self.url_in)
        url_form.addRow("后续延迟(秒)", self.url_delay_in)
        self.editor_stack.addWidget(self.page_url)

        self.page_cmd = QWidget()
        cmd_form = QFormLayout(self.page_cmd)
        self.cmd_name_in = QLineEdit()
        self.cmd_in = QTextEdit()
        self.cmd_in.setMaximumHeight(120)
        self.cmd_shell_in = ThemedComboBox()
        self.cmd_shell_in.addItems(["cmd", "powershell"])
        self.cmd_delay_in = ThemedDoubleSpinBox()
        self._configure_seconds_spinbox(self.cmd_delay_in)
        cmd_form.addRow("步骤名称", self.cmd_name_in)
        cmd_form.addRow("执行命令", self.cmd_in)
        cmd_form.addRow("Shell 类型", self.cmd_shell_in)
        cmd_form.addRow("后续延迟(秒)", self.cmd_delay_in)
        self.editor_stack.addWidget(self.page_cmd)

        self.page_wait = QWidget()
        wait_form = QFormLayout(self.page_wait)
        self.wait_name_in = QLineEdit()
        self.wait_seconds_in = ThemedDoubleSpinBox()
        self._configure_seconds_spinbox(self.wait_seconds_in)
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

    def _connect_step_editor_dirty_signals(self) -> None:
        """Track inspector drafts without serializing or rebuilding the step list per keypress."""

        for line_edit in (
            self.app_name_in,
            self.app_path_in,
            self.url_name_in,
            self.url_in,
            self.cmd_name_in,
            self.wait_name_in,
        ):
            line_edit.textChanged.connect(self._on_step_editor_changed)

        for text_edit in (self.app_args_in, self.cmd_in):
            text_edit.textChanged.connect(self._on_step_editor_changed)

        for spinbox in (
            self.app_delay_in,
            self.url_delay_in,
            self.cmd_delay_in,
            self.wait_seconds_in,
        ):
            spinbox.valueChanged.connect(self._on_step_editor_changed)

        self.cmd_shell_in.currentTextChanged.connect(self._on_step_editor_changed)

    def _on_step_editor_changed(self, *_args) -> None:
        """Mark only the visible draft dirty; model and disk writes stay boundary-based."""

        if self.loading_editor or self.current_editor_index is None:
            return
        self.current_step_dirty = True
        self.plan_dirty = True

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
        """Return the packaged ICO shared by source, frozen, and activation windows."""
        return load_app_icon(self.project_root, self.disk_logger)

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
    def _shortcut_tooltip(self, description: str, action: QAction) -> str:
        shortcut = next(
            (label for label in SHORTCUTS.values() if QKeySequence(label) == action.shortcut()),
            action.shortcut().toString(QKeySequence.SequenceFormat.PortableText),
        )
        return f"{description}（{shortcut}）" if shortcut else description

    def _configure_tooltips(self) -> None:
        """Bind concise help text to widgets using the QAction shortcut source of truth."""

        self.btn_save.setToolTip(self._shortcut_tooltip("保存当前方案", self.action_save))
        self.btn_save_as.setToolTip(self._shortcut_tooltip("将当前方案保存为新文件", self.action_save_as))
        self.btn_trial_run.setToolTip(
            self._shortcut_tooltip("后台执行当前方案，命令输出显示在下方日志", self.action_trial_run)
        )
        self.btn_export_exe.setToolTip(
            self._shortcut_tooltip("将当前方案导出为独立启动器", self.action_export_exe)
        )
        self.btn_apply.setToolTip("将右侧编辑内容应用到当前步骤")
        self.btn_delete_step.setToolTip(
            self._shortcut_tooltip("删除当前选中步骤", self.action_delete_step)
        )
        self.btn_add_app.setToolTip("添加一个应用启动步骤")
        self.btn_add_url.setToolTip("添加一个网页打开步骤")
        self.btn_add_cmd.setToolTip("添加一个后台命令步骤，输出显示在日志区")
        self.btn_add_wait.setToolTip("添加一个等待步骤")
        self.btn_open_log.setToolTip("隐藏或显示 LaunchFlow 内置运行日志区域")
        self.btn_log_expand.setToolTip("放大日志区域；放大后再次点击恢复正常大小")
        self.btn_clear_log.setToolTip("只清空当前显示，不删除磁盘日志")
        self.btn_copy_log.setToolTip("复制当前显示的全部日志")
        self.btn_open_logs_dir.setToolTip("打开 LaunchFlow 当前数据目录中的日志文件夹")
        self.btn_feedback.setToolTip("预览并复制经过掩码的诊断信息，不会自动上传")
        accessible_names = {
            self.btn_log_expand: "展开或还原日志",
            self.btn_clear_log: "清空显示日志",
            self.btn_copy_log: "复制全部日志",
            self.btn_open_logs_dir: "打开日志目录",
            self.btn_feedback: "反馈问题",
        }
        for button, name in accessible_names.items():
            button.setAccessibleName(name)
        self.flow_list.setToolTip(
            f"拖动以调整步骤顺序；顶部和底部有扩展投放区\n"
            f"{SHORTCUTS['move_up']} 上移 / {SHORTCUTS['move_down']} 下移"
        )
        self.cmd_shell_in.setToolTip("选择使用 CMD 或 PowerShell 解析命令；默认不会弹出外部终端")

        for action in (self.action_move_step_up, self.action_move_step_down):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.flow_list.addAction(action)

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

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._schedule_log_toolbar_update()

    def _apply_theme(self) -> None:
        """
        应用当前主题样式到整个主窗口。

        说明：
        - 所有界面配色统一由 ThemeManager 管理；
        - 主题切换时直接整体替换样式表，避免局部控件状态不一致。
        """
        base_style = ThemeManager.DARK if self.is_dark_theme else ThemeManager.LIGHT
        tooltip_style = (
            "QToolTip { background: #111827; color: #F8FAFC; border: 1px solid #475569; "
            "padding: 6px 8px; border-radius: 5px; }"
            if self.is_dark_theme
            else "QToolTip { background: #FFFFFF; color: #111827; border: 1px solid #CBD5E1; "
            "padding: 6px 8px; border-radius: 5px; }"
        )
        self.setStyleSheet(base_style + tooltip_style)
        log_tool_style = (
            "QFrame#LogToolbar, QFrame#LogHeader { background: transparent; border: none; }"
            "QPushButton#LogToolButton { padding: 0; background: #1E293B; border: 1px solid #475569; "
            "border-radius: 6px; } QPushButton#LogToolButton:hover { background: #334155; }"
            "QPushButton#LogToolButton:pressed { background: #475569; }"
            "QPushButton#LogHeaderButton { padding: 0 8px; color: #CBD5E1; background: #111827; "
            "border: 1px solid #475569; border-radius: 6px; }"
            "QPushButton#LogHeaderButton:hover { background: #1E293B; color: #FFFFFF; }"
            "QPushButton#LogHeaderButton:pressed { background: #334155; }"
            "QLabel#LogUnseenLabel { color: #FBBF24; font-weight: 600; }"
            if self.is_dark_theme
            else
            "QFrame#LogToolbar, QFrame#LogHeader { background: transparent; border: none; }"
            "QPushButton#LogToolButton { padding: 0; background: #FFFFFF; border: 1px solid #CBD5E1; "
            "border-radius: 6px; } QPushButton#LogToolButton:hover { background: #E2E8F0; }"
            "QPushButton#LogToolButton:pressed { background: #CBD5E1; }"
            "QPushButton#LogHeaderButton { padding: 0 8px; color: #475569; background: #FFFFFF; "
            "border: 1px solid #CBD5E1; border-radius: 6px; }"
            "QPushButton#LogHeaderButton:hover { background: #F1F5F9; color: #111827; }"
            "QPushButton#LogHeaderButton:pressed { background: #E2E8F0; }"
            "QLabel#LogUnseenLabel { color: #B45309; font-weight: 600; }"
        )
        self.setStyleSheet(self.styleSheet() + log_tool_style)
        self.log_text.set_theme(self.is_dark_theme)
        themed_widgets = [
            *self.findChildren(ThemedDoubleSpinBox),
            *self.findChildren(ThemedComboBox),
        ]
        for widget in themed_widgets:
            widget.setProperty("darkTheme", self.is_dark_theme)
            widget.update()
        self._schedule_log_toolbar_update()

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
        settings = self.plan_service.load_settings()
        settings["theme"] = "dark" if self.is_dark_theme else "light"
        self.plan_service.save_settings(settings)

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
        self.last_error_status = f"{title}: {text}"
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

    def _log(self, text: str, kind: Optional[LogKind] = None) -> None:
        """
        向日志抽屉追加一条日志，同时更新底部状态文字。

        参数：
        - text: 待写入的日志文本。

        说明：
        - 日志和状态栏共用同一份短文本，有助于让用户同时看到“详细过程”和“当前状态”。
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append_entry(now, text, kind or infer_log_kind(text))
        self.status_label.setText(f"状态：{text}")
        self.disk_logger.info(text)

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
        """Hide the body, or restore a constrained/collapsed drawer to normal."""

        should_restore = self.log_layout_state == "collapsed" or self._log_toolbar_mode != "full"
        self.set_log_layout_state("normal" if should_restore else "collapsed")

    def _on_log_unseen_output_changed(self, has_unseen: bool) -> None:
        self.log_unseen_label.setVisible(has_unseen and self.log_layout_state != "collapsed")

    def _toggle_log_expand(self) -> None:
        if self.log_layout_state == "expanded":
            self.set_log_layout_state("normal")
        elif self.log_layout_state == "collapsed":
            self.set_log_layout_state("normal")
        else:
            self.set_log_layout_state("expanded")

    def _restore_default_log_layout(self) -> None:
        self.set_log_layout_state("normal")

    def _apply_log_state_widgets(self, state: str) -> None:
        collapsed = state == "collapsed"
        self.log_layout_state = state
        self.log_hint.setVisible(not collapsed)
        self.log_text.setVisible(not collapsed)
        self.log_unseen_label.setVisible(not collapsed and self.log_text.has_unseen_output)

        expanded = state == "expanded"
        self.btn_log_expand.setAccessibleName("恢复正常大小" if expanded else "放大日志区域")
        self.btn_log_expand.setToolTip(
            "恢复日志区域正常大小" if expanded else "放大日志区域"
        )
        self.btn_log_expand.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_TitleBarNormalButton
                if expanded
                else QStyle.StandardPixmap.SP_TitleBarMaxButton
            )
        )
        self._update_log_header_control()
        self._schedule_log_toolbar_update()

    def _update_log_header_control(self) -> None:
        """Keep one compact header action useful at every drawer height."""

        if self.log_layout_state == "collapsed":
            text = "显示日志"
            icon = QStyle.StandardPixmap.SP_TitleBarNormalButton
        elif self._log_toolbar_mode != "full":
            text = "恢复高度"
            icon = QStyle.StandardPixmap.SP_TitleBarNormalButton
        else:
            text = "隐藏日志"
            icon = QStyle.StandardPixmap.SP_TitleBarShadeButton
        self.btn_open_log.setText(text)
        self.btn_open_log.setAccessibleName(text)
        self.btn_open_log.setToolTip(f"{text}区域")
        self.btn_open_log.setIcon(self.style().standardIcon(icon))

    def _log_toolbar_height_requirements(self) -> tuple[int, int]:
        layout = self.log_toolbar.layout()
        margins = layout.contentsMargins()
        button_heights = [max(button.height(), button.sizeHint().height()) for button in self.log_tool_buttons]
        one = margins.top() + margins.bottom() + button_heights[0]
        full = margins.top() + margins.bottom() + sum(button_heights)
        full += layout.spacing() * max(0, len(button_heights) - 1)
        return one, full

    def update_log_toolbar_visibility(self, available_height: Optional[int] = None) -> str:
        """Show five, one, or zero complete tool buttons based on real height."""

        self._log_toolbar_update_pending = False
        if self.log_layout_state == "collapsed":
            mode = "hidden"
        else:
            if available_height is None:
                layout = self.log_drawer.layout()
                margins = layout.contentsMargins()
                available_height = max(
                    0,
                    self.log_drawer.contentsRect().height() - margins.top() - margins.bottom(),
                )
            one_height, full_height = self._log_toolbar_height_requirements()
            mode = "full" if available_height >= full_height else "expand" if available_height >= one_height else "hidden"

        if mode == self._log_toolbar_mode:
            self._update_log_header_control()
            return mode

        self._log_toolbar_mode = mode
        show_toolbar = mode != "hidden"
        self.log_toolbar.setVisible(show_toolbar)
        for index, button in enumerate(self.log_tool_buttons):
            button.setVisible(mode == "full" or (mode == "expand" and index == 0))
        self._update_log_header_control()
        return mode

    def _schedule_log_toolbar_update(self) -> None:
        if self._log_toolbar_update_pending or not hasattr(self, "log_toolbar"):
            return
        self._log_toolbar_update_pending = True
        QTimer.singleShot(0, self.update_log_toolbar_visibility)

    def _on_main_splitter_moved(self, _position: int, _index: int) -> None:
        if self._setting_log_layout:
            return
        sizes = self.main_splitter.sizes()
        total = max(1, sum(sizes))
        log_height = sizes[1]
        state = "expanded" if log_height / total >= 0.45 else "normal"
        if state != self.log_layout_state:
            self._apply_log_state_widgets(state)
        else:
            self._schedule_log_toolbar_update()

    def set_log_layout_state(self, state: str) -> None:
        """Apply a reversible collapsed/normal/expanded splitter preset."""

        if state not in {"collapsed", "normal", "expanded"}:
            raise ValueError(f"Unsupported log layout state: {state}")

        sizes = self.main_splitter.sizes()
        total = max(sum(sizes), self.main_splitter.height(), 570)
        if state == "collapsed":
            desired = 44
        elif state == "expanded":
            desired = min(max(260, round(total * 0.5)), max(220, total - 320))
        else:
            desired = min(240, max(220, total - 320))

        self._setting_log_layout = True
        try:
            self._apply_log_state_widgets(state)
            self.main_splitter.setSizes([max(320, total - desired), desired])
        finally:
            self._setting_log_layout = False
        self._schedule_log_toolbar_update()

    def _clear_visible_log(self) -> None:
        self.log_text.clear_visible()
        self.status_label.setText("状态：显示日志已清空，磁盘日志未删除。")

    def _copy_visible_log(self) -> None:
        QApplication.clipboard().setText(self.log_text.toPlainText())
        self.status_label.setText("状态：显示日志已复制。")

    def _open_logs_directory(self) -> None:
        try:
            path = open_logs_directory()
            self.status_label.setText(f"状态：已打开日志目录 {path}")
        except OSError as exc:
            self._error("无法打开日志目录", str(exc))

    def _build_diagnostic_text(self) -> str:
        return collect_diagnostics(
            plan_name=self.current_plan.plan_name,
            step_count=len(self.current_plan.steps),
            visible_log=self.log_text.toPlainText(),
            current_error=self.last_error_status,
        )

    def _create_diagnostics_dialog(self) -> DiagnosticsDialog:
        return DiagnosticsDialog(self, self._build_diagnostic_text(), self.is_dark_theme)

    def _show_feedback_dialog(self) -> None:
        self._create_diagnostics_dialog().exec()

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
        return self.plan_service.get_build_cache_dir()

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
        self.plan_dirty = True
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
        if not self._loading_plan:
            self._mark_plan_changed()

    def _on_new_plan(self) -> None:
        """
        新建空白方案并重置编辑状态。
        """
        self.current_plan = Plan(plan_name="未命名方案")
        self.current_plan_path = None
        self._loading_plan = True
        self.plan_name_edit.setText(self.current_plan.plan_name)
        self._loading_plan = False
        self.current_editor_index = None
        self.current_step_dirty = False
        self._refresh_flow_list()
        self.flow_list.clearSelection()
        self._restore_history_selection()
        self._set_editor_no_steps()
        self.plan_dirty = False
        self._log("已新建空白方案。")

    def _on_save_plan(self) -> None:
        """Commit the visible draft, then save it in the normal plans directory."""
        self._save_current_plan(show_confirmation=True)

    def _save_current_plan(self, *, show_confirmation: bool) -> bool:
        """Shared save path used by Ctrl+S and the history dirty-change guard."""

        commit_result = self.commit_current_step_editor()
        if not commit_result.success:
            self._error("无法保存", commit_result.error)
            return False

        name = self.current_plan.plan_name.strip()
        if not name:
            self._error("无法保存", "方案名称不能为空。")
            return False

        file_path = self.plan_service.get_plans_dir() / f"{name}.json"
        try:
            errors = validate_plan_dict(self.current_plan.to_dict())
            if errors:
                self._error("方案校验失败", "\n".join(errors))
                return False
            self.plan_service.save_plan(self.current_plan, file_path)
            self.current_plan_path = file_path
            self.plan_dirty = False
            self._load_history_plans()
            self._log(f"方案已保存至: {file_path}", LogKind.SUCCESS)
            if show_confirmation:
                self._info("保存成功", "方案已成功保存。")
            return True
        except Exception as e:
            self._error("保存失败", str(e))
            return False

    def _on_save_plan_as(self) -> None:
        """Commit the visible draft, then save to a user-selected path."""
        commit_result = self.commit_current_step_editor()
        if not commit_result.success:
            self._error("无法另存", commit_result.error)
            return

        name = self.current_plan.plan_name.strip()
        if not name:
            self._error("无法保存", "方案名称不能为空。")
            return
        file_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "方案另存为",
            str(self.plan_service.get_plans_dir() / f"{name}.json"),
            "LaunchFlow Plan (*.json)",
        )
        if not file_path_str:
            return
        try:
            errors = validate_plan_dict(self.current_plan.to_dict())
            if errors:
                self._error("方案校验失败", "\n".join(errors))
                return
            file_path = Path(file_path_str)
            self.plan_service.save_plan(self.current_plan, file_path)
            self.current_plan_path = file_path
            self.plan_dirty = False
            self._log(f"方案已另存为: {file_path}")
            self._info("另存成功", "方案已保存到所选位置。")
        except Exception as e:
            self._error("另存失败", str(e))

    def _load_history_plans(self) -> None:
        """
        重新加载左侧历史方案列表。
        """
        self.history_list.clear()
        plans_dir = self.plan_service.get_plans_dir()
        for f in sorted(plans_dir.glob("*.json")):
            item = QListWidgetItem(f"📄 {f.stem}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setToolTip("单击载入方案")
            self.history_list.addItem(item)
        self._restore_history_selection()

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(str(Path(path).resolve(strict=False)))

    def _is_current_plan_path(self, path: Path) -> bool:
        return self.current_plan_path is not None and self._path_key(self.current_plan_path) == self._path_key(path)

    def _restore_history_selection(self) -> None:
        self.history_list.blockSignals(True)
        try:
            matching_item = None
            if self.current_plan_path is not None:
                current_key = self._path_key(self.current_plan_path)
                for index in range(self.history_list.count()):
                    item = self.history_list.item(index)
                    if self._path_key(Path(item.data(Qt.ItemDataRole.UserRole))) == current_key:
                        matching_item = item
                        break
            if matching_item is None:
                self.history_list.setCurrentRow(-1)
                self.history_list.clearSelection()
            else:
                self.history_list.setCurrentItem(matching_item)
        finally:
            self.history_list.blockSignals(False)

    def _prompt_unsaved_plan_change(self, target_path: Path) -> PlanSwitchDecision:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("当前方案有未保存修改")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(f"载入“{target_path.stem}”前，当前方案有尚未保存的修改。")
        dialog.setInformativeText("请选择保存当前修改、放弃修改，或取消载入。")
        save_button = dialog.addButton("保存并载入", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton("放弃修改并载入", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(save_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is save_button:
            return PlanSwitchDecision.SAVE
        if clicked is discard_button:
            return PlanSwitchDecision.DISCARD
        if clicked is cancel_button:
            return PlanSwitchDecision.CANCEL
        return PlanSwitchDecision.CANCEL

    def _load_history_plan_item(self, item: QListWidgetItem) -> bool:
        """
        根据历史方案列表项载入对应方案。

        参数：
        - item: 被单击或通过 Enter 激活的列表项。
        """
        file_path = Path(item.data(Qt.ItemDataRole.UserRole))
        if self._is_current_plan_path(file_path):
            self._restore_history_selection()
            return False

        try:
            if not file_path.is_file():
                raise FileNotFoundError(f"方案文件不存在：{file_path}")
            loaded_plan = self.plan_service.load_plan(file_path)
        except Exception as e:
            self._restore_history_selection()
            self._error("载入失败", f"无法读取方案“{file_path.name}”：{e}")
            return False

        if self.current_step_dirty or self.plan_dirty:
            decision = self._prompt_unsaved_plan_change(file_path)
            if decision is PlanSwitchDecision.CANCEL:
                self._restore_history_selection()
                return False
            if decision is PlanSwitchDecision.SAVE:
                if not self._save_current_plan(show_confirmation=False):
                    self._restore_history_selection()
                    return False
                if self._is_current_plan_path(file_path):
                    # Saving can legitimately resolve to the clicked history
                    # path (for example, an unsaved plan with the same name).
                    # In that case the current in-memory plan is already the
                    # newest saved representation and must not be overwritten.
                    self._restore_history_selection()
                    return False
                try:
                    loaded_plan = self.plan_service.load_plan(file_path)
                except Exception as e:
                    self._restore_history_selection()
                    self._error("载入失败", f"保存当前方案后无法重新读取“{file_path.name}”：{e}")
                    return False

        try:
            self.current_plan = loaded_plan
            self.current_plan_path = file_path
            self._loading_plan = True
            self.plan_name_edit.setText(self.current_plan.plan_name)
            self._loading_plan = False
            self.current_editor_index = None
            self.current_step_dirty = False
            self._refresh_flow_list()
            self.flow_list.clearSelection()

            if not self.current_plan.steps:
                self._set_editor_no_steps()
            else:
                self.flow_list.setCurrentRow(0)

            self.plan_dirty = False
            self._restore_history_selection()
            self._log(f"成功载入方案: {file_path.name}", LogKind.SYSTEM)
            return True
        except Exception as e:
            self._restore_history_selection()
            self._error("载入失败", f"载入方案失败：{str(e)}")
            return False

    def _format_step_list_text(self, step) -> str:
        icon = (
            "📱" if step.type == "app"
            else "🌐" if step.type == "url"
            else "⌨️" if step.type == "command"
            else "⏳"
        )
        return f"{icon}  {step.name}"

    def _update_step_list_item(self, index: int) -> None:
        if 0 <= index < self.flow_list.count() and index < len(self.current_plan.steps):
            item = self.flow_list.item(index)
            if item is not None:
                item.setText(self._format_step_list_text(self.current_plan.steps[index]))

    def commit_current_step_editor(self) -> StepCommitResult:
        """Commit the currently displayed inspector draft without execution validation."""

        index = self.current_editor_index
        if index is None:
            return StepCommitResult(success=True)
        if index < 0 or index >= len(self.current_plan.steps):
            return StepCommitResult(
                success=False,
                error="当前编辑步骤已不存在，请重新选择步骤。",
                step_index=index,
            )

        step = self.current_plan.steps[index]
        if not self.current_step_dirty:
            return StepCommitResult(success=True, step_index=index, step_id=step.id)

        try:
            before = step.to_dict()
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
                # Preserve the command exactly. Whitespace is only stripped by preflight checks.
                step.command = self.cmd_in.toPlainText()
                step.shell = self.cmd_shell_in.currentText()
                step.delay_after = self.cmd_delay_in.value()
            elif isinstance(step, WaitStep):
                step.name = self.wait_name_in.text().strip()
                step.seconds = self.wait_seconds_in.value()
            else:
                return StepCommitResult(
                    success=False,
                    error="当前步骤类型无法编辑。",
                    step_index=index,
                    step_id=getattr(step, "id", None),
                )
        except Exception as exc:
            return StepCommitResult(
                success=False,
                error=f"无法保存当前步骤修改：{exc}",
                step_index=index,
                step_id=getattr(step, "id", None),
            )

        changed = before != step.to_dict()
        self.current_step_dirty = False
        if changed:
            self._update_step_list_item(index)
            self._mark_plan_changed()
            self._log(f"已更新步骤: {step.name}")
        return StepCommitResult(
            success=True,
            changed=changed,
            step_index=index,
            step_id=step.id,
        )

    def _commit_before_editor_boundary(self, title: str) -> bool:
        result = self.commit_current_step_editor()
        if result.success:
            return True
        self._error(title, result.error)
        return False

    # ---------------- add step ----------------
    def _on_add_app_step(self) -> None:
        """
        通过文件选择框添加一个应用步骤。

        说明：
        - 当前支持 exe / bat / cmd / ps1 / lnk 等常见启动入口；
        - 选择成功后会立即将步骤加入当前方案并刷新界面。
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择应用程序",
            "",
            "Applications (*.exe *.bat *.cmd *.ps1 *.lnk)"
        )
        if not file_path:
            return
        if not self._commit_before_editor_boundary("无法新增步骤"):
            return

        new_step = self.plan_service.create_app_step(Path(file_path).stem, file_path)
        self.current_plan.steps.append(new_step)
        self.current_editor_index = None
        self._refresh_flow_list()
        self._mark_plan_changed()
        self._select_new_step(len(self.current_plan.steps) - 1)

    def _on_add_template_step(self, step_type: str) -> None:
        """
        根据模板类型添加一个非应用步骤。

        参数：
        - step_type: 模板类型，可选值为 url / command / wait。
        """
        fresh_templates = {
            "url": {"type": "url", "name": "新网页", "default_url": "", "delay_after": 1.0},
            "command": {
                "type": "command",
                "name": "新命令",
                "default_command": "",
                "default_shell": "cmd",
                "delay_after": 1.0,
            },
            "wait": {"type": "wait", "name": "新等待", "default_seconds": 1.0},
        }
        template = fresh_templates.get(step_type)
        if template is None:
            raise ValueError(f"不支持的步骤类型: {step_type}")
        if not self._commit_before_editor_boundary("无法新增步骤"):
            return

        new_step = self.plan_service.create_step_from_template(template)
        self.current_plan.steps.append(new_step)
        self.current_editor_index = None
        self._refresh_flow_list()
        self._mark_plan_changed()
        self._select_new_step(len(self.current_plan.steps) - 1)

    def _select_new_step(self, index: int) -> None:
        """Select a newly appended step and make its inspector ready to edit."""
        if index < 0 or index >= self.flow_list.count():
            return

        self.flow_list.clearSelection()
        self.flow_list.setCurrentRow(index)
        item = self.flow_list.item(index)
        if item is not None:
            self.flow_list.scrollToItem(item)

        step = self.current_plan.steps[index]
        editor = (
            self.app_name_in
            if isinstance(step, AppStep)
            else self.url_name_in
            if isinstance(step, UrlStep)
            else self.cmd_name_in
            if isinstance(step, CommandStep)
            else self.wait_name_in
        )
        editor.setFocus()
        editor.selectAll()

    # ---------------- flow ----------------
    def _prepare_step_drag(self) -> bool:
        result = self.commit_current_step_editor()
        if result.success:
            return True
        self._error("无法调整步骤顺序", result.error)
        return False

    def _step_index_by_id(self, step_id: str) -> Optional[int]:
        return next((index for index, step in enumerate(self.current_plan.steps) if step.id == step_id), None)

    def _select_step_by_id(self, step_id: str) -> None:
        index = self._step_index_by_id(step_id)
        if index is None:
            return
        self._selection_change_in_progress = True
        try:
            self.flow_list.clearSelection()
            self.flow_list.setCurrentRow(index)
        finally:
            self._selection_change_in_progress = False
        self._on_step_selected(index)
        item = self.flow_list.item(index)
        if item is not None:
            self.flow_list.scrollToItem(item)

    def reorder_steps(self, source_index: int, target_index: int) -> Optional[int]:
        """Move one existing step without recreating it and return its final index."""

        count = len(self.current_plan.steps)
        if source_index < 0 or target_index < 0 or source_index >= count or target_index >= count:
            return None
        if source_index == target_index:
            return source_index

        commit_result = self.commit_current_step_editor()
        if not commit_result.success:
            self._error("无法调整步骤顺序", commit_result.error)
            return None

        step = self.current_plan.steps.pop(source_index)
        self.current_plan.steps.insert(target_index, step)
        self.current_editor_index = None
        self.current_step_dirty = False
        self._refresh_flow_list()
        self._select_step_by_id(step.id)
        self._mark_plan_changed()
        self._log(f"已移动步骤“{step.name}”：{source_index + 1} → {target_index + 1}")
        return target_index

    def _move_selected_step(self, offset: int) -> Optional[int]:
        selected = self.flow_list.selectedItems()
        if len(selected) != 1:
            return None
        source_index = self.flow_list.row(selected[0])
        target_index = source_index + offset
        if target_index < 0 or target_index >= len(self.current_plan.steps):
            return source_index
        return self.reorder_steps(source_index, target_index)

    def _refresh_flow_list(self) -> None:
        """
        根据当前方案重新渲染左侧步骤列表。
        """
        previous_guard = self._selection_change_in_progress
        self._selection_change_in_progress = True
        try:
            self.flow_list.clear()
            for step in self.current_plan.steps:
                item = QListWidgetItem(self._format_step_list_text(step))
                item.setData(Qt.ItemDataRole.UserRole, step.id)
                item.setToolTip(
                    f"拖动以调整步骤顺序\n{SHORTCUTS['move_up']} 上移 / {SHORTCUTS['move_down']} 下移"
                )
                self.flow_list.addItem(item)
        finally:
            self._selection_change_in_progress = previous_guard

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
        if self._selection_change_in_progress:
            return
        if not self.current_plan.steps:
            self.current_editor_index = None
            self.current_step_dirty = False
            self._set_editor_no_steps()
            return

        selected_items = self.flow_list.selectedItems()
        count = len(selected_items)
        next_index = self.flow_list.row(selected_items[0]) if count == 1 else None
        previous_index = self.current_editor_index

        if previous_index is not None and previous_index != next_index:
            result = self.commit_current_step_editor()
            if not result.success:
                self._selection_change_in_progress = True
                try:
                    self.flow_list.clearSelection()
                    if 0 <= previous_index < self.flow_list.count():
                        self.flow_list.setCurrentRow(previous_index)
                finally:
                    self._selection_change_in_progress = False
                self._error("无法切换步骤", result.error)
                return
            self.current_editor_index = None
            self.current_step_dirty = False

        if count == 0:
            self._set_editor_no_selection()
        elif count == 1:
            self.btn_apply.setEnabled(True)
            self.btn_delete_step.setEnabled(True)
            self.btn_delete_step.setText("🗑️ 删除此步骤")
            self._on_step_selected(next_index)
        else:
            self._set_editor_multi_selection(count)

    def _on_step_selected(self, index: Optional[int]) -> None:
        """
        根据索引加载单个步骤到右侧编辑器。

        参数：
        - index: 当前步骤在方案列表中的索引。
        """
        if index is None or index < 0 or index >= len(self.current_plan.steps):
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
        self.loading_editor = True
        try:
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
                self.cmd_in.setPlainText(step.command)
                self.cmd_shell_in.setCurrentText(step.shell)
                self.cmd_delay_in.setValue(step.delay_after)

            elif isinstance(step, WaitStep):
                self.editor_stack.setCurrentWidget(self.page_wait)
                self.wait_name_in.setText(step.name)
                self.wait_seconds_in.setValue(step.seconds)
        finally:
            self.loading_editor = False
        self.current_editor_index = index
        self.current_step_dirty = False

    def _apply_step_changes(self) -> None:
        """
        将右侧编辑器中的改动写回当前选中步骤。
        """
        result = self.commit_current_step_editor()
        if not result.success:
            self._error("无法保存步骤", result.error)

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

        self.current_editor_index = None
        self.current_step_dirty = False
        self._refresh_flow_list()
        self.flow_list.clearSelection()
        self._mark_plan_changed()

        if not self.current_plan.steps:
            self._set_editor_no_steps()
        else:
            self._set_editor_no_selection()

    def _focus_preflight_issue(self, issue: PlanValidationIssue) -> None:
        """Select the invalid step and focus the field the user needs to fix."""

        index = issue.step_index
        if index is None or index < 0 or index >= len(self.current_plan.steps):
            return

        self._selection_change_in_progress = True
        try:
            self.flow_list.clearSelection()
            self.flow_list.setCurrentRow(index)
        finally:
            self._selection_change_in_progress = False
        self._on_step_selected(index)

        step = self.current_plan.steps[index]
        field_widgets = {
            ("app", "path"): self.app_path_in,
            ("url", "url"): self.url_in,
            ("command", "command"): self.cmd_in,
            ("command", "shell"): self.cmd_shell_in,
            ("wait", "seconds"): self.wait_seconds_in,
        }
        widget = field_widgets.get((step.type, issue.field))
        if widget is not None:
            widget.setFocus()
        self.status_label.setText(f"状态：{issue.message}")

    def _prepare_plan_for_execution(self, action_label: str) -> PlanPreparationResult:
        """Commit the draft, run full-plan preflight, and return a stable snapshot."""

        commit_result = self.commit_current_step_editor()
        if not commit_result.success:
            return PlanPreparationResult(
                success=False,
                error=commit_result.error,
                step_index=commit_result.step_index,
                step_id=commit_result.step_id,
            )

        issue = validate_plan_for_execution(self.current_plan, action_label)
        if issue is not None:
            self._focus_preflight_issue(issue)
            return PlanPreparationResult(
                success=False,
                error=issue.message,
                step_index=issue.step_index,
                step_id=issue.step_id,
                field=issue.field,
            )

        return PlanPreparationResult(success=True, snapshot=deepcopy(self.current_plan))

    # ---------------- run / export ----------------
    def _on_trial_run(self) -> None:
        """
        直接试运行当前方案。

        说明：
        - 试运行会真实执行应用、网址和命令步骤；
        - 为避免用户误触，这里先弹确认框；
        - 运行日志会自动展开到底部日志抽屉。
        """
        preparation = self._prepare_plan_for_execution("试运行")
        if not preparation.success or preparation.snapshot is None:
            self._error("无法试运行", preparation.error)
            return

        if not self._confirm(
                "确认试运行",
                "试运行会真实打开应用、网址和命令窗口。\n确定继续吗？",
                "开始试运行",
        ):
            return

        if self.log_layout_state == "collapsed":
            self.set_log_layout_state("normal")

        self.btn_trial_run.setEnabled(False)
        self._log("开始直接试运行当前方案...")

        self.trial_run_worker = TrialRunWorker(preparation.snapshot)
        self.trial_run_worker.progress.connect(self._log)
        self.trial_run_worker.success.connect(self._on_trial_run_success)
        self.trial_run_worker.failed.connect(self._on_trial_run_failed)
        self.trial_run_worker.finished.connect(self._on_trial_run_finished)
        self.trial_run_worker.start()

    def _on_trial_run_success(self) -> None:
        """
        试运行成功后的收尾处理。
        """
        self._log("试运行完成。")

    def _on_trial_run_failed(self, error_msg: str) -> None:
        """
        试运行失败后的错误提示处理。

        参数：
        - error_msg: 后台线程返回的错误文本。
        """
        self._log(f"试运行失败: {error_msg}")
        self._error("试运行失败", error_msg)

    def _on_trial_run_finished(self) -> None:
        """Release the worker only after its run method and pipe logging finish."""
        worker = self.sender()
        self.btn_trial_run.setEnabled(True)
        if worker is self.trial_run_worker:
            self.trial_run_worker = None
        if isinstance(worker, QThread):
            worker.deleteLater()

    def _on_export_exe(self) -> None:
        """
        将当前方案导出为独立 exe。

        说明：
        - 开发版优先使用当前 Python 环境中的 PyInstaller；
        - 发布版会尝试使用系统 PATH 中的 pyinstaller 或 python -m PyInstaller。
        """
        preparation = self._prepare_plan_for_execution("导出")
        if not preparation.success or preparation.snapshot is None:
            self._error("无法导出", preparation.error)
            return

        plan_snapshot = preparation.snapshot

        target_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "导出单文件 EXE",
            f"{plan_snapshot.plan_name}.exe",
            "Executable Files (*.exe)"
        )
        if not target_path_str:
            return

        target_path = Path(target_path_str)
        packable_count = sum(
            1
            for step in plan_snapshot.steps
            if isinstance(step, AppStep)
            and Path(step.path).suffix.lower() in PACKABLE_APP_SUFFIXES
            and Path(step.path).is_file()
        )

        if packable_count > 0:
            message = (
                f"检测到 {packable_count} 个本地应用启动文件。\n\n"
                "导出时会自动把这些文件随包携带，并在启动包运行时优先从包内启动。\n"
                "如果这些应用依赖外部 DLL、配置文件或数据目录，请确保目标电脑也具备对应环境。"
            )
            if not self._confirm("确认导出", message, "继续导出"):
                return

        if getattr(sys, "frozen", False):
            self._log("发布版导出将使用系统 PATH 中的 PyInstaller 构建器。")

        self._create_progress_dialog("正在导出", "正在封装独立 EXE，请稍候...")

        self.build_worker = BuildWorker(plan_snapshot, target_path)
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
