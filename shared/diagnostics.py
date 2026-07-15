"""Safe, local-only diagnostics collection for the feedback preview."""

from __future__ import annotations

import os
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

from shared.app_info import APP_NAME, APP_VERSION
from shared.app_paths import get_app_data_dir, get_logs_dir


_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(machine[_ -]?id|request[_ -]?id|signature)\b(\s*[:=]\s*)([^\s,;]+)"
)
_LFREQ1 = re.compile(r"LFREQ1\.[A-Za-z0-9_-]{16,}(?:\.[A-Za-z0-9_-]{4,})?")


def normalize_user_paths(text: str) -> str:
    """Replace common user-specific path prefixes with stable environment labels."""

    replacements = [
        (os.environ.get("LOCALAPPDATA", ""), "%LOCALAPPDATA%"),
        (str(Path.home()), "%USERPROFILE%"),
    ]
    result = text
    for source, replacement in replacements:
        if source:
            result = re.sub(re.escape(source), replacement, result, flags=re.IGNORECASE)
    return result


def redact_diagnostic_text(text: str) -> str:
    """Mask known identifiers/tokens and suppress private-key references."""

    safe_lines: list[str] = []
    for line in text.splitlines():
        if "private_key.pem" in line.lower():
            safe_lines.append("[已隐藏私钥相关日志]")
            continue
        line = _LFREQ1.sub("LFREQ1.[MASKED]", line)
        line = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[MASKED]", line)
        safe_lines.append(line)
    return normalize_user_paths("\n".join(safe_lines))


def _latest_log_file() -> Path:
    logs_dir = get_logs_dir()
    preferred = logs_dir / "launchflow.log"
    if preferred.is_file():
        return preferred
    candidates = sorted(logs_dir.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else preferred


def _recent_log_text(visible_log: str, max_lines: int) -> tuple[str, Path]:
    log_path = _latest_log_file()
    text = visible_log
    if not text.strip() and log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    return "\n".join(text.splitlines()[-max_lines:]), log_path


def collect_diagnostics(
    *,
    plan_name: str,
    step_count: int,
    visible_log: str,
    current_error: str = "",
    max_log_lines: int = 150,
) -> str:
    """Build a previewable diagnostic report without reading license data."""

    max_log_lines = max(1, min(max_log_lines, 200))
    recent_log, log_path = _recent_log_text(visible_log, max_log_lines)
    frozen = bool(getattr(sys, "frozen", False))
    lines = [
        f"{APP_NAME} 诊断信息",
        f"版本: {APP_VERSION}",
        f"构建渠道: {'frozen' if frozen else 'source'}",
        f"当前时间: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Windows: {platform.platform()}",
        f"Python: {sys.version.split()[0] if not frozen else 'embedded'}",
        f"Frozen: {frozen}",
        f"当前方案: {plan_name or '未命名方案'}",
        f"步骤数量: {step_count}",
        f"当前错误: {current_error or '无'}",
        f"数据目录: {get_app_data_dir()}",
        f"日志文件: {log_path}",
        "",
        f"最近日志（最多 {max_log_lines} 行）:",
        recent_log or "（无可用日志）",
    ]
    return redact_diagnostic_text("\n".join(lines))


def open_logs_directory() -> Path:
    """Open the single app_paths-owned logs directory and return it for auditing/tests."""

    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(logs_dir))
    return logs_dir
