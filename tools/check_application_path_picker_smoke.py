"""Offscreen smoke for Application path typing, browse wiring, and keyword lookup."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_temp_base = PROJECT_ROOT.parent / "test"
_temp_base.mkdir(parents=True, exist_ok=True)
_temp_data = _temp_base / f"launchflow-app-path-picker-{os.getpid()}-{uuid.uuid4().hex}"
_temp_data.mkdir(parents=True)
os.environ["LAUNCHFLOW_DATA_DIR"] = str(_temp_data / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from editor.edition_ui import (  # noqa: E402
    BASIC_APP_PATH_PLACEHOLDER,
    PROFESSIONAL_APP_PATH_PLACEHOLDER,
    application_file_dialog_filter,
    application_lookup_suffixes,
)
from editor.ui.main_window import MainWindow  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.app_paths import APP_DATA_ENV  # noqa: E402
from editor.launch import (  # noqa: E402
    apply_basic_launch_edition,
    apply_current_product_launch_edition,
)
from shared.edition_policy import EditionContext, set_process_edition_context  # noqa: E402
from shared.models import AppStep, Plan  # noqa: E402
from shared.platform.application_lookup import (  # noqa: E402
    BASIC_LOOKUP_SUFFIXES,
    PROFESSIONAL_LOOKUP_SUFFIXES,
    SOURCE_APP_PATHS,
    STATUS_AMBIGUOUS,
    STATUS_FOUND,
    STATUS_NOT_FOUND,
    ApplicationLookupMatch,
    ApplicationLookupResult,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _select_app_step(window: MainWindow, path: str = "") -> AppStep:
    step = AppStep(name="新应用", path=path, args=[], working_dir="", delay_after=1.0)
    window.current_plan = Plan(plan_name="path-picker", steps=[step])
    window.current_plan_path = None
    window.current_editor_index = None
    window.current_step_dirty = False
    window.plan_dirty = False
    window._loading_plan = True
    window.plan_name_edit.setText(window.current_plan.plan_name)
    window._loading_plan = False
    window._refresh_flow_list()
    window.flow_list.setCurrentRow(0)
    QApplication.processEvents()
    return step


def _build_window(root: Path, *, basic: bool) -> MainWindow:
    if basic:
        apply_basic_launch_edition()
    else:
        apply_current_product_launch_edition()
    window = MainWindow(PROJECT_ROOT)
    window.show()
    QApplication.processEvents()
    return window


def check_shared_controls(window: MainWindow, *, basic: bool) -> None:
    _select_app_step(window, path=r"C:\Windows\System32\notepad.exe")
    require(hasattr(window, "btn_browse_app_path"), "browse button is missing")
    require(hasattr(window, "btn_find_app_path"), "find button is missing")
    require(window.btn_browse_app_path.isVisible(), "browse button should stay visible once an App step is selected")
    require(window.btn_find_app_path.isVisible(), "find button should stay visible once an App step is selected")
    require(window.app_path_in.isVisible(), "path field should stay visible once an App step is selected")
    expected = BASIC_APP_PATH_PLACEHOLDER if basic else PROFESSIONAL_APP_PATH_PLACEHOLDER
    require(window.app_path_in.placeholderText() == expected, "path placeholder drifted")
    suffixes = application_lookup_suffixes()
    require(
        suffixes == (BASIC_LOOKUP_SUFFIXES if basic else PROFESSIONAL_LOOKUP_SUFFIXES),
        "lookup suffixes drifted from the edition contract",
    )
    require("*.exe" in application_file_dialog_filter(), "file-dialog filter lost executables")
    if basic:
        require("*.ps1" not in application_file_dialog_filter(), "Basic dialog filter still includes scripts")
    else:
        require("*.ps1" in application_file_dialog_filter(), "Professional dialog filter lost scripts")


def check_typing_does_not_search(window: MainWindow) -> None:
    _select_app_step(window)
    calls: list[str] = []

    def fake_lookup(keyword: str, **_kwargs: object) -> ApplicationLookupResult:
        calls.append(keyword)
        return ApplicationLookupResult("steam", STATUS_FOUND, (), "should not run")

    window.application_lookup = fake_lookup
    window.app_path_in.setText("steam")
    QApplication.processEvents()
    require(window.app_path_in.text() == "steam", "typed keyword should stay in the field")
    require(calls == [], "keyword lookup must not run on each keystroke")


def check_browse_sets_path(window: MainWindow) -> None:
    _select_app_step(window)
    chosen = r"C:\Program Files\Demo\demo.exe"
    calls: list[tuple] = []
    old_dialog = QFileDialog.getOpenFileName

    def fake_dialog(*args: object, **kwargs: object) -> tuple[str, str]:
        calls.append((args, kwargs))
        return chosen, "Applications"

    QFileDialog.getOpenFileName = staticmethod(fake_dialog)  # type: ignore[method-assign]
    try:
        window.btn_browse_app_path.click()
        QApplication.processEvents()
    finally:
        QFileDialog.getOpenFileName = old_dialog  # type: ignore[method-assign]
    require(calls, "browse button did not open the file dialog")
    require(window.app_path_in.text() == chosen, "browse did not write the chosen path")
    require(window.current_step_dirty, "browse should mark the inspector draft dirty")


def check_find_unique_and_not_found(window: MainWindow) -> None:
    _select_app_step(window)
    found_path = r"C:\Program Files (x86)\Steam\steam.exe"
    window.app_path_in.setText("steam")

    def unique_lookup(keyword: str, **_kwargs: object) -> ApplicationLookupResult:
        require(keyword == "steam", "find did not pass the typed keyword")
        match = ApplicationLookupMatch(found_path, "Steam", SOURCE_APP_PATHS, "App Paths")
        return ApplicationLookupResult("steam", STATUS_FOUND, (match,), f"已找到 Steam：{found_path}")

    window.application_lookup = unique_lookup
    window.btn_find_app_path.click()
    QApplication.processEvents()
    require(window.app_path_in.text() == found_path, "unique lookup did not fill the absolute path")
    require(window.app_name_in.text() == "Steam", "default app name should follow a unique lookup")

    errors: list[tuple[str, str]] = []
    window._error = lambda title, text: errors.append((title, text))  # type: ignore[method-assign]
    window.app_path_in.setText("missing-app")

    def missing_lookup(keyword: str, **_kwargs: object) -> ApplicationLookupResult:
        return ApplicationLookupResult(
            keyword,
            STATUS_NOT_FOUND,
            (),
            "没有在注册表、开始菜单、桌面或常见安装目录中找到“missing-app”。未扫描整个磁盘。",
        )

    window.application_lookup = missing_lookup
    window.btn_find_app_path.click()
    QApplication.processEvents()
    require(errors, "not-found lookup should show a clear error")
    require(window.app_path_in.text() == "missing-app", "not-found lookup must not invent a path")
    require("未扫描整个磁盘" in errors[0][1], "not-found error text drifted")


def check_find_ambiguous_picker(window: MainWindow) -> None:
    _select_app_step(window, path=r"C:\Old\app.exe")
    window.app_name_in.setText("自定义名称")
    window.app_path_in.setText("demo")
    first = ApplicationLookupMatch(r"C:\Alpha\demo.exe", "Demo Alpha", SOURCE_APP_PATHS)
    second = ApplicationLookupMatch(r"C:\Beta\demo.exe", "Demo Beta", SOURCE_APP_PATHS)
    picked: list[ApplicationLookupMatch] = []

    def ambiguous_lookup(keyword: str, **_kwargs: object) -> ApplicationLookupResult:
        return ApplicationLookupResult(
            keyword,
            STATUS_AMBIGUOUS,
            (first, second),
            "找到 2 个匹配项，请选择要使用的程序。",
        )

    def fake_picker(matches: tuple[ApplicationLookupMatch, ...]):
        picked.extend(matches)
        return second

    window.application_lookup = ambiguous_lookup
    window._pick_application_lookup_match = fake_picker  # type: ignore[method-assign]
    window.btn_find_app_path.click()
    QApplication.processEvents()
    require(len(picked) == 2, "ambiguous lookup did not open the chooser")
    require(window.app_path_in.text() == second.path, "chooser selection was not stored")
    require(window.app_name_in.text() == "自定义名称", "custom step name should not be overwritten")

    cancelled: list[int] = []

    def cancel_picker(matches: tuple[ApplicationLookupMatch, ...]):
        cancelled.append(len(matches))
        return None

    window._pick_application_lookup_match = cancel_picker  # type: ignore[method-assign]
    window.app_path_in.setText("demo")
    window.btn_find_app_path.click()
    QApplication.processEvents()
    require(cancelled == [2], "cancelling the chooser should still receive the matches")
    require(window.app_path_in.text() == "demo", "cancelled chooser must not invent a path")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    previous = set_process_edition_context(EditionContext())
    windows: list[MainWindow] = []
    old_override = os.environ.get(APP_DATA_ENV)
    try:
        os.environ[APP_DATA_ENV] = str(_temp_data / "professional")
        professional = _build_window(PROJECT_ROOT, basic=False)
        windows.append(professional)
        check_shared_controls(professional, basic=False)
        check_typing_does_not_search(professional)
        check_browse_sets_path(professional)
        check_find_unique_and_not_found(professional)
        check_find_ambiguous_picker(professional)

        os.environ[APP_DATA_ENV] = str(_temp_data / "basic")
        basic = _build_window(PROJECT_ROOT, basic=True)
        windows.append(basic)
        check_shared_controls(basic, basic=True)
        _select_app_step(basic, path=r"C:\Games\steam.exe")
        check_browse_sets_path(basic)
        require(professional.btn_find_app_path.isVisible(), "creating a Basic window changed Professional controls")
        print("application path picker smoke ok")
        print("editions=professional,basic")
        print("cases=placeholder,type,browse,unique-find,not-found,ambiguous,cancel")
        return 0
    finally:
        for window in windows:
            window.close()
        reset_app_logger_for_tests()
        set_process_edition_context(previous)
        if old_override is None:
            os.environ.pop(APP_DATA_ENV, None)
        else:
            os.environ[APP_DATA_ENV] = old_override
        app.quit()


if __name__ == "__main__":
    raise SystemExit(main())
