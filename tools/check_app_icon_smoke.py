"""Validate source/frozen icon resolution and top-level Qt icon contracts."""

from __future__ import annotations

import ast
import inspect
import os
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = ROOT.parent / "test" / f"app-icon-smoke-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from editor.ui.activation_window import ActivationWindow  # noqa: E402
from editor.ui.main_window import MainWindow  # noqa: E402
import shared.app_icon as app_icon  # noqa: E402
from shared.app_icon import (  # noqa: E402
    APP_USER_MODEL_ID,
    apply_application_icon,
    configure_windows_app_id,
    resolve_app_icon_path,
)
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from tools.build_editor_release import build_editor_command  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_entry_order() -> None:
    tree = ast.parse((ROOT / "editor" / "main.py").read_text(encoding="utf-8"))
    main_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = [node for node in ast.walk(main_node) if isinstance(node, ast.Call)]
    configure_calls = [
        node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "configure_windows_app_id"
    ]
    application_calls = [
        node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "QApplication"
    ]
    require(len(configure_calls) == 1, "editor entry must configure AppUserModelID exactly once")
    require(len(application_calls) == 1, "editor entry QApplication construction count changed")
    require(
        configure_calls[0].lineno < application_calls[0].lineno,
        "Windows AppUserModelID is not configured before QApplication",
    )


def check_public_identity_facade() -> None:
    require(
        str(inspect.signature(configure_windows_app_id))
        == "(app_id: 'str' = 'forgottenlab.launchflow.editor') -> 'bool'",
        "configure_windows_app_id public signature changed",
    )
    source = inspect.getsource(configure_windows_app_id)
    require("get_desktop_integration()" in source, "identity facade bypasses DesktopIntegration")
    require("ctypes.windll" not in source and "sys.platform" not in source, "identity facade retained OS coupling")

    original_factory = app_icon.get_desktop_integration
    factory_calls: list[bool] = []
    identity_calls: list[str] = []

    class RecordingIntegration:
        def __init__(self, result: bool = True, error: BaseException | None = None) -> None:
            self.result = result
            self.error = error

        def configure_application_identity(self, app_id: str) -> bool:
            identity_calls.append(app_id)
            if self.error is not None:
                raise self.error
            return self.result

    try:
        integration = RecordingIntegration()
        app_icon.get_desktop_integration = (  # type: ignore[assignment]
            lambda: factory_calls.append(True) or integration
        )
        require(configure_windows_app_id() is True, "identity facade changed the success return")
        require(
            configure_windows_app_id("custom.launchflow.identity") is True,
            "identity facade changed the explicit-ID return",
        )
        require(factory_calls == [True, True], "identity facade factory call count changed")
        require(
            identity_calls == [APP_USER_MODEL_ID, "custom.launchflow.identity"],
            "identity facade changed AppUserModelID forwarding",
        )

        integration.result = False
        require(configure_windows_app_id() is False, "identity facade changed the false return")

        sentinel = RuntimeError("raw identity error")
        integration.error = sentinel
        try:
            configure_windows_app_id()
        except BaseException as caught:
            require(caught is sentinel, "identity facade replaced an unhandled backend error")
        else:
            raise AssertionError("identity facade swallowed an unhandled backend error")
    finally:
        app_icon.get_desktop_integration = original_factory  # type: ignore[assignment]


def main() -> int:
    icon_path = ROOT / "assets" / "launchflow.ico"
    require(icon_path.is_file() and icon_path.stat().st_size > 0, "assets/launchflow.ico is missing or empty")
    require(resolve_app_icon_path(ROOT) == icon_path, "source icon resolution is incorrect")

    old_frozen = getattr(sys, "frozen", None)
    had_frozen = hasattr(sys, "frozen")
    old_meipass = getattr(sys, "_MEIPASS", None)
    had_meipass = hasattr(sys, "_MEIPASS")
    try:
        sys.frozen = True
        sys._MEIPASS = str(ROOT)
        require(resolve_app_icon_path(TEMP) == icon_path, "frozen icon resolution did not use _MEIPASS")
    finally:
        if had_frozen:
            sys.frozen = old_frozen
        else:
            delattr(sys, "frozen")
        if had_meipass:
            sys._MEIPASS = old_meipass
        else:
            delattr(sys, "_MEIPASS")

    check_entry_order()
    require(APP_USER_MODEL_ID == "forgottenlab.launchflow.editor", "unstable Windows AppUserModelID")
    require(callable(configure_windows_app_id), "Windows AppUserModelID configuration entry is missing")
    check_public_identity_facade()

    app = QApplication.instance() or QApplication([])
    app.setWindowIcon(QIcon())
    require(not apply_application_icon(app, ROOT).isNull(), "QApplication icon was not loaded")
    require(not app.windowIcon().isNull(), "QApplication windowIcon is null")

    window = MainWindow(ROOT)
    activation = ActivationWindow(ROOT)
    try:
        require(not window.windowIcon().isNull(), "MainWindow icon is null")
        require(not activation.windowIcon().isNull(), "ActivationWindow icon is null")
    finally:
        activation.close()
        window.close()
        app.processEvents()

    command = build_editor_command(ROOT)
    require("--icon" in command and str(icon_path) in command, "release command lost --icon")
    require(
        "--add-data" in command and any("launchflow.ico" in part and "assets" in part for part in command),
        "release command no longer bundles the runtime icon",
    )

    reset_app_logger_for_tests()
    shutil.rmtree(TEMP, ignore_errors=True)
    print("app icon smoke ok")
    print("source_frozen_resolution=shared-app-icon")
    print("windows_app_id=before-QApplication")
    print("identity_facade=signature,constant,delegation,return,error-compatible")
    print("qt_icons=application,main-window,activation-window")
    print("release_icon=--icon,--add-data")
    print("taskbar_display=manual-check-required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
