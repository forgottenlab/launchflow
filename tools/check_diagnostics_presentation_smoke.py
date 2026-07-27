"""Independent smoke coverage for the diagnostics presentation boundary."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def platform_info(system: str):
    from shared.platform.base import PlatformInfo

    return PlatformInfo(system, "x86_64", "fixture-os", "fixture-platform")


def check_import_boundary() -> None:
    module_path = ROOT / "shared" / "platform" / "diagnostics.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    require("PySide6" not in imported_roots, "platform diagnostics must not import Qt")
    require("editor" not in imported_roots, "platform diagnostics must not import editor")
    require("licensing" not in imported_roots, "platform diagnostics must not import licensing")
    require("winreg" not in imported_roots, "platform diagnostics must not import winreg")

    cwd_before = Path.cwd()
    environment_before = dict(os.environ)
    module = importlib.import_module("shared.platform.diagnostics")
    require(Path.cwd() == cwd_before, "import changed cwd")
    require(dict(os.environ) == environment_before, "import changed environment")
    require(not hasattr(module, "get_logs_dir"), "platform diagnostics must not read logs")
    require(not hasattr(module, "get_desktop_integration"), "platform diagnostics must not open directories")


def check_provider_selection_and_structures() -> None:
    from shared.platform.diagnostics import (
        DiagnosticPathAlias,
        DiagnosticsPresentation,
        LegacyPosixDiagnosticsPresentationProvider,
        WindowsDiagnosticsPresentationProvider,
        get_diagnostics_presentation_provider,
    )

    windows = get_diagnostics_presentation_provider(platform_info("windows"))
    linux = get_diagnostics_presentation_provider(platform_info("linux"))
    macos = get_diagnostics_presentation_provider(platform_info("macos"))
    unknown = get_diagnostics_presentation_provider(platform_info("unknown"))
    require(isinstance(windows, WindowsDiagnosticsPresentationProvider), "Windows provider mismatch")
    require(isinstance(linux, LegacyPosixDiagnosticsPresentationProvider), "Linux fallback mismatch")
    require(isinstance(macos, LegacyPosixDiagnosticsPresentationProvider), "macOS fallback mismatch")
    require(isinstance(unknown, LegacyPosixDiagnosticsPresentationProvider), "unknown selected Windows")

    local = r"C:\Users\TestUser-Unique\AppData\Local"
    home = r"C:\Users\TestUser-Unique\Secret Home"
    provider = get_diagnostics_presentation_provider(
        platform_info("windows"),
        environment={"LOCALAPPDATA": local},
        home_path=home,
    )
    presentation = provider.build_presentation()
    expected_aliases = (
        DiagnosticPathAlias(local, "%LOCALAPPDATA%"),
        DiagnosticPathAlias(home, "%USERPROFILE%"),
    )
    require(
        presentation == DiagnosticsPresentation("Windows", expected_aliases),
        "Windows presentation fields or alias order changed",
    )
    require(
        provider.build_presentation(environment={}, home_path="").path_aliases == (),
        "empty sources must not enter aliases",
    )
    try:
        presentation.platform_label = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("DiagnosticsPresentation is not frozen")
    try:
        expected_aliases[0].source = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("DiagnosticPathAlias is not frozen")

    for fallback in (linux, macos, unknown):
        legacy = fallback.build_presentation(
            environment={"LOCALAPPDATA": local},
            home_path=home,
        )
        require(legacy == presentation, "legacy output no longer preserves historical labels")
        require(legacy.platform_label not in {"Linux", "macOS"}, "native label was introduced")


def normalize_with_sources(text: str, *, local: str = "", home: str = "") -> str:
    import shared.diagnostics as diagnostics
    from shared.platform.diagnostics import get_diagnostics_presentation_provider

    provider = get_diagnostics_presentation_provider(platform_info("windows"))
    environment = {"LOCALAPPDATA": local} if local else {}
    with (
        patch.object(diagnostics, "get_diagnostics_presentation_provider", return_value=provider),
        patch.dict(diagnostics.os.environ, environment, clear=True),
        patch.object(diagnostics.Path, "home", return_value=home),
    ):
        return diagnostics.normalize_user_paths(text)


def check_path_redaction_contract() -> None:
    local = r"C:\Users\TestUser-Unique\AppData\Local"
    home = r"C:\Users\TestUser-Unique\Secret Home"
    text = f"{local}\\one | {home}\\two | {local}\\three | {home}\\four"
    expected = (
        "%LOCALAPPDATA%\\one | %USERPROFILE%\\two | "
        "%LOCALAPPDATA%\\three | %USERPROFILE%\\four"
    )
    require(normalize_with_sources(text, local=local, home=home) == expected, "basic/repeated redaction changed")

    require(
        normalize_with_sources(local.upper() + r"\Case", local=local, home=home)
        == "%LOCALAPPDATA%\\Case",
        "path replacement must remain case-insensitive",
    )
    unicode_home = r"C:\Users\测试用户\秘密 家庭"
    require(
        normalize_with_sources(unicode_home + r"\计划.json", home=unicode_home)
        == "%USERPROFILE%\\计划.json",
        "Unicode/space path redaction changed",
    )
    slash_local = "C:/Users/TestUser-Unique/AppData/Local"
    slash_home = "C:/Users/TestUser-Unique/Secret Home"
    require(
        normalize_with_sources(
            f"{slash_local}/logs {slash_home}/docs",
            local=slash_local,
            home=slash_home,
        )
        == "%LOCALAPPDATA%/logs %USERPROFILE%/docs",
        "forward-slash sources changed",
    )
    require(
        normalize_with_sources(local.replace("\\", "/"), local=local, home=home)
        == local.replace("\\", "/"),
        "separator normalization was unexpectedly introduced",
    )

    same = r"C:\Same Unique Path"
    require(
        normalize_with_sources(same + r"\item", local=same, home=same)
        == "%LOCALAPPDATA%\\item",
        "first alias must win when sources are identical",
    )
    nested_home = r"C:\Users\UniqueUser"
    nested_local = nested_home + r"\AppData\Local"
    require(
        normalize_with_sources(
            nested_local + r"\logs " + nested_home + r"\docs",
            local=nested_local,
            home=nested_home,
        )
        == "%LOCALAPPDATA%\\logs %USERPROFILE%\\docs",
        "nested source replacement order changed",
    )
    require(
        normalize_with_sources("no paths", local="", home="") == "no paths",
        "empty sources changed text",
    )


class FixedNow:
    def astimezone(self):
        return self

    def isoformat(self, *, timespec: str) -> str:
        require(timespec == "seconds", "datetime precision changed")
        return "2026-07-27T12:34:56+08:00"


class FixedDateTime:
    @classmethod
    def now(cls) -> FixedNow:
        return FixedNow()


EXPECTED_FULL_TEXT = "\n".join(
    (
        "LaunchFlow 诊断信息",
        "版本: 9.9.9-fixture",
        "构建渠道: source",
        "当前时间: 2026-07-27T12:34:56+08:00",
        "Windows: Windows-11-10.0.26100-SP0",
        "Python: 3.13.9",
        "Frozen: False",
        "当前方案: Fixture Plan",
        "步骤数量: 4",
        "当前错误: 无法读取 %USERPROFILE%\\Project\\计划.json; signature=[MASKED]",
        "数据目录: %LOCALAPPDATA%\\LaunchFlow",
        "日志文件: %LOCALAPPDATA%\\LaunchFlow\\logs\\launchflow.log",
        "",
        "最近日志（最多 150 行）:",
        "command=%USERPROFILE%\\Tools\\runner.exe",
        "output=%LOCALAPPDATA%\\LaunchFlow\\logs\\launchflow.log",
        "machine_id=[MASKED]",
        "[已隐藏私钥相关日志]",
    )
)


def check_full_text_fixture() -> None:
    import shared.diagnostics as diagnostics
    from shared.platform.diagnostics import get_diagnostics_presentation_provider

    local = r"C:\Users\TestUser-Unique\AppData\Local"
    home = r"C:\Users\TestUser-Unique\Secret Home"
    recent = "\n".join(
        (
            f"command={home}\\Tools\\runner.exe",
            f"output={local}\\LaunchFlow\\logs\\launchflow.log",
            "machine_id=FAKE-MACHINE-ID",
            "private_key.pem should-hide-whole-line",
        )
    )
    provider = get_diagnostics_presentation_provider(platform_info("windows"))
    with (
        patch.object(diagnostics, "APP_NAME", "LaunchFlow"),
        patch.object(diagnostics, "APP_VERSION", "9.9.9-fixture"),
        patch.object(diagnostics, "datetime", FixedDateTime),
        patch.object(diagnostics.platform, "platform", return_value="Windows-11-10.0.26100-SP0"),
        patch.object(diagnostics.sys, "version", "3.13.9 fixture"),
        patch.object(diagnostics.sys, "frozen", False, create=True),
        patch.object(diagnostics, "get_diagnostics_presentation_provider", return_value=provider),
        patch.object(
            diagnostics,
            "_recent_log_text",
            return_value=(recent, Path(local) / "LaunchFlow" / "logs" / "launchflow.log"),
        ),
        patch.object(diagnostics, "get_app_data_dir", return_value=Path(local) / "LaunchFlow"),
        patch.dict(diagnostics.os.environ, {"LOCALAPPDATA": local}, clear=True),
        patch.object(diagnostics.Path, "home", return_value=home),
    ):
        actual = diagnostics.collect_diagnostics(
            plan_name="Fixture Plan",
            step_count=4,
            visible_log="ignored-by-fixture",
            current_error=f"无法读取 {home}\\Project\\计划.json; signature=FAKE-SIGNATURE",
            max_log_lines=150,
        )

    require(actual == EXPECTED_FULL_TEXT, "full diagnostics text changed:\n" + repr(actual))
    require(type(actual) is str, "diagnostics return type changed")
    require(not actual.endswith("\n"), "trailing-newline behavior changed")
    require(local not in actual and home not in actual, "fixture paths leaked from full diagnostics")
    require("%LOCALAPPDATA%" in actual and "%USERPROFILE%" in actual, "required aliases missing")
    require(
        hashlib.sha256(actual.encode("utf-8")).hexdigest()
        == "edd9423b9127229e2c0d1c0ecbbea50c923a951f293536c17f6229284ed7af10",
        "frozen full-text hash changed",
    )


def check_public_api_and_ui_path() -> None:
    import shared.diagnostics as diagnostics

    require(not hasattr(diagnostics, "build_diagnostic_text"), "unexpected public build_diagnostic_text added")
    require(
        str(inspect.signature(diagnostics.collect_diagnostics))
        == "(*, plan_name: 'str', step_count: 'int', visible_log: 'str', current_error: 'str' = '', max_log_lines: 'int' = 150) -> 'str'",
        "collect_diagnostics signature changed",
    )
    require(
        str(inspect.signature(diagnostics.open_logs_directory)) == "() -> 'Path'",
        "open_logs_directory signature changed",
    )
    require(isinstance(EXPECTED_FULL_TEXT, str), "diagnostics return type changed")

    main_window_path = ROOT / "editor" / "ui" / "main_window.py"
    source = main_window_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    build_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_build_diagnostic_text"
    ]
    require(len(build_functions) == 1, "UI diagnostic builder boundary changed")
    build_function = build_functions[0]
    require([arg.arg for arg in build_function.args.args] == ["self"], "UI builder signature changed")
    require(
        isinstance(build_function.returns, ast.Name) and build_function.returns.id == "str",
        "UI builder return annotation changed",
    )
    require(
        "QApplication.clipboard().setText(self.preview.toPlainText())" in source,
        "diagnostics clipboard call path changed",
    )
    require(
        "return collect_diagnostics(" in source,
        "UI no longer delegates to collect_diagnostics",
    )


def main() -> int:
    check_import_boundary()
    check_provider_selection_and_structures()
    check_path_redaction_contract()
    check_full_text_fixture()
    check_public_api_and_ui_path()
    print("diagnostics presentation smoke ok")
    print("providers=windows,legacy-linux,legacy-macos,legacy-unknown")
    print("presentation=frozen,label-and-alias-order-exact")
    print("full_text=exact,sha256=edd9423b9127229e2c0d1c0ecbbea50c923a951f293536c17f6229284ed7af10")
    print("redaction=spaces,unicode,same,nested,empty,slashes,case,repeated")
    print("side_effects=none")
    print("public_api=collect,open-logs,ui-builder,clipboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
