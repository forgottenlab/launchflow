"""Edition-aware editor presentation helpers.

Professional / the current product entry keeps the full existing workbench:
Command, Wait, application arguments, and custom delay_after. Basic hides or
withholds those Professional-only capabilities so the in-app UI matches the
already-enforced plan contract.
"""

from __future__ import annotations

from typing import Any

from shared.edition_policy import is_basic_edition_active
from shared.platform.application_lookup import (
    BASIC_LOOKUP_SUFFIXES,
    PROFESSIONAL_LOOKUP_SUFFIXES,
)


ALL_EDITOR_STEP_TYPES = frozenset({"app", "url", "command", "wait"})
BASIC_EDITOR_STEP_TYPES = frozenset({"app", "url"})

PROFESSIONAL_APP_DIALOG_FILTER = "Applications (*.exe *.bat *.cmd *.ps1 *.lnk)"
BASIC_APP_DIALOG_FILTER = "Applications (*.exe *.lnk)"

PROFESSIONAL_WORKBENCH_TITLE = "Launch Flow 工作台"
BASIC_WORKBENCH_TITLE = "LaunchFlow Basic 工作台"
PROFESSIONAL_BRAND_TITLE = "Launch Flow"
BASIC_BRAND_TITLE = "LaunchFlow Basic"

PROFESSIONAL_EMPTY_STEPS_HINT = "请先在左侧点击“+ 应用 / + 网页 / + 命令 / + 等待”来添加步骤。"
BASIC_EMPTY_STEPS_HINT = "请先在左侧点击“+ 应用 / + 网页”来添加步骤。"

PROFESSIONAL_APP_PATH_PLACEHOLDER = "输入绝对路径，或浏览 / 按名称查找 .exe / .bat / .cmd / .ps1"
BASIC_APP_PATH_PLACEHOLDER = "输入绝对路径，或浏览 / 按名称查找本地 .exe / .lnk"

PROFESSIONAL_LOG_HINT = "后台 Command 的标准输出、错误和退出码集中显示在这里。"
BASIC_LOG_HINT = "应用和网页步骤的运行结果会显示在这里。"

PROFESSIONAL_TRIAL_RUN_MESSAGE = "试运行会真实打开应用、网址和命令窗口。\n确定继续吗？"
BASIC_TRIAL_RUN_MESSAGE = "试运行会真实打开应用和网页。\n确定继续吗？"


def visible_editor_step_types() -> frozenset[str]:
    """Return the step types the current editor entry should offer."""

    if is_basic_edition_active():
        return BASIC_EDITOR_STEP_TYPES
    return ALL_EDITOR_STEP_TYPES


def shows_professional_editor_controls() -> bool:
    """True when Command, Wait, app args, and custom delays stay visible."""

    return not is_basic_edition_active()


def application_file_dialog_filter() -> str:
    """Return the file-dialog filter for adding an application step."""

    if is_basic_edition_active():
        return BASIC_APP_DIALOG_FILTER
    return PROFESSIONAL_APP_DIALOG_FILTER


def workbench_title() -> str:
    return BASIC_WORKBENCH_TITLE if is_basic_edition_active() else PROFESSIONAL_WORKBENCH_TITLE


def brand_title() -> str:
    return BASIC_BRAND_TITLE if is_basic_edition_active() else PROFESSIONAL_BRAND_TITLE


def empty_steps_hint() -> str:
    return BASIC_EMPTY_STEPS_HINT if is_basic_edition_active() else PROFESSIONAL_EMPTY_STEPS_HINT


def application_path_placeholder() -> str:
    return BASIC_APP_PATH_PLACEHOLDER if is_basic_edition_active() else PROFESSIONAL_APP_PATH_PLACEHOLDER


def application_lookup_suffixes() -> tuple[str, ...]:
    """Return the path suffixes keyword lookup may store for this edition."""

    if is_basic_edition_active():
        return BASIC_LOOKUP_SUFFIXES
    return PROFESSIONAL_LOOKUP_SUFFIXES


def log_hint_text() -> str:
    return BASIC_LOG_HINT if is_basic_edition_active() else PROFESSIONAL_LOG_HINT


def trial_run_confirm_message() -> str:
    return BASIC_TRIAL_RUN_MESSAGE if is_basic_edition_active() else PROFESSIONAL_TRIAL_RUN_MESSAGE


def filter_templates_for_current_edition(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return templates the current edition may offer or persist as defaults."""

    allowed = visible_editor_step_types()
    return [template for template in templates if template.get("type") in allowed]
