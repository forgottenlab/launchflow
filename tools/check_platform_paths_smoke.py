"""Verify Phase 1a platform detection and Windows path equivalence."""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import shared.app_paths as app_paths
from shared.platform.base import PlatformPathProvider
from shared.platform.detection import current_platform_info, detect_platform
from shared.platform.paths import (
    LegacyFallbackPlatformPaths,
    WindowsPlatformPaths,
    get_platform_path_provider,
)


EXPECTED_SUBDIRECTORIES = ("config", "data", "licenses", "logs", "plans", "cache", "temp")
PUBLIC_FUNCTIONS = (
    "get_app_data_dir",
    "get_config_dir",
    "get_data_dir",
    "get_license_dir",
    "get_logs_dir",
    "get_plans_dir",
    "get_cache_dir",
    "get_temp_dir",
    "ensure_app_directories",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_detection() -> None:
    cases = (
        ({"system": "Windows", "machine": "AMD64", "os_name": "nt", "sys_platform": "win32"}, ("windows", "x86_64")),
        ({"system": "Linux", "machine": "x86_64", "os_name": "posix", "sys_platform": "linux"}, ("linux", "x86_64")),
        ({"system": "Darwin", "machine": "arm64", "os_name": "posix", "sys_platform": "darwin"}, ("macos", "arm64")),
        ({"system": "Other", "machine": "mystery", "os_name": "other", "sys_platform": "other"}, ("unknown", "unknown")),
        ({"system": "Linux", "machine": "aarch64", "os_name": "posix", "sys_platform": "linux"}, ("linux", "arm64")),
        ({"system": "Linux", "machine": "x86", "os_name": "posix", "sys_platform": "linux"}, ("linux", "x86")),
        ({"system": "Linux", "machine": "i386", "os_name": "posix", "sys_platform": "linux"}, ("linux", "x86")),
        ({"system": "Linux", "machine": "i686", "os_name": "posix", "sys_platform": "linux"}, ("linux", "x86")),
    )
    for values, expected in cases:
        info = detect_platform(**values)
        require((info.system, info.architecture) == expected, f"detection mismatch: {values} -> {info}")
    require(current_platform_info().system == "windows", "current Windows host was not detected")
    require(current_platform_info().architecture == "x86_64", "current AMD64 host was not normalized")


def _assert_provider_contract(temp_root: Path) -> None:
    windows = detect_platform(system="Windows", machine="AMD64", os_name="nt", sys_platform="win32")
    local_app_data = Path("C:/Users/TestUser/AppData/Local")
    provider = get_platform_path_provider(
        platform_info=windows,
        environment={"LOCALAPPDATA": str(local_app_data)},
        home=Path("C:/Users/TestUser"),
    )
    require(isinstance(provider, WindowsPlatformPaths), "Windows provider was not selected")
    require(isinstance(provider, PlatformPathProvider), "Windows provider does not satisfy Protocol")
    require(provider.default_app_root("LaunchFlow", False) == local_app_data / "LaunchFlow", "Windows default changed")
    require(provider.default_app_root("LaunchFlow", True) == local_app_data / "LaunchFlow-Dev", "Windows dev default changed")

    fallback_provider = WindowsPlatformPaths(windows, {}, Path("C:/Users/TestUser"))
    require(
        fallback_provider.default_app_root("LaunchFlow", False)
        == Path("C:/Users/TestUser/AppData/Local/LaunchFlow"),
        "Windows home fallback changed",
    )

    override = temp_root / "explicit root"
    require(provider.resolve_app_root("LaunchFlow", False, str(override)) == override, "override lost priority")
    require(provider.resolve_app_root("LaunchFlow", True, str(override)) == override, "override gained Dev suffix")
    require(not override.exists(), "provider created the explicit root")

    for system, sys_platform in (("Linux", "linux"), ("Darwin", "darwin"), ("Other", "other")):
        info = detect_platform(system=system, machine="x86_64", os_name="posix", sys_platform=sys_platform)
        fallback = get_platform_path_provider(
            platform_info=info,
            environment={"LOCALAPPDATA": "C:/must-not-be-used"},
            home=temp_root / f"{info.system}-home",
        )
        require(isinstance(fallback, LegacyFallbackPlatformPaths), f"legacy fallback not selected: {info}")
        require(
            fallback.default_app_root("LaunchFlow", False)
            == temp_root / f"{info.system}-home" / ".local" / "share" / "LaunchFlow",
            f"legacy fallback changed: {info}",
        )
        require(not (temp_root / f"{info.system}-home").exists(), "legacy provider created a directory")


def _assert_compatibility_api(temp_root: Path) -> None:
    require(app_paths.APP_DATA_ENV == "LAUNCHFLOW_DATA_DIR", "APP_DATA_ENV changed")
    require(app_paths.APP_DIR_NAME == "LaunchFlow", "APP_DIR_NAME changed")
    require(app_paths.APP_SUBDIRECTORIES == EXPECTED_SUBDIRECTORIES, "subdirectory contract changed")
    require(issubclass(app_paths.AppPathError, RuntimeError), "AppPathError base changed")
    for name in PUBLIC_FUNCTIONS:
        function = getattr(app_paths, name, None)
        require(callable(function), f"public function missing: {name}")
        require(str(inspect.signature(function)).startswith("()"), f"signature changed: {name}")

    override = temp_root / "override root"
    alternate = temp_root / "alternate root"
    local_app_data = temp_root / "Local AppData"
    old_override = os.environ.get(app_paths.APP_DATA_ENV)
    old_local = os.environ.get("LOCALAPPDATA")
    old_userprofile = os.environ.get("USERPROFILE")
    try:
        os.environ["LOCALAPPDATA"] = str(local_app_data)
        os.environ.pop(app_paths.APP_DATA_ENV, None)
        require(app_paths.get_app_data_dir() == local_app_data / "LaunchFlow", "compat Windows default changed")
        require(not local_app_data.exists(), "path calculation created LOCALAPPDATA")

        os.environ[app_paths.APP_DATA_ENV] = str(override)
        require(app_paths.get_app_data_dir() == override, "compat override changed")
        require(not override.exists(), "compat calculation created override")
        os.environ[app_paths.APP_DATA_ENV] = str(alternate)
        require(app_paths.get_app_data_dir() == alternate, "environment is not read on every call")

        expansion_parent = temp_root / "expanded parent"
        os.environ["LAUNCHFLOW_SMOKE_PARENT"] = str(expansion_parent)
        os.environ[app_paths.APP_DATA_ENV] = r"%LAUNCHFLOW_SMOKE_PARENT%\expanded"
        require(
            app_paths.get_app_data_dir() == expansion_parent / "expanded",
            "environment expansion behavior changed",
        )

        user_home = temp_root / "User Home"
        os.environ["USERPROFILE"] = str(user_home)
        os.environ[app_paths.APP_DATA_ENV] = "~/user-root"
        require(app_paths.get_app_data_dir() == user_home / "user-root", "user expansion behavior changed")

        exact_with_parent = temp_root / "segment" / ".." / "exact"
        os.environ[app_paths.APP_DATA_ENV] = str(exact_with_parent)
        require(app_paths.get_app_data_dir() == exact_with_parent, "override was unexpectedly resolved")

        os.environ[app_paths.APP_DATA_ENV] = "relative-data-root"
        try:
            app_paths.get_app_data_dir()
        except app_paths.AppPathError as exc:
            require(
                str(exc) == "LAUNCHFLOW_DATA_DIR 必须是绝对路径: relative-data-root",
                f"relative override error text changed: {exc}",
            )
        else:
            raise AssertionError("relative override was accepted")

        os.environ[app_paths.APP_DATA_ENV] = "   "
        require(app_paths.get_app_data_dir() == local_app_data / "LaunchFlow", "blank override behavior changed")

        os.environ[app_paths.APP_DATA_ENV] = str(local_app_data / "LaunchFlow-Dev")
        require(
            app_paths.get_app_data_dir() == local_app_data / "LaunchFlow-Dev",
            "development override changed",
        )

        os.environ[app_paths.APP_DATA_ENV] = str(override)
        calculated = {
            "root": app_paths.get_app_data_dir(),
            "config": app_paths.get_config_dir(),
            "data": app_paths.get_data_dir(),
            "licenses": app_paths.get_license_dir(),
            "logs": app_paths.get_logs_dir(),
            "plans": app_paths.get_plans_dir(),
            "cache": app_paths.get_cache_dir(),
            "temp": app_paths.get_temp_dir(),
        }
        require(all(isinstance(path, Path) for path in calculated.values()), "compat API stopped returning Path")
        require(not override.exists(), "subdirectory calculations created directories")
        created = app_paths.ensure_app_directories()
        require(created == calculated, "ensure_app_directories return mapping changed")
        require(all(path.is_dir() for path in created.values()), "ensure_app_directories did not create directories")
    finally:
        os.environ.pop("LAUNCHFLOW_SMOKE_PARENT", None)
        if old_override is None:
            os.environ.pop(app_paths.APP_DATA_ENV, None)
        else:
            os.environ[app_paths.APP_DATA_ENV] = old_override
        if old_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_local
        if old_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = old_userprofile


def _assert_import_has_no_side_effect(temp_root: Path) -> None:
    import_root = temp_root / "import-only-root"
    alternate_cwd = temp_root / "alternate-cwd"
    alternate_cwd.mkdir()
    env = os.environ.copy()
    env[app_paths.APP_DATA_ENV] = str(import_root)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", "import shared.app_paths, shared.platform"],
        cwd=alternate_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    require(completed.returncode == 0, f"fresh import failed: {completed.stderr}")
    require(not import_root.exists(), "import created the data root")
    require(list(alternate_cwd.iterdir()) == [], "import wrote into cwd")


def _assert_shared_platform_is_stdlib_only() -> None:
    for path in sorted((PROJECT_ROOT / "shared" / "platform").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        require("PySide" not in text and "QStandardPaths" not in text, f"Qt dependency found: {path.name}")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-platform-paths-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    try:
        _assert_detection()
        _assert_provider_contract(temp_root)
        _assert_compatibility_api(temp_root)
        _assert_import_has_no_side_effect(temp_root)
        _assert_shared_platform_is_stdlib_only()
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    require(not temp_root.exists(), "platform paths smoke left temporary data")
    print("platform paths smoke ok")
    print("detection=windows,linux,macos,unknown")
    print("architecture=x86_64,arm64,x86,unknown")
    print("windows_paths=LaunchFlow,LaunchFlow-Dev")
    print("override=absolute,exact,no-app-or-dev-suffix")
    print("relative_override=AppPathError,compatible-message")
    print("compat_api=constants,error,nine-functions,path-returns")
    print("side_effects=import:none,calculate:none,ensure:create")
    print("non_windows=legacy-fallback-only,not-supported")
    print("dependencies=stdlib-only,no-qt")


if __name__ == "__main__":
    main()
