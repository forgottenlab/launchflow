"""Shared LaunchFlow application icon and Windows identity helpers."""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget


APP_USER_MODEL_ID = "forgottenlab.launchflow.editor"


def resolve_app_icon_path(project_root: Optional[Path] = None) -> Path:
    """Resolve ``assets/launchflow.ico`` in source and PyInstaller onefile modes."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        resource_root = Path(sys._MEIPASS)
    elif project_root is not None:
        resource_root = Path(project_root)
    else:
        resource_root = Path(__file__).resolve().parent.parent
    return resource_root / "assets" / "launchflow.ico"


def configure_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Set the Windows process identity before QApplication/window creation."""

    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except (AttributeError, OSError):
        return False


def load_app_icon(
    project_root: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> QIcon:
    """Load the shared ICO resource without making startup depend on it."""

    icon_path = resolve_app_icon_path(project_root)
    if not icon_path.is_file():
        (logger or logging.getLogger("launchflow")).warning(
            "LaunchFlow icon resource not found: %s; continuing without a custom icon",
            icon_path,
        )
        return QIcon()

    icon = QIcon(str(icon_path))
    if icon.isNull():
        (logger or logging.getLogger("launchflow")).warning(
            "LaunchFlow icon resource could not be loaded: %s; continuing without a custom icon",
            icon_path,
        )
    return icon


def apply_application_icon(
    app: QApplication,
    project_root: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> QIcon:
    """Apply the shared icon globally and return the resolved QIcon."""

    icon = load_app_icon(project_root, logger)
    if not icon.isNull():
        app.setWindowIcon(icon)
    return icon


def apply_window_icon(
    window: QWidget,
    project_root: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> QIcon:
    """Apply the QApplication icon to a top-level window, with resource fallback."""

    app = QApplication.instance()
    icon = app.windowIcon() if app is not None else QIcon()
    if icon.isNull():
        icon = load_app_icon(project_root, logger)
    if not icon.isNull():
        window.setWindowIcon(icon)
    return icon
