"""Launch-entry helpers for LaunchFlow edition identity.

The current product entry (editor.main / LaunchFlow.exe) stays on the
Professional path and must not activate Basic. The Basic entry
(editor.main_basic / LaunchFlow-Basic.exe) sets the process-wide Basic
edition context before any data-directory, migration, or licensing work.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.edition_policy import (
    BASIC_EDITION,
    EditionContext,
    get_edition_context,
    set_process_edition_context,
)


CURRENT_PRODUCT_ENTRY = "editor.main"
BASIC_EDITOR_ENTRY = "editor.main_basic"
BASIC_EDITOR_APP_ID = "forgottenlab.launchflow.editor.basic"
BASIC_APP_DISPLAY_NAME = "LaunchFlow Basic"
BASIC_APP_DIR_NAME = "LaunchFlow-Basic"


def get_project_root() -> Path:
    """Return the source root, or the packaged executable directory."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ensure_project_root_on_path(project_root: Path | None = None) -> Path:
    """Insert the project root on sys.path without changing edition context."""

    root = project_root if project_root is not None else get_project_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


def edition_for_launch_entry(entry: str) -> str | None:
    """Return the edition implied by a launch entry.

    The current product entry returns None, which is the Professional path.
    """

    normalized = str(entry or "").strip().replace("\\", "/")
    if normalized in {
        BASIC_EDITOR_ENTRY,
        "editor/main_basic.py",
        "main_basic.py",
    }:
        return BASIC_EDITION
    if normalized in {
        CURRENT_PRODUCT_ENTRY,
        "editor/main.py",
        "main.py",
    }:
        return None
    raise ValueError(f"unknown LaunchFlow launch entry: {entry}")


def apply_current_product_launch_edition() -> EditionContext:
    """Keep the current product entry on the unset Professional path."""

    set_process_edition_context(EditionContext())
    return get_edition_context()


def apply_basic_launch_edition() -> EditionContext:
    """Activate Basic edition context for the Basic launch entry."""

    set_process_edition_context(EditionContext(edition=BASIC_EDITION))
    return get_edition_context()


def apply_launch_edition_for_entry(entry: str) -> EditionContext:
    """Set process-wide edition context from the entry that was launched."""

    edition = edition_for_launch_entry(entry)
    if edition == BASIC_EDITION:
        return apply_basic_launch_edition()
    return apply_current_product_launch_edition()
