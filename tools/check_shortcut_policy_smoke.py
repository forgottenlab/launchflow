"""Freeze the Windows-equivalent shortcut policy and QAction behavior."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import FrozenInstanceError, fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP = Path(tempfile.gettempdir()) / f"launchflow-shortcuts-{os.getpid()}-{uuid.uuid4().hex}"
TEMP.mkdir(parents=True)
OLD_DATA_DIR = os.environ.get("LAUNCHFLOW_DATA_DIR")
OLD_QT_PLATFORM = os.environ.get("QT_QPA_PLATFORM")
os.environ["LAUNCHFLOW_DATA_DIR"] = str(TEMP / "data root 中文")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QPlainTextEdit,
    QPushButton,
)

import editor.ui.main_window as main_window_module  # noqa: E402
from editor.ui.main_window import MainWindow, SHORTCUTS  # noqa: E402
from shared.app_logging import reset_app_logger_for_tests  # noqa: E402
from shared.models import CommandStep, Plan  # noqa: E402
from shared.platform.base import PlatformInfo  # noqa: E402
from shared.platform.shortcuts import (  # noqa: E402
    LegacyShortcutPolicy,
    ShortcutProfile,
    WindowsShortcutPolicy,
    get_shortcut_policy,
)


EXPECTED_PROFILE = {
    "save": "Ctrl+S",
    "save_as": "Ctrl+Shift+S",
    "trial_run": "Ctrl+R",
    "export": "Ctrl+E",
    "delete_step": "Delete",
    "move_up": "Alt+Up",
    "move_down": "Alt+Down",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def platform_info(system: str) -> PlatformInfo:
    values = {
        "windows": ("nt", "win32"),
        "linux": ("posix", "linux"),
        "macos": ("posix", "darwin"),
        "unknown": ("other", "other"),
    }
    os_name, sys_platform = values[system]
    return PlatformInfo(system, "x86_64", os_name, sys_platform)


def check_provider_and_frozen_profile() -> None:
    windows = get_shortcut_policy(platform_info("windows"))
    require(isinstance(windows, WindowsShortcutPolicy), "Windows selected the wrong shortcut policy")
    for system in ("linux", "macos", "unknown"):
        policy = get_shortcut_policy(platform_info(system))
        require(isinstance(policy, LegacyShortcutPolicy), f"{system} incorrectly selected Windows policy")

    expected_fields = tuple(EXPECTED_PROFILE)
    require(tuple(field.name for field in fields(ShortcutProfile)) == expected_fields, "profile fields drifted")
    for policy in (
        windows,
        get_shortcut_policy(platform_info("linux")),
        get_shortcut_policy(platform_info("macos")),
        get_shortcut_policy(platform_info("unknown")),
    ):
        actual = {name: getattr(policy.profile, name) for name in expected_fields}
        require(actual == EXPECTED_PROFILE, f"legacy shortcut values drifted: {actual}")
        try:
            policy.profile.save = "changed"  # type: ignore[misc]
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError("ShortcutProfile is not frozen")


def check_import_side_effects() -> None:
    source_path = ROOT / "shared" / "platform" / "shortcuts.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    require(
        imported_roots <= {"__future__", "dataclasses", "typing", "shared"},
        f"shortcut policy gained non-stdlib dependencies: {sorted(imported_roots)}",
    )
    for forbidden in (
        "import PySide6",
        "from PySide6",
        "import editor",
        "from editor",
        "import shared.models",
        "from shared.models",
        "import licensing",
        "from licensing",
    ):
        require(forbidden not in source, f"shortcut policy contains forbidden dependency: {forbidden}")

    probe_root = TEMP / "import probe"
    probe_root.mkdir()
    probe = """
import json, os, sys
from pathlib import Path
before_cwd = os.getcwd()
before_env = dict(os.environ)
before_files = sorted(path.name for path in Path.cwd().iterdir())
import shared.platform.shortcuts
after_files = sorted(path.name for path in Path.cwd().iterdir())
print(json.dumps({
    'cwd_same': os.getcwd() == before_cwd,
    'env_same': dict(os.environ) == before_env,
    'files_same': before_files == after_files,
    'qt_loaded': any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules),
    'editor_loaded': any(name == 'editor' or name.startswith('editor.') for name in sys.modules),
    'models_loaded': 'shared.models' in sys.modules,
    'licensing_loaded': any(name == 'licensing' or name.startswith('licensing.') for name in sys.modules),
}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=probe_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    require(result.returncode == 0, f"shortcut import probe failed: {result.stderr}")
    report = json.loads(result.stdout)
    require(report == {
        "cwd_same": True,
        "editor_loaded": False,
        "env_same": True,
        "files_same": True,
        "licensing_loaded": False,
        "models_loaded": False,
        "qt_loaded": False,
    }, f"shortcut import had side effects: {report}")


def check_standard_keys() -> None:
    standard = QKeySequence.StandardKey
    expected = {
        "Save": "Ctrl+S",
        "SaveAs": "Ctrl+Shift+S",
        "Delete": "Del",
    }
    for name, expected_text in expected.items():
        key = getattr(standard, name)
        sequence = QKeySequence(key)
        bindings = QKeySequence.keyBindings(key)
        require(sequence.toString() == expected_text, f"StandardKey.{name} changed: {sequence.toString()!r}")
        require(
            sequence.toString(QKeySequence.SequenceFormat.PortableText) == expected_text,
            f"StandardKey.{name} portable text changed",
        )
        require(
            sequence.toString(QKeySequence.SequenceFormat.NativeText) == expected_text,
            f"StandardKey.{name} native text changed",
        )
        require(len(bindings) == 1 and bindings[0] == sequence, f"StandardKey.{name} gained alternatives")
    names = set(standard.__members__)
    require(not any("Run" in name or "Export" in name for name in names), "unexpected Run/Export StandardKey")


def action_contract(window: MainWindow) -> None:
    expected_actions = (
        ("action_save", "保存", "Ctrl+S", Qt.ShortcutContext.WindowShortcut),
        ("action_save_as", "另存为", "Ctrl+Shift+S", Qt.ShortcutContext.WindowShortcut),
        ("action_trial_run", "运行", "Ctrl+R", Qt.ShortcutContext.WindowShortcut),
        ("action_export_exe", "导出 EXE", "Ctrl+E", Qt.ShortcutContext.WindowShortcut),
        ("action_delete_step", "删除当前选中步骤", "Del", Qt.ShortcutContext.WindowShortcut),
        ("action_move_step_up", "上移当前步骤", "Alt+Up", Qt.ShortcutContext.WidgetWithChildrenShortcut),
        ("action_move_step_down", "下移当前步骤", "Alt+Down", Qt.ShortcutContext.WidgetWithChildrenShortcut),
    )
    objects: list[QAction] = []
    for attribute, text, shortcut, context in expected_actions:
        action = getattr(window, attribute)
        objects.append(action)
        require(action.text() == text, f"{attribute} text changed")
        require(action.shortcut().toString() == shortcut, f"{attribute} shortcut changed")
        require(action.shortcutContext() == context, f"{attribute} context changed")
        require(action.isEnabled(), f"{attribute} initial enabled state changed")
        require(not action.isCheckable() and not action.isChecked(), f"{attribute} check state changed")
        require(action.toolTip() == text and action.statusTip() == "", f"{attribute} tip state changed")
        require(action.parent() is window, f"{attribute} parent changed")
    require(len({id(action) for action in objects}) == len(objects), "QAction objects are duplicated")

    menus = window.main_menu_bar.actions()
    require([action.menu().title() for action in menus] == ["文件", "编辑"], "menu order changed")
    file_items = ["<separator>" if item.isSeparator() else item.text() for item in menus[0].menu().actions()]
    edit_items = ["<separator>" if item.isSeparator() else item.text() for item in menus[1].menu().actions()]
    require(file_items == ["保存", "另存为", "<separator>", "运行", "导出 EXE"], "file menu changed")
    require(edit_items == ["上移当前步骤", "下移当前步骤", "<separator>", "删除当前选中步骤"], "edit menu changed")
    menu_actions = [item for menu in menus for item in menu.menu().actions() if not item.isSeparator()]
    require(all(menu_actions.count(action) == 1 for action in objects), "menu QAction reuse changed")

    top_order: list[str] = []
    expected_buttons = {
        id(window.btn_save): "btn_save",
        id(window.btn_save_as): "btn_save_as",
        id(window.btn_trial_run): "btn_trial_run",
        id(window.btn_export_exe): "btn_export_exe",
    }
    layout = window.top_bar.layout()
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if isinstance(widget, QPushButton) and id(widget) in expected_buttons:
            top_order.append(expected_buttons[id(widget)])
    require(
        top_order == ["btn_save", "btn_save_as", "btn_trial_run", "btn_export_exe"],
        f"top button order changed: {top_order}",
    )
    require(
        {name: value for name, value in SHORTCUTS.items()} == {
            "save": "Ctrl+S",
            "save_as": "Ctrl+Shift+S",
            "trial_run": "Ctrl+R",
            "export": "Ctrl+E",
            "delete": "Delete",
            "move_up": "Alt+Up",
            "move_down": "Alt+Down",
        },
        "public SHORTCUTS mapping changed",
    )
    require(type(SHORTCUTS) is dict, "SHORTCUTS mapping type changed")
    expected_tooltips = {
        window.btn_save: "保存当前方案（Ctrl+S）",
        window.btn_save_as: "将当前方案保存为新文件（Ctrl+Shift+S）",
        window.btn_trial_run: "后台执行当前方案，命令输出显示在下方日志（Ctrl+R）",
        window.btn_export_exe: "将当前方案导出为独立启动器（Ctrl+E）",
        window.btn_delete_step: "删除当前选中步骤（Delete）",
    }
    for button, tooltip in expected_tooltips.items():
        require(button.toolTip() == tooltip, f"tooltip changed: {button.toolTip()!r}")


def install_command_plan(window: MainWindow, name: str, command: str = "old") -> None:
    window.current_plan = Plan(plan_name=name, steps=[CommandStep(name="命令", command=command)])
    window.current_plan_path = None
    window.current_editor_index = None
    window.current_step_dirty = False
    window.plan_dirty = False
    window._loading_plan = True
    window.plan_name_edit.setText(name)
    window._loading_plan = False
    window._refresh_flow_list()
    window.flow_list.setCurrentRow(0)
    QApplication.processEvents()


class FakeSignal:
    def __init__(self) -> None:
        self.slots: list[object] = []

    def connect(self, slot) -> None:  # type: ignore[no-untyped-def]
        self.slots.append(slot)


def behavior_contract(window: MainWindow) -> None:
    window._info = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    window._error = lambda title, message: (_ for _ in ()).throw(AssertionError(f"{title}: {message}"))  # type: ignore[method-assign]

    install_command_plan(window, "shortcut-save")
    window.cmd_in.setPlainText('echo "latest save %PATH%"\n中文')
    window.action_save.trigger()
    saved_path = window.plan_service.get_plans_dir() / "shortcut-save.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    require(saved["steps"][0]["command"] == 'echo "latest save %PATH%"\n中文', "save action lost draft")

    save_as_path = TEMP / "save as 中文.json"
    old_dialog = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = lambda *_args, **_kwargs: (str(save_as_path), "")
    try:
        window.cmd_in.setPlainText("latest save-as draft")
        window.action_save_as.trigger()
    finally:
        QFileDialog.getSaveFileName = old_dialog
    saved_as = json.loads(save_as_path.read_text(encoding="utf-8"))
    require(saved_as["steps"][0]["command"] == "latest save-as draft", "save-as action lost draft")

    trial_capture: dict[str, object] = {}

    class FakeTrialWorker:
        def __init__(self, plan: Plan) -> None:
            trial_capture["plan"] = plan
            self.progress = FakeSignal()
            self.success = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

        def start(self) -> None:
            trial_capture["started"] = True

    old_trial_worker = main_window_module.TrialRunWorker
    old_confirm = window._confirm
    main_window_module.TrialRunWorker = FakeTrialWorker  # type: ignore[assignment]
    window._confirm = lambda *_args, **_kwargs: True  # type: ignore[method-assign]
    try:
        window.cmd_in.setPlainText("latest trial draft")
        window.action_trial_run.trigger()
    finally:
        main_window_module.TrialRunWorker = old_trial_worker
        window._confirm = old_confirm
        window.trial_run_worker = None
        window.btn_trial_run.setEnabled(True)
    trial_plan = trial_capture.get("plan")
    require(trial_capture.get("started") is True and isinstance(trial_plan, Plan), "trial action did not start worker")
    require(trial_plan is not window.current_plan, "trial action did not use a deep copy")
    require(trial_plan.steps[0].command == "latest trial draft", "trial action used stale draft")

    export_capture: dict[str, object] = {}

    class FakeBuildWorker:
        def __init__(self, plan: Plan, output_path: Path) -> None:
            export_capture["plan"] = plan
            export_capture["path"] = output_path
            self.progress = FakeSignal()
            self.success = FakeSignal()
            self.failed = FakeSignal()

        def start(self) -> None:
            export_capture["started"] = True

    export_path = TEMP / "inert-output.exe"
    old_build_worker = main_window_module.BuildWorker
    old_dialog = QFileDialog.getSaveFileName
    main_window_module.BuildWorker = FakeBuildWorker  # type: ignore[assignment]
    QFileDialog.getSaveFileName = lambda *_args, **_kwargs: (str(export_path), "")
    try:
        window.cmd_in.setPlainText("latest export draft")
        window.action_export_exe.trigger()
    finally:
        main_window_module.BuildWorker = old_build_worker
        QFileDialog.getSaveFileName = old_dialog
        if window.progress_dialog is not None:
            window.progress_dialog.close()
            window.progress_dialog = None
    export_plan = export_capture.get("plan")
    require(export_capture.get("started") is True and isinstance(export_plan, Plan), "export action did not start worker")
    require(export_plan is not window.current_plan, "export action did not use a deep copy")
    require(export_plan.steps[0].command == "latest export draft", "export action used stale draft")
    require(export_capture.get("path") == export_path, "export destination changed")

    install_command_plan(window, "delete-action")
    confirmations: list[bool] = []
    window._confirm = lambda *_args, **_kwargs: (confirmations.append(True) or True)  # type: ignore[method-assign]
    window.action_delete_step.trigger()
    require(len(confirmations) == 1 and not window.current_plan.steps, "delete QAction changed handler behavior")


def focus_contract(window: MainWindow) -> None:
    install_command_plan(window, "focus-contract", "abc")
    confirmations: list[bool] = []
    window._confirm = lambda *_args, **_kwargs: (confirmations.append(True) or True)  # type: ignore[method-assign]

    window.cmd_name_in.setText("abc")
    window.cmd_name_in.setCursorPosition(1)
    window.cmd_name_in.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.cmd_name_in, Qt.Key.Key_Delete)
    QApplication.processEvents()
    require(window.cmd_name_in.text() == "ac", "QLineEdit Delete behavior changed")
    require(not confirmations and len(window.current_plan.steps) == 1, "QLineEdit Delete triggered step deletion")

    window.cmd_in.setPlainText("abc")
    cursor = window.cmd_in.textCursor()
    cursor.setPosition(1)
    window.cmd_in.setTextCursor(cursor)
    window.cmd_in.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.cmd_in, Qt.Key.Key_Delete)
    QApplication.processEvents()
    require(window.cmd_in.toPlainText() == "ac", "QTextEdit Delete behavior changed")
    require(not confirmations and len(window.current_plan.steps) == 1, "QTextEdit Delete triggered step deletion")
    require(not window.findChildren(QPlainTextEdit), "production UI unexpectedly gained QPlainTextEdit")

    for widget, read_text in (
        (window.cmd_name_in, window.cmd_name_in.text),
        (window.cmd_in, window.cmd_in.toPlainText),
    ):
        if widget is window.cmd_name_in:
            widget.setText("abc")
        else:
            widget.setPlainText("abc")
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        require(QApplication.clipboard().text() == "abc", "Ctrl+C text behavior changed")
        QTest.keyClick(widget, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        require(read_text() == "", "Ctrl+X text behavior changed")
        QTest.keyClick(widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        require(read_text() == "abc", "Ctrl+Z text behavior changed")
        QTest.keyClick(widget, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        require(read_text() == "", "Ctrl+Y text behavior changed")
        QTest.keyClick(widget, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        require(read_text() == "abc", "Ctrl+V text behavior changed")

    window.flow_list.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.flow_list, Qt.Key.Key_Delete)
    QApplication.processEvents()
    require(
        len(confirmations) == 1 and not window.current_plan.steps,
        f"flow-list Delete behavior changed: confirmations={len(confirmations)}, steps={len(window.current_plan.steps)}, focus={window.flow_list.hasFocus()}",
    )

    source = (ROOT / "editor" / "ui" / "main_window.py").read_text(encoding="utf-8")
    require("def eventFilter" not in source, "global event filter was added")
    require(source.count("def keyPressEvent") == 3, "keyPressEvent ownership changed")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window: MainWindow | None = None
    try:
        check_provider_and_frozen_profile()
        check_import_side_effects()
        check_standard_keys()
        window = MainWindow(ROOT)
        window.show()
        QApplication.processEvents()
        action_contract(window)
        behavior_contract(window)
        window.close()
        QApplication.processEvents()
        window = MainWindow(ROOT)
        window.show()
        QApplication.processEvents()
        focus_contract(window)
        print("shortcut policy smoke ok")
        print("providers=windows-policy,legacy-linux,legacy-macos,legacy-unknown")
        print("profile=frozen,seven-fields,windows-equivalent")
        print("standard_keys=Save:Ctrl+S,SaveAs:Ctrl+Shift+S,Delete:Del,not-adopted")
        print("actions=seven-unique,menu-order,top-button-order,contexts,tips")
        print("handlers=save,save-as,trial-snapshot,export-snapshot,delete")
        print("focus=QLineEdit,QTextEdit,FlowList,standard-editing-shortcuts")
        print("side_effects=no-qt,no-editor,no-models,no-licensing,no-files,no-env,no-cwd")
        return 0
    finally:
        if window is not None:
            window.close()
            app.processEvents()
        reset_app_logger_for_tests()
        if OLD_DATA_DIR is None:
            os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
        else:
            os.environ["LAUNCHFLOW_DATA_DIR"] = OLD_DATA_DIR
        if OLD_QT_PLATFORM is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = OLD_QT_PLATFORM
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
