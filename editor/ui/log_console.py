"""Rich UI log presentation that preserves plain-text disk and clipboard output."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QTextEdit


class LogKind(str, Enum):
    SYSTEM = "system"
    EXECUTION = "execution"
    OUTPUT = "output"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    SEPARATOR = "separator"


_DARK_COLORS = {
    LogKind.SYSTEM: "#94A3B8",
    LogKind.EXECUTION: "#38BDF8",
    LogKind.OUTPUT: "#E2E8F0",
    LogKind.SUCCESS: "#4ADE80",
    LogKind.WARNING: "#FBBF24",
    LogKind.ERROR: "#FB7185",
    LogKind.SEPARATOR: "#64748B",
}

_LIGHT_COLORS = {
    LogKind.SYSTEM: "#64748B",
    LogKind.EXECUTION: "#0369A1",
    LogKind.OUTPUT: "#0F172A",
    LogKind.SUCCESS: "#15803D",
    LogKind.WARNING: "#B45309",
    LogKind.ERROR: "#BE123C",
    LogKind.SEPARATOR: "#94A3B8",
}

LOG_KIND_PROPERTY = int(QTextFormat.Property.UserProperty) + 1
TIMESTAMP_PROPERTY = int(QTextFormat.Property.UserProperty) + 2


def infer_log_kind(message: str) -> LogKind:
    """Compatibility classifier for legacy string-only runtime log callbacks."""

    stripped = message.strip()
    if stripped and set(stripped) == {"="}:
        return LogKind.SEPARATOR
    if stripped.startswith(("[错误]", "[失败]")) or "试运行失败" in stripped or "导出失败" in stripped:
        return LogKind.ERROR
    if stripped.startswith("[成功]") or stripped in {"方案执行完成", "试运行完成。"} or "导出成功" in stripped:
        return LogKind.SUCCESS
    if stripped.startswith(("[等待]", "[提示]", "[警告]", "[跳过]")):
        return LogKind.WARNING
    if stripped.startswith(("[输出]", "[标准错误]")):
        return LogKind.OUTPUT
    if stripped.startswith(("[执行]", "[命令]", "[退出码]")) or stripped.startswith("开始执行方案"):
        return LogKind.EXECUTION
    return LogKind.SYSTEM


def log_formats(is_dark: bool) -> dict[LogKind, QTextCharFormat]:
    """Return independently colored formats for every semantic log category."""

    colors = _DARK_COLORS if is_dark else _LIGHT_COLORS
    formats: dict[LogKind, QTextCharFormat] = {}
    for kind, color in colors.items():
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if kind in {LogKind.EXECUTION, LogKind.SUCCESS, LogKind.WARNING, LogKind.ERROR}:
            fmt.setFontWeight(600)
        fmt.setProperty(LOG_KIND_PROPERTY, kind.value)
        formats[kind] = fmt
    return formats


def timestamp_format(is_dark: bool) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor("#64748B" if is_dark else "#94A3B8"))
    fmt.setProperty(TIMESTAMP_PROPERTY, True)
    return fmt


class LogConsole(QTextEdit):
    """Incremental rich-text console with bounded blocks and respectful scrolling."""

    unseenOutputChanged = Signal(bool)

    def __init__(self, parent=None, *, max_blocks: int = 4000) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(max_blocks)
        self.max_blocks = max_blocks
        self.is_dark_theme = True
        self.has_unseen_output = False
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

    def set_theme(self, is_dark: bool) -> None:
        if self.is_dark_theme == is_dark:
            return
        self.is_dark_theme = is_dark
        kind_formats = log_formats(is_dark)
        block = self.document().firstBlock()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    old_format = fragment.charFormat()
                    replacement = None
                    if old_format.boolProperty(TIMESTAMP_PROPERTY):
                        replacement = timestamp_format(is_dark)
                    else:
                        kind_value = old_format.stringProperty(LOG_KIND_PROPERTY)
                        if kind_value:
                            replacement = kind_formats[LogKind(kind_value)]
                    if replacement is not None:
                        cursor = QTextCursor(self.document())
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(),
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        cursor.setCharFormat(replacement)
                iterator += 1
            block = block.next()

    def is_at_bottom(self) -> bool:
        scrollbar = self.verticalScrollBar()
        return scrollbar.value() >= max(0, scrollbar.maximum() - 2)

    def append_entry(self, timestamp: str, message: str, kind: LogKind) -> None:
        """Append one entry without rebuilding the QTextDocument."""

        was_at_bottom = self.is_at_bottom()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(f"[{timestamp}] ", timestamp_format(self.is_dark_theme))
        cursor.insertText(message, log_formats(self.is_dark_theme)[kind])

        if was_at_bottom:
            scrollbar = self.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            self._set_unseen_output(False)
        else:
            self._set_unseen_output(True)

    def clear_visible(self) -> None:
        self.clear()
        self._set_unseen_output(False)

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self.is_at_bottom():
            self._set_unseen_output(False)

    def _set_unseen_output(self, value: bool) -> None:
        if self.has_unseen_output == value:
            return
        self.has_unseen_output = value
        self.unseenOutputChanged.emit(value)
